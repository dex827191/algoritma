#!/bin/sh
set -eu

# UI + Xray reverse proxy: public/local port 8080.
nginx -c /app/nginx.conf

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

# SSH backend: Dropbear -> WebSocket proxy -> TCP mux on 8081.
mkdir -p /etc/dropbear /etc/stunnel /etc/ssh-sni /var/run/stunnel
cat > /etc/dropbear/banner <<'BANNER'
=================================================
             SSH SERVER - DROPBEAR
=================================================
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
MAIN_MUX_PORT=8081 \
SSL_TARGET_HOST=127.0.0.1 SSL_TARGET_PORT=2443 \
WS_MUX_TARGET_HOST=127.0.0.1 WS_MUX_TARGET_PORT=8880 \
  python3 /app/mux.py &

# One Cloudflare Tunnel can publish two hostnames to two different local services.
if [ -n "${CF_TOKEN:-}" ]; then
  cloudflared tunnel --no-autoupdate run --token "$CF_TOKEN" &
fi

trap 'kill "$XRAY_PID" "$APP_PID" 2>/dev/null || true; exit 0' INT TERM
# Keep the Xray/UI ingress process in foreground.
exec python3 /app/proxy_wrapper.py
