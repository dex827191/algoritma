
#!/bin/bash
set -m

# =================================================================
# KONFIGURASI & ENVIRONMENT
# =================================================================

NET_BIN="/usr/local/bin/badvpn-udpgw"
# UDPGW adalah relay UDP-over-TCP untuk klien SSH saja; tidak terkait Xray.
SSH_UDPGW_PORT="${SSH_UDPGW_PORT:-${UDPGW_PORT:-7300}}"
SSH_UDPGW_MAX_CLIENTS="${SSH_UDPGW_MAX_CLIENTS:-${UDPGW_MAX_CLIENTS:-1000}}"
ENABLE_SSH_UDPGW="${ENABLE_SSH_UDPGW:-true}"
ENABLE_BBR="${ENABLE_BBR:-true}"

NGINX_CONFIG="/app/nginx.conf"
NGINX_PORT="8082"

export XRAY_PROXY_PORT="${XRAY_PROXY_PORT:-8080}"
export SSH_PORT="${SSH_PORT:-8081}"
export APP_PORT="${APP_PORT:-2053}"

# =================================================================
# VALIDASI PORT
# =================================================================

if [ "$APP_PORT" = "8080" ]; then
    echo "[!] APP_PORT bentrok dengan proxy. Menggunakan 2053."
    export APP_PORT=2053
fi

if [ "$APP_PORT" = "$XRAY_PROXY_PORT" ]; then
    echo "[!] APP_PORT bentrok dengan XRAY_PROXY_PORT."
    export APP_PORT=2053
fi

echo "=========================================================="
echo "[i] KONFIGURASI PORT"
echo "    APP_PORT        : ${APP_PORT}"
echo "    XRAY_PROXY_PORT : ${XRAY_PROXY_PORT}"
echo "    NGINX_PORT      : ${NGINX_PORT}"
echo "    SSH_PORT        : ${SSH_PORT}"
echo "    SSH_UDPGW_PORT  : ${SSH_UDPGW_PORT}"
echo "    SSH_UDPGW       : ${ENABLE_SSH_UDPGW}"
echo "=========================================================="

# =================================================================
# INISIALISASI UTMP / WTMP
# =================================================================

echo "[*] Inisialisasi utmp/wtmp..."

touch /run/utmp /var/run/utmp 2>/dev/null || true
touch /var/log/wtmp /var/log/btmp 2>/dev/null || true

chmod 664 /run/utmp /var/run/utmp 2>/dev/null || true
chmod 664 /var/log/wtmp /var/log/btmp 2>/dev/null || true

# =================================================================
# DROPBEAR HOST KEYS
# =================================================================

mkdir -p /etc/dropbear

if [ ! -f /etc/dropbear/dropbear_ed25519_host_key ]; then
    echo "[*] Generate Dropbear ed25519 key..."

    dropbearkey -t ed25519 \
        -f /etc/dropbear/dropbear_ed25519_host_key
fi

if [ ! -f /etc/dropbear/dropbear_rsa_host_key ]; then
    echo "[*] Generate Dropbear RSA key..."

    dropbearkey -t rsa -s 2048 \
        -f /etc/dropbear/dropbear_rsa_host_key
fi

# =================================================================
# DROPBEAR BANNER
# =================================================================

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

# =================================================================
# START DROPBEAR
# =================================================================

echo "[*] Starting Dropbear..."

dropbear \
    -p 127.0.0.1:22 \
    -E -a \
    -b /etc/dropbear/banner &

sleep 1

# =================================================================
# STUNNEL
# =================================================================

if [ ! -f /etc/stunnel/stunnel.pem ]; then

    echo "[*] Generate stunnel certificate..."

    openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
        -keyout /etc/stunnel/stunnel.key \
        -out /etc/stunnel/stunnel.crt \
        -subj "/CN=localhost" 2>/dev/null

    cat /etc/stunnel/stunnel.key \
        /etc/stunnel/stunnel.crt \
        > /etc/stunnel/stunnel.pem

    chmod 600 /etc/stunnel/stunnel.pem
fi

mkdir -p /var/run/stunnel

cat > /etc/stunnel/stunnel.conf <<EOF
pid = /var/run/stunnel/stunnel.pid
foreground = yes

[ssh-tls]
accept = 127.0.0.1:2443
connect = 127.0.0.1:22
cert = /etc/stunnel/stunnel.pem
EOF

echo "[*] Starting stunnel..."

stunnel4 /etc/stunnel/stunnel.conf &

# =================================================================
# BADVPN UDPGW - KHUSUS KLIEN SSH
# UDPGW BadVPN menerima koneksi TCP (UDP-over-TCP), bukan listener UDP.
# Xray tidak diarahkan dan tidak menggunakan layanan ini.
# =================================================================

if [ "$ENABLE_SSH_UDPGW" = "true" ]; then
    if [ -x "$NET_BIN" ]; then
        echo "[*] Starting SSH UDPGW (TCP) on 0.0.0.0:${SSH_UDPGW_PORT}..."

        nohup "$NET_BIN" \
            --listen-addr "0.0.0.0:${SSH_UDPGW_PORT}" \
            --max-clients "${SSH_UDPGW_MAX_CLIENTS}" \
            --max-connections-for-client 50 \
            --loglevel 0 >/var/log/ssh-udpgw.log 2>&1 &

        SSH_UDPGW_PID=$!
        sleep 1
        if kill -0 "$SSH_UDPGW_PID" 2>/dev/null; then
            echo "[OK] SSH UDPGW aktif pada TCP ${SSH_UDPGW_PORT}."
        else
            echo "[!] SSH UDPGW gagal start. Periksa /var/log/ssh-udpgw.log."
        fi
    else
        echo "[!] Binary BadVPN tidak ditemukan. SSH UDPGW dilewati."
    fi
else
    echo "[i] SSH UDPGW dinonaktifkan (ENABLE_SSH_UDPGW=false)."
fi

# =================================================================
# KERNEL TWEAKS
# =================================================================

echo "[*] Tuning kernel..."

sysctl -w net.ipv4.tcp_tw_reuse=1 2>/dev/null || true
sysctl -w net.ipv4.tcp_fin_timeout=10 2>/dev/null || true
sysctl -w net.core.default_qdisc=fq 2>/dev/null || true

if [ "$ENABLE_BBR" = "true" ]; then

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

# =================================================================
# START XRAY
# =================================================================

echo "[*] Starting Xray..."

xray -c /app/config.json &
XRAY_PID=$!

sleep 2

if ! kill -0 "$XRAY_PID" 2>/dev/null; then

    echo "[FATAL] Xray gagal start."
    echo "[FATAL] Periksa /app/config.json."

    exit 1
fi

echo "[OK] Xray process berjalan."

# =================================================================
# START UI PANEL
# =================================================================

echo "[*] Starting app.py..."

APP_PORT="${APP_PORT}" \
APP_HOST="127.0.0.1" \
python3 /app/app.py &

APP_PID=$!

sleep 2

if ! kill -0 "$APP_PID" 2>/dev/null; then

    echo "[FATAL] app.py gagal start."

    exit 1
fi

echo "[OK] UI process berjalan."

# =================================================================
# NGINX CONFIGURATION
# =================================================================

echo "=========================================================="
echo "[*] Memeriksa konfigurasi Nginx..."
echo "    Config: ${NGINX_CONFIG}"
echo "    Port  : ${NGINX_PORT}"
echo "=========================================================="

if [ ! -f "$NGINX_CONFIG" ]; then

    echo "[FATAL] File nginx.conf tidak ditemukan!"
    echo "[FATAL] Lokasi yang diperlukan: ${NGINX_CONFIG}"

    exit 1
fi

# Hentikan nginx bawaan jika ada
nginx -s quit 2>/dev/null || true

# Test konfigurasi yang benar
if ! nginx -t -c "$NGINX_CONFIG"; then

    echo "[FATAL] Konfigurasi Nginx tidak valid."

    exit 1
fi

echo "[OK] Konfigurasi Nginx valid."

# =================================================================
# START NGINX
# =================================================================

echo "[*] Starting Nginx..."

nginx -g 'daemon off;' -c "$NGINX_CONFIG" &

NGINX_PID=$!

sleep 2

if ! kill -0 "$NGINX_PID" 2>/dev/null; then

    echo "[FATAL] Nginx gagal start."

    exit 1
fi

if command -v ss >/dev/null 2>&1; then

    if ! ss -lnt 2>/dev/null | grep -q "127.0.0.1:${NGINX_PORT}"; then

        echo "[FATAL] Nginx tidak listen di ${NGINX_PORT}."

        exit 1
    fi

fi

echo "[OK] Nginx aktif di 127.0.0.1:${NGINX_PORT}"

# =================================================================
# START PROXY WRAPPER
# =================================================================

echo "[*] Starting proxy_wrapper.py..."

XRAY_PROXY_PORT="${XRAY_PROXY_PORT}" \
python3 /app/proxy_wrapper.py &

PROXY_PID=$!

sleep 2

if ! kill -0 "$PROXY_PID" 2>/dev/null; then

    echo "[FATAL] proxy_wrapper.py gagal berjalan."

    exit 1
fi

if command -v ss >/dev/null 2>&1; then

    if ! ss -lnt 2>/dev/null | grep -q "0.0.0.0:${XRAY_PROXY_PORT}"; then

        echo "[FATAL] Port ${XRAY_PROXY_PORT} tidak listen."

        exit 1
    fi

fi

echo "[OK] Proxy aktif di 0.0.0.0:${XRAY_PROXY_PORT}"

# =================================================================
# START SSH WEBSOCKET
# =================================================================

echo "[*] Starting ws-proxy.py..."

WS_PORT=8880 python3 /app/ws-proxy.py &

WS_PID=$!

sleep 1

if ! kill -0 "$WS_PID" 2>/dev/null; then
    echo "[!] WS SSH gagal berjalan."
else
    echo "[OK] WS SSH aktif di port 8880."
fi

# =================================================================
# START SSH MUX
# =================================================================

echo "[*] Starting mux.py..."

SSH_PORT="${SSH_PORT}" python3 /app/mux.py &

MUX_PID=$!

sleep 1

if ! kill -0 "$MUX_PID" 2>/dev/null; then
    echo "[!] SSH Mux gagal berjalan."
else
    echo "[OK] SSH Mux aktif di port ${SSH_PORT}."
fi

# =================================================================
# CLOUDFLARE TUNNEL
# =================================================================

if [ -n "${CF_TOKEN:-}" ]; then

    if command -v cloudflared >/dev/null 2>&1; then

        echo "[*] Starting Cloudflare Tunnel..."

        nohup cloudflared tunnel \
            --no-autoupdate run \
            --token "$CF_TOKEN" \
            >/var/log/cloudflared.log 2>&1 &

        CF_PID=$!

        sleep 2

        if kill -0 "$CF_PID" 2>/dev/null; then

            echo "[OK] Cloudflare Tunnel berjalan."
            echo "[i] Log: /var/log/cloudflared.log"

        else

            echo "[!] Cloudflare Tunnel gagal start."
            echo "[!] Periksa /var/log/cloudflared.log"

        fi

    else

        echo "[!] cloudflared tidak ditemukan."

    fi

else

    echo "[i] CF_TOKEN kosong. Tunnel dilewati."

fi

# =================================================================
# FINAL STATUS
# =================================================================

sleep 1

echo ""
echo "=========================================================="
echo "[✓] SEMUA SERVICE SELESAI DIJALANKAN"
echo "=========================================================="

echo "UI Panel    : http://0.0.0.0:${XRAY_PROXY_PORT}/"
echo "Proxy       : ${XRAY_PROXY_PORT}"
echo "Nginx       : 127.0.0.1:${NGINX_PORT}"
echo "App UI      : 127.0.0.1:${APP_PORT}"
echo "SSH Mux     : 0.0.0.0:${SSH_PORT}"
echo "WS SSH      : 0.0.0.0:8880"
if [ "$ENABLE_SSH_UDPGW" = "true" ]; then
    echo "SSH UDPGW   : 0.0.0.0:${SSH_UDPGW_PORT}/tcp"
else
    echo "SSH UDPGW   : DISABLED"
fi
echo "Xray UDPGW  : TIDAK DIGUNAKAN"

if [ -n "${CF_TOKEN:-}" ]; then
    echo "Cloudflare  : Tunnel aktif"
fi

echo "=========================================================="

# =================================================================
# MONITOR PROSES
# =================================================================

wait
