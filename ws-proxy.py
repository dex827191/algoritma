#!/usr/bin/env python3
"""
WebSocket <-> raw SSH TCP bridge.

WebSocket clients send masked frames; SSH speaks an unframed byte stream.
This proxy converts between those protocols. Non-WebSocket HTTP payload
mode is retained for legacy clients that deliberately use a raw tunnel.
"""
import asyncio
import base64
import hashlib
import logging
import os
import signal
import struct
import sys

WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("WS_PORT", "8880"))
TARGET_HOST = os.environ.get("WS_TARGET_HOST", "127.0.0.1")
TARGET_PORT = int(os.environ.get("WS_TARGET_PORT", "22"))
MAX_FRAME = int(os.environ.get("WS_MAX_FRAME", str(16 * 1024 * 1024)))
DEFAULT_RESPONSE = os.environ.get("WS_RESPONSE", "HTTP/1.1 101 Switching Protocols\r\n\r\n")

logging.basicConfig(level=logging.INFO, format="[ws-proxy] %(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ws-proxy")


async def read_http_headers(reader):
    data = bytearray()
    while not data.endswith(b"\r\n\r\n"):
        chunk = await reader.read(1)
        if not chunk:
            break
        data += chunk
        if len(data) > 65536:
            raise ValueError("HTTP header terlalu besar")
    return bytes(data)


def parse_headers(raw):
    result = {}
    lines = raw.decode("latin-1", errors="replace").split("\r\n")
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip().lower()] = value.strip()
    return result


def make_accept_key(key):
    digest = hashlib.sha1((key + WS_MAGIC).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


async def read_ws_frame(reader):
    """Read one RFC 6455 frame and return (fin, opcode, payload)."""
    head = await reader.readexactly(2)
    b1, b2 = head
    fin = bool(b1 & 0x80)
    if b1 & 0x70:
        raise ValueError("WebSocket RSV bit tidak didukung")
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    if not masked:
        raise ValueError("Frame dari client harus menggunakan mask")

    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    if length > MAX_FRAME:
        raise ValueError(f"Frame terlalu besar: {length} bytes")
    if opcode >= 8 and (not fin or length > 125):
        raise ValueError("Frame kontrol WebSocket tidak valid")

    mask = await reader.readexactly(4)
    payload = bytearray(await reader.readexactly(length))
    for i in range(length):
        payload[i] ^= mask[i & 3]
    return fin, opcode, bytes(payload)


def make_ws_frame(payload, opcode=2):
    """Server-to-client frames are not masked."""
    n = len(payload)
    first = bytes((0x80 | opcode,))
    if n < 126:
        header = first + bytes((n,))
    elif n <= 0xFFFF:
        header = first + bytes((126,)) + struct.pack("!H", n)
    else:
        header = first + bytes((127,)) + struct.pack("!Q", n)
    return header + payload


async def ws_client_to_ssh(reader, ssh_writer, ws_writer, send_lock):
    fragment_opcode = None
    fragments = bytearray()
    while True:
        fin, opcode, payload = await read_ws_frame(reader)

        if opcode == 0x8:  # close
            async with send_lock:
                ws_writer.write(make_ws_frame(payload[:125], 0x8))
                await ws_writer.drain()
            return
        if opcode == 0x9:  # ping
            async with send_lock:
                ws_writer.write(make_ws_frame(payload, 0xA))
                await ws_writer.drain()
            continue
        if opcode == 0xA:  # pong
            continue

        if opcode in (0x1, 0x2):
            if fragment_opcode is not None:
                raise ValueError("Frame data baru sebelum fragment selesai")
            if fin:
                if payload:
                    ssh_writer.write(payload)
                    await ssh_writer.drain()
            else:
                fragment_opcode = opcode
                fragments.extend(payload)
        elif opcode == 0x0:  # continuation
            if fragment_opcode is None:
                raise ValueError("Continuation frame tanpa fragment awal")
            fragments.extend(payload)
            if len(fragments) > MAX_FRAME:
                raise ValueError("Pesan fragment terlalu besar")
            if fin:
                if fragments:
                    ssh_writer.write(fragments)
                    await ssh_writer.drain()
                fragments.clear()
                fragment_opcode = None
        else:
            raise ValueError(f"Opcode WebSocket tidak didukung: {opcode}")


async def ssh_to_ws(ssh_reader, ws_writer, send_lock):
    while True:
        data = await ssh_reader.read(65536)
        if not data:
            break
        async with send_lock:
            ws_writer.write(make_ws_frame(data, 0x2))
            await ws_writer.drain()
    # Signal end of the WebSocket stream to the client.
    async with send_lock:
        ws_writer.write(make_ws_frame(b"", 0x8))
        await ws_writer.drain()


async def raw_pipe(src, dst):
    while True:
        data = await src.read(65536)
        if not data:
            return
        dst.write(data)
        await dst.drain()


async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    ssh_writer = None
    tasks = []
    try:
        raw_headers = await asyncio.wait_for(read_http_headers(reader), timeout=20)
        if not raw_headers.endswith(b"\r\n\r\n"):
            raise ValueError("HTTP handshake tidak lengkap")
        headers = parse_headers(raw_headers)
        is_upgrade = (
            headers.get("upgrade", "").lower() == "websocket"
            and "upgrade" in headers.get("connection", "").lower()
            and "sec-websocket-key" in headers
        )

        if is_upgrade:
            key = headers["sec-websocket-key"]
            try:
                decoded = base64.b64decode(key, validate=True)
            except Exception:
                raise ValueError("Sec-WebSocket-Key tidak valid")
            if len(decoded) != 16:
                raise ValueError("Sec-WebSocket-Key harus 16 bytes")

            target_reader, ssh_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {make_accept_key(key)}\r\n\r\n"
            )
            writer.write(response.encode("ascii"))
            await writer.drain()
            log.info("%s WebSocket -> SSH %s:%s", peer, TARGET_HOST, TARGET_PORT)

            send_lock = asyncio.Lock()
            tasks = [
                asyncio.create_task(ws_client_to_ssh(reader, ssh_writer, writer, send_lock)),
                asyncio.create_task(ssh_to_ws(target_reader, writer, send_lock)),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
        else:
            # Legacy non-WebSocket payload mode: intentionally raw TCP.
            target_reader, ssh_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
            writer.write(DEFAULT_RESPONSE.encode("latin-1"))
            await writer.drain()
            log.info("%s raw payload -> SSH %s:%s", peer, TARGET_HOST, TARGET_PORT)
            tasks = [
                asyncio.create_task(raw_pipe(reader, ssh_writer)),
                asyncio.create_task(raw_pipe(target_reader, writer)),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc

    except asyncio.IncompleteReadError:
        log.info("%s WebSocket/TCP stream ended", peer)
    except (ConnectionError, asyncio.TimeoutError, ValueError) as exc:
        log.warning("%s closed: %s", peer, exc)
    except Exception:
        log.exception("Error handling %s", peer)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if ssh_writer is not None:
            ssh_writer.close()
            try:
                await ssh_writer.wait_closed()
            except Exception:
                pass
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        log.info("%s disconnected", peer)


async def main():
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    log.info("Listening on %s:%s -> SSH %s:%s", LISTEN_HOST, LISTEN_PORT, TARGET_HOST, TARGET_PORT)
    async with server:
        await server.serve_forever()


def handle_sigterm(*_):
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
