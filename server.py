#!/usr/bin/env python3
"""Panel SSH/Xray API + standalone index.html server (stdlib only)."""
import datetime
import json
import os
import re
import shutil
import subprocess
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR") or os.environ.get("FILE_PATH") or BASE_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("PANEL_PORT", "2053"))
HOST = os.environ.get("PANEL_HOST", "0.0.0.0")
DB_FILE = DATA_DIR / "ssh_accounts.json"
XRAY_DB_FILE = DATA_DIR / "xray_accounts.json"
XRAY_CONFIG_FILE = Path(os.environ.get("XRAY_CONFIG") or DATA_DIR / "config.json")
ADMIN_FILE = Path("/tmp/admin_pass.txt")
WS_FILE = Path("/tmp/ws_proxy_config.json")
SYS_FILE = Path("/tmp/system_config.json")
UUID_FILE = DATA_DIR / "uuid.txt"
INDEX_FILE = BASE_DIR / "index.html"
RESERVED = set("root daemon bin sys sync games man lp mail news uucp proxy www-data backup list irc gnats nobody ubuntu sshd dropbear stunnel".split())

def read_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return fallback

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)

def run(command, args, input_text=None):
    return subprocess.run(
        [command, *args], input=input_text, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
    ).stdout

def linux_uid(username):
    try:
        return int(run("id", ["-u", username]).strip())
    except Exception:
        return None

def valid_username(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value, re.I) is not None

def valid_password(value):
    return isinstance(value, str) and bool(value) and not re.search(r"[\r\n:]", value)

def create_linux_user(username):
    run("useradd", ["-m", "-s", "/bin/bash", "--", username])

def set_linux_password(username, password):
    run("chpasswd", [], f"{username}:{password}\n")

def remove_linux_user(username):
    subprocess.run(["pkill", "-9", "-u", username], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run("userdel", ["-r", "--", username])

def load_db():
    value = read_json(DB_FILE, {})
    return value if isinstance(value, dict) else {}

def save_db(db):
    write_json(DB_FILE, db)

def list_ssh():
    db = load_db()
    users = []
    try:
        passwd = Path("/etc/passwd").read_text(encoding="utf-8")
    except OSError:
        passwd = ""
    for line in passwd.splitlines():
        fields = line.split(":")
        if len(fields) < 7:
            continue
        username = fields[0]
        try:
            uid = int(fields[2])
        except ValueError:
            continue
        if uid < 1000 or username.lower() in RESERVED:
            continue
        row = db.get(username, {})
        users.append({
            "username": username, "uid": uid, "shell": fields[-1],
            "password": row.get("password") or "-",
            "ip": row.get("ip_address") or "Unknown",
            "user_agent": row.get("user_agent") or "Unknown",
            "created_at": row.get("created_at"),
            "has_db_entry": username in db
        })
    users.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"status": "success", "total": len(users), "users": users}

def add_ssh(username, password, ip, agent):
    if not valid_username(username):
        return {"status": "error", "message": "Username tidak valid. Gunakan huruf, angka, _ atau -."}
    if not valid_password(password):
        return {"status": "error", "message": "Password kosong atau mengandung karakter yang tidak didukung."}
    db = load_db()
    if username in db or linux_uid(username) is not None:
        return {"status": "error", "message": "Username sudah digunakan."}
    created = False
    try:
        create_linux_user(username)
        created = True
        set_linux_password(username, password)
        db[username] = {
            "password": password, "ip_address": str(ip or "Unknown")[:255],
            "user_agent": str(agent or "Unknown")[:1000],
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        save_db(db)
        domain = os.environ.get("SSH_DOMAIN") or os.environ.get("DOMAIN") or "isi SSH_DOMAIN di Railway Variables"
        return {"status": "success", "username": username, "password": password,
                "message": f"Akun SSH berhasil dibuat\nHost: {domain}\nPort: 8080\nPath: /ssh-ws\nUsername: {username}\nPassword: {password}"}
    except Exception as exc:
        if created:
            try: remove_linux_user(username)
            except Exception: pass
        detail = getattr(exc, "stderr", "") or str(exc)
        if isinstance(detail, bytes): detail = detail.decode(errors="replace")
        return {"status": "error", "message": f"Gagal membuat akun: {str(detail).strip()}"}

def delete_ssh(username):
    if not valid_username(username):
        return {"status": "error", "message": "Username tidak valid."}
    db = load_db()
    if username not in db:
        return {"status": "error", "message": "Akun tidak ditemukan di database SSH."}
    try:
        uid = linux_uid(username)
        if uid is not None:
            if uid < 1000:
                return {"status": "error", "message": "Akun sistem dilindungi."}
            remove_linux_user(username)
        del db[username]
        save_db(db)
        return {"status": "success", "message": f"Akun {username} berhasil dihapus."}
    except Exception as exc:
        return {"status": "error", "message": f"Gagal menghapus akun: {exc}"}

def restore_accounts():
    db = load_db()
    restored = exists = 0
    failures = []
    for username, entry in db.items():
        try:
            if not valid_username(username) or not valid_password(entry.get("password")):
                raise ValueError("data akun tidak valid")
            uid = linux_uid(username)
            if uid is None:
                create_linux_user(username)
                uid = linux_uid(username)
                if uid is None: raise RuntimeError("useradd gagal")
                restored += 1
            else:
                if uid < 1000: raise ValueError("UID sistem dilindungi")
                exists += 1
            set_linux_password(username, entry["password"])
        except Exception as exc:
            failures.append({"username": username, "error": str(exc)})
    return {"total": len(db), "restored": restored, "exists": exists, "failures": failures}

def valid_xray_name(value):
    return isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,23}", value) is not None

def load_xray_accounts():
    rows = read_json(XRAY_DB_FILE, [])
    return rows if isinstance(rows, list) else []

def save_xray_accounts(rows):
    write_json(XRAY_DB_FILE, rows)

def xray_client_for(protocol, account):
    if protocol == "trojan":
        return {"password": account["id"], "email": account["name"]}
    if protocol == "vmess":
        return {"id": account["id"], "alterId": 0, "email": account["name"]}
    return {"id": account["id"], "email": account["name"], "level": 0}

def build_xray_config(accounts):
    config = read_json(XRAY_CONFIG_FILE, None)
    if not isinstance(config, dict) or not isinstance(config.get("inbounds"), list):
        raise RuntimeError("data/config.json tidak valid atau tidak ditemukan")
    changed = 0
    for inbound in config["inbounds"]:
        protocol = str(inbound.get("protocol") or "").lower()
        if protocol not in ("vless", "vmess", "trojan"):
            continue
        inbound.setdefault("settings", {})["clients"] = [xray_client_for(protocol, a) for a in accounts]
        changed += 1
    if not changed:
        raise RuntimeError("Tidak ada inbound VLESS, VMess, atau Trojan di konfigurasi Xray")
    return config

def apply_xray_accounts(accounts):
    next_config = build_xray_config(accounts)
    tmp = XRAY_CONFIG_FILE.with_name(XRAY_CONFIG_FILE.name + f".{os.getpid()}.tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(next_config, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    try:
        xray_bin = os.environ.get("XRAY_BIN", "/usr/local/bin/xray")
        subprocess.run([xray_bin, "run", "-test", "-c", str(tmp)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        os.replace(tmp, XRAY_CONFIG_FILE)
    except Exception as exc:
        try: tmp.unlink()
        except OSError: pass
        detail = getattr(exc, "stderr", None) or str(exc)
        raise RuntimeError(f"Validasi konfigurasi Xray gagal: {detail}")
    subprocess.run(["pkill", "-x", "xray"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def migrate_xray_accounts():
    if XRAY_DB_FILE.exists():
        return
    config = read_json(XRAY_CONFIG_FILE, None)
    seen = {}
    for inbound in (config or {}).get("inbounds", []):
        protocol = str(inbound.get("protocol") or "").lower()
        if protocol not in ("vless", "vmess", "trojan"):
            continue
        for client in (inbound.get("settings") or {}).get("clients", []):
            client_id = client.get("password") if protocol == "trojan" else client.get("id")
            if isinstance(client_id, str) and client_id.strip() and client_id not in seen:
                seen[client_id] = {"id": client_id, "name": f"legacy-{len(seen)+1}",
                                   "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save_xray_accounts(list(seen.values()))

def add_xray_account(name):
    if not valid_xray_name(name):
        return {"status": "error", "message": "Nama akun harus 1–24 karakter: huruf, angka, _ atau -."}
    accounts = load_xray_accounts()
    if any(row.get("name", "").lower() == name.lower() for row in accounts):
        return {"status": "error", "message": "Nama akun Xray sudah digunakan."}
    account = {"id": str(uuid.uuid4()), "name": name,
               "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    next_accounts = accounts + [account]
    try:
        apply_xray_accounts(next_accounts)
        save_xray_accounts(next_accounts)
        return {"status": "success", "account": account, "total": len(next_accounts),
                "message": f"Akun Xray {name} berhasil dibuat."}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

def delete_xray_account(account_id):
    if not isinstance(account_id, str) or not re.fullmatch(r"[0-9a-f-]{36}", account_id, re.I):
        return {"status": "error", "message": "ID akun tidak valid."}
    accounts = load_xray_accounts()
    if not any(row.get("id") == account_id for row in accounts):
        return {"status": "error", "message": "Akun Xray tidak ditemukan."}
    next_accounts = [row for row in accounts if row.get("id") != account_id]
    try:
        apply_xray_accounts(next_accounts)
        save_xray_accounts(next_accounts)
        return {"status": "success", "total": len(next_accounts), "message": "Akun Xray berhasil dihapus."}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

def get_admin_password():
    try:
        value = ADMIN_FILE.read_text(encoding="utf-8").strip()
        if value: return value
    except OSError:
        pass
    return os.environ.get("ADMIN_PASSWORD") or None

def verify_admin(value):
    current = get_admin_password()
    return bool(current) and value == current

def get_settings(path, fallback):
    return read_json(path, fallback)

def get_server_uuid():
    value = os.environ.get("UUID", "").strip()
    if value: return value
    try:
        value = UUID_FILE.read_text(encoding="utf-8").strip()
        if value: return value
    except OSError:
        pass
    value = str(uuid.uuid4())
    UUID_FILE.write_text(value, encoding="utf-8")
    return value

SERVER_UUID = get_server_uuid()

def query_one(query, key, default=""):
    return query.get(key, [default])[0]

class Handler(BaseHTTPRequestHandler):
    server_version = "PanelPython/1.0"

    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def send_text(self, value, status=200):
        body = value.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 1024 * 1024:
            raise ValueError("Request terlalu besar")
        raw = self.rfile.read(length) if length else b"{}"
        try: return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError): raise ValueError("JSON request tidak valid")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query, keep_blank_values=True)
        get = lambda key, default="": query_one(q, key, default)
        path = parsed.path
        ip = self.headers.get("CF-Connecting-IP") or self.client_address[0] or "Unknown"
        agent = self.headers.get("User-Agent", "Unknown")

        if path == "/healthz":
            return self.send_text("ok\n")
        if path == "/__info":
            return self.send_json({"uuid": SERVER_UUID, "domain": os.environ.get("XRAY_DOMAIN") or os.environ.get("DOMAIN") or self.headers.get("Host", ""),
                                   "ssh_domain": os.environ.get("SSH_DOMAIN") or os.environ.get("DOMAIN") or "",
                                   "xray_domain": os.environ.get("XRAY_DOMAIN") or os.environ.get("DOMAIN") or self.headers.get("Host", ""),
                                   "paths": {"vless": "/vless", "vmess": "/vmess", "trojan": "/trojan"},
                                   "xray_accounts": len(load_xray_accounts())})
        if path == "/api/setup-pass":
            next_pass, old_pass, current = get("pass").strip(), get("old_pass").strip(), get_admin_password()
            if current and old_pass != current:
                return self.send_json({"status": "error", "message": "Password admin lama salah."})
            if len(next_pass) < 4:
                return self.send_json({"status": "error", "message": "Password minimal 4 karakter."})
            ADMIN_FILE.write_text(next_pass, encoding="utf-8")
            os.chmod(ADMIN_FILE, 0o600)
            return self.send_json({"status": "success", "message": "Password admin berhasil disimpan."})
        if path == "/api/login":
            if not get_admin_password():
                return self.send_json({"status": "not_configured", "message": "Password admin belum dibuat."})
            return self.send_json({"status": "success", "token": get("pass")} if verify_admin(get("pass")) else {"status": "error", "message": "Password salah."})
        if path == "/api/xray/list":
            if not verify_admin(get("token")):
                return self.send_json({"status": "error", "message": "Akses ditolak."}, 403)
            accounts = load_xray_accounts()
            return self.send_json({"status": "success", "total": len(accounts), "accounts": accounts})
        if path == "/api/add":
            return self.send_json(add_ssh(get("user"), get("pass"), ip, agent))
        if path == "/api/list":
            return self.send_json(list_ssh())
        if path == "/api/delete":
            if not verify_admin(get("token")):
                return self.send_json({"status": "error", "message": "Akses ditolak."}, 403)
            return self.send_json(delete_ssh(get("user")))
        if path == "/api/set-wsproxy":
            if not verify_admin(get("pass")):
                return self.send_json({"status": "error", "message": "Akses ditolak."}, 403)
            try:
                ssh_port, keep_alive, max_buffer = int(get("ssh_port", "22")), int(get("keep_alive", "15000")), int(get("max_buffer", "32768"))
            except ValueError:
                return self.send_json({"status": "error", "message": "Nilai pengaturan harus berupa angka."}, 400)
            if not 1 <= ssh_port <= 65535:
                return self.send_json({"status": "error", "message": "Port SSH harus 1–65535."}, 400)
            if not 1000 <= keep_alive <= 300000:
                return self.send_json({"status": "error", "message": "KeepAlive harus 1000–300000 ms."}, 400)
            if not 4096 <= max_buffer <= 1048576:
                return self.send_json({"status": "error", "message": "MaxBuffer harus 4096–1048576 byte."}, 400)
            write_json(WS_FILE, {"sshPort": ssh_port, "keepAlive": keep_alive, "maxBuffer": max_buffer})
            return self.send_json({"status": "success", "message": "WSProxy dan SSH config diterapkan otomatis tanpa restart container."})
        if path == "/api/set-system":
            if not verify_admin(get("pass")):
                return self.send_json({"status": "error", "message": "Akses ditolak."}, 403)
            try:
                requested_port, requested_clients = int(get("udpgw_port", "7300")), int(get("udpgw_max_clients", "1000"))
            except ValueError:
                return self.send_json({"status": "error", "message": "Nilai UDPGW harus berupa angka."}, 400)
            if not 1 <= requested_port <= 65535:
                return self.send_json({"status": "error", "message": "Port UDPGW harus 1–65535."}, 400)
            if not 1 <= requested_clients <= 100000:
                return self.send_json({"status": "error", "message": "Max clients UDPGW harus 1–100000."}, 400)
            settings = {"banner": get("banner"), "enable_bbr": "false" if get("enable_bbr") == "false" else "true",
                        "udpgw_port": str(requested_port), "udpgw_max_clients": str(requested_clients)}
            write_json(SYS_FILE, settings)
            default_banner = '<p style="text-align:center;"><b>\\n<font color="#800080">─── SERVER PREMIUM ───</font><br>\\n<font color="#8A2BE2">! TERM OF SERVICE !</font><br>\\n<font color="#9370DB">NO MULTI LOGIN / NO TORRENT</font><br>\\n<font color="#8A2BE2">NO SPAM, NO DDOS, NO HACKING</font><br></b>\\n</p>\\n'
            try: Path("/etc/app_motd").write_text(settings["banner"] or default_banner, encoding="utf-8")
            except OSError: pass
            commands = [
                ["sysctl", "-w", "net.ipv4.tcp_tw_reuse=1"],
                ["sysctl", "-w", "net.ipv4.tcp_fin_timeout=10"],
                ["sysctl", "-w", "net.core.default_qdisc=fq"],
                ["sysctl", "-w", f"net.ipv4.tcp_congestion_control={'bbr' if settings['enable_bbr']=='true' else 'cubic'}"],
                ["sysctl", "-w", "net.ipv4.tcp_rmem=4096 8388608 16777216"],
                ["sysctl", "-w", "net.ipv4.tcp_wmem=4096 8388608 16777216"],
                ["sysctl", "-w", "net.core.rmem_max=16777216"],
                ["sysctl", "-w", "net.core.wmem_max=16777216"],
                ["sysctl", "-w", "net.core.netdev_max_backlog=50000"],
                ["sysctl", "-w", "net.ipv4.tcp_max_syn_backlog=8192"]
            ]
            for cmd in commands:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self.send_json({"status": "success", "message": "Pengaturan tersimpan. Banner, kernel, dan UDPGW diterapkan otomatis."})
        if path == "/api/stats":
            ws = get_settings(WS_FILE, {"sshPort": 22, "keepAlive": 15000, "maxBuffer": 32768})
            sys_settings = get_settings(SYS_FILE, {"banner": "", "enable_bbr": "true", "udpgw_port": "7300", "udpgw_max_clients": "1000"})
            try:
                cpus = []
                for line in Path("/proc/cpuinfo").read_text().splitlines():
                    if line.lower().startswith("model name"):
                        cpus.append(line.split(":", 1)[1].strip())
                cpu_model = cpus[0] if cpus else "Unknown"
            except OSError: cpu_model = "Unknown"
            try:
                mem = {}
                for line in Path("/proc/meminfo").read_text().splitlines():
                    key, value = line.split(":", 1)
                    mem[key] = int(value.strip().split()[0]) * 1024
                total_mem, free_mem = mem.get("MemTotal", 0), mem.get("MemAvailable", mem.get("MemFree", 0))
                ram_total = f"{total_mem/1073741824:.2f} GB"
                ram_used = f"{(total_mem-free_mem)/1073741824:.2f} GB"
            except Exception: ram_total = ram_used = "N/A"
            try:
                disk = subprocess.check_output(["df", "-h", "/"], text=True).splitlines()[1].split()[4]
            except Exception: disk = "N/A"
            try:
                active = int(subprocess.check_output("ss -tn state established '( sport = :22 )' | tail -n +2 | wc -l", shell=True, text=True).strip() or 0)
            except Exception: active = 0
            try:
                uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
            except Exception: uptime_seconds = 0
            railway_sni = f"{os.environ.get('RAILWAY_TCP_PROXY_DOMAIN')}:{os.environ.get('RAILWAY_TCP_PROXY_PORT', '')}" if os.environ.get("RAILWAY_TCP_PROXY_DOMAIN") else "Tidak Aktif"
            tunnel_process = subprocess.run(["pgrep", "-x", "cloudflared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            ssh_domain = os.environ.get("SSH_DOMAIN") or os.environ.get("DOMAIN") or ""
            xray_domain = os.environ.get("XRAY_DOMAIN") or os.environ.get("DOMAIN") or self.headers.get("Host", "")
            return self.send_json({
                "pass_configured": bool(get_admin_password()), "status": "ONLINE",
                "domain": ssh_domain or self.headers.get("Host", ""),
                "ssh_domain": ssh_domain, "xray_domain": xray_domain,
                "cloudflared_process": tunnel_process,
                "railway_public": os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "Tidak Aktif",
                "railway_sni": railway_sni, "ws_proxy_cfg": ws, "sys_settings": sys_settings,
                "cpu_model": cpu_model, "ram_total": ram_total, "ram_used": ram_used,
                "disk_usage": disk, "uptime": f"{uptime_seconds/3600:.2f} Hours",
                "ssh_online": str(active),
                "user_list_details": f"{active} koneksi SSH aktif" if active else "Semua user offline"
            })
        if path in ("/", "/index.html"):
            try:
                body = INDEX_FILE.read_bytes()
            except OSError:
                return self.send_text("index.html tidak ditemukan.", 503)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if self.command != "HEAD": self.wfile.write(body)
            return
        return self.send_text("Not Found", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/xray/add", "/api/xray/delete"):
            return self.send_json({"status": "error", "message": "Not Found"}, 404)
        try:
            body = self.read_body()
        except ValueError as exc:
            return self.send_json({"status": "error", "message": str(exc)}, 400)
        if not verify_admin(str(body.get("token") or "")):
            return self.send_json({"status": "error", "message": "Akses ditolak."}, 403)
        if path == "/api/xray/add":
            return self.send_json(add_xray_account(str(body.get("name") or "").strip()))
        return self.send_json(delete_xray_account(str(body.get("id") or "")))

    def log_message(self, fmt, *args):
        print("[PANEL] " + (fmt % args), flush=True)

def main():
    migrate_xray_accounts()
    summary = restore_accounts()
    print(f"[SSH] Restore: total={summary['total']}, created={summary['restored']}, existing={summary['exists']}, failed={len(summary['failures'])}", flush=True)
    if summary["failures"]:
        print("[SSH] Restore failures: " + json.dumps(summary["failures"], ensure_ascii=False), flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[PANEL] UI + API Python server listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
