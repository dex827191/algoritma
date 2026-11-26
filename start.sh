#!/bin/sh
set -eu

PORT="${PORT:-8080}"
SSL_INTERNAL_PORT="${SSL_INTERNAL_PORT:-2443}"
WS_INTERNAL_PORT="${WS_INTERNAL_PORT:-8880}"

ulimit -n 65535 2>/dev/null || true

# Mount a Railway Volume at /data to preserve accounts and Xray configuration.
mkdir -p /data
if [ ! -s /data/config.json ]; then cp /app/config.json /data/config.json; fi
[ -s /data/ssh-users.json ] || printf '[]\n' > /data/ssh-users.json
[ -s /data/xray-accounts.json ] || printf '[]\n' > /data/xray-accounts.json

# Restore panel-created SSH users from password hashes stored on the persistent volume.
if command -v jq >/dev/null 2>&1 && [ -s /data/ssh-users.json ]; then
    jq -c '.[]' /data/ssh-users.json | while IFS= read -r item; do
        name="$(printf '%s' "$item" | jq -r '.username // empty')"
        hash="$(printf '%s' "$item" | jq -r '.password_hash // empty')"
        case "$name" in
            ''|*[!a-zA-Z0-9_-]*) continue ;;
        esac
        if [ -n "$hash" ] && ! id "$name" >/dev/null 2>&1; then
            useradd -m -s /bin/bash -p "$hash" "$name" || true
        fi
    done
fi

cat > /etc/dropbear_banner <<'EOF'
=================================================
                  SELAMAT MENIKMATI
             PREMIUM SSH SERVER DROPBEAR modssh3
=================================================
       Dilarang Torrent / DDOS / Hacking!
                 Powered By: dedefathu
=================================================
EOF

# Generate a local certificate for SSH-over-TLS (Stunnel).
if [ ! -s /etc/stunnel/stunnel.pem ]; then
    openssl req -new -newkey rsa:2048 -days 365 -nodes -x509 \
      -subj "/C=ID/O=SSH-Proxy/CN=localhost" \
      -keyout /tmp/stunnel.key -out /tmp/stunnel.crt >/dev/null 2>&1
    cat /tmp/stunnel.key /tmp/stunnel.crt > /etc/stunnel/stunnel.pem
    chmod 600 /etc/stunnel/stunnel.pem
    rm -f /tmp/stunnel.key /tmp/stunnel.crt
fi

# Internal SSH listener.
dropbear -F -E -p 127.0.0.1:22 -b /etc/dropbear_banner -W 65536 &
cat > /etc/stunnel/stunnel.conf <<EOF
foreground = yes
pid = /tmp/stunnel.pid
[ssh-tls]
accept = 127.0.0.1:${SSL_INTERNAL_PORT}
connect = 127.0.0.1:22
cert = /etc/stunnel/stunnel.pem
EOF
stunnel /etc/stunnel/stunnel.conf >/dev/stdout 2>&1 &

# Internal SSH-over-WebSocket listener.
WS_PORT="$WS_INTERNAL_PORT" SSH_TARGET="127.0.0.1:22" /usr/local/bin/ssh-wsproxy &

# Nginx remains the reverse proxy for all existing Xray transports.
nginx -c /app/nginx.conf

# Xray is restarted by this loop after account changes.
(
  while :; do
    /usr/local/bin/xray run -c /data/config.json
    sleep 1
  done
) &

# BadVPN UDPGW lokal untuk klien yang memerlukan UDP forwarding.
echo "[*] Memulai BadVPN UDPGW Engine di Port Lokal 7300..."
/usr/local/bin/badvpn-udpgw \
    --listen-addr 127.0.0.1:7300 \
    --max-clients 500 \
    --max-connections-for-client 20 \
    --loglevel warning &

# Optional Cloudflare Tunnel.
if [ -n "${CF_TUNNEL_TOKEN:-}" ]; then
    cloudflared tunnel --no-autoupdate run --token "$CF_TUNNEL_TOKEN" &
fi

echo "[*] Memulai Multiplexer Publik (Golang Engine) di Port PUBLIK ${PORT}..."
exec env \
    PORT="$PORT" \
    SSL_TARGET_HOST="127.0.0.1" \
    SSL_TARGET_PORT="$SSL_INTERNAL_PORT" \
    WS_MUX_TARGET_HOST="127.0.0.1" \
    WS_MUX_TARGET_PORT="$WS_INTERNAL_PORT" \
    /usr/local/bin/mux
