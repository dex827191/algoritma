# SSH + Xray port separation

## Local listeners
- `proxy_wrapper.py` is **Xray/UI only** and listens on `0.0.0.0:8080` (`PORT`, default 8080).
- `mux.py` is **SSH only** and listens on `0.0.0.0:8081` (`MAIN_MUX_PORT`).
- `ws-proxy.py` is the SSH WebSocket backend on `127.0.0.1:8880`, forwarding to Dropbear `127.0.0.1:22`.
- Stunnel SSH backend is `127.0.0.1:2443`.
- Nginx's private Xray/UI origin moved to `127.0.0.1:8082` to avoid colliding with SSH mux port 8081.

## Cloudflare Tunnel hostnames
Use the same named tunnel/token and add two Public Hostname routes in Cloudflare Zero Trust:

| Hostname | Service | Purpose |
|---|---|---|
| Xray hostname, e.g. `xray.example.com` | `http://localhost:8080` | Xray paths and UI root |
| SSH hostname, e.g. `ssh.example.com` | `http://localhost:8081` | SSH WebSocket via mux -> ws-proxy |

The SSH hostname is for WebSocket-over-HTTPS clients. Do not configure `proxy_wrapper.py` as the SSH backend. If using Cloudflare's raw TCP Access mode instead of a WebSocket hostname, the client must use `cloudflared access tcp` and the tunnel route must be configured for TCP accordingly.

## Environment
- `CF_TOKEN`: Cloudflare tunnel token (optional)
- `SSH_USER`, `SSH_PASSWORD`: bootstrap Dropbear login (defaults `dd` / `dd`)
- `PORT`: Xray/UI wrapper port (default 8080)
- `MAIN_MUX_PORT`: SSH mux port (default 8081)


### Pengelolaan akun SSH dan panel

Endpoint tambah akun SSH (`/api/add`), hapus (`/api/delete`), dan daftar (`/api/list`) kini ditangani langsung oleh `app.py`. Fungsi yang sebelumnya berada di `addssh`, `delssh`, dan `listssh` sudah digabung ke `app.py`; file terpisah tersebut tidak diperlukan. Konten `index.html` juga sudah ditanam di dalam `app.py`, sehingga file HTML terpisah tidak diperlukan saat runtime.
