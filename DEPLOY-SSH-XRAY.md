# SSH + Xray + UI deployment

## Local listeners (defaults)
- `app.py` serves the embedded HTML UI/API on `APP_PORT=8080`.
- `proxy_wrapper.py` is **Xray ingress only** on `XRAY_PROXY_PORT=8080`; Xray paths go through nginx and UI/API requests are forwarded to nginx -> app.py.
- `mux.py` is **SSH only** on `SSH_PORT=8081` (the value is read from ENV).
- `ws-proxy.py` is the SSH WebSocket backend on `127.0.0.1:8880`, forwarding to Dropbear `127.0.0.1:22`.
- Stunnel SSH backend is `127.0.0.1:2443`.
- Nginx's private Xray/UI origin listens on `127.0.0.1:8082`.

## Cloudflare Tunnel hostnames
Create two Public Hostname routes in the same named tunnel:

| Hostname | Service | Purpose |
|---|---|---|
| `${XRAY_DOMAIN}` | `http://localhost:8080` (or configured `XRAY_PROXY_PORT`) | Xray WebSocket paths and UI/API on the same Xray domain |
| `${SSH_DOMAIN}` | `http://localhost:8081` (or configured `SSH_PORT`) | SSH WebSocket through mux -> ws-proxy |

The SSH hostname must be used for SSH WebSocket-over-HTTPS clients. Do not route SSH through `proxy_wrapper.py`.

## Environment variables
- `APP_PORT=2053`: UI/API port inside the container.
- `XRAY_DOMAIN`: hostname used in generated Xray links and displayed by the panel.
- `XRAY_PROXY_PORT=8080`: Xray ingress listener used as the Xray Tunnel service target.
- `SSH_DOMAIN`: SSH hostname displayed in the panel/account details.
- `SSH_PORT=8081`: SSH mux listener and SSH Tunnel service target.
- `CF_TOKEN`: Cloudflare Tunnel token (optional).
- `SSH_USER`, `SSH_PASSWORD`: bootstrap Dropbear login (defaults `dd` / `dd`).
- `DOMAIN`: backward-compatible fallback for `XRAY_DOMAIN`.

The dashboard obtains domain and port values from `/__info`, so its labels and generated links follow ENV settings rather than hardcoded hostnames.
