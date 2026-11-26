# Panel SSH + Xray — Satu Domain, Port 80 dan 443

Versi ini menggunakan satu domain Cloudflare Tunnel untuk SSH WebSocket, VLESS, VMess, dan Trojan. Client dapat memilih dua mode koneksi:

- **Port 80, TLS OFF**: HTTP/WebSocket tanpa TLS pada sisi client.
- **Port 443, TLS ON**: HTTPS/WebSocket dengan TLS pada sisi client; sertifikat TLS disediakan Cloudflare.

Keduanya masuk ke origin HTTP yang sama, yaitu `http://localhost:8080`. Go Multiplexer dan Nginx mengarahkan request berdasarkan path.

## Environment Railway — hanya dua variabel

Masukkan hanya dua variable berikut di Railway → Service → Variables:

```env
DOMAIN=vpn.domainkamu.com
CF_TUNNEL_TOKEN=TOKEN_TUNNEL_CLOUDFLARE_KAMU
```

Tidak perlu menambahkan `PORT`, `XRAY_DOMAIN`, `SERVER_NAME`, `SNI`, atau `BUG_DOMAIN`. Port aplikasi otomatis `8080`, sedangkan semua domain/SNI/Host akun mengambil nilai dari `DOMAIN`.

`CF_TUNNEL_TOKEN` adalah rahasia. Jangan commit token asli ke GitHub. File `.env.example` hanya berisi placeholder.

## Cloudflare Tunnel

Buat/pilih satu tunnel, lalu tambahkan satu Published Application Route:

| Field | Value |
|---|---|
| Hostname | `vpn.domainkamu.com` |
| Service type | `HTTP` |
| Service URL | `http://localhost:8080` |

`cloudflared` dan Go Multiplexer harus berjalan di container/service Railway yang sama agar `localhost:8080` mengarah ke aplikasi ini. Simpan token tunnel pada Railway variable `CF_TUNNEL_TOKEN`.

Aktifkan WebSockets pada Cloudflare. Pastikan hostname memiliki sertifikat edge Cloudflare yang aktif untuk HTTPS port 443. Jika ingin profil port 80 TLS OFF tetap bisa dipakai, nonaktifkan aturan **Always Use HTTPS** untuk hostname ini; jika aturan tersebut aktif, Cloudflare dapat mengalihkan HTTP ke HTTPS.

Cloudflare Tunnel menerima koneksi publik HTTP/HTTPS dan meneruskannya ke origin HTTP lokal. Jadi port 80 dan 443 adalah port publik client, bukan dua port listener di container.

## Profil koneksi

Gunakan hostname/domain yang sama untuk semua protokol.

### SSH WebSocket — root tanpa path

| Mode | Host | Port | TLS | Path |
|---|---|---:|---|---|
| TLS OFF | `vpn.domainkamu.com` | `80` | OFF | kosong (`/`) |
| TLS ON | `vpn.domainkamu.com` | `443` | ON | kosong (`/`) |

### VLESS WebSocket

| Mode | Host | Port | TLS | Path |
|---|---|---:|---|---|
| TLS OFF | `vpn.domainkamu.com` | `80` | OFF | `/vless` |
| TLS ON | `vpn.domainkamu.com` | `443` | ON | `/vless` |

### VMess WebSocket

| Mode | Host | Port | TLS | Path |
|---|---|---:|---|---|
| TLS OFF | `vpn.domainkamu.com` | `80` | OFF | `/vmess` |
| TLS ON | `vpn.domainkamu.com` | `443` | ON | `/vmess` |

### Trojan WebSocket

| Mode | Host | Port | TLS | Path |
|---|---|---:|---|---|
| TLS OFF | `vpn.domainkamu.com` | `80` | OFF | `/trojan` |
| TLS ON | `vpn.domainkamu.com` | `443` | ON | `/trojan` |

Panel membuat link Xray WebSocket untuk kedua mode (port 80/TLS OFF dan port 443/TLS ON). WebSocket dipilih sebagai transport yang kompatibel dengan Cloudflare Tunnel. Pada mode TLS ON, TLS berhenti di Cloudflare; koneksi dari `cloudflared` ke origin tetap HTTP lokal. Karena itu inbound Xray di origin menggunakan WebSocket tanpa TLS. Transport XHTTP/HTTPUpgrade tetap ada di konfigurasi backend, tetapi tidak ditampilkan sebagai profil Cloudflare pada panel ini.

## Routing internal

```text
Client :80 (TLS OFF) -----------+
                                |
Client :443 (TLS ON) ------------+--> Cloudflare Tunnel
                                      |
                                      v
                               http://localhost:8080
                                      |
                                 Go Multiplexer
                         +------------+-------------+
                         |            |             |
                      path /       /vless        /vmess /trojan
                         |            |             |
                      SSH WS       Nginx         Nginx
                         |            |             |
                    Dropbear :22   Xray Core     Xray Core
```

| Service | Port internal | Keterangan |
|---|---:|---|
| Go Multiplexer | `8080` | Origin tunggal untuk Cloudflare Tunnel |
| SSH WebSocket proxy | `8880` | Backend internal SSH WS |
| Dropbear | `22` | Backend SSH |
| Nginx | `8081` | Reverse proxy Xray |
| Xray | `18080–18088` | Inbound Xray |
| Stunnel | `2443` | Jalur TLS raw internal/direct; bukan TLS edge Cloudflare |

Jangan mengubah semua port internal menjadi 80/443/8080. Hanya Go Multiplexer yang menjadi origin publik `8080`.

## Deploy

1. Ekstrak ZIP dan upload seluruh isi folder ke repository GitHub.
2. Hubungkan repository ke Railway dan deploy menggunakan Dockerfile.
3. Tambahkan dua Railway Variables di atas.
4. Tambahkan Railway Volume pada `/data` agar akun tetap tersimpan saat redeploy.
5. Di Cloudflare Tunnel, buat satu route `vpn.domainkamu.com` → `http://localhost:8080`.
6. Pastikan tunnel berstatus Healthy dan WebSockets aktif.
7. Tes panel melalui `https://vpn.domainkamu.com`.
8. Tes profil port 443 TLS ON dan port 80 TLS OFF.

## Batasan penting

- SSH WebSocket melalui Cloudflare Tunnel didukung pada path root `/`.
- SSH Direct TCP biasa bukan HTTP/WebSocket dan tidak otomatis melewati Published Application HTTP. Untuk SSH TCP langsung, gunakan TCP proxy/layanan TCP terpisah atau mekanisme Cloudflare Access TCP dengan client `cloudflared`.
- Keberhasilan build tidak menjamin tunnel/protokol aktif sebelum diuji pada deployment Railway dan domain Cloudflare milik pengguna.
