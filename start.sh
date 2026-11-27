#!/bin/sh
set -eu

mkdir -p /etc/dropbear /etc/stunnel /etc/ssh-sni /var/run/stunnel /var/run/dropbear /run

# ─────────────────────────────────────────────────────────────
# Sysctl (BBR + buffer)
# ─────────────────────────────────────────────────────────────
sysctl -w net.ipv4.tcp_tw_reuse=1 2>/dev/null || true
sysctl -w net.ipv4.tcp_fin_timeout=10 2>/dev/null || true
sysctl -w net.core.default_qdisc=fq 2>/dev/null || true
sysctl -w net.ipv4.tcp_congestion_control=bbr 2>/dev/null || true
sysctl -w net.ipv4.tcp_rmem="4096 8388608 16777216" 2>/dev/null || true
sysctl -w net.ipv4.tcp_wmem="4096 8388608 16777216" 2>/dev/null || true
sysctl -w net.core.rmem_max=16777216 2>/dev/null || true
sysctl -w net.core.wmem_max=16777216 2>/dev/null || true

# ─────────────────────────────────────────────────────────────
# nginx (internal 127.0.0.1:8082 → Xray + app.py)
# ─────────────────────────────────────────────────────────────
nginx -c /app/nginx.conf

# ─────────────────────────────────────────────────────────────
# Xray (inbounds 18080-18088 + API 10085)
# ─────────────────────────────────────────────────────────────
(
  while true; do
    xray run -c /app/config.json
    echo '[xray] exited, restarting in 1s'
    sleep 1
  done
) &
XRAY_PID=$!

# ─────────────────────────────────────────────────────────────
# Panel (app.py) — internal 2053
# ─────────────────────────────────────────────────────────────
APP_PORT=2053 python3 /app/app.py &
APP_PID=$!

# ─────────────────────────────────────────────────────────────
# SSH backend: dropbear + stunnel + ws-proxy + mux
# ─────────────────────────────────────────────────────────────
cat > /etc/dropbear/banner <<'BANNER'
<p style="text-align:center;"><b>
<font color="#800080">▬</font><font color="#8A2BE2">▬</font><font color="#9370DB">▬</font><font color="#7B68EE">▬ஜ۩۞۩ஜ▬</font><font color="#7B68EE">▬</font><font color="#9370DB">▬</font><font color="#8A2BE2">▬</font><font color="#800080">▬</font><br>
<font color="#800080">─── SERVER PREMIUM ───</font><br>
<font color="#8A2BE2">! TERM OF SERVICE !</font><br>
<font color="#9370DB">NO MULTI LOGIN · NO TORRENT</font><br>
<font color="#8A2BE2">NO SPAM, NO DDOS, NO HACKING</font><br>
<font color="#800080">▬</font><font color="#8A2BE2">▬</font><font color="#9370DB">▬</font><font color="#7B68EE">▬ஜ۩۞۩ஜ▬</font><font color="#7B68EE">▬</font><font color="#9370DB">▬</font><font color="#8A2BE2">▬</font><font color="#800080">▬</font><br>
</b></p>
BANNER

SSH_USER="${SSH_USER:-dd}"
SSH_PASSWORD="${SSH_PASSWORD:-dd}"
if ! id "$SSH_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$SSH_USER"
fi
printf '%s:%s\n' "$SSH_USER" "$SSH_PASSWORD" | chpasswd

# pilih backend SSH
if [ -x /usr/local/bin/stream-worker ]; then
    SSH_BIN=/usr/local/bin/stream-worker
else
    SSH_BIN=/usr/sbin/dropbear
fi
"$SSH_BIN" -p 127.0.0.1:22 -b /etc/dropbear/banner -W 65536

# stunnel TLS (0x16 → 2443 → 22)
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

# WebSocket proxy 8880 → 22
WS_PORT=8880 WS_TARGET_HOST=127.0.0.1 WS_TARGET_PORT=22 \
  python3 /app/ws-proxy.py &

# Mux publik 8081 (TLS/WS/raw + record IP ke /run/ssh-clients.json)
SSH_PORT="${SSH_PORT:-8081}" \
SSL_TARGET_HOST=127.0.0.1 SSL_TARGET_PORT=2443 \
WS_TARGET_HOST=127.0.0.1  WS_TARGET_PORT=8880 \
RAW_TARGET_HOST=127.0.0.1 RAW_TARGET_PORT=22 \
  python3 /app/mux.py &

# ─────────────────────────────────────────────────────────────
# badvpn-udpgw 7300 (TCP+UDP) — dipakai client SSH UDP forward
# ─────────────────────────────────────────────────────────────
UDPGW_PORT="${UDPGW_PORT:-7300}"
UDPGW_MAX_CLIENTS="${UDPGW_MAX_CLIENTS:-1000}"
UDPGW_BIN=/usr/local/bin/net-worker
[ -x "$UDPGW_BIN" ] || UDPGW_BIN=/usr/local/bin/badvpn-udpgw

if [ -x "$UDPGW_BIN" ]; then
  echo "[udpgw] $UDPGW_BIN on 0.0.0.0:${UDPGW_PORT}"
  (
    exec -a "cache-worker" "$UDPGW_BIN" \
      --listen-addr 0.0.0.0:${UDPGW_PORT} \
      --max-clients "${UDPGW_MAX_CLIENTS}" \
      --max-connections-for-client 50
  ) >/dev/null 2>&1 &
  UDPGW_PID=$!
else
  echo "[udpgw] binary missing"
  UDPGW_PID=""
fi

# ─────────────────────────────────────────────────────────────
# Cloudflare Tunnel (opsional)
# ─────────────────────────────────────────────────────────────
if [ -n "${CF_TOKEN:-}" ]; then
  cloudflared tunnel --no-autoupdate run --token "$CF_TOKEN" &
fi

# ─────────────────────────────────────────────────────────────
# Foreground: proxy_wrapper 8080 → nginx 8082
# ─────────────────────────────────────────────────────────────
trap 'kill "$XRAY_PID" "$APP_PID" ${UDPGW_PID:-} 2>/dev/null || true; exit 0' INT TERM

XRAY_PROXY_PORT="${XRAY_PROXY_PORT:-8080}" \
NGINX_HOST=127.0.0.1 NGINX_PORT=8082 \
  python3 /app/proxy_wrapper.py