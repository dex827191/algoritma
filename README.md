# SSH + Xray gateway (dual SSH mode)

## Routing
- HTTP origin utama: `0.0.0.0:8080` (Nginx).
- SSH WebSocket: `https://DOMAIN/ssh` atau `wss://DOMAIN/ssh` -> Nginx -> `ws-proxy.py:8880` -> Dropbear `127.0.0.1:22`.
- Xray: seluruh path dan inbound tetap mengikuti `config.json` dan `nginx.conf` semula.
- SSH SSL/TLS: koneksi TCP mentah ke `mux.py:8881`; mux mengenali TLS record dan meneruskannya ke stunnel `127.0.0.1:2443` -> Dropbear `127.0.0.1:22`.
- Mux juga dapat meneruskan koneksi TCP non-TLS ke ws-proxy, tetapi mode WebSocket yang direkomendasikan untuk Cloudflare HTTP origin adalah `/ssh` melalui Nginx.
- `ws-xray.py` tetap khusus jalur Xray TCP dan tidak dipakai untuk SSH.

## Cloudflare Tunnel
Untuk hostname HTTP/HTTPS yang melayani panel, Xray WS, dan SSH WebSocket, set service ke `http://localhost:8080`. Tidak perlu hostname baru untuk `/ssh`.

**Penting:** SSH SSL/TLS melalui mux adalah TCP mentah, bukan HTTP. Cloudflare Tunnel service `http://localhost:8080` tidak dapat meneruskan koneksi TCP SSL ke mux hanya berdasarkan path. Agar SSH SSL dapat diakses dari luar, platform harus menyediakan TCP port forwarding/proxy ke container port `8881`, atau gunakan Cloudflare Tunnel TCP dengan klien yang mendukung `cloudflared access tcp`. Jangan arahkan hostname HTTP yang sama ke mux.

## Port internal
- `22`: Dropbear (loopback)
- `2443`: stunnel (loopback)
- `8880`: ws-proxy (loopback)
- `8881`: mux TCP (listen semua interface)
- `8080`: Nginx HTTP origin (listen semua interface)
- `18080-18088`: Xray (loopback)
- `8882`: ws-xray helper (listen semua interface)

## Environment
- `CF_TOKEN`: token Cloudflare Tunnel (opsional)
- `DOMAIN`: domain untuk tautan panel
- `MAIN_MUX_PORT`: port mux, default `8881`
- `SSL_TARGET_HOST` / `SSL_TARGET_PORT`: default `127.0.0.1:2443`
- `WS_TARGET_HOST` / `WS_TARGET_PORT`: default `127.0.0.1:8880`

## Validasi
Di dalam container:
```bash
nginx -t -c /app/nginx.conf
python3 -m py_compile /app/mux.py /app/ws-proxy.py /app/ws-xray.py /app/app.py
ss -lntp
```
Handshake WebSocket untuk tes lokal harus menggunakan key valid:
```bash
curl -i -N --http1.1 \
  -H 'Host: DOMAIN' \
  -H 'Connection: Upgrade' \
  -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' \
  -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  http://127.0.0.1:8080/ssh
```
Tes handshake hanya membuktikan jalur HTTP Upgrade, bukan autentikasi SSH lengkap.
