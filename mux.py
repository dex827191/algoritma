#!/usr/bin/env python3
"""Pure TCP splitter: TLS ClientHello (0x16) -> stunnel; everything else -> WS proxy."""
import asyncio
import logging
import os
import socket

HOST = "0.0.0.0"
PORT = int(os.getenv("PUBLIC_PORT", os.getenv("PORT", "8881")))
SSL_HOST = os.getenv("SSL_TARGET_HOST", "127.0.0.1")
SSL_PORT = int(os.getenv("SSL_TARGET_PORT", "2443"))
WS_HOST = os.getenv("WS_TARGET_HOST", "127.0.0.1")
WS_PORT = int(os.getenv("WS_TARGET_PORT", "8880"))

logging.basicConfig(level=logging.INFO, format="[Mux Python] %(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mux")


def tune(writer):
    sock = writer.get_extra_info("socket")
    if sock is not None:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)


async def pump(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass


async def handle(client_reader, client_writer):
    peer = client_writer.get_extra_info("peername")
    backend_writer = None
    try:
        first = await asyncio.wait_for(client_reader.read(1), timeout=15)
        if not first:
            return

        if first[0] == 0x16:
            host, port, label = SSL_HOST, SSL_PORT, "TLS/stunnel"
        else:
            host, port, label = WS_HOST, WS_PORT, "WS/SSH"

        # Connect based on the first byte, then forward it and all subsequent
        # bytes unchanged. No HTTP path/header inspection is performed.
        backend_reader, backend_writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=10
        )
        tune(client_writer)
        tune(backend_writer)
        backend_writer.write(first)
        await backend_writer.drain()
        log.info("%s -> %s %s:%s", peer, label, host, port)

        up = asyncio.create_task(pump(client_reader, backend_writer))
        down = asyncio.create_task(pump(backend_reader, client_writer))
        done, pending = await asyncio.wait((up, down), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
        log.warning("Connection %s: %s", peer, exc)
    finally:
        for writer in (backend_writer, client_writer):
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass


async def main():
    server = await asyncio.start_server(handle, HOST, PORT, limit=65536)
    log.info("Pure Traffic Splitter Active on %s:%s (TLS=%s, WS=%s)", HOST, PORT, SSL_PORT, WS_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
