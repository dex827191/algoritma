#!/bin/bash
set -eu

BANNER_FILE="${BANNER_FILE:-/etc/dropbear/banner}"
NET_BIN="${NET_BIN:-/usr/local/bin/badvpn-udpgw}"
UDPGW_PORT="${UDPGW_PORT:-7300}"
UDPGW_MAX_CLIENTS="${UDPGW_MAX_CLIENTS:-250}"

mkdir -p /etc/dropbear /etc/stunnel /etc/ssh-sni
if [ ! -f /etc/dropbear/dropbear_ed25519_host_key ]; then
  dropbearkey -t ed25519 -f /etc/dropbear/dropbear_ed25519_host_key >/dev/null
fi
[ -f /etc/ssh-sni/users.json ] || printf '{}\n' > /etc/ssh-sni/users.json

# =================================================================
# 🚀 Kernel tweaks
# =================================================================
sysctl -w net.ipv4.tcp_tw_reuse=1 2>/dev/null || true
sysctl -w net.ipv4.tcp_fin_timeout=10 2>/dev/null || true
sysctl -w net.core.default_qdisc=fq 2>/dev/null || true
if [ "${ENABLE_BBR:-false}" = "true" ]; then
    sysctl -w net.ipv4.tcp_congestion_control=bbr 2>/dev/null || true
else
    sysctl -w net.ipv4.tcp_congestion_control=cubic 2>/dev/null || true
fi
sysctl -w net.ipv4.tcp_rmem="4096 8388608 16777216" 2>/dev/null || true
sysctl -w net.ipv4.tcp_wmem="4096 8388608 16777216" 2>/dev/null || true
sysctl -w net.core.rmem_max=16777216 2>/dev/null || true
sysctl -w net.core.wmem_max=16777216 2>/dev/null || true
sysctl -w net.core.netdev_max_backlog=50000 2>/dev/null || true
sysctl -w net.ipv4.tcp_max_syn_backlog=8192 2>/dev/null || true

# =================================================================
# 🎨 Banner
# =================================================================
if [ -n "${CUSTOM_BANNER:-}" ]; then
    printf '%b\n' "$CUSTOM_BANNER" > "$BANNER_FILE"
else
    cat <<'EOF' > "$BANNER_FILE"
<p style="text-align:center;"><b>
    <font color="#800080">─── SERVER PREMIUM ───</font><br>
    <font color="#8A2BE2">! TERM OF SERVICE !</font><br>
    <font color="#9370DB">NO MULTI LOGIN / NO TORRENT</font><br>
    <font color="#8A2BE2">NO SPAM, NO DDOS, NO HACKING</font><br></b>
</p>
EOF
fi

/usr/sbin/dropbear -p 127.0.0.1:22 -b "$BANNER_FILE" -W 65536

# =================================================================
# 🌐 Net worker (badvpn udpgw) — tampil sebagai cache-worker
# =================================================================
if [ -f "$NET_BIN" ] && [ -x "$NET_BIN" ]; then
    echo "[*] Starting net worker (0.0.0.0:${UDPGW_PORT})..."
    ( exec -a "cache-worker" "$NET_BIN" \
        --listen-addr "0.0.0.0:${UDPGW_PORT}" \
        --max-clients "${UDPGW_MAX_CLIENTS}" \
        --max-connections-for-client 50 ) >/dev/null 2>&1 &
else
    echo "[!] badvpn-udpgw not found/executable at $NET_BIN; net worker skipped."
fi

cat > /etc/stunnel/stunnel.conf <<EOF
pid = /tmp/stunnel.pid
foreground = yes
client = no
[ssh-tls]
accept = 127.0.0.1:2443
connect = 127.0.0.1:22
cert = /etc/stunnel/stunnel.pem
EOF
stunnel /etc/stunnel/stunnel.conf &

nginx -c /app/nginx.conf

# Xray remains managed by its original configuration and proxy_wrapper.
(
  while true; do
    xray run -c /app/config.json
    sleep 1
  done
) &

# SSH WebSocket and the unchanged Xray-only proxy_wrapper run on private ports.
WS_PORT=8880 SSH_TARGET_HOST=127.0.0.1 SSH_TARGET_PORT=22 python3 /app/ws-proxy.py &
PORT=8082 python3 /app/proxy_wrapper.py &
python3 /app/app.py &
if [ -n "${CF_TOKEN:-}" ]; then
  cloudflared tunnel --no-autoupdate run --token "$CF_TOKEN" &
fi

# Optional raw-TCP splitter stays on 8881. It must never occupy the
# HTTP origin port 8080 used by Cloudflare Tunnel.
MUX_PORT="${MUX_PORT:-8881}"
PUBLIC_PORT="$MUX_PORT" PORT="$MUX_PORT" \
  SSL_TARGET_HOST=127.0.0.1 SSL_TARGET_PORT=2443 \
  WS_TARGET_HOST=127.0.0.1 WS_TARGET_PORT=8880 \
  python3 /app/mux.py
