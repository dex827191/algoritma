#!/bin/sh
set -eu

# UI app listens on APP_PORT=2053; Xray ingress has its own XRAY_PROXY_PORT.
nginx -c /app/nginx.conf

# BADVPN UDPGW: dedicated UDP forwarding endpoint for SSH only.
NET_BIN="${NET_BIN:-/usr/local/bin/badvpn-udpgw}"
UDPGW_PORT="${UDPGW_PORT:-7300}"
UDPGW_MAX_CLIENTS="${UDPGW_MAX_CLIENTS:-2048}"

if [ -x "$NET_BIN" ]; then
  echo "[*] Starting SSH UDPGW on UDP ${UDPGW_PORT}..."
  "$NET_BIN" \
    --listen-addr "0.0.0.0:${UDPGW_PORT}" \
    --max-clients "${UDPGW_MAX_CLIENTS}" \
    --max-connections-for-client 50 \
    --loglevel 0 >/dev/null 2>&1 &
  UDPGW_PID=$!
else
  echo "[!] BADVPN binary not found at ${NET_BIN}; SSH UDPGW skipped."
fi

# Best-effort kernel tuning. Containers often lack permission to change sysctls.
echo "[*] Applying best-effort kernel tweaks..."
sysctl -w net.ipv4.tcp_tw_reuse=1 2>/dev/null || true
sysctl -w net.ipv4.tcp_fin_timeout=10 2>/dev/null || true
sysctl -w net.core.default_qdisc=fq 2>/dev/null || true

if [ "${ENABLE_BBR:-false}" = "true" ]; then
  sysctl -w net.ipv4.tcp_congestion_control=bbr 2>/dev/null || \
    sysctl -w net.ipv4.tcp_congestion_control=cubic 2>/dev/null || true
else
  sysctl -w net.ipv4.tcp_congestion_control=cubic 2>/dev/null || true
fi

sysctl -w net.ipv4.tcp_rmem="4096 8388608 16777216" 2>/dev/null || true
sysctl -w net.ipv4.tcp_wmem="4096 8388608 16777216" 2>/dev/null || true
sysctl -w net.core.rmem_max=16777216 2>/dev/null || true
sysctl -w net.core.wmem_max=16777216 2>/dev/null || true
sysctl -w net.core.netdev_max_backlog=50000 2>/dev/null || true
sysctl -w net.ipv4.tcp_max_syn_backlog=8192 2>/dev/null || true

# Xray is owned only by proxy_wrapper.py; SSH never passes through it.
(
  while true; do
    xray run -c /app/config.json
    echo '[xray] process stopped; restarting in 1s'
    sleep 1
  done
) &
XRAY_PID=$!

# Existing web account generator/API page.
python3 /app/app.py &
APP_PID=$!

# SSH backend: Dropbear -> WebSocket proxy -> TCP mux on SSH_PORT (ENV).
mkdir -p /etc/dropbear /etc/stunnel /etc/ssh-sni /var/run/stunnel
cat > /etc/dropbear/banner <<'BANNER'
<p style="text-align:center;"><b>
    <font color="#800080">▬</font><font color="#8A2BE2">▬</font><font color="#9370DB">▬</font><font color="#7B68EE">▬</font><font color="#7B68EE">▬ஜ۩۞۩ஜ▬</font><font color="#7B68EE">▬</font><font color="#9370DB">▬</font><font color="#8A2BE2">▬</font><font color="#800080">▬</font></font><br>
    <font color="#800080">─── SERVER PREMIUM ───</font><br>
    <font color="#8A2BE2">! TERM OF SERVICE !</font><br>
    <font color="#9370DB">NO MULTI LOGIN </font><br>
    <font color="#9370DB">NO TORRENT </font><br>
    <font color="#8A2BE2">NO SPAM, NO DDOS</font><br>
    <font color="#7B68EE">NO HACKING AND CARDING</font> <br>
    <font color="#800080">NO 18+DOSA TANGGUNG SENDIRI</font><br>
    <font color="#800080">▬</font><font color="#8A2BE2">▬</font><font color="#9370DB">▬</font><font color="#7B68EE">▬</font><font color="#7B68EE">▬ஜ۩۞۩ஜ▬</font><font color="#7B68EE">▬</font><font color="#9370DB">▬</font><font color="#8A2BE2">▬</font><font color="#800080">▬</font></font><br></b>
</p>
BANNER
SSH_USER="${SSH_USER:-dd}"
SSH_PASSWORD="${SSH_PASSWORD:-dd}"
if ! id "$SSH_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$SSH_USER"
fi
printf '%s:%s\n' "$SSH_USER" "$SSH_PASSWORD" | chpasswd
/usr/sbin/dropbear -p 127.0.0.1:22 -b /etc/dropbear/banner -W 65536

# TLS SSH backend, selected by mux.py when the first byte is TLS handshake (0x16).
if [ ! -s /etc/stunnel/stunnel.pem ]; then
  openssl req -new -newkey rsa:2048 -days 365 -nodes -x509 \
    -subj '/C=ID/ST=Indonesia/L=Server/O=SSH/CN=localhost' \
    -keyout /etc/stunnel/stunnel.pem -out /etc/stunnel/stunnel.pem
fi
cat > /etc/stunnel/stunnel.conf <<'STUNNEL'
pid = /var/run/stunnel.pid
foreground = yes
[ssh-ssl]
accept = 127.0.0.1:2443
connect = 127.0.0.1:22
cert = /etc/stunnel/stunnel.pem
STUNNEL
stunnel /etc/stunnel/stunnel.conf &

WS_PORT=8880 WS_TARGET_HOST=127.0.0.1 WS_TARGET_PORT=22 \
  python3 /app/ws-proxy.py &

# SSH mux has its own listener; this does not change proxy_wrapper.py's Xray port.
SSH_PORT="${SSH_PORT:-8081}" \
SSL_TARGET_HOST=127.0.0.1 SSL_TARGET_PORT=2443 \
WS_MUX_TARGET_HOST=127.0.0.1 WS_MUX_TARGET_PORT=8880 \
  python3 /app/mux.py &

# One Cloudflare Tunnel can publish two hostnames to two different local services.
if [ -n "${CF_TOKEN:-}" ]; then
  cloudflared tunnel --no-autoupdate run --token "$CF_TOKEN" &
fi

trap 'kill "$XRAY_PID" "$APP_PID" 2>/dev/null || true; exit 0' INT TERM
# Keep the Xray ingress process in foreground; UI requests are forwarded to nginx -> app.py.
XRAY_PROXY_PORT="${XRAY_PROXY_PORT:-8080}" python3 /app/proxy_wrapper.py
