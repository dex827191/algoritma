# Combined SSH + Xray Panel

## Komponen
- `app.py`: API panel + menyajikan UI dari `index.html` yang di-embed sebagai asset container.
- `addssh`, `delssh`, `listssh`: utilitas manajemen akun SSH dari `ssh.zip`; endpoint panel memakai `addssh`/`delssh`.
- `ws-proxy.py`: transport SSH WebSocket ke Dropbear internal.
- `mux.py`: satu listener publik; memisahkan TLS SSH, raw SSH, SSH WebSocket, dan path Xray.
- `proxy_wrapper.py`: tetap khusus Xray dan tidak diubah.
- `nginx.conf` + `config.json`: backend inbound Xray.

## Deploy
Build image dari folder ini, lalu jalankan dengan port TCP publik 8080 (atau set `PORT`).
Disarankan set `DOMAIN` ke domain publik yang dipakai untuk membuat link Xray.
Opsional:
- `CF_TOKEN`: token Cloudflare Tunnel.
- `SSH_USER` dan `SSH_PASSWORD`: membuat akun SSH awal saat container start.
- `SSH_EXPIRE_DAYS`: masa aktif akun awal; `0` berarti tanpa expiry.

Panel web dilayani pada `/` oleh `app.py` port internal 2053 dan di-route oleh `mux.py` untuk request HTTP biasa (misalnya `http://domain:8080`). Koneksi TLS pada port publik yang sama diprioritaskan ke stunnel untuk SSH TLS; terminasi HTTPS untuk panel harus dilakukan oleh proxy/provider di depan service dan diteruskan ke origin sebagai HTTP.
Akun SSH tambahan dapat dibuat dari menu **Buat Akun SSH**. Data metadata tersimpan di `/etc/ssh-sni/users.json`.

## Catatan
- Port publik harus berupa TCP passthrough untuk mendukung TLS/raw SSH dan WebSocket. Proxy HTTP-only tidak dapat membawa semua mode ini.
- `proxy_wrapper.py` dipertahankan byte-for-byte dari project awal dan berjalan pada port privat 8082.
- Sebelum penggunaan produksi, ganti kredensial awal, batasi akses panel/API melalui firewall atau autentikasi tambahan, dan uji konfigurasi domain/TLS sesuai provider.
