#!/bin/sh
set -eu

# Nginx is the single HTTP/WebSocket ingress on port 8080.
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

# Xray runs as a private local service; Nginx routes public HTTP paths to it.
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

# SSH backend: Dropbear is private; WebSocket bridge is routed by Nginx /sshws.
mkdir -p /etc/dropbear /etc/ssh-sni
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

WS_PORT=8880 WS_TARGET_HOST=127.0.0.1 WS_TARGET_PORT=22 \
  python3 /app/ws-proxy.py &

# One Cloudflare Tunnel can publish two hostnames to two different local services.
if [ -n "${CF_TOKEN:-}" ]; then
  cloudflared tunnel --no-autoupdate run --token "$CF_TOKEN" &
fi

trap 'kill "$XRAY_PID" "$APP_PID" 2>/dev/null || true; exit 0' INT TERM
# Keep container alive while Nginx, SSH WS, Xray, panel and optional cloudflared run.
wait
