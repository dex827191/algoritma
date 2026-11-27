#!/usr/bin/env python3
"""Minimal RFC 6455 WebSocket-to-TCP bridge for SSH. Supports masked client frames,
fragmentation, ping/pong and close control frames; sends SSH bytes as binary frames."""
import asyncio, base64, hashlib, logging, os, struct

HOST = '127.0.0.1'
PORT = int(os.environ.get('WS_PORT', '8880'))
TARGET_HOST = os.environ.get('WS_TARGET_HOST', '127.0.0.1')
TARGET_PORT = int(os.environ.get('WS_TARGET_PORT', '22'))
PATH = os.environ.get('WS_PATH', '/sshws')
MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
logging.basicConfig(level=logging.INFO, format='[ssh-ws] %(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('ssh-ws')

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
    if length > 2 * 1024 * 1024:
        raise ValueError('WebSocket frame too large')
    mask = await reader.readexactly(4) if masked else b''
    payload = await reader.readexactly(length)
    if masked:
        payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    return fin, opcode, payload

async def send_frame(writer, opcode, payload=b''):
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126: head += bytes([n])
    elif n < 65536: head += bytes([126]) + struct.pack('!H', n)
    else: head += bytes([127]) + struct.pack('!Q', n)
    writer.write(head + payload)
    await writer.drain()

async def handle(reader, writer):
    peer = writer.get_extra_info('peername')
    target_writer = None
    try:
        raw = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=10)
        if len(raw) > 16384: raise ValueError('HTTP headers too large')
        lines = raw.decode('latin-1').split('\r\n')
        parts = lines[0].split(' ')
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1); headers[k.strip().lower()] = v.strip()
        if len(parts) < 3 or parts[0] != 'GET' or parts[1].split('?',1)[0] != PATH:
            writer.write(b'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            await writer.drain(); return
        key = headers.get('sec-websocket-key')
        if headers.get('upgrade','').lower() != 'websocket' or not key or headers.get('sec-websocket-version') != '13':
            writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            await writer.drain(); return
        accept = base64.b64encode(hashlib.sha1((key + MAGIC).encode()).digest()).decode()
        writer.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n').encode())
        await writer.drain()
        target_reader, target_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
        log.info('WebSocket SSH connected from %s', peer)

        async def ws_to_ssh():
            fragments = bytearray(); fragment_opcode = None
            while True:
                fin, opcode, data = await read_frame(reader)
                if opcode == 8:
                    await send_frame(writer, 8, data[:125]); break
                if opcode == 9:
                    await send_frame(writer, 10, data); continue
                if opcode == 10: continue
                if opcode in (1, 2):
                    if fragment_opcode is not None: raise ValueError('unexpected new data frame')
                    fragment_opcode = opcode; fragments.extend(data)
                elif opcode == 0 and fragment_opcode is not None:
                    fragments.extend(data)
                else:
                    raise ValueError('invalid WebSocket opcode/fragment')
                if fin and fragment_opcode is not None:
                    target_writer.write(fragments); await target_writer.drain()
                    fragments.clear(); fragment_opcode = None

        async def ssh_to_ws():
            while True:
                data = await target_reader.read(32768)
                if not data: break
                await send_frame(writer, 2, data)

        tasks = [asyncio.create_task(ws_to_ssh()), asyncio.create_task(ssh_to_ws())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending: task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError):
        pass
    except Exception as exc:
        log.warning('Connection %s ended: %s', peer, exc)
    finally:
        if target_writer:
            target_writer.close()
            try: await target_writer.wait_closed()
            except Exception: pass
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass

async def main():
    server = await asyncio.start_server(handle, HOST, PORT, limit=2*1024*1024+16)
    log.info('SSH WebSocket listening on %s:%s path=%s -> %s:%s', HOST, PORT, PATH, TARGET_HOST, TARGET_PORT)
    async with server: await server.serve_forever()

if __name__ == '__main__': asyncio.run(main())
