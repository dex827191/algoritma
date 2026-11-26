#!/usr/bin/env bash
# =================================================================
# App Bootstrap — Go proxy wrapper + Nginx + SSH/WSProxy + BadVPN
# =================================================================
set -Eeuo pipefail
set -o pipefail

ulimit -n 65535 2>/dev/null || true
ulimit -s unlimited 2>/dev/null || true

mkdir -p /var/log/nginx /var/run /app/data /etc/dropbear
SYS_CFG="/tmp/system_config.json"
WS_CFG="/tmp/ws_proxy_config.json"

SSH_BIN="/usr/local/bin/svc-helper"
NET_BIN="/usr/local/bin/net-worker"
WS_BIN="/usr/local/bin/stream-worker"
XRAY_BIN="/usr/local/bin/xray"
WRAPPER_BIN="/usr/local/bin/proxy-wrapper"
BANNER_FILE="/etc/app_motd"

# =================================================================
# Cleanup proses sisa (hanya proses milik stack ini)
# =================================================================
echo "[*] Cleanup..."
pkill -9 -x stream-worker 2>/dev/null || true
pkill -9 -x net-worker 2>/dev/null || true
pkill -9 -x svc-helper 2>/dev/null || true
pkill -9 -x nginx 2>/dev/null || true
pkill -9 -x cloudflared 2>/dev/null || true
pkill -9 -x xray 2>/dev/null || true
if command -v fuser >/dev/null 2>&1; then
  for port in 8443 2443 8880 8881 8080 8081 8082 2053 80 22 7300; do
    fuser -k "${port}/tcp" 2>/dev/null || true
  done
fi
sleep 1

# =================================================================
# Load konfigurasi awal
# =================================================================
load_system_config() {
  if [[ -f "$SYS_CFG" ]] && command -v jq >/dev/null 2>&1; then
    CUSTOM_BANNER="$(jq -r '.banner // empty' "$SYS_CFG" 2>/dev/null || true)"
    ENABLE_BBR="$(jq -r '.enable_bbr // "true"' "$SYS_CFG" 2>/dev/null || true)"
    UDPGW_PORT="$(jq -r '.udpgw_port // "7300"' "$SYS_CFG" 2>/dev/null || true)"
    UDPGW_MAX_CLIENTS="$(jq -r '.udpgw_max_clients // "1000"' "$SYS_CFG" 2>/dev/null || true)"
  else
    CUSTOM_BANNER=""
    ENABLE_BBR="${ENABLE_BBR:-true}"
    UDPGW_PORT="${UDPGW_PORT:-7300}"
    UDPGW_MAX_CLIENTS="${UDPGW_MAX_CLIENTS:-1000}"
  fi
  UDPGW_PORT="${UDPGW_PORT:-7300}"
  UDPGW_MAX_CLIENTS="${UDPGW_MAX_CLIENTS:-1000}"
  ENABLE_BBR="${ENABLE_BBR:-true}"
  [[ "$UDPGW_PORT" =~ ^[0-9]+$ ]] && (( UDPGW_PORT >= 1 && UDPGW_PORT <= 65535 )) || UDPGW_PORT=7300
  [[ "$UDPGW_MAX_CLIENTS" =~ ^[0-9]+$ ]] && (( UDPGW_MAX_CLIENTS >= 1 && UDPGW_MAX_CLIENTS <= 100000 )) || UDPGW_MAX_CLIENTS=1000
}

load_ws_config() {
  if [[ -f "$WS_CFG" ]] && command -v jq >/dev/null 2>&1; then
    SSH_PORT="$(jq -r '.sshPort // 22' "$WS_CFG" 2>/dev/null || echo 22)"
  else
    SSH_PORT="${SSH_PORT:-22}"
  fi
  [[ "$SSH_PORT" =~ ^[0-9]+$ ]] && (( SSH_PORT >= 1 && SSH_PORT <= 65535 )) || SSH_PORT=22
}

load_system_config
load_ws_config

# =================================================================
# Kernel tweaks — best effort; beberapa container tidak diberi CAP_SYS_ADMIN
# =================================================================
apply_kernel_tweaks() {
  sysctl -w net.ipv4.tcp_tw_reuse=1 >/dev/null 2>&1 || true
  sysctl -w net.ipv4.tcp_fin_timeout=10 >/dev/null 2>&1 || true
  sysctl -w net.core.default_qdisc=fq >/dev/null 2>&1 || true
  if [[ "${ENABLE_BBR:-true}" == "true" ]]; then
    sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1 || true
  else
    sysctl -w net.ipv4.tcp_congestion_control=cubic >/dev/null 2>&1 || true
  fi
  sysctl -w 'net.ipv4.tcp_rmem=4096 8388608 16777216' >/dev/null 2>&1 || true
  sysctl -w 'net.ipv4.tcp_wmem=4096 8388608 16777216' >/dev/null 2>&1 || true
  sysctl -w net.core.rmem_max=16777216 >/dev/null 2>&1 || true
  sysctl -w net.core.wmem_max=16777216 >/dev/null 2>&1 || true
  sysctl -w net.core.netdev_max_backlog=50000 >/dev/null 2>&1 || true
  sysctl -w net.ipv4.tcp_max_syn_backlog=8192 >/dev/null 2>&1 || true
}
apply_kernel_tweaks

# =================================================================
# Banner — custom dari panel atau default premium
# =================================================================
write_banner() {
  local banner="${1:-}"
  if [[ -n "$banner" ]]; then
    printf '%b\n' "$banner" > "$BANNER_FILE"
  else
    cat > "$BANNER_FILE" <<'EOF'
<p style="text-align:center;"><b>
    <font color="#800080">─── SERVER PREMIUM ───</font><br>
    <font color="#8A2BE2">! TERM OF SERVICE !</font><br>
    <font color="#9370DB">NO MULTI LOGIN / NO TORRENT</font><br>
    <font color="#8A2BE2">NO SPAM, NO DDOS, NO HACKING</font><br></b>
</p>
EOF
  fi
  chmod 644 "$BANNER_FILE"
}
write_banner "$CUSTOM_BANNER"

# =================================================================
# Host key
# =================================================================
if [[ ! -f /etc/dropbear/dropbear_rsa_host_key ]]; then
  echo "[!] Host key hilang, generating ulang..."
  "$SSH_BIN" -R 2>/dev/null || true
fi

# =================================================================
# SSH helper supervisor — ikut perubahan port dan banner secara dinamis
# =================================================================
(
  child=""
  active_signature=""
  while true; do
    load_ws_config
    load_system_config
    write_banner "$CUSTOM_BANNER"
    signature="${SSH_PORT}:$(sha256sum "$BANNER_FILE" 2>/dev/null | awk '{print $1}')"
    if [[ "$signature" != "$active_signature" ]] || [[ -z "$child" ]] || ! kill -0 "$child" 2>/dev/null; then
      if [[ -n "$child" ]]; then kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
      echo "[*] Starting SSH helper on 127.0.0.1:${SSH_PORT}"
      ( exec -a node-worker "$SSH_BIN" -F -R -p "127.0.0.1:${SSH_PORT}" -b "$BANNER_FILE" -W 1048576 -K 15 -I 300 ) >/tmp/ssh-helper.log 2>&1 &
      child=$!
      active_signature="$signature"
    fi
    sleep 2
  done
) >/tmp/ssh-supervisor.log 2>&1 &

# =================================================================
# Go WSProxy — reload ws_proxy_config.json per incoming connection
# =================================================================
if [[ -x "$WS_BIN" ]]; then
  ( exec -a app-worker env WS_PORT=8880 WS_BIND=127.0.0.1 "$WS_BIN" ) >/tmp/wsproxy.log 2>&1 &
else
  echo "[!] WSProxy binary tidak ditemukan: $WS_BIN" >&2
fi

# =================================================================
# BadVPN UDPGW supervisor — restart otomatis jika port/max-clients berubah
# =================================================================
(
  child=""
  active_signature=""
  while true; do
    load_system_config
    signature="${UDPGW_PORT}:${UDPGW_MAX_CLIENTS}"
    if [[ "$signature" != "$active_signature" ]] || [[ -z "$child" ]] || ! kill -0 "$child" 2>/dev/null; then
      if [[ -n "$child" ]]; then kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
      if [[ -x "$NET_BIN" ]]; then
        echo "[*] Starting BadVPN UDPGW on 0.0.0.0:${UDPGW_PORT} (max=${UDPGW_MAX_CLIENTS})"
        ( exec -a cache-worker "$NET_BIN" --listen-addr "0.0.0.0:${UDPGW_PORT}" --max-clients "$UDPGW_MAX_CLIENTS" --max-connections-for-client 50 ) >/tmp/udpgw.log 2>&1 &
        child=$!
      else
        echo "[!] BadVPN binary tidak ditemukan: $NET_BIN" >&2
        child=""
      fi
      active_signature="$signature"
    fi
    sleep 2
  done
) >/tmp/udpgw-supervisor.log 2>&1 &

# =================================================================
# Cloudflare Named Tunnel token
# =================================================================
CF_TUNNEL_TOKEN="${CF_TOKEN:-${TOKEN:-}}"
if [[ -n "$CF_TUNNEL_TOKEN" ]]; then
  printf '%s' "$CF_TUNNEL_TOKEN" > /tmp/zt_single_token.txt
  /usr/local/bin/cloudflared tunnel run --no-autoupdate --token "$CF_TUNNEL_TOKEN" >/tmp/cloudflared.log 2>&1 &
else
  rm -f /tmp/zt_single_token.txt 2>/dev/null || true
fi

# =================================================================
# Nginx
# =================================================================
echo "[*] Starting Nginx..."
if ! nginx -t -c /etc/nginx/nginx.conf; then
  echo "[FATAL] nginx.conf invalid!" >&2
  exit 1
fi
nginx -c /etc/nginx/nginx.conf
sleep 1
if ! pgrep -x nginx >/dev/null 2>&1; then
  echo "[FATAL] Nginx gagal start!" >&2
  exit 1
fi

# =================================================================
# Xray — independent supervisor; Python API updates config then restarts it
# =================================================================
XRAY_CONFIG="${XRAY_CONFIG:-/app/data/config.json}"
if [[ ! -f "$XRAY_CONFIG" ]]; then
  echo "[FATAL] Missing Xray config: $XRAY_CONFIG" >&2
  exit 1
fi
(
  while true; do
    "$XRAY_BIN" run -c "$XRAY_CONFIG" || true
    sleep 1
  done
) >/tmp/xray-supervisor.log 2>&1 &

# =================================================================
# Panel/API and Go TCP entrypoint
# =================================================================
PANEL_PORT="${PANEL_PORT:-2053}" python3 /app/server.py >/tmp/panel-api.log 2>&1 &
sleep 1
if ! kill -0 "$!" 2>/dev/null; then
  echo "[FATAL] Panel API gagal start" >&2
  cat /tmp/panel-api.log || true
  exit 1
fi

if [[ ! -x "$WRAPPER_BIN" ]]; then
  echo "[FATAL] Proxy wrapper tidak ditemukan: $WRAPPER_BIN" >&2
  exit 1
fi
echo "[*] Starting Go proxy wrapper (UI/API -> Python 0.0.0.0:2053, Xray -> Nginx 127.0.0.1:8081)..."
exec "$WRAPPER_BIN"
