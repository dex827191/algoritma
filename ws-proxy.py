#!/usr/bin/env python3
"""RFC6455 WebSocket <-> raw SSH TCP bridge (stdlib only)."""
import asyncio
import base64
import hashlib
import logging
import os
import struct

HOST = os.getenv('WS_LISTEN_HOST', '127.0.0.1')
PORT = int(os.getenv('WS_PORT', '8880'))
TARGET_HOST = os.getenv('WS_TARGET_HOST', '127.0.0.1')
TARGET_PORT = int(os.getenv('WS_TARGET_PORT', '22'))
MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
MAX_FRAME = int(os.getenv('WS_MAX_FRAME', str(2 * 1024 * 1024)))
logging.basicConfig(level=logging.INFO, format='[ws-proxy] %(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('ws-proxy')

async def read_headers(reader):
    data = await reader.readuntil(b'\r\n\r\n')
    if len(data) > 65536:
        raise ValueError('HTTP headers too large')
    return data

def parse_headers(raw):
    lines = raw.decode('latin1').split('\r\n')
    request = lines[0].split()
    headers = {}
    for line in lines[1:]:
        if ':' in line:
            k, v = line.split(':', 1)
            headers[k.strip().lower()] = v.strip()
    return request, headers

async def send_http_error(writer, status, message):
    body = (message + '\n').encode()
    writer.write(f'HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body)
    await writer.drain()

async def read_frame(reader):
    head = await reader.readexactly(2)
    fin = bool(head[0] & 0x80)
    opcode = head[0] & 0x0f
    masked = bool(head[1] & 0x80)
    length = head[1] & 0x7f
    if length == 126:
        length = struct.unpack('!H', await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack('!Q', await reader.readexactly(8))[0]
    if length > MAX_FRAME:
        raise ValueError('WebSocket frame too large')
    mask = await reader.readexactly(4) if masked else b''
    payload = await reader.readexactly(length) if length else b''
    if masked:
        payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    return fin, opcode, payload

async def send_frame(writer, opcode, payload=b''):
    n = len(payload)
    first = bytes([0x80 | opcode])
    if n < 126:
        header = first + bytes([n])
    elif n < 65536:
        header = first + bytes([126]) + struct.pack('!H', n)
    else:
        header = first + bytes([127]) + struct.pack('!Q', n)
    writer.write(header + payload)
    await writer.drain()

async def ws_to_ssh(reader, ssh_writer, ws_writer):
    fragmented = bytearray()
    fragment_opcode = None
    while True:
        fin, opcode, payload = await read_frame(reader)
        if opcode == 0x8:
            try: await send_frame(ws_writer, 0x8, payload[:125])
            except Exception: pass
            break
        if opcode == 0x9:
            await send_frame(ws_writer, 0xA, payload)
            continue
        if opcode == 0xA:
            continue
        if opcode in (0x1, 0x2):
            if fragment_opcode is not None:
                raise ValueError('unexpected new data frame during fragmentation')
            if fin:
                if opcode == 0x2:
                    ssh_writer.write(payload); await ssh_writer.drain()
                # Text frames are ignored: SSH is a binary byte stream.
            else:
                fragment_opcode = opcode
                fragmented.extend(payload)
        elif opcode == 0x0:
            if fragment_opcode is None:
                raise ValueError('unexpected continuation frame')
            fragmented.extend(payload)
            if len(fragmented) > MAX_FRAME:
                raise ValueError('fragmented message too large')
            if fin:
                if fragment_opcode == 0x2:
                    ssh_writer.write(fragmented); await ssh_writer.drain()
                fragmented.clear(); fragment_opcode = None
        else:
            raise ValueError('unsupported WebSocket opcode')

async def ssh_to_ws(ssh_reader, ws_writer):
    while True:
        data = await ssh_reader.read(32768)
        if not data:
            break
        await send_frame(ws_writer, 0x2, data)
    try: await send_frame(ws_writer, 0x8, struct.pack('!H', 1000))
    except Exception: pass

async def handle(reader, writer):
    peer = writer.get_extra_info('peername')
    ssh_writer = None
    try:
        raw = await read_headers(reader)
        request, h = parse_headers(raw)
        if len(request) < 3 or request[0] != 'GET':
            await send_http_error(writer, '400 Bad Request', 'WebSocket GET required'); return
        key = h.get('sec-websocket-key', '')
        try:
            decoded = base64.b64decode(key, validate=True)
        except Exception:
            decoded = b''
        if (h.get('upgrade', '').lower() != 'websocket' or
            'upgrade' not in h.get('connection', '').lower() or
            h.get('sec-websocket-version') != '13' or len(decoded) != 16):
            await send_http_error(writer, '400 Bad Request', 'Invalid WebSocket handshake'); return
        accept = base64.b64encode(hashlib.sha1((key + MAGIC).encode()).digest()).decode()
        ssh_reader, ssh_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
        writer.write((f'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n').encode())
        await writer.drain()
        log.info('WebSocket %s established; SSH target %s:%s', peer, TARGET_HOST, TARGET_PORT)
        tasks = [asyncio.create_task(ws_to_ssh(reader, ssh_writer, writer)),
                 asyncio.create_task(ssh_to_ws(ssh_reader, writer))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending: task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc: log.info('connection %s ended: %s', peer, exc)
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.LimitOverrunError):
        log.info('connection %s closed', peer)
    except Exception as e:
        log.warning('connection %s error: %s', peer, e)
    finally:
        if ssh_writer:
            ssh_writer.close()
            try: await ssh_writer.wait_closed()
            except Exception: pass
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass

async def main():
    server = await asyncio.start_server(handle, HOST, PORT, limit=MAX_FRAME + 65536)
    log.info('listening %s:%s -> %s:%s', HOST, PORT, TARGET_HOST, TARGET_PORT)
    async with server: await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
