#!/usr/bin/env python3
"""HTTP stream wrapper: public listener -> internal Nginx router.

Only the configured WebSocket paths are normalized to a WebSocket handshake.
XHTTP and HTTPUpgrade requests are forwarded unchanged so each Xray transport
keeps its own protocol semantics.
"""
import asyncio
import os
import re

LISTEN_HOST = os.getenv("WRAPPER_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("WRAPPER_PORT", "8080"))
NGINX_HOST = os.getenv("NGINX_HOST", "127.0.0.1")
NGINX_PORT = int(os.getenv("NGINX_PORT", "8082"))
HEADER_LIMIT = 65536

# These are the WebSocket inbounds only. Do not add XHTTP or HTTPUpgrade paths.
XRAY_PATHS = ("/vless", "/vmess", "/trojan")


async def pipe_client_to_up(reader, writer):
    first_chunk = True
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
            if first_chunk:
                first_chunk = False
                data = re.sub(rb"^HTTP/[^\r\n]*\r\n\r\n", b"", data)
                if not data:
                    continue
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def pipe_up_to_client(reader, writer):
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _pipe_bidirectional(client_reader, client_writer, up_reader, up_writer):
    tasks = [
        asyncio.create_task(pipe_client_to_up(client_reader, up_writer)),
        asyncio.create_task(pipe_up_to_client(up_reader, client_writer)),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def handle_client(client_reader, client_writer):
    up_writer = None
    try:
        while True:
            raw_head = await asyncio.wait_for(
                client_reader.readuntil(b"\r\n\r\n"), timeout=30
            )
            if len(raw_head) > HEADER_LIMIT:
                raise ValueError("HTTP header too large")

            text_head = raw_head.decode("latin-1", errors="ignore")
            lines = text_head.split("\r\n")
            first_line = lines[0]

            # Ignore stray/interim HTTP response lines, as in the requested flow.
            if first_line.startswith("HTTP/"):
                continue

            parts = first_line.split(" ")
            path = parts[1] if len(parts) >= 2 else "/"
            is_ws_path = any(path.split("?", 1)[0].startswith(p) for p in XRAY_PATHS)

            up_reader, up_writer = await asyncio.open_connection(NGINX_HOST, NGINX_PORT)

            if is_ws_path:
                host_header = next(
                    (line for line in lines if line.lower().startswith("host:")),
                    "Host: localhost",
                )
                ws_headers = [
                    line for line in lines[1:]
                    if line.lower().startswith("sec-websocket-")
                ]
                if not any(h.lower().startswith("sec-websocket-key:") for h in ws_headers):
                    ws_headers.append("Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==")
                if not any(h.lower().startswith("sec-websocket-version:") for h in ws_headers):
                    ws_headers.append("Sec-WebSocket-Version: 13")

                extra = "\r\n".join(ws_headers)
                clean_request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"{host_header}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"{extra}\r\n\r\n"
                ).encode("latin-1")
                up_writer.write(clean_request)
            else:
                # XHTTP, HTTPUpgrade, health checks, and other HTTP requests
                # retain their original method, path, and headers.
                up_writer.write(raw_head)

            await up_writer.drain()

            if is_ws_path:
                up_resp = await asyncio.wait_for(
                    up_reader.readuntil(b"\r\n\r\n"), timeout=30
                )
                client_writer.write(up_resp)
                await client_writer.drain()

            await _pipe_bidirectional(
                client_reader, client_writer, up_reader, up_writer
            )
            return

    except Exception:
        pass
    finally:
        if up_writer is not None:
            try:
                up_writer.close()
                await up_writer.wait_closed()
            except Exception:
                pass
        try:
            client_writer.close()
            await client_writer.wait_closed()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(
        handle_client, LISTEN_HOST, LISTEN_PORT, limit=HEADER_LIMIT
    )
    print(
        f"[wrapper] listening on {LISTEN_HOST}:{LISTEN_PORT} "
        f"-> {NGINX_HOST}:{NGINX_PORT}; websocket paths={XRAY_PATHS}",
        flush=True,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
