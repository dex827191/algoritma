# SSH + Xray + UI deployment

## Local listeners (defaults)
- `app.py` serves the embedded HTML UI/API on `APP_PORT=2053` (default).
- `proxy_wrapper.py` is **Xray ingress only** on `XRAY_PROXY_PORT=8080`; Xray paths go through nginx and UI/API requests are forwarded to nginx -> app.py.
- `mux.py` is **SSH only** on `SSH_PORT=8081` (the value is read from ENV).
- `badvpn-udpgw` is a separate **UDP-only SSH auxiliary service** on `UDPGW_PORT=7300/udp`; it is not used by Xray.
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

**UDPGW note:** the normal Cloudflare Tunnel public-hostname route shown above is HTTP/TCP and does not publish this UDP listener. To use BADVPN UDPGW, the deployment platform must provide a directly reachable UDP port (or a separate UDP-capable network path). Merely adding `7300/udp` to Docker `EXPOSE` does not guarantee that the hosting platform exposes it publicly.

## Environment variables
- `APP_PORT=2053`: UI/API port inside the container.
- `XRAY_DOMAIN`: hostname used in generated Xray links and displayed by the panel.
- `XRAY_PROXY_PORT=8080`: Xray ingress listener used as the Xray Tunnel service target.
- `SSH_DOMAIN`: SSH hostname displayed in the panel/account details.
- `SSH_PORT=8081`: SSH mux listener and SSH Tunnel service target.
- `CF_TOKEN`: Cloudflare Tunnel token (optional).
- `UDPGW_PORT=7300`: BADVPN UDP listener for SSH clients only.
- `UDPGW_MAX_CLIENTS=2048`: maximum UDPGW clients.
- `NET_BIN=/usr/local/bin/badvpn-udpgw`: BADVPN executable path.
- `ENABLE_BBR=false`: best-effort kernel congestion-control setting; container permissions may prevent applying it.
- `SSH_USER`, `SSH_PASSWORD`: bootstrap Dropbear login (defaults `dd` / `dd`).
- `DOMAIN`: backward-compatible fallback for `XRAY_DOMAIN`.

The dashboard obtains domain and port values from `/__info`, so its labels and generated links follow ENV settings rather than hardcoded hostnames.


## Port separation summary

| Service | Default | Protocol | Purpose |
|---|---:|---|---|
| UI/API | 2053 | TCP, internal | Panel behind Nginx |
| Xray ingress | 8080 | TCP | Xray paths and UI/API forwarding |
| SSH mux | 8081 | TCP | SSH protocol selection |
| SSH WebSocket backend | 8880 | TCP, internal | SSH WebSocket |
| SSH TLS backend | 2443 | TCP, internal | Stunnel to Dropbear |
| BADVPN UDPGW | 7300 | UDP | SSH UDP forwarding only |

Xray inbounds remain on their existing internal ports `18080`–`18088`; none of them points to BADVPN.


## Live Xray user monitoring
The dashboard polls `/api/stats` every 5 seconds and reads active Xray users from the local Xray StatsService. The Xray API inbound is bound only to `127.0.0.1:10085` and must not be exposed through Cloudflare Tunnel or a public port. User online counters are enabled for the default client level.

**Source IP limitation:** Cloudflare Tunnel terminates the public connection before it reaches the Xray TCP inbound. Xray therefore sees the tunnel/origin-side peer, not necessarily the visitor's public IP. The panel deliberately labels Xray source IP as unavailable rather than presenting a Cloudflare or internal address as the user's real IP. The same caveat applies to SSH sessions routed through the Tunnel.

After deploying this revision on Railway, rebuild/redeploy the service so the updated `config.json` and `app.py` are active. Existing account data is kept in the Railway volume only if the deployment already uses a persistent volume for `/app/users.json` and the SSH data directory.
