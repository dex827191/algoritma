#!/usr/bin/env python3
"""
ws-xray.py — WebSocket helper / normalizer KHUSUS Xray.

Renamed from proxy_wrapper.py. TIDAK dipakai untuk SSH (SSH pakai
mux.py + ws-proxy.py).

Menerima koneksi TCP mentah (mis. dari HTTP Injector / NPV Tunnel /
Railway TCP Proxy), membaca HTTP request head, mengambil path, lalu
membangun ulang request WebSocket yang bersih dan meneruskannya ke
nginx:8080. nginx yang mem-routing berdasarkan path ke inbound Xray
yang sesuai (/xhttp -> 18080, /vless -> 18082, dst).

Environment:
  WS_XRAY_PORT   (default 8882)  — port listen
  NGINX_HOST     (default 127.0.0.1)
  NGINX_PORT     (default 8080)
"""

import asyncio
import logging
import os
import signal
import sys

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("WS_XRAY_PORT", os.environ.get("PORT", "8882")))

NGINX_HOST = os.environ.get("NGINX_HOST", "127.0.0.1")
NGINX_PORT = int(os.environ.get("NGINX_PORT", "8080"))

XRAY_PATHS = (
    "/xhttp", "/httpup", "/vless",
    "/vmess-xhttp", "/vmess-httpup", "/vmess",
    "/trojan-xhttp", "/trojan-httpup", "/trojan",
)

logging.basicConfig(
    level=logging.INFO,
    format="[ws-xray] %(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("ws-xray")


async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
    try:
        while True:
            data = await src.read(16384)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        log.debug("pipe error: %s", e)
    finally:
        try:
            dst.close()
        except Exception:
            pass


async def handle_client(client_reader: asyncio.StreamReader,
                        client_writer: asyncio.StreamWriter):
    peer = client_writer.get_extra_info("peername")
    try:
        try:
            raw_head = await asyncio.wait_for(
                client_reader.readuntil(b"\r\n\r\n"), timeout=15
            )
        except Exception:
            return

        text = raw_head.decode("latin-1", errors="ignore")
        lines = text.split("\r\n")
        first = lines[0] if lines else ""
        parts = first.split(" ")
        if len(parts) < 2:
            return
        path = parts[1]

        if not any(path.startswith(p) for p in XRAY_PATHS):
            client_writer.write(
                b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            await client_writer.drain()
            return

        host_header = next(
            (l for l in lines[1:] if l.lower().startswith("host:")),
            "Host: localhost",
        )
        ws_headers = [l for l in lines[1:] if l.lower().startswith("sec-websocket-")]
        if not any(h.lower().startswith("sec-websocket-key:") for h in ws_headers):
            ws_headers.append("Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==")
        if not any(h.lower().startswith("sec-websocket-version:") for h in ws_headers):
            ws_headers.append("Sec-WebSocket-Version: 13")
        extra = "\r\n".join(ws_headers)

        clean_request = (
            f"GET {path} HTTP/1.1\r\n"
            f"{host_header}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"{extra}\r\n\r\n"
        ).encode("latin-1")

        up_reader, up_writer = await asyncio.open_connection(NGINX_HOST, NGINX_PORT)
        up_writer.write(clean_request)
        await up_writer.drain()

        log.info("Xray %s -> %s", peer, path)

        await asyncio.gather(
            pipe(client_reader, up_writer),
            pipe(up_reader, client_writer),
        )
    except Exception as e:
        log.error("Error handling %s: %s", peer, e)
    finally:
        try:
            client_writer.close()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    log.info("ws-xray listening on %s:%s -> nginx %s:%s",
             LISTEN_HOST, LISTEN_PORT, NGINX_HOST, NGINX_PORT)
    async with server:
        await server.serve_forever()


def _sigterm(*_):
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _sigterm)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass