#!/usr/bin/env python3
"""Public TCP multiplexer: TLS -> stunnel, SSH WebSocket -> ws-proxy,
and Xray HTTP/WebSocket paths -> the Xray-only proxy_wrapper."""
import asyncio, logging, os

HOST = "0.0.0.0"
PORT = int(os.environ.get("MAIN_MUX_PORT", os.environ.get("PORT", "8080")))
TLS_HOST, TLS_PORT = os.getenv("SSL_TARGET_HOST","127.0.0.1"), int(os.getenv("SSL_TARGET_PORT","2443"))
SSH_HOST, SSH_PORT = os.getenv("WS_MUX_TARGET_HOST","127.0.0.1"), int(os.getenv("WS_MUX_TARGET_PORT","8880"))
XRAY_HOST, XRAY_PORT = os.getenv("XRAY_PROXY_HOST","127.0.0.1"), int(os.getenv("XRAY_PROXY_PORT","8082"))
XRAY_PATHS = ("/xhttp","/httpup","/vless","/vmess-xhttp","/vmess-httpup","/vmess",
              "/trojan-xhttp","/trojan-httpup","/trojan")
logging.basicConfig(level=logging.INFO, format="[mux] %(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("mux")

async def pipe(src,dst):
    try:
        while True:
            chunk=await src.read(65536)
            if not chunk: break
            dst.write(chunk); await dst.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try: dst.close()
        except Exception: pass

async def handle(reader,writer):
    peer=writer.get_extra_info("peername")
    upstream_writer=None
    try:
        first=await asyncio.wait_for(reader.read(1),timeout=3)
        if not first: return
        if first[0] == 0x16:
            host,port,label=TLS_HOST,TLS_PORT,"TLS/stunnel"
            initial=first
        else:
            # HTTP Upgrade requests are used by both SSH and Xray; inspect the request path.
            try:
                rest=await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),timeout=5)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                rest=b""
            initial=first+rest
            line=initial.split(b"\r\n",1)[0].decode("latin-1","ignore")
            parts=line.split()
            path=parts[1].split("?",1)[0] if len(parts)>1 else "/"
            headers=initial.lower()
            is_xray=any(path.startswith(p) for p in XRAY_PATHS)
            is_upgrade=b"upgrade: websocket" in headers
            if is_xray:
                host,port,label=XRAY_HOST,XRAY_PORT,"Xray"
            elif is_upgrade:
                host,port,label=SSH_HOST,SSH_PORT,"SSH WebSocket"
            else:
                host,port,label=PANEL_HOST,PANEL_PORT,"Panel/API"
        log.info("%s -> %s %s:%s",peer,label,host,port)
        up_reader,upstream_writer=await asyncio.open_connection(host,port)
        if initial:
            upstream_writer.write(initial); await upstream_writer.drain()
        await asyncio.gather(pipe(reader,upstream_writer),pipe(up_reader,writer))
    except Exception as e:
        log.warning("Connection %s: %s",peer,e)
    finally:
        for w in (upstream_writer,writer):
            if w:
                try: w.close()
                except Exception: pass

async def main():
    server=await asyncio.start_server(handle,HOST,PORT,limit=131072)
    log.info("Listening on %s:%s",HOST,PORT)
    async with server: await server.serve_forever()
if __name__=="__main__": asyncio.run(main())
