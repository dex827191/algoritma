#!/usr/bin/env python3
"""Public TCP multiplexer: TLS SSH -> stunnel, raw SSH -> Dropbear,
SSH WebSocket -> ws-proxy, Xray HTTP paths -> the unchanged Xray wrapper."""
import asyncio
import logging
import os
import signal
import sys

HOST = "0.0.0.0"
PORT = int(os.environ.get("MAIN_MUX_PORT", os.environ.get("PORT", "8080")))
TLS_HOST, TLS_PORT = os.getenv("SSL_TARGET_HOST","127.0.0.1"), int(os.getenv("SSL_TARGET_PORT","2443"))
WS_HOST, WS_PORT = os.getenv("WS_MUX_TARGET_HOST","127.0.0.1"), int(os.getenv("WS_MUX_TARGET_PORT","8880"))
SSH_HOST, SSH_PORT = os.getenv("SSH_TARGET_HOST","127.0.0.1"), int(os.getenv("SSH_TARGET_PORT","22"))
XRAY_HOST, XRAY_PORT = os.getenv("XRAY_TARGET_HOST","127.0.0.1"), int(os.getenv("XRAY_TARGET_PORT","8082"))
APP_HOST, APP_PORT = os.getenv("APP_TARGET_HOST","127.0.0.1"), int(os.getenv("APP_TARGET_PORT","2053"))
XRAY_PATHS = ("/xhttp", "/httpup", "/vless", "/vmess-xhttp", "/vmess-httpup",
              "/vmess", "/trojan-xhttp", "/trojan-httpup", "/trojan")
logging.basicConfig(level=logging.INFO, format="[mux] %(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mux")

async def relay(src, dst):
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass

async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    backend_writer = None
    try:
        first = await asyncio.wait_for(reader.read(1), timeout=2.0)
        if not first:
            return
        buffered = first
        if first[0] == 0x16:  # TLS ClientHello
            host, port, label = TLS_HOST, TLS_PORT, "SSH TLS/stunnel"
        elif first.startswith(b"S"):  # raw SSH identification string
            more = await asyncio.wait_for(reader.read(3), timeout=1.0)
            buffered += more
            if buffered.startswith(b"SSH-"):
                host, port, label = SSH_HOST, SSH_PORT, "raw SSH"
            else:
                host, port, label = WS_HOST, WS_PORT, "SSH WebSocket"
        elif first in (b"G", b"P", b"H", b"O", b"D", b"C", b"T"):
            try:
                header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3.0)
                buffered += header
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                host, port, label = WS_HOST, WS_PORT, "SSH WebSocket"
            else:
                try:
                    request_line = buffered.split(b"\r\n",1)[0].decode("latin1")
                    parts = request_line.split()
                    path = parts[1].split("?",1)[0] if len(parts) > 1 else "/"
                except Exception:
                    path = "/"
                is_websocket = b"upgrade: websocket" in buffered.lower()
                if any(path.startswith(p) for p in XRAY_PATHS):
                    host, port, label = XRAY_HOST, XRAY_PORT, "Xray"
                elif is_websocket:
                    host, port, label = WS_HOST, WS_PORT, "SSH WebSocket"
                elif path == "/" or path == "/index.html" or path.startswith("/api/") or path == "/__info":
                    host, port, label = APP_HOST, APP_PORT, "Web panel/API"
                else:
                    host, port, label = WS_HOST, WS_PORT, "SSH WebSocket"
        else:
            host, port, label = WS_HOST, WS_PORT, "SSH WebSocket"

        log.info("%s -> %s (%s:%s)", peer, label, host, port)
        backend_reader, backend_writer = await asyncio.open_connection(host, port)
        backend_writer.write(buffered)
        await backend_writer.drain()
        await asyncio.gather(relay(reader, backend_writer), relay(backend_reader, writer))
    except Exception as exc:
        log.warning("Koneksi %s gagal: %s", peer, exc)
    finally:
        for stream in (writer, backend_writer):
            if stream:
                try:
                    stream.close()
                except Exception:
                    pass

async def main():
    server = await asyncio.start_server(handle_client, HOST, PORT, limit=65536)
    log.info("Listening %s:%s | TLS=%s:%s WS=%s:%s SSH=%s:%s XRAY=%s:%s",
             HOST, PORT, TLS_HOST, TLS_PORT, WS_HOST, WS_PORT,
             SSH_HOST, SSH_PORT, XRAY_HOST, XRAY_PORT)
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
