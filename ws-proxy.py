#!/usr/bin/env python3
"""WebSocket → TCP proxy (WS-over-HTTP for SSH clients)."""
import base64, hashlib, os, socket, struct, threading

LISTEN_HOST = os.environ.get("WS_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("WS_PORT", "8880"))
TARGET_HOST = os.environ.get("WS_TARGET_HOST", "127.0.0.1")
TARGET_PORT = int(os.environ.get("WS_TARGET_PORT", "22"))

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError()
        buf += chunk
    return buf


def ws_recv_frame(sock):
    b0, b1 = recv_exact(sock, 2)
    fin = b0 & 0x80
    opcode = b0 & 0x0f
    masked = b1 & 0x80
    length = b1 & 0x7f
    if length == 126:
        length = struct.unpack(">H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", recv_exact(sock, 8))[0]
    mask = recv_exact(sock, 4) if masked else None
    payload = bytearray(recv_exact(sock, length))
    if mask:
        for i in range(length):
            payload[i] ^= mask[i % 4]
    return opcode, bytes(payload), fin


def ws_send(sock, data, opcode=0x2):
    length = len(data)
    header = bytes([0x80 | opcode])
    if length < 126:
        header += bytes([length])
    elif length < 65536:
        header += bytes([126]) + struct.pack(">H", length)
    else:
        header += bytes([127]) + struct.pack(">Q", length)
    sock.sendall(header + data)


def handle(client, addr):
    try:
        client.settimeout(10)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = client.recv(4096)
            if not chunk:
                return
            buf += chunk
        header, rest = buf.split(b"\r\n\r\n", 1)
        headers = {}
        for line in header.split(b"\r\n")[1:]:
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower().decode()] = v.strip().decode()
        key = headers.get("sec-websocket-key", "")
        if not key:
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        accept = base64.b64encode(
            hashlib.sha1((key + GUID).encode()).digest()
        ).decode()
        client.sendall((
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode())
        client.settimeout(None)

        upstream = socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=10)

        # kalau ada frame pertama di 'rest'
        if rest:
            try:
                data, _ = _decode_frames_bytes(rest)
                if data:
                    upstream.sendall(data)
            except Exception:
                upstream.sendall(rest)

        def c2s():
            try:
                while True:
                    op, payload, fin = ws_recv_frame(client)
                    if op == 0x8:  # close
                        break
                    if op in (0x1, 0x2, 0x0):
                        upstream.sendall(payload)
                    elif op == 0x9:  # ping
                        ws_send(client, payload, 0xA)
            except Exception:
                pass
            finally:
                try: upstream.shutdown(socket.SHUT_WR)
                except Exception: pass

        def s2c():
            try:
                while True:
                    data = upstream.recv(65536)
                    if not data:
                        break
                    ws_send(client, data)
            except Exception:
                pass
            finally:
                try: client.close()
                except Exception: pass

        t1 = threading.Thread(target=c2s, daemon=True)
        t2 = threading.Thread(target=s2c, daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()
        upstream.close()
    except Exception as e:
        print(f"[ws] {addr}: {e}")
    finally:
        try: client.close()
        except Exception: pass


def _decode_frames_bytes(buf):
    out = bytearray()
    while len(buf) >= 2:
        b0, b1 = buf[0], buf[1]
        opcode = b0 & 0x0f
        masked = b1 & 0x80
        length = b1 & 0x7f
        off = 2
        if length == 126:
            if len(buf) < 4: break
            length = struct.unpack(">H", buf[2:4])[0]; off = 4
        elif length == 127:
            if len(buf) < 10: break
            length = struct.unpack(">Q", buf[2:10])[0]; off = 10
        mask = None
        if masked:
            if len(buf) < off + 4: break
            mask = buf[off:off+4]; off += 4
        if len(buf) < off + length: break
        payload = bytearray(buf[off:off+length])
        if mask:
            for i in range(len(payload)):
                payload[i] ^= mask[i % 4]
        if opcode in (0x1, 0x2, 0x0):
            out += payload
        buf = buf[off+length:]
    return bytes(out), buf


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((LISTEN_HOST, LISTEN_PORT))
    s.listen(256)
    print(f"[ws] {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}")
    while True:
        c, a = s.accept()
        threading.Thread(target=handle, args=(c, a), daemon=True).start()


if __name__ == "__main__":
    main()