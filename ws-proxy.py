#!/usr/bin/env python3
"""Raw TCP WebSocket-to-SSH bridge, mirroring the supplied Node.js behavior."""
import asyncio
import base64
import hashlib
import logging
import os
import socket
import json
import time

HOST = "0.0.0.0"
PORT = int(os.getenv("WS_PORT", "8880"))
SSH_HOST = os.getenv("SSH_TARGET_HOST", "127.0.0.1")
CONFIG_FILE = "/tmp/ws_proxy_config.json"
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
CONNS_FILE = "/tmp/ssh_conns.json"
ACTIVE_WS = {}
CONN_SEQ = 0


def write_registry():
    try:
        items = list(ACTIVE_WS.values())
        data = {
            "updated": int(time.time() * 1000),
            "total": len(items),
            "ws_active": len(items),
            "ssl_active": 0,
            "list": items,
        }
        tmp = CONNS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, CONNS_FILE)
    except Exception:
        pass


write_registry()

logging.basicConfig(level=logging.INFO, format="[WS Engine Python] %(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ws-proxy")


def get_proxy_config():
    import json
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if isinstance(cfg, dict):
                return cfg
    except (OSError, ValueError, TypeError):
        pass
    return {
        "sshPort": int(os.getenv("SSH_TARGET_PORT", "22")),
        "keepAlive": 15000,
        "maxBuffer": 32 * 1024,
    }


def parse_headers(raw):
    headers = {}
    try:
        lines = raw.decode("latin-1", "ignore").split("\r\n")
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
    except Exception:
        pass
    return headers


def ws_accept(key):
    digest = hashlib.sha1((key + WS_MAGIC).encode()).digest()
    return base64.b64encode(digest).decode()


def tune(writer, keepalive_ms):
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, max(1, int(keepalive_ms / 1000)))
    except (AttributeError, OSError):
        pass


async def write_data(writer, data):
    if data and not writer.is_closing():
        writer.write(data)
        await writer.drain()


async def handle_client(client_reader, client_writer):
    cfg = get_proxy_config()
    ssh_port = int(cfg.get("sshPort") or os.getenv("SSH_TARGET_PORT", "22"))
    keepalive = int(cfg.get("keepAlive") or 15000)
    max_buffer = int(cfg.get("maxBuffer") or 32768)
    global CONN_SEQ
    peer = client_writer.get_extra_info("peername")
    tune(client_writer, keepalive)
    ssh_writer = None
    conn_id = None
    headers_for_ip = {}

    try:
        # Read the initial HTTP request/header block while retaining any bytes
        # that arrived after CRLFCRLF in the same TCP packet.
        initial = await asyncio.wait_for(client_reader.read(65536), timeout=15)
        if not initial:
            return

        header_end = initial.find(b"\r\n\r\n")
        if header_end >= 0:
            header_block = initial[:header_end + 4]
            trailing = initial[header_end + 4:]
        else:
            header_block, trailing = initial, b""

        headers = parse_headers(header_block)
        headers_for_ip = headers
        lower = header_block.lower()
        is_upgrade = b"upgrade: websocket" in lower or headers.get("upgrade", "").lower() == "websocket"

        if is_upgrade:
            key = headers.get("sec-websocket-key")
            if not key:
                # Match the permissive fallback in the supplied JS.
                key = base64.b64encode(os.urandom(16)).decode()
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {ws_accept(key)}\r\n"
            )
            if headers.get("sec-websocket-protocol"):
                response += f"Sec-WebSocket-Protocol: {headers['sec-websocket-protocol']}\r\n"
            response += "\r\n"
            await write_data(client_writer, response.encode())
        else:
            default_resp = os.getenv("WS_RESPONSE", "HTTP/1.1 101 Switching Protocols\r\n\r\n")
            await write_data(client_writer, default_resp.encode())

        ssh_reader, ssh_writer = await asyncio.wait_for(
            asyncio.open_connection(SSH_HOST, ssh_port), timeout=10
        )
        tune(ssh_writer, keepalive)
        pending = bytearray()

        async def send_client_payload(data):
            nonlocal pending, conn_id
            global CONN_SEQ
            if not data:
                return
            if pending is not None:
                pending.extend(data)
                marker = pending.find(b"SSH-")
                if marker >= 0:
                    await write_data(ssh_writer, bytes(pending[marker:]))
                    pending = None
                    if conn_id is None:
                        CONN_SEQ += 1
                        conn_id = str(CONN_SEQ)
                        ip = (headers_for_ip.get("cf-connecting-ip")
                              or headers_for_ip.get("x-forwarded-for", "").split(",")[0].strip()
                              or (peer[0] if peer else "Unknown"))
                        ACTIVE_WS[conn_id] = {"ip": ip, "since": int(time.time() * 1000), "via": "WS"}
                        write_registry()
                elif len(pending) > max_buffer:
                    raise ConnectionError("SSH identification string not found within maxBuffer")
            else:
                await write_data(ssh_writer, data)

        if trailing:
            await send_client_payload(trailing)

        async def client_to_ssh():
            while True:
                chunk = await client_reader.read(65536)
                if not chunk:
                    break
                await send_client_payload(chunk)

        async def ssh_to_client():
            while True:
                chunk = await ssh_reader.read(65536)
                if not chunk:
                    break
                await write_data(client_writer, chunk)

        tasks = [asyncio.create_task(client_to_ssh()), asyncio.create_task(ssh_to_client())]
        done, pending_tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending_tasks:
            task.cancel()
        await asyncio.gather(*pending_tasks, return_exceptions=True)
    except (asyncio.TimeoutError, ConnectionError, OSError, ValueError) as exc:
        log.info("Connection %s closed: %s", peer, exc)
    except Exception:
        log.exception("Unhandled client error from %s", peer)
    finally:
        if conn_id is not None:
            ACTIVE_WS.pop(conn_id, None)
            write_registry()
        for writer in (ssh_writer, client_writer):
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass


async def main():
    server = await asyncio.start_server(handle_client, HOST, PORT, limit=65536)
    log.info("Dynamic Proxy Active on %s:%s -> %s:%s", HOST, PORT, SSH_HOST, os.getenv("SSH_TARGET_PORT", "22"))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
