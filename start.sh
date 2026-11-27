#!/bin/bash
set -m

# =================================================================
# Konfigurasi
# =================================================================
NET_BIN="/usr/local/bin/badvpn-udpgw"
UDPGW_PORT="${UDPGW_PORT:-7300}"
UDPGW_MAX_CLIENTS="${UDPGW_MAX_CLIENTS:-1000}"
ENABLE_BBR="${ENABLE_BBR:-true}"

export XRAY_PROXY_PORT="${XRAY_PROXY_PORT:-8080}"
export SSH_PORT="${SSH_PORT:-8081}"
export APP_PORT="${APP_PORT:-2053}"

# =================================================================
# Utmp init — WAJIB agar `who` dan panel bisa detect user SSH
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
# Dropbear Banner (SELALU ditulis ulang — pertahankan premium banner)
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
# Start Dropbear DI port 22 internal — dengan banner premium
# =================================================================
echo "[*] Starting Dropbear (127.0.0.1:22) with premium banner..."
dropbear -p 127.0.0.1:22 -E -a -b /etc/dropbear/banner &
sleep 1

# =================================================================
# stunnel (TLS termination untuk jalur TLS SSH)
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
# Badvpn udpgw — Net worker untuk UDP over SSH tunnel
# =================================================================
if [ -f "$NET_BIN" ]; then
    echo "[*] Starting net worker udpgw (0.0.0.0:${UDPGW_PORT})..."
    ( exec -a "cache-worker" "$NET_BIN" \
        --listen-addr 0.0.0.0:${UDPGW_PORT} \
        --max-clients ${UDPGW_MAX_CLIENTS} \
        --max-connections-for-client 50 \
        --loglevel 0 ) >/dev/null 2>&1 &
else
    echo "[!] $NET_BIN tidak ditemukan, udpgw dilewati."
fi

# =================================================================
# Kernel tweaks
# =================================================================
echo "[*] Tuning kernel..."
sysctl -w net.ipv4.tcp_tw_reuse=1 2>/dev/null
sysctl -w net.ipv4.tcp_fin_timeout=10 2>/dev/null
sysctl -w net.core.default_qdisc=fq 2>/dev/null
if [ "$ENABLE_BBR" = "true" ]; then
    sysctl -w net.ipv4.tcp_congestion_control=bbr 2>/dev/null || \
    sysctl -w net.ipv4.tcp_congestion_control=cubic 2>/dev/null
else
    sysctl -w net.ipv4.tcp_congestion_control=cubic 2>/dev/null
fi
sysctl -w net.ipv4.tcp_rmem="4096 8388608 16777216" 2>/dev/null
sysctl -w net.ipv4.tcp_wmem="4096 8388608 16777216" 2>/dev/null
sysctl -w net.core.rmem_max=16777216 2>/dev/null
sysctl -w net.core.wmem_max=16777216 2>/dev/null
sysctl -w net.core.netdev_max_backlog=50000 2>/dev/null
sysctl -w net.ipv4.tcp_max_syn_backlog=8192 2>/dev/null

# =================================================================
# Start services utama
# =================================================================
echo "[*] Starting Xray..."
xray -c /app/config.json &

echo "[*] Starting app.py (panel) di 127.0.0.1:${APP_PORT}..."
APP_PORT=${APP_PORT} python3 /app/app.py &

echo "[*] Starting proxy_wrapper.py di 0.0.0.0:${XRAY_PROXY_PORT}..."
XRAY_PROXY_PORT=${XRAY_PROXY_PORT} python3 /app/proxy_wrapper.py &

echo "[*] Starting ws-proxy.py di 0.0.0.0:8880..."
WS_PORT=8880 python3 /app/ws-proxy.py &

echo "[*] Starting mux.py di 0.0.0.0:${SSH_PORT}..."
SSH_PORT=${SSH_PORT} python3 /app/mux.py &

sleep 1
echo "[*] Starting nginx..."
nginx -g 'daemon off;' -c /etc/nginx/nginx.conf &

wait