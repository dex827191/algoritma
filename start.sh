
#!/bin/sh
set -eu

# =========================================================
# ENVIRONMENT
# =========================================================
PORT="${PORT:-8080}"
SSL_INTERNAL_PORT="${SSL_INTERNAL_PORT:-2443}"
WS_INTERNAL_PORT="${WS_INTERNAL_PORT:-8880}"
DATA_DIR="${DATA_DIR:-/data}"
DOMAIN="${DOMAIN:-}"
export DOMAIN

umask 077

ulimit -n 65535 2>/dev/null || true

echo "================================================="
echo "       PREMIUM SSH SERVER DROPBEAR modssh3"
echo "================================================="


# =========================================================
# REQUIRED DIRECTORIES
# =========================================================
mkdir -p \
    "$DATA_DIR" \
    /etc/dropbear \
    /var/run/dropbear \
    /etc/stunnel \
    /var/run/stunnel \
    /tmp


# =========================================================
# CHECK REQUIRED COMMANDS
# =========================================================
for cmd in \
    jq \
    openssl \
    nginx \
    dropbear \
    dropbearkey \
    useradd
do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[ERROR] Command tidak ditemukan: $cmd"
        exit 1
    fi
done


# =========================================================
# CHECK REQUIRED BINARIES
# =========================================================
for file in \
    /usr/local/bin/mux \
    /usr/local/bin/ssh-wsproxy \
    /usr/local/bin/xray/xray \
    /usr/local/bin/badvpn-udpgw
do
    if [ ! -x "$file" ]; then
        echo "[ERROR] Binary tidak ditemukan: $file"
        exit 1
    fi
done


# =========================================================
# PERSISTENT CONFIGURATION
# =========================================================
echo "[*] Memeriksa konfigurasi..."

if [ ! -s "$DATA_DIR/config.json" ]; then
    cp /app/config.json "$DATA_DIR/config.json"
fi

if [ ! -s "$DATA_DIR/ssh-users.json" ]; then
    printf '[]\n' > "$DATA_DIR/ssh-users.json"
fi

if [ ! -s "$DATA_DIR/xray-accounts.json" ]; then
    printf '[]\n' > "$DATA_DIR/xray-accounts.json"
fi


# =========================================================
# VALIDATE JSON
# =========================================================
jq -e 'type == "object"' \
    "$DATA_DIR/config.json" >/dev/null

jq -e 'type == "array"' \
    "$DATA_DIR/ssh-users.json" >/dev/null

jq -e 'type == "array"' \
    "$DATA_DIR/xray-accounts.json" >/dev/null


# =========================================================
# RESTORE SSH USERS
# =========================================================
echo "[*] Memulihkan akun SSH..."

jq -c '.[]' "$DATA_DIR/ssh-users.json" |
while IFS= read -r item; do

    name="$(printf '%s' "$item" | jq -r '.username // empty')"
    hash="$(printf '%s' "$item" | jq -r '.password_hash // empty')"

    case "$name" in
        ''|*[!a-zA-Z0-9_-]*)
            continue
            ;;
    esac

    if [ "${#name}" -gt 32 ]; then
        continue
    fi

    if [ -n "$hash" ] && ! id "$name" >/dev/null 2>&1; then
        echo "[*] Membuat user: $name"
        useradd -m -s /bin/bash -p "$hash" "$name" || true
    fi

done


# =========================================================
# DROPBEAR BANNER
# =========================================================
cat > /etc/dropbear_banner <<'EOF'
=================================================
                  SELAMAT MENIKMATI
             PREMIUM SSH SERVER DROPBEAR modssh3
=================================================
       Dilarang Torrent / DDOS / Hacking!
                 Powered By: dedefathu
=================================================
EOF


# =========================================================
# DROPBEAR HOST KEY
# =========================================================
if [ ! -s /etc/dropbear/dropbear_ed25519_host_key ]; then

    echo "[*] Membuat Dropbear host key..."

    dropbearkey \
        -t ed25519 \
        -f /etc/dropbear/dropbear_ed25519_host_key

fi

chmod 600 /etc/dropbear/dropbear_ed25519_host_key


# =========================================================
# STUNNEL CERTIFICATE
# =========================================================
echo "[*] Memeriksa sertifikat Stunnel..."

mkdir -p /etc/stunnel /var/run/stunnel

if [ ! -s /etc/stunnel/stunnel.pem ]; then

    openssl req \
        -new \
        -newkey rsa:2048 \
        -days 365 \
        -nodes \
        -x509 \
        -subj "/C=ID/O=SSH-Proxy/CN=localhost" \
        -keyout /tmp/stunnel.key \
        -out /tmp/stunnel.crt \
        >/dev/null 2>&1

    cat \
        /tmp/stunnel.key \
        /tmp/stunnel.crt \
        > /etc/stunnel/stunnel.pem

    chmod 600 /etc/stunnel/stunnel.pem

    rm -f /tmp/stunnel.key /tmp/stunnel.crt

fi


# =========================================================
# DROPBEAR SSH INTERNAL
# =========================================================
echo "[*] Memulai Dropbear SSH..."

dropbear \
    -F \
    -E \
    -p 127.0.0.1:22 \
    -b /etc/dropbear_banner \
    -r /etc/dropbear/dropbear_ed25519_host_key \
    -W 65536 &


# =========================================================
# STUNNEL SSH SSL
# =========================================================
echo "[*] Mengonfigurasi Stunnel..."

cat > /etc/stunnel/stunnel.conf <<EOF
foreground = yes
pid = /tmp/stunnel.pid

[ssh-tls]
accept = 127.0.0.1:${SSL_INTERNAL_PORT}
connect = 127.0.0.1:22
cert = /etc/stunnel/stunnel.pem
EOF

if command -v stunnel >/dev/null 2>&1; then
    STUNNEL_BIN="stunnel"
elif command -v stunnel4 >/dev/null 2>&1; then
    STUNNEL_BIN="stunnel4"
else
    echo "[ERROR] Stunnel tidak ditemukan"
    exit 1
fi

"$STUNNEL_BIN" /etc/stunnel/stunnel.conf \
    >/dev/stdout 2>&1 &


# =========================================================
# SSH WEBSOCKET
# =========================================================
echo "[*] Memulai SSH WebSocket..."

WS_PORT="$WS_INTERNAL_PORT" \
SSH_TARGET="127.0.0.1:22" \
/usr/local/bin/ssh-wsproxy &


# =========================================================
# NGINX
# =========================================================
echo "[*] Memeriksa konfigurasi Nginx..."

nginx -t -c /etc/nginx/nginx.conf

echo "[*] Memulai Nginx..."

nginx -c /etc/nginx/nginx.conf


# =========================================================
# XRAY CORE
# =========================================================
echo "[*] Memulai Xray Core..."

(
    while :; do

        echo "[*] Menjalankan Xray..."

        /usr/local/bin/xray/xray \
            run \
            -c "$DATA_DIR/config.json"

        echo "[WARNING] Xray berhenti. Restart dalam 3 detik..."

        sleep 3

    done
) &


# =========================================================
# BADVPN UDPGW
# =========================================================
echo "[*] Memulai BadVPN UDPGW Engine di Port Lokal 7300..."

/usr/local/bin/badvpn-udpgw \
    --listen-addr 127.0.0.1:7300 \
    --max-clients 500 \
    --max-connections-for-client 20 \
    --loglevel warning &


# =========================================================
# CLOUDFLARE TUNNEL
# =========================================================
if [ -n "${CF_TUNNEL_TOKEN:-}" ]; then

    echo "[*] Memulai Cloudflare Tunnel..."

    /usr/local/bin/cloudflared \
        tunnel \
        --no-autoupdate \
        run \
        --token "$CF_TUNNEL_TOKEN" &

else

    echo "[INFO] CF_TUNNEL_TOKEN tidak tersedia. Tunnel dilewati."

fi


# =========================================================
# PUBLIC MULTIPLEXER
# =========================================================
echo "================================================="
echo "[*] Memulai Multiplexer Publik"
echo "[*] Public Port: ${PORT}"
echo "[*] SSL Internal: ${SSL_INTERNAL_PORT}"
echo "[*] WS Internal: ${WS_INTERNAL_PORT}"
echo "================================================="

exec env \
    PORT="$PORT" \
    SSL_TARGET_HOST="127.0.0.1" \
    SSL_TARGET_PORT="$SSL_INTERNAL_PORT" \
    WS_MUX_TARGET_HOST="127.0.0.1" \
    WS_MUX_TARGET_PORT="$WS_INTERNAL_PORT" \
    /usr/local/bin/mux
    
