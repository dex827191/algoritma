#!/usr/bin/env python3
"""Public ingress — forwards all TCP to nginx (127.0.0.1:8082)."""
import os, socket, threading

LISTEN_HOST = os.environ.get("PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("XRAY_PROXY_PORT", "8080"))
TARGET_HOST = os.environ.get("NGINX_HOST", "127.0.0.1")
TARGET_PORT = int(os.environ.get("NGINX_PORT", "8082"))


def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass


def handle(client, addr):
    try:
        upstream = socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=10)
        t1 = threading.Thread(target=pipe, args=(client, upstream), daemon=True)
        t2 = threading.Thread(target=pipe, args=(upstream, client), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()
        upstream.close()
    except Exception as e:
        print(f"[proxy] {addr}: {e}")
    finally:
        try: client.close()
        except Exception: pass


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((LISTEN_HOST, LISTEN_PORT))
    s.listen(512)
    print(f"[proxy] {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}")
    while True:
        c, a = s.accept()
        threading.Thread(target=handle, args=(c, a), daemon=True).start()


if __name__ == "__main__":
    main()