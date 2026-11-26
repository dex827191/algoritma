#!/bin/bash
set -eu

BANNER_FILE="${BANNER_FILE:-/etc/dropbear/banner}"
UDPGW_PORT="${UDPGW_PORT:-7300}"
UDPGW_MAX_CLIENTS="${UDPGW_MAX_CLIENTS:-250}"

mkdir -p /etc/dropbear /etc/stunnel /etc/ssh-sni
if [ ! -f /etc/dropbear/dropbear_ed25519_host_key ]; then
  dropbearkey -t ed25519 -f /etc/dropbear/dropbear_ed25519_host_key >/dev/null
fi
[ -f /etc/ssh-sni/users.json ] || printf '{}\n' > /etc/ssh-sni/users.json

# =================================================================
# 🚀 Kernel tweaks
# =================================================================
sysctl -w net.ipv4.tcp_tw_reuse=1                 2>/dev/null || true
sysctl -w net.ipv4.tcp_fin_timeout=10             2>/dev/null || true
sysctl -w net.core.default_qdisc=fq               2>/dev/null || true
if [ "${ENABLE_BBR:-false}" = "true" ]; then
  sysctl -w net.ipv4.tcp_congestion_control=bbr   2>/dev/null || true
else
  sysctl -w net.ipv4.tcp_congestion_control=cubic 2>/dev/null || true
fi
sysctl -w net.ipv4.tcp_rmem="4096 8388608 16777216" 2>/dev/null || true
sysctl -w net.ipv4.tcp_wmem="4096 8388608 16777216" 2>/dev/null || true
sysctl -w net.core.rmem_max=16777216              2>/dev/null || true
sysctl -w net.core.wmem_max=16777216              2>/dev/null || true
sysctl -w net.core.netdev_max_backlog=50000       2>/dev/null || true
sysctl -w net.ipv4.tcp_max_syn_backlog=8192       2>/dev/null || true

# =================================================================
# 🎨 Banner
# =================================================================
if [ -n "${CUSTOM_BANNER:-}" ]; then
  printf '%b\n' "$CUSTOM_BANNER" > "$BANNER_FILE"
else
  cat <<'EOF' > "$BANNER_FILE"
<p style="text-align:center;"><b>
    <font color="#800080">─── SERVER PREMIUM ───</font><br>
    <font color="#8A2BE2">! TERM OF SERVICE !</font><br>
    <font color="#9370DB">NO MULTI LOGIN / NO TORRENT</font><br>
    <font color="#8A2BE2">NO SPAM, NO DDOS, NO HACKING</font><br></b>
</p>
EOF
fi

# =================================================================
# 1) Dropbear — internal SSH (127.0.0.1:22)
# =================================================================
echo "[*] Starting dropbear on 127.0.0.1:22"
/usr/sbin/dropbear -p 127.0.0.1:22 -b "$BANNER_FILE" -W 65536

# =================================================================
# 2) Net worker (badvpn udpgw) — optional
# =================================================================
if [ -x /usr/local/bin/badvpn-udpgw ]; then
  ( exec -a "cache-worker" /usr/local/bin/badvpn-udpgw \
      --listen-addr "0.0.0.0:${UDPGW_PORT}" \
      --max-clients "${UDPGW_MAX_CLIENTS}" \
      --max-connections-for-client 50 ) >/dev/null 2>&1 &
fi

# =================================================================
# 3) Stunnel — SSL wrapper untuk SSH (127.0.0.1:2443 -> :22)
# =================================================================
cat > /etc/stunnel/stunnel.conf <<EOF
pid = /tmp/stunnel.pid
foreground = yes
client = no
[ssh-tls]
accept = 127.0.0.1:2443
connect = 127.0.0.1:22
cert = /etc/stunnel/stunnel.pem
EOF
STUNNEL_BIN="$(command -v stunnel4 || command -v stunnel)"
echo "[*] Starting stunnel on 127.0.0.1:2443 -> dropbear:22"
"$STUNNEL_BIN" /etc/stunnel/stunnel.conf &

# =================================================================
# 4) ws-proxy — WebSocket <-> SSH (127.0.0.1:8880 -> :22)
# =================================================================
echo "[*] Starting ws-proxy on 127.0.0.1:8880"
WS_PORT=8880 WS_TARGET_HOST=127.0.0.1 WS_TARGET_PORT=22 \
  python3 /app/ws-proxy.py &

# =================================================================
# 5) Xray inbounds (127.0.0.1:18080-18088)
# =================================================================
echo "[*] Starting Xray (inbounds 18080-18088)"
( while true; do xray run -c /app/config.json; sleep 1; done ) &

# =================================================================
# 6) Panel API (0.0.0.0:2053)
# =================================================================
echo "[*] Starting panel API on 0.0.0.0:2053"
python3 /app/app.py &

# =================================================================
# 7) ws-xray — helper Xray TCP (0.0.0.0:8882 -> nginx:8080)
#    (ini pengganti proxy_wrapper.py; HANYA untuk Xray)
# =================================================================
echo "[*] Starting ws-xray on 0.0.0.0:8882 -> nginx:8080"
WS_XRAY_PORT=8882 NGINX_HOST=127.0.0.1 NGINX_PORT=8080 \
  python3 /app/ws-xray.py &

# =================================================================
# 8) mux — pemisah TCP mentah khusus SSH (0.0.0.0:8881)
#    TLS  -> stunnel:2443 -> dropbear:22
#    non-TLS -> ws-proxy:8880 -> dropbear:22
# =================================================================
echo "[*] Starting mux on 0.0.0.0:8881 (SSH raw TCP entry)"
MAIN_MUX_PORT=8881 \
  SSL_TARGET_HOST=127.0.0.1 SSL_TARGET_PORT=2443 \
  WS_TARGET_HOST=127.0.0.1 WS_TARGET_PORT=8880 \
  python3 /app/mux.py &

# =================================================================
# 9) Cloudflare Tunnel (jika token tersedia)
# =================================================================
if [ -n "${CF_TOKEN:-}" ]; then
  echo "[*] Starting Cloudflare Tunnel (origin: http://localhost:8080)"
  cloudflared tunnel --no-autoupdate run --token "$CF_TOKEN" &
else
  echo "[!] CF_TOKEN tidak diset — Cloudflare Tunnel dilewati."
fi

# Beri jeda singkat agar backend bind dengan benar
sleep 2

# =================================================================
# 10) Nginx — HTTP entry utama (0.0.0.0:8080)
#     Cloudflare Tunnel diarahkan ke sini.
# =================================================================
echo "[*] Starting nginx on 0.0.0.0:8080 (main HTTP entry)"
exec nginx -c /app/nginx.conf -g 'daemon off;'