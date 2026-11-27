#!/usr/bin/env python3
"""
TCP Multiplexer ala sslh — High-Speed Pure Edition + Real-IP Recorder.

Mendengarkan di SATU port publik (SSH_PORT/8081), mengintip byte pertama
dengan proteksi timeout, lalu:
  - 0x16               -> TLS handshake  -> stunnel (2443) -> dropbear (22)
  - HTTP verb (WS)     -> WebSocket      -> ws-proxy (8880) -> dropbear (22)
  - HTTP verb (other)  -> ditutup (bukan WS upgrade)
  - byte lain          -> RAW SSH        -> dropbear (22)

Setiap koneksi dicatat ke /run/ssh-clients.json supaya panel `app.py`
bisa menampilkan IP asli client di dashboard.
"""

import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LISTEN_HOST = os.environ.get("SSH_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("SSH_PORT", os.environ.get("MAIN_MUX_PORT", "8081")))

SSL_TARGET_HOST = os.environ.get("SSL_TARGET_HOST", "127.0.0.1")
SSL_TARGET_PORT = int(os.environ.get("SSL_TARGET_PORT", "2443"))

WS_TARGET_HOST = os.environ.get("WS_TARGET_HOST",
                                os.environ.get("WS_MUX_TARGET_HOST", "127.0.0.1"))
WS_TARGET_PORT = int(os.environ.get("WS_TARGET_PORT",
                                    os.environ.get("WS_MUX_TARGET_PORT", "8880")))

RAW_TARGET_HOST = os.environ.get("RAW_TARGET_HOST", "127.0.0.1")
RAW_TARGET_PORT = int(os.environ.get("RAW_TARGET_PORT", "22"))

TLS_HANDSHAKE_BYTE = 0x16
HTTP_VERB_BYTES = set(b"GPHDOCONRT")   # GET, POST, HEAD, DELETE, OPTIONS, CONNECT, ...

CLIENT_FILE = os.environ.get("SSH_CLIENTS_FILE", "/run/ssh-clients.json")
CLIENT_TTL_SEC = 3600
RECORD_INTERVAL_MIN = 5.0   # detik — hindari spam disk kalau IP sama berulang

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[mux] %(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("mux")

# ---------------------------------------------------------------------------
# Real-IP recorder (async-safe, single writer)
# ---------------------------------------------------------------------------
_record_lock = asyncio.Lock()
_recent_ips: dict[str, float] = {}   # ip -> last_write_ts


def _load_clients() -> list[dict]:
    try:
        if not os.path.exists(CLIENT_FILE):
            return []
        with open(CLIENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_clients(data: list[dict]) -> None:
    try:
        d = os.path.dirname(CLIENT_FILE) or "."
        os.makedirs(d, exist_ok=True)
        tmp = CLIENT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, CLIENT_FILE)
    except Exception as e:
        log.debug("record save error: %s", e)


async def record_client(ip: str, kind: str) -> None:
    """Catat IP client ke /run/ssh-clients.json (dedupe dalam RECORD_INTERVAL_MIN)."""
    if not ip or ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "0.0.0.0"):
        return
    now = time.time()
    if now - _recent_ips.get(ip, 0) < RECORD_INTERVAL_MIN:
        return
    async with _record_lock:
        _recent_ips[ip] = now
        data = _load_clients()
        data = [d for d in data if isinstance(d, dict)
                and (now - d.get("ts", 0)) < CLIENT_TTL_SEC]
        data.append({"ip": ip, "kind": kind, "ts": now})
        _save_clients(data)


# ---------------------------------------------------------------------------
# Pipe (full-speed, no fragmentation)
# ---------------------------------------------------------------------------
async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(65536)
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


def _set_socket_options(writer: asyncio.StreamWriter) -> None:
    """TCP_NODELAY + keepalive pada upstream socket (anti-lag & dead detection)."""
    try:
        sock = writer.get_extra_info("socket")
        if sock is None:
            return
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # Linux-specific tuning (aman diabaikan kalau tidak tersedia)
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 4)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Handle client
# ---------------------------------------------------------------------------
async def handle_client(reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    peer_ip = peer[0] if peer else "?"
    first_byte = b""

    try:
        # Intip 1 byte dengan timeout 0.5s
        try:
            first_byte = await asyncio.wait_for(reader.read(1), timeout=0.5)
        except asyncio.TimeoutError:
            first_byte = b""

        if not first_byte:
            # klien lambat / port scanner — tutup
            writer.close()
            return

        # ---- Tentukan backend ----
        b0 = first_byte[0]
        kind = "raw"
        if b0 == TLS_HANDSHAKE_BYTE:
            th, tp, label, kind = SSL_TARGET_HOST, SSL_TARGET_PORT, "SSL", "tls"
        elif b0 in HTTP_VERB_BYTES:
            # baca header awal (peek) untuk deteksi WebSocket Upgrade
            peek = b""
            try:
                peek = await asyncio.wait_for(reader.read(512), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            low = (first_byte + peek).lower()
            if b"upgrade" in low and b"websocket" in low:
                th, tp, label, kind = WS_TARGET_HOST, WS_TARGET_PORT, "WS", "ws"
                # prepend: put back peeked data by concatenating later
                _prepend_ws = first_byte + peek
            else:
                # HTTP non-WS → tutup (bukan SSH)
                writer.close()
                return
        else:
            th, tp, label, kind = RAW_TARGET_HOST, RAW_TARGET_PORT, "RAW", "raw"

        log.info("%s -> %s (%s:%s)", peer_ip, label, th, tp)

        # ---- Buka upstream ----
        try:
            target_reader, target_writer = await asyncio.open_connection(th, tp)
        except Exception as e:
            log.error("connect %s:%s failed: %s", th, tp, e)
            writer.close()
            return

        _set_socket_options(target_writer)
        _set_socket_options(writer)

        # ---- Kirim byte yang sudah diintip ----
        if kind == "ws":
            target_writer.write(first_byte + peek)
        else:
            target_writer.write(first_byte)
        await target_writer.drain()

        # Catat real-IP client (async, jangan block pipe)
        asyncio.create_task(record_client(peer_ip, kind))

        # ---- Full-speed bidirectional pipe ----
        await asyncio.gather(
            pipe(reader, target_writer),
            pipe(target_reader, writer),
        )

    except Exception as e:
        log.error("client %s error: %s", peer_ip, e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    server = await asyncio.start_server(
        handle_client, LISTEN_HOST, LISTEN_PORT, limit=16384,
    )
    log.info(
        "mux %s:%s | TLS:%s WS:%s RAW:%s | recorder:%s",
        LISTEN_HOST, LISTEN_PORT,
        SSL_TARGET_PORT, WS_TARGET_PORT, RAW_TARGET_PORT,
        CLIENT_FILE,
    )
    async with server:
        await server.serve_forever()


def _handle_sigterm(*_):
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass