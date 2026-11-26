# Nginx Proxy App + SSH API

Gabungan panel web (HTML tertanam langsung di `app.py`), Xray, dan SSH Dropbear.

## Jalur koneksi
- Port publik `PORT` (default 8080) dijalankan oleh `mux.py`.
- TLS mentah diarahkan ke stunnel -> Dropbear pada `127.0.0.1:22`.
- HTTP WebSocket SSH diarahkan ke `ws-proxy.py` -> Dropbear.
- Path Xray (`/xhttp`, `/vless`, `/vmess`, `/trojan`, dan varian HTTPUp/XHTTP) diarahkan ke `proxy_wrapper.py` (tetap khusus Xray), lalu Nginx dan Xray.
- Panel dan API dijalankan oleh `app.py` pada port internal 2053 melalui Nginx.

## API SSH
Semua API memakai JSON:
- `GET /api/ssh/list`
- `POST /api/ssh/add` body `{"user":"nama","pass":"password"}`
- `POST /api/ssh/delete` body `{"user":"nama"}`

Alias kompatibilitas lama `/api/list`, `/api/add`, `/api/delete` juga tersedia.
Pembuatan user memakai `useradd` + `chpasswd`; penghapusan memakai `userdel -r`.
Data akun tersimpan di `/etc/ssh-sni/users.json`.

## API Xray
- `GET /api/xray/list`
- `POST /api/xray/add` body `{"name":"nama"}`
- `POST /api/xray/delete` body `{"id":"uuid"}`

## Environment
- `PORT`: port publik mux (default 8080)
- `DOMAIN`: domain untuk link Xray (opsional)
- `CF_TOKEN`: Cloudflare Tunnel token (opsional)

Build dan jalankan dengan Docker. Disarankan menambahkan autentikasi/API token dan pembatasan akses sebelum panel diekspos ke internet publik; API SSH saat ini merupakan self-service tanpa autentikasi.

## Optimasi kernel, banner, dan UDP gateway
- `ENABLE_BBR=true` mengaktifkan BBR; nilai selain `true` memakai cubic. Perubahan sysctl dicoba saat container mulai. Pada container tanpa izin kernel yang sesuai, pengaturan dapat ditolak dan dilewati.
- `CUSTOM_BANNER` (opsional) mengganti banner default. Banner ditulis ke `/etc/dropbear/banner`. Dropbear menampilkan isi file sebagai teks terminal; markup HTML tidak dirender sebagai HTML.
- `NET_BIN` (default `/usr/local/bin/badvpn-udpgw`) menunjuk binary `badvpn-udpgw`. `UDPGW_PORT` default `7300`, `UDPGW_MAX_CLIENTS` default `250`. Worker hanya dijalankan jika binary tersedia dan executable. Binary badvpn-udpgw tidak dibundel di ZIP ini.
