#!/bin/bash
set -m

# =================================================================
# Konfigurasi & Environment
# =================================================================
NET_BIN="/usr/local/bin/badvpn-udpgw"
UDPGW_PORT="${UDPGW_PORT:-7300}"
UDPGW_MAX_CLIENTS="${UDPGW_MAX_CLIENTS:-1000}"
ENABLE_BBR="${ENABLE_BBR:-true}"

export XRAY_PROXY_PORT="${XRAY_PROXY_PORT:-8080}"
export SSH_PORT="${SSH_PORT:-8081}"
export APP_PORT="${APP_PORT:-2053}"

# =================================================================
# Guard: cegah bentrok port 8080 antara app.py dan proxy_wrapper.py
# =================================================================
if [ "$APP_PORT" = "8080" ]; then
    echo "[!] APP_PORT=8080 bentrok dengan proxy_wrapper.py. Paksa ke 2053."
    export APP_PORT=2053
fi

if [ "$APP_PORT" = "$XRAY_PROXY_PORT" ]; then
    echo "[!] APP_PORT=${APP_PORT} sama dengan XRAY_PROXY_PORT. Geser UI ke 2053."
    export APP_PORT=2053
fi

echo "=========================================================="
echo "[i] Konfigurasi port:"
echo "    APP_PORT (UI internal)   = ${APP_PORT}"
echo "    XRAY_PROXY_PORT (publik) = ${XRAY_PROXY_PORT}"
echo "    SSH_PORT (mux publik)    = ${SSH_PORT}"
echo "    UDPGW_PORT (UDP relay)   = ${UDPGW_PORT}"
echo "=========================================================="

# =================================================================
# Utmp init — WAJIB agar `who` & panel bisa deteksi user SSH
# =================================================================
echo "[*] Inisialisasi utmp/wtmp..."
touch /run/utmp /var/run/utmp 2>/dev/null || true
touch /var/log/wtmp /var/log/btmp 2>/dev/null || true
chmod 664 /run/utmp /var/run/utmp 2>/dev/null || true
chmod 664 /var/log/wtmp /var/log/btmp 2>/dev/null || true

# =================================================================
# Dropbear host keys
# =================================================================
mkdir -p /etc/dropbear
if [ ! -f /etc/dropbear/dropbear_ed25519_host_key ]; then
    echo "[*] Generate Dropbear ed25519 key..."
    dropbearkey -t ed25519 -f /etc/dropbear/dropbear_ed25519_host_key
fi
if [ ! -f /etc/dropbear/dropbear_rsa_host_key ]; then
    echo "[*] Generate Dropbear RSA key..."
    dropbearkey -t rsa -s 2048 -f /etc/dropbear/dropbear_rsa_host_key
fi

# =================================================================
# Dropbear Banner (SELALU ditulis ulang — premium banner)
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
# Start Dropbear (port 22 internal, dengan banner)
# =================================================================
echo "[*] Starting Dropbear (127.0.0.1:22) with premium banner..."
dropbear -p 127.0.0.1:22 -E -a -b /etc/dropbear/banner &
sleep 1

# =================================================================
# stunnel (TLS termination untuk SSH via TLS)
# =================================================================
if [ ! -f /etc/stunnel/stunnel.pem ]; then
    echo "[*] Generate stunnel cert..."
    openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
        -keyout /etc/stunnel/stunnel.key \
        -out /etc/stunnel/stunnel.crt \
        -subj "/CN=localhost" 2>/dev/null
    cat /etc/stunnel/stunnel.key /etc/stunnel/stunnel.crt > /etc/stunnel/stunnel.pem
    chmod 600 /etc/stunnel/stunnel.pem
fi

cat > /etc/stunnel/stunnel.conf <<EOF
pid = /var/run/stunnel/stunnel.pid
foreground = yes
[ssh-tls]
accept = 127.0.0.1:2443
connect = 127.0.0.1:22
cert = /etc/stunnel/stunnel.pem
EOF

echo "[*] Starting stunnel (127.0.0.1:2443)..."
stunnel4 /etc/stunnel/stunnel.conf &

# =================================================================
# Badvpn udpgw — UDP over SSH tunnel relay
# =================================================================
if [ -f "$NET_BIN" ]; then
    echo "[*] Starting net worker udpgw (0.0.0.0:${UDPGW_PORT})..."
    nohup "$NET_BIN" \
        --listen-addr "0.0.0.0:${UDPGW_PORT}" \
        --max-clients "${UDPGW_MAX_CLIENTS}" \
        --max-connections-for-client 50 \
        --loglevel 0 >/dev/null 2>&1 &
else
    echo "[!] $NET_BIN tidak ditemukan, udpgw dilewati."
fi

# =================================================================
# Kernel tweaks (butuh --cap-add=NET_ADMIN; kalau gagal, fallback aman)
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
# Start Xray
# =================================================================
echo "[*] Starting Xray..."
xray -c /app/config.json &
XRAY_PID=$!
sleep 1

if ! kill -0 $XRAY_PID 2>/dev/null; then
    echo "[FATAL] Xray gagal start. Cek /app/config.json."
    exit 1
fi

# =================================================================
# Start app.py (UI Panel) — internal 127.0.0.1:APP_PORT
# =================================================================
echo "[*] Starting app.py (panel) di 127.0.0.1:${APP_PORT}..."
APP_PORT=${APP_PORT} python3 /app/app.py &
APP_PID=$!
sleep 1

if ! kill -0 $APP_PID 2>/dev/null; then
    echo "[FATAL] app.py gagal start. Cek log di atas."
    exit 1
fi

# =================================================================
# Start nginx (reverse proxy internal 127.0.0.1:8082)
# =================================================================
echo "[*] Starting nginx (127.0.0.1:8082)..."
nginx -g 'daemon off;' -c /etc/nginx/nginx.conf &
NGINX_PID=$!
sleep 1

if ! kill -0 $NGINX_PID 2>/dev/null; then
    echo "[FATAL] nginx gagal start. Cek /etc/nginx/nginx.conf."
    exit 1
fi

# =================================================================
# Start proxy_wrapper.py (GATEWAY PUBLIK) — 0.0.0.0:XRAY_PROXY_PORT
# =================================================================
echo "[*] Starting proxy_wrapper.py di 0.0.0.0:${XRAY_PROXY_PORT}..."
XRAY_PROXY_PORT=${XRAY_PROXY_PORT} python3 /app/proxy_wrapper.py &
PROXY_PID=$!
sleep 2

if ! kill -0 $PROXY_PID 2>/dev/null; then
    echo "[FATAL] proxy_wrapper.py mati! Cek log di atas."
    exit 1
fi

# Verifikasi port publik benar-benar listen
if command -v ss >/dev/null 2>&1; then
    if ! ss -tln 2>/dev/null | grep -q ":${XRAY_PROXY_PORT} "; then
        echo "[FATAL] Port ${XRAY_PROXY_PORT} tidak listen. Railway health check akan gagal."
        exit 1
    fi
fi

echo "[OK] Gateway publik aktif di 0.0.0.0:${XRAY_PROXY_PORT}"

# =================================================================
# Start ws-proxy.py (SSH via WebSocket) — 0.0.0.0:8880
# =================================================================
echo "[*] Starting ws-proxy.py di 0.0.0.0:8880..."
WS_PORT=8880 python3 /app/ws-proxy.py &
sleep 1

# =================================================================
# Start mux.py (SSH TCP/TLS) — 0.0.0.0:SSH_PORT
# =================================================================
echo "[*] Starting mux.py di 0.0.0.0:${SSH_PORT}..."
SSH_PORT=${SSH_PORT} python3 /app/mux.py &

# =================================================================
# Ringkasan akhir
# =================================================================
sleep 1
echo "=========================================================="
echo "[✓] Semua service berjalan:"
echo "    UI Panel    : http://0.0.0.0:${XRAY_PROXY_PORT}/  (via proxy_wrapper)"
echo "    Xray paths  : /xhttp /vless /vmess /trojan ..."
echo "    SSH mux     : 0.0.0.0:${SSH_PORT}  (TCP + TLS)"
echo "    WS SSH      : 0.0.0.0:8880  (WebSocket)"
echo "    UDPGW       : 0.0.0.0:${UDPGW_PORT}/udp"
echo "=========================================================="

# =================================================================
# Tunggu semua proses (Railway anggap container hidup selama ini)
# =================================================================
wait