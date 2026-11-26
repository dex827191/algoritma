# SSH & Xray Panel (Python)

Panel web menggunakan `app.py` dan `index.html`; komponen proxy Go tetap disertakan.

## Menjalankan

Jalankan dalam container yang memiliki hak akses untuk mengelola akun sistem dan Xray:

```bash
python3 app.py
```

Port default: `3000` (dapat diubah melalui `PANEL_PORT`). Data disimpan di `data/` secara default.

## Catatan

- Simpan backup `data/config.json` dan data akun sebelum melakukan upgrade.
- Pengelolaan akun SSH memerlukan hak akses sistem yang sesuai.
- Panel tanpa login: gunakan hanya pada lingkungan pribadi. Cloudflare Named Tunnel membaca CF_TOKEN atau TOKEN dari environment.


## Cloudflare Named Tunnel dan domain otomatis

Set `CF_TOKEN` (atau `TOKEN`) pada environment container menggunakan token Cloudflare Named Tunnel. Buka panel melalui hostname publik Cloudflare Tunnel. Generator mengambil hostname dari header `Host` pada request panel; kolom domain terisi otomatis dan tidak perlu `DOMAIN`. Jika proxy tidak meneruskan hostname asli, set `DOMAIN` sebagai fallback.

Port panel internal default `3000`. Atur Public Hostname Cloudflare Tunnel ke service HTTP panel pada port tersebut. SSH WebSocket dan Xray memerlukan routing/protocol yang sesuai pada konfigurasi tunnel dan proxy; hostname otomatis pada generator tidak dengan sendirinya membuat TCP SSH/Xray bisa melewati HTTP tunnel.


## Troubleshooting Cloudflare Tunnel
- Masukkan token Named Tunnel lengkap sebagai environment variable `CF_TOKEN` (atau `TOKEN`) pada container; jangan sertakan tanda kutip tambahan.
- Di Cloudflare Tunnel, Public Hostname/service harus mengarah ke layanan panel yang benar, misalnya `http://localhost:3000` jika cloudflared dan panel berada di container yang sama.
- Jika gagal startup, periksa `/tmp/cloudflared.log` dan log container. Skrip kini menampilkan log terakhir bila cloudflared langsung berhenti.
- Status `Healthy`/`Connected` di Cloudflare dashboard diperlukan; pastikan token berasal dari tunnel yang sama dan tunnel tersebut belum dihapus.
