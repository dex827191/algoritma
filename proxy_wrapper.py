import asyncio
import os
import re

PUBLIC_PORT = int(os.environ.get("XRAY_PROXY_PORT", "8080"))
NGINX_HOST = "127.0.0.1"
NGINX_PORT = 8082

XRAY_PATHS = (
    "/xhttp", "/httpup", "/vless",
    "/vmess-xhttp", "/vmess-httpup", "/vmess",
    "/trojan-xhttp", "/trojan-httpup", "/trojan"
)

# Whitelist UI/API — hanya path ini yang diteruskan ke nginx -> app.py:2053
UI_EXACT_PATHS = {"/", "/index.html", "/__info"}
UI_API_PREFIX = "/api/"

# HTTP decoy responses: empty body, keep-alive or close.
DECOY_KEEPALIVE = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Length: 0\r\n"
    b"Connection: keep-alive\r\n"
    b"\r\n"
)
DECOY_CLOSE = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Length: 0\r\n"
    b"Connection: close\r\n"
    b"\r\n"
)


def is_ui_path(path: str) -> bool:
    return path in UI_EXACT_PATHS or path.startswith(UI_API_PREFIX)


async def pipe_client_to_up(reader, writer, strip_first_http_header=True):
    first_chunk = True
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
            if first_chunk:
                first_chunk = False
                if strip_first_http_header:
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


async def _drain_body(client_reader, lines, content_length):
    """Buang body request (POST/PUT) supaya koneksi keep-alive tidak desync."""
    if content_length <= 0:
        return
    to_read = content_length
    if client_reader._buffer:
        to_read -= len(bytes(client_reader._buffer))
        client_reader._buffer.clear()
        if to_read <= 0:
            return
    while to_read > 0:
        chunk = await client_reader.read(min(8192, to_read))
        if not chunk:
            break
        to_read -= len(chunk)


async def handle_client(client_reader, client_writer):
    try:
        while True:
            try:
                raw_head = await client_reader.readuntil(b"\r\n\r\n")
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                break

            text_head = raw_head.decode("latin-1", errors="ignore")
            lines = text_head.split("\r\n")
            first_line = lines[0]

            if first_line.startswith("HTTP/"):
                # Baris response nyeleneh, abaikan
                continue

            parts = first_line.split(" ")
            path = parts[1] if len(parts) >= 2 else "/"

            # ---------- 1) Xray WebSocket ----------
            if any(path.startswith(p) for p in XRAY_PATHS):
                host_header = next(
                    (l for l in lines if l.lower().startswith("host:")),
                    "Host: localhost",
                )
                ws_headers = [
                    l for l in lines[1:]
                    if l.lower().startswith("sec-websocket-")
                ]
                if not any(h.lower().startswith("sec-websocket-key:") for h in ws_headers):
                    ws_headers.append("Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==")
                if not any(h.lower().startswith("sec-websocket-version:") for h in ws_headers):
                    ws_headers.append("Sec-WebSocket-Version: 13")

                extra = "\r\n".join(ws_headers) + "\r\n"
                clean_request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"{host_header}\r\n"
                    f"Upgrade: websocket\r\n"
                    f"Connection: Upgrade\r\n"
                    f"{extra}\r\n"
                ).encode("latin-1")

                up_reader, up_writer = await asyncio.open_connection(
                    NGINX_HOST, NGINX_PORT
                )
                up_writer.write(clean_request)
                await up_writer.drain()

                up_resp = await up_reader.readuntil(b"\r\n\r\n")
                client_writer.write(up_resp)
                await client_writer.drain()

                if client_reader._buffer:
                    buf = bytes(client_reader._buffer)
                    cleaned = re.sub(rb"^HTTP/[^\r\n]*\r\n\r\n", b"", buf)
                    client_reader._buffer.clear()
                    if cleaned:
                        up_writer.write(cleaned)
                        await up_writer.drain()

                await asyncio.gather(
                    pipe_client_to_up(client_reader, up_writer),
                    pipe_up_to_client(up_reader, client_writer),
                )
                return

            # ---------- 2) Decoy untuk semua path non-UI ----------
            if not is_ui_path(path):
                content_length = 0
                wants_close = False
                is_chunked = False
                for l in lines:
                    ll = l.lower()
                    if ll.startswith("content-length:"):
                        try:
                            content_length = int(l.split(":", 1)[1].strip())
                        except ValueError:
                            content_length = 0
                    elif ll.startswith("transfer-encoding:") and "chunked" in ll:
                        is_chunked = True
                    elif ll.startswith("connection:") and "close" in ll:
                        wants_close = True

                if is_chunked:
                    wants_close = True
                else:
                    await _drain_body(client_reader, lines, content_length)

                if wants_close or first_line.endswith("HTTP/1.0"):
                    client_writer.write(DECOY_CLOSE)
                    await client_writer.drain()
                    break

                client_writer.write(DECOY_KEEPALIVE)
                await client_writer.drain()
                continue  # request berikutnya di koneksi yang sama

            # ---------- 3) UI / API: proxy ke nginx -> app.py:2053 ----------
            up_reader, up_writer = await asyncio.open_connection(
                NGINX_HOST, NGINX_PORT
            )
            up_writer.write(raw_head)
            await up_writer.drain()
            if client_reader._buffer:
                buffered = bytes(client_reader._buffer)
                client_reader._buffer.clear()
                if buffered:
                    up_writer.write(buffered)
                    await up_writer.drain()
            await asyncio.gather(
                pipe_client_to_up(client_reader, up_writer, strip_first_http_header=False),
                pipe_up_to_client(up_reader, client_writer),
            )
            return

    except Exception:
        pass
    finally:
        try:
            client_writer.close()
            await client_writer.wait_closed()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", PUBLIC_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())