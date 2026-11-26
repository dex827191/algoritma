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
- Atur akses jaringan/firewall dan password admin sebelum membuka panel ke publik.
