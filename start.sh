#!/bin/sh
set -eu
cd /app
mkdir -p /etc/dropbear /etc/stunnel /etc/ssh-sni /var/run/dropbear

cat > /etc/dropbear/dropbear_banner <<'EOF'
=================================================
              SSH WEBSOCKET SERVER
          Dropbear SSH - Managed Panel
=================================================
Gunakan layanan secara legal dan bertanggung jawab.
=================================================
EOF

# SSH daemon hanya listen di loopback; akses publik dipilah oleh mux.py.
if ! id "${SSH_USER:-}" >/dev/null 2>&1 && [ -n "${SSH_USER:-}" ] && [ -n "${SSH_PASSWORD:-}" ]; then
  python3 /usr/local/bin/addssh "$SSH_USER" "$SSH_PASSWORD" "${SSH_EXPIRE_DAYS:-0}" || true
fi
/usr/sbin/dropbear -E -F -p "127.0.0.1:${SSH_TARGET_PORT:-22}" \
  -b /etc/dropbear/dropbear_banner -W 65536 >/tmp/dropbear.log 2>&1 &

# TLS-over-SSH backend (stunnel -> Dropbear).
openssl req -new -newkey rsa:2048 -days 3650 -nodes -x509 \
  -subj "/C=ID/O=SSH-Panel/CN=localhost" \
  -keyout /etc/stunnel/stunnel.pem -out /etc/stunnel/stunnel.pem >/dev/null 2>&1
chmod 600 /etc/stunnel/stunnel.pem
cat > /etc/stunnel/stunnel.conf <<EOF
foreground = yes
pid = /tmp/stunnel.pid
debug = 4
[ssh-tls]
accept = 127.0.0.1:${SSL_INTERNAL_PORT:-2443}
connect = 127.0.0.1:${SSH_TARGET_PORT:-22}
cert = /etc/stunnel/stunnel.pem
EOF
stunnel /etc/stunnel/stunnel.conf >/tmp/stunnel.log 2>&1 &

# Xray + Nginx remain independent from SSH transport.
nginx -c /app/nginx.conf
(
  while :; do
    xray run -c /app/config.json
    sleep 2
  done
) >/tmp/xray.log 2>&1 &

# Embedded HTML panel + SSH WS transport + unchanged Xray wrapper on private ports.
python3 /app/app.py >/tmp/app.log 2>&1 &
WS_PORT="${WS_INTERNAL_PORT:-8880}" WS_TARGET_HOST=127.0.0.1 \
  WS_TARGET_PORT="${SSH_TARGET_PORT:-22}" python3 /app/ws-proxy.py >/tmp/ws-proxy.log 2>&1 &
PORT="${XRAY_WRAPPER_PORT:-8082}" python3 /app/proxy_wrapper.py >/tmp/xray-wrapper.log 2>&1 &

if [ -n "${CF_TOKEN:-}" ]; then
  cloudflared tunnel --no-autoupdate run --token "$CF_TOKEN" >/tmp/cloudflared.log 2>&1 &
fi

sleep 2
exec env \
  PORT="${PORT:-8080}" \
  SSL_TARGET_HOST=127.0.0.1 SSL_TARGET_PORT="${SSL_INTERNAL_PORT:-2443}" \
  WS_MUX_TARGET_HOST=127.0.0.1 WS_MUX_TARGET_PORT="${WS_INTERNAL_PORT:-8880}" \
  SSH_TARGET_HOST=127.0.0.1 SSH_TARGET_PORT="${SSH_TARGET_PORT:-22}" \
  XRAY_TARGET_HOST=127.0.0.1 XRAY_TARGET_PORT="${XRAY_WRAPPER_PORT:-8082}" \
  APP_TARGET_HOST=127.0.0.1 APP_TARGET_PORT=2053 \
  python3 /app/mux.py
