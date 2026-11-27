# Railway SSH WebSocket + Xray (single service)

## Jalur koneksi
- Cloudflare Tunnel HTTP origin: `http://localhost:8080`.
- SSH WebSocket: `wss://DOMAIN/ssh` -> Nginx `:8080` -> `ws-proxy.py :8880` -> Dropbear `127.0.0.1:22`.
- Xray dan panel tetap menggunakan routing yang sudah ada di `nginx.conf` dan `config.json`.
- `ws-xray.py` tetap khusus helper Xray.
- `mux.py` tidak dijalankan. Stunnel/TCP SSL tidak digunakan pada deployment ini.

## Railway
Gunakan satu Railway Service dengan Dockerfile. Cloudflare Tunnel hostname diarahkan ke `http://localhost:8080`. Tidak perlu TCP Proxy Railway.

## SSH WebSocket payload
Path: `/ssh`
Host: domain Cloudflare kamu
Port: 443 untuk WSS atau 80 untuk WS sesuai hostname.
Klien harus membuat `Sec-WebSocket-Key` acak/valid dan mengirim data SSH sebagai WebSocket binary frames.

## Pemeriksaan
```bash
nginx -t -c /app/nginx.conf
python3 -m py_compile /app/ws-proxy.py /app/ws-xray.py /app/app.py
bash -n /app/start.sh
ss -lntp
```
Handshake lokal (hanya menguji HTTP Upgrade, bukan login SSH):
```bash
curl -i -N --http1.1 \
  -H 'Host: DOMAIN' \
  -H 'Connection: Upgrade' \
  -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' \
  -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  http://127.0.0.1:8080/ssh
```
