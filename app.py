#!/usr/bin/env python3
"""Combined web panel + SSH/Xray account API."""

import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APP_PORT", "2053"))
SSH_DATA_DIR = os.environ.get("SSH_DATA_DIR", "/etc/ssh-sni")
SSH_USERS_FILE = os.path.join(SSH_DATA_DIR, "users.json")
XRAY_USERS_FILE = "/app/users.json"
XRAY_CONFIG_FILE = "/app/config.json"

XRAY_PROXY_PORT = int(os.environ.get("XRAY_PROXY_PORT", "8080"))
SSH_PUBLIC_PORT = int(os.environ.get("SSH_PORT", "8081"))
UDPGW_PORT = int(os.environ.get("UDPGW_PORT", "7300"))
ENABLE_BBR = os.environ.get("ENABLE_BBR", "false").lower()

XRAY_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,23}")

# --- Cloudflare Tunnel domain auto-detection -------------------------------
CLOUDFLARED_LOG_FILE = os.environ.get("CLOUDFLARED_LOG_FILE", "/data/cloudflared.log")
DOMAIN_STATE_FILE    = os.environ.get("DOMAIN_STATE_FILE",    "/data/domain.json")
DOMAIN_REFRESH_SEC   = max(3, int(os.environ.get("DOMAIN_REFRESH_SECONDS", "10")))

DOMAIN_STATE_LOCK = threading.Lock()
DOMAIN_STATE = {"domain": "", "updated_at": None}


# ---------------------------------------------------------------------------
# Embedded Web UI  (lined / cyber style + Takina widget + SweetAlert2)
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="id" data-theme="light">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#7c3aed"><title>Server Panel • Modern Console</title>
<script>
(function(){
  try{
    var t = localStorage.getItem('panel-theme');
    if(t !== 'dark' && t !== 'light') t = 'light';
    document.documentElement.setAttribute('data-theme', t);
    var m = document.querySelector('meta[name="theme-color"]');
    if(m) m.setAttribute('content', t === 'dark' ? '#1a1525' : '#7c3aed');
  }catch(e){}
})();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preload" href="https://i.ibb.co.com/M0N8h0C/takina.webp" as="image">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/sakana-widget@2.7.0/lib/sakana.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/sweetalert2@11/dist/sweetalert2.min.css">
<style>
:root{
  color-scheme:light;
  --primary:#7c3aed;--primary-2:#a855f7;--primary-3:#6366f1;--accent:#06b6d4;
  --surface:#ffffff;--surface-2:#faf8ff;--surface-3:#f3efff;
  --text:#0f0d1a;--muted:#64748b;
  --grid:rgba(124,58,237,.045);
  --line:rgba(124,58,237,.14);
  --line-strong:rgba(124,58,237,.28);
  --border:rgba(124,58,237,.10);--border-2:rgba(124,58,237,.18);
  --success:#10b981;--success-bg:#d1fae5;--success-text:#047857;
  --radius:18px;--radius-sm:12px;
  --shadow:0 4px 24px rgba(124,58,237,.08),0 1px 3px rgba(15,13,26,.04);
  --shadow-lg:0 24px 56px rgba(124,58,237,.16),0 4px 12px rgba(15,13,26,.04);
  --gradient:linear-gradient(135deg,#7c3aed 0%,#6366f1 50%,#06b6d4 100%);
  --gradient-soft:linear-gradient(135deg,rgba(124,58,237,.08) 0%,rgba(6,182,212,.08) 100%);
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;
  background-color:#faf9ff;
  background-image:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px),
    radial-gradient(1200px 800px at 100% -10%,rgba(168,85,247,.13),transparent 60%),
    radial-gradient(900px 600px at -10% 100%,rgba(6,182,212,.10),transparent 60%);
  background-size:44px 44px, 44px 44px, auto, auto;
  background-attachment:fixed;
  color:var(--text);font:14px/1.55 Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  min-height:100vh;-webkit-font-smoothing:antialiased;
}
button,input,select,textarea{font:inherit;color:inherit}
button{cursor:pointer;border:0}
.app{min-height:100vh}

/* ===== Sidebar ===== */
.sidebar{
  position:fixed;inset:0 auto 0 0;width:268px;
  background:rgba(255,255,255,.82);
  backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-right:1px solid var(--border-2);
  padding:20px 16px;display:flex;flex-direction:column;z-index:5;
  transition:transform .3s cubic-bezier(.4,0,.2,1);
  box-shadow:1px 0 0 rgba(255,255,255,.5), inset -1px 0 0 rgba(124,58,237,.05);
}
.sidebar::after{
  content:'';position:absolute;top:0;bottom:0;right:-1px;width:2px;
  background:linear-gradient(180deg,transparent,var(--primary),transparent);
  opacity:.35;pointer-events:none;
}
.brand{display:flex;align-items:center;gap:12px;padding:6px 8px 24px;font-weight:750;font-size:16px;letter-spacing:-.01em;position:relative}
.brand::after{content:'';position:absolute;left:8px;right:8px;bottom:8px;height:1px;background:linear-gradient(90deg,var(--line-strong),transparent)}
.brandmark{
  width:42px;height:42px;border-radius:12px;
  background:var(--gradient);color:#fff;display:grid;place-items:center;font-size:20px;
  box-shadow:0 8px 20px rgba(124,58,237,.35),0 0 0 4px rgba(124,58,237,.08);
  animation:float 4s ease-in-out infinite;position:relative;
}
.brandmark::after{content:'';position:absolute;inset:-4px;border-radius:16px;border:1px dashed rgba(124,58,237,.3)}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
.brand small{color:var(--muted);font-weight:500;font-size:11px;letter-spacing:.02em}
.navlabel{
  font-size:10px;letter-spacing:.16em;color:var(--muted);font-weight:750;
  padding:10px 14px;text-transform:uppercase;position:relative;
  display:flex;align-items:center;gap:8px;
}
.navlabel::after{content:'';flex:1;height:1px;background:var(--line)}
.nav button{
  width:100%;background:transparent;color:var(--muted);
  padding:12px 14px;border-radius:12px;text-align:left;
  display:flex;gap:12px;align-items:center;margin:3px 0;
  font-weight:650;font-size:13.5px;border:1px solid transparent;
  transition:all .18s;position:relative;
}
.nav button:hover{background:var(--surface-3);color:var(--text);border-color:var(--border)}
.nav button.active{
  background:var(--gradient);color:#fff;
  box-shadow:0 8px 20px rgba(124,58,237,.3);transform:translateX(2px);
  border-color:transparent;
}
.nav button.active::before{
  content:'';position:absolute;left:-16px;top:50%;transform:translateY(-50%);
  width:3px;height:22px;border-radius:2px;background:var(--primary);
  box-shadow:0 0 12px var(--primary-2);
}
.nav .ico{width:20px;text-align:center;font-size:17px;display:inline-flex;justify-content:center}
.sidefoot{margin-top:auto;border-top:1px dashed var(--line);padding:16px 6px 4px}
.status{display:inline-flex;align-items:center;gap:8px;border-radius:30px;padding:7px 13px;background:var(--surface-3);font-size:11.5px;font-weight:650;color:var(--muted);border:1px solid var(--border)}
.dot{width:8px;height:8px;background:var(--success);border-radius:50%;box-shadow:0 0 0 4px rgba(16,185,129,.15);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 4px rgba(16,185,129,.15)}50%{box-shadow:0 0 0 8px rgba(16,185,129,.05)}}

/* ===== Main ===== */
.main{margin-left:268px;min-width:0}
.topbar{
  height:72px;display:flex;align-items:center;justify-content:space-between;
  padding:0 32px;background:rgba(255,255,255,.75);
  backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-bottom:1px solid var(--border-2);position:sticky;top:0;z-index:3;
  box-shadow:0 1px 0 rgba(124,58,237,.05), 0 4px 24px rgba(124,58,237,.04);
}
.top-left{display:flex;align-items:center;gap:14px}
.topbar h2{font-size:15px;margin:0;font-weight:750;letter-spacing:-.005em;position:relative;padding-left:14px}
.topbar h2::before{content:'';position:absolute;left:0;top:50%;transform:translateY(-50%);width:3px;height:16px;border-radius:2px;background:var(--gradient)}
.top-actions{display:flex;gap:10px;align-items:center}
.content{max-width:1160px;margin:auto;padding:32px 32px 60px}

.page-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px;gap:16px;position:relative;padding-bottom:18px}
.page-head::after{content:'';position:absolute;left:0;right:0;bottom:0;height:1px;background:linear-gradient(90deg,var(--primary),var(--accent),transparent)}
.page-head h1{
  font-size:28px;letter-spacing:-.025em;margin:0 0 6px;font-weight:800;
  background:linear-gradient(135deg,#1e1b2e 30%,#7c3aed 100%);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
}
.page-head p{color:var(--muted);margin:0;font-size:13.5px}

/* ===== Cards with corner brackets ===== */
.card{
  position:relative;
  background:rgba(255,255,255,.9);
  backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
  border:1px solid var(--border-2);
  border-radius:var(--radius);
  padding:22px;margin-bottom:16px;box-shadow:var(--shadow);
  transition:box-shadow .25s,border-color .25s;
}
.card:hover{box-shadow:var(--shadow-lg);border-color:var(--line-strong)}
.card::before,
.card::after{
  content:'';position:absolute;width:18px;height:18px;
  border:2px solid var(--primary);pointer-events:none;opacity:.85;
  transition:width .25s,height .25s,border-color .25s;
}
.card::before{top:-1px;left:-1px;border-right:0;border-bottom:0;border-top-left-radius:var(--radius)}
.card::after{bottom:-1px;right:-1px;border-left:0;border-top:0;border-bottom-right-radius:var(--radius)}
.card:hover::before,.card:hover::after{width:26px;height:26px;border-color:var(--accent)}
.card h3{
  font-size:14px;margin:0 0 16px;font-weight:750;letter-spacing:.02em;
  display:flex;align-items:center;gap:10px;text-transform:uppercase;
  padding-bottom:12px;border-bottom:1px dashed var(--line);
  position:relative;
}
.card h3::before{content:'';width:4px;height:14px;border-radius:2px;background:var(--gradient);box-shadow:0 0 8px rgba(124,58,237,.4)}
.card h3::after{content:'';flex:1;height:1px;background:repeating-linear-gradient(90deg,var(--line) 0 6px,transparent 6px 10px)}

.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.grid.four{grid-template-columns:repeat(4,minmax(0,1fr))}
.grid.five{grid-template-columns:repeat(5,minmax(0,1fr))}

/* ===== Stat with scanlines ===== */
.stat{
  padding:18px;border-radius:14px;
  background:linear-gradient(135deg,rgba(255,255,255,1),rgba(243,239,255,.65));
  border:1px solid var(--border-2);min-width:0;position:relative;overflow:hidden;
  transition:transform .2s,box-shadow .2s,border-color .2s;
}
.stat::before{content:'';position:absolute;inset:0;background-image:repeating-linear-gradient(0deg,rgba(124,58,237,.035) 0 1px,transparent 1px 4px);pointer-events:none}
.stat::after{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:linear-gradient(90deg,var(--primary),var(--accent),var(--primary));
  background-size:200% 100%;animation:slide 6s linear infinite;
}
@keyframes slide{0%{background-position:0% 50%}100%{background-position:200% 50%}}
.stat:hover{transform:translateY(-2px);box-shadow:0 12px 28px rgba(124,58,237,.12);border-color:var(--line-strong)}
.stat .k{color:var(--muted);font-size:10.5px;font-weight:750;letter-spacing:.1em;text-transform:uppercase;position:relative;display:flex;align-items:center;gap:6px}
.stat .k::before{content:'▸';color:var(--primary);font-size:10px}
.stat .v{font-size:18px;font-weight:800;margin-top:8px;overflow-wrap:anywhere;letter-spacing:-.015em;position:relative}
.stat .sub{font-size:11.5px;color:var(--muted);margin-top:3px;position:relative}

/* ===== Fields ===== */
.field{display:flex;flex-direction:column;gap:7px;margin-bottom:14px;min-width:0}
.field label{font-size:11px;font-weight:750;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
.field input,.field select,.field textarea{
  width:100%;border:1.5px solid var(--border-2);background:var(--surface);
  border-radius:10px;padding:11px 14px;color:var(--text);outline:none;min-width:0;
  transition:border-color .18s,box-shadow .18s,background .18s;
  font-family:ui-monospace,SFMono-Regular,'JetBrains Mono',Consolas,monospace;
  font-size:13px;
}
.field input:hover,.field select:hover,.field textarea:hover{border-color:var(--line-strong)}
.field input:focus,.field select:focus,.field textarea:focus{border-color:var(--primary);box-shadow:0 0 0 4px rgba(124,58,237,.1);background:var(--surface-2)}
.row{display:flex;gap:12px;align-items:end}
.row>*{flex:1;min-width:0}

/* ===== Buttons ===== */
.btn{
  border:0;border-radius:10px;padding:11px 20px;min-height:42px;
  font-weight:750;font-size:13px;display:inline-flex;align-items:center;justify-content:center;gap:8px;
  transition:all .18s;white-space:nowrap;position:relative;letter-spacing:.01em;
}
.btn:disabled{opacity:.55;cursor:not-allowed}
.filled{background:var(--gradient);color:#fff;box-shadow:0 4px 14px rgba(124,58,237,.35), inset 0 1px 0 rgba(255,255,255,.25)}
.filled:hover:not(:disabled){box-shadow:0 8px 24px rgba(124,58,237,.45), inset 0 1px 0 rgba(255,255,255,.3);transform:translateY(-1px)}
.filled:active{transform:translateY(0)}
.tonal{background:var(--surface-3);color:var(--primary);border:1px solid var(--border-2)}
.tonal:hover{background:#ede9fe;border-color:var(--line-strong)}
.outlined{background:transparent;color:var(--primary);border:1.5px solid var(--border-2)}
.outlined:hover{background:var(--surface-3);border-color:var(--primary)}
.danger{background:#fee2e2;color:#991b1b;border:1px solid #fecaca}
.danger:hover{background:#fecaca}
.textbtn{background:transparent;color:var(--muted);padding:8px 12px;border:1px solid transparent}
.textbtn:hover{background:var(--surface-3);color:var(--text);border-color:var(--border)}
.wide{width:100%}

/* ===== Chips ===== */
.chip{
  display:inline-flex;align-items:center;gap:6px;border-radius:8px;
  background:var(--surface-3);padding:6px 12px;font-size:11px;font-weight:750;
  color:var(--muted);border:1px solid var(--border);letter-spacing:.02em;
  font-family:ui-monospace,monospace;
}
.chip.good{background:var(--success-bg);color:var(--success-text);border-color:rgba(16,185,129,.25)}

/* ===== Table ===== */
.tablewrap{overflow:auto;border-radius:12px;border:1px solid var(--border-2);background:rgba(255,255,255,.6)}
table{border-collapse:collapse;width:100%;min-width:460px}
th,td{text-align:left;padding:13px 14px;border-bottom:1px solid var(--border)}
th{font-size:10.5px;text-transform:uppercase;color:var(--muted);letter-spacing:.1em;font-weight:750;background:var(--surface-2);border-bottom:2px solid var(--line)}
td{font-size:13px}
tbody tr{transition:background .15s}
tbody tr:hover{background:var(--surface-2)}
tbody tr:last-child td{border-bottom:0}

/* ===== Misc ===== */
.mono,pre{font-family:ui-monospace,SFMono-Regular,'JetBrains Mono',Consolas,monospace;overflow-wrap:anywhere}
.muted{color:var(--muted)}
.output{
  background:linear-gradient(135deg,#f8f5ff 0%,#eef9fd 100%);
  border:1px solid var(--border-2);border-radius:10px;padding:16px;
  white-space:pre-wrap;overflow-wrap:anywhere;max-height:340px;overflow:auto;
  font-size:12px;position:relative;
}
.output::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:linear-gradient(180deg,var(--primary),var(--accent));border-radius:10px 0 0 10px}
.notice{background:var(--gradient-soft);color:#403653;padding:14px 16px;border-radius:10px;font-size:12.5px;border:1px solid var(--border-2);border-left:3px solid var(--primary)}
.hidden{display:none!important}
.hamb{display:none}
.overlay{display:none}

/* ===== Modal ===== */
.modal{
  position:fixed;inset:0;background:rgba(15,13,26,.6);
  backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);
  z-index:15;display:grid;place-items:center;padding:20px;animation:fadeIn .2s;
}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.modalbox{
  background:var(--surface);border-radius:18px;padding:26px;
  width:min(100%,480px);box-shadow:var(--shadow-lg);
  animation:modalIn .3s cubic-bezier(.4,0,.2,1);
  border:1px solid var(--border-2);position:relative;
}
.modalbox::before,
.modalbox::after{
  content:'';position:absolute;width:22px;height:22px;
  border:2px solid var(--primary);pointer-events:none;
}
.modalbox::before{top:-1px;left:-1px;border-right:0;border-bottom:0;border-top-left-radius:18px}
.modalbox::after{bottom:-1px;right:-1px;border-left:0;border-top:0;border-bottom-right-radius:18px}
@keyframes modalIn{from{opacity:0;transform:scale(.95) translateY(10px)}to{opacity:1;transform:scale(1) translateY(0)}}
.modalbox h3{margin:0 0 8px}

/* ===== Traffic ===== */
.traffic{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.traffic>div{background:var(--gradient-soft);border:1px solid var(--border-2);border-radius:10px;padding:14px;position:relative;overflow:hidden}
.traffic>div::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:linear-gradient(180deg,var(--primary),var(--accent))}
.genbuttons{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}
.genbuttons button{font-size:12px;padding:12px 6px}
.linkbox{background:var(--surface-3);padding:12px;border-radius:10px;margin:8px 0;border:1px solid var(--border)}
.linktop{display:flex;justify-content:space-between;gap:8px;align-items:center}
.small{font-size:11px}
.mt{margin-top:14px}
.right{text-align:right}
.empty{text-align:center;color:var(--muted);padding:32px 20px;font-size:13px}
.empty::before{content:'◇';display:block;font-size:32px;color:var(--line-strong);margin-bottom:8px;font-weight:300}
.mobile-only{display:none}

/* divider */
.divider{height:1px;background:repeating-linear-gradient(90deg,var(--line) 0 6px,transparent 6px 12px);margin:16px 0;border:0}

/* ===== Sakana widget ===== */
#sakana-widget.sakana-widget{
  position:fixed !important;
  right:20px !important;
  bottom:0 !important;
  z-index:9999 !important;
  pointer-events:none;
}

/* ===== SweetAlert2 theme ===== */
.swal2-popup{
  border-radius:16px !important;
  border:1px solid var(--border-2) !important;
  box-shadow:var(--shadow-lg) !important;
  font-family:Inter,sans-serif !important;
}
.swal2-title{ font-weight:750 !important; }
.swal2-toast{
  border-radius:12px !important;
  border:1px solid var(--border-2) !important;
  box-shadow:var(--shadow-lg) !important;
  background:#fff !important;
  padding:12px 16px !important;
}
.swal2-toast .swal2-title{
  font-size:13px !important;
  font-weight:650 !important;
  color:var(--text) !important;
}
.swal2-toast .swal2-icon{
  width:26px !important;
  height:26px !important;
  margin:0 8px 0 0 !important;
}
.swal2-toast.swal2-icon-success .swal2-success-ring{ border-color:var(--success) !important; }
.swal2-timer-progress-bar{ background:var(--primary) !important; }

@media(max-width:1000px){
  .grid.four,.grid.five{grid-template-columns:repeat(2,minmax(0,1fr))}
  .grid.five .stat:first-child{grid-column:span 2}
}
@media(max-width:760px){
  .sidebar{transform:translateX(-105%);width:290px;box-shadow:var(--shadow-lg)}
  .sidebar.open{transform:translateX(0)}
  .overlay.show{display:block;position:fixed;inset:0;background:rgba(15,13,26,.4);z-index:4;backdrop-filter:blur(4px)}
  .main{margin-left:0}
  .topbar{height:62px;padding:0 16px}
  .content{padding:22px 15px 45px}
  .hamb,.mobile-only{display:inline-flex}
  .page-head h1{font-size:23px}
  .grid,.grid.four,.grid.five{grid-template-columns:repeat(2,minmax(0,1fr))}
  .row{flex-direction:column;align-items:stretch;gap:0}
  .row .btn{width:100%}
  #sakana-widget.sakana-widget{
    transform:scale(.65);
    transform-origin:bottom right;
    right:-18px !important;
    bottom:-24px !important;
  }
}
@media(max-width:430px){
  .card{padding:16px}
  .stat{padding:14px}
  .stat .v{font-size:15px}
  .genbuttons{gap:6px}
  .genbuttons button{font-size:10px;padding:11px 3px}
  .page-head{flex-direction:column}
  .traffic{gap:8px}
}

/* ===== Theme switch: smooth transition ===== */
html,body,.card,.stat,.field input,.field select,.field textarea,.sidebar,.topbar,
.output,.notice,.tablewrap,.linkbox,.modalbox,.chip,.btn{
  transition:background-color .3s ease, color .3s ease, border-color .3s ease,
             box-shadow .3s ease, background .3s ease;
}

/* Tombol theme toggle */
.theme-toggle{
  width:42px;height:42px;padding:0;border-radius:50%;
  background:var(--surface-3);border:1px solid var(--border-2);
  font-size:17px;display:inline-flex;align-items:center;justify-content:center;
  transition:transform .25s ease, background .25s ease, border-color .25s ease;
  flex-shrink:0;
}
.theme-toggle:hover{
  background:var(--surface-2);
  border-color:var(--primary);
  transform:rotate(20deg) scale(1.05);
}

/* ===== DARK MODE ===== */
[data-theme="dark"]{
  color-scheme:dark;
  --primary:#a855f7;
  --primary-2:#c084fc;
  --primary-3:#818cf8;
  --accent:#22d3ee;
  --surface:#1a1525;
  --surface-2:#221b30;
  --surface-3:#2a2238;
  --text:#f0ecff;
  --muted:#a098c0;
  --grid:rgba(168,85,247,.06);
  --line:rgba(168,85,247,.18);
  --line-strong:rgba(168,85,247,.32);
  --border:rgba(168,85,247,.14);
  --border-2:rgba(168,85,247,.22);
  --success:#34d399;
  --success-bg:#064e3b;
  --success-text:#6ee7b7;
  --shadow:0 4px 24px rgba(0,0,0,.45),0 1px 3px rgba(0,0,0,.3);
  --shadow-lg:0 24px 56px rgba(0,0,0,.6),0 4px 12px rgba(0,0,0,.4);
  --gradient:linear-gradient(135deg,#9333ea 0%,#6366f1 50%,#06b6d4 100%);
  --gradient-soft:linear-gradient(135deg,rgba(168,85,247,.15) 0%,rgba(6,182,212,.12) 100%);
}
[data-theme="dark"] body{
  background-color:#0d0918;
  background-image:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px),
    radial-gradient(1200px 800px at 100% -10%,rgba(168,85,247,.22),transparent 60%),
    radial-gradient(900px 600px at -10% 100%,rgba(6,182,212,.16),transparent 60%);
}
[data-theme="dark"] .sidebar{
  background:rgba(26,21,37,.85);
  box-shadow:1px 0 0 rgba(255,255,255,.02), inset -1px 0 0 rgba(168,85,247,.08);
}
[data-theme="dark"] .topbar{
  background:rgba(26,21,37,.78);
  box-shadow:0 1px 0 rgba(168,85,247,.08), 0 4px 24px rgba(0,0,0,.3);
}
[data-theme="dark"] .card{
  background:rgba(34,27,48,.85);
}
[data-theme="dark"] .stat{
  background:linear-gradient(135deg,rgba(34,27,48,1),rgba(42,34,56,.7));
}
[data-theme="dark"] .stat::before{
  background-image:repeating-linear-gradient(0deg,rgba(168,85,247,.04) 0 1px,transparent 1px 4px);
}
[data-theme="dark"] .field input,
[data-theme="dark"] .field select,
[data-theme="dark"] .field textarea{
  background:#181223;
  color:#f0ecff;
}
[data-theme="dark"] .field input:focus,
[data-theme="dark"] .field select:focus,
[data-theme="dark"] .field textarea:focus{
  background:#221b30;
}
[data-theme="dark"] .output{
  background:linear-gradient(135deg,#181223 0%,#0d1a1f 100%);
  color:#e0dcf0;
}
[data-theme="dark"] .notice{
  color:#d8d0ee;
}
[data-theme="dark"] .tablewrap{
  background:rgba(26,21,37,.6);
}
[data-theme="dark"] th{ background:var(--surface-2); }
[data-theme="dark"] tbody tr:hover{ background:#221b30; }
[data-theme="dark"] .tonal{ background:#2a2238; }
[data-theme="dark"] .tonal:hover{ background:#332a44; }
[data-theme="dark"] .outlined:hover{ background:#2a2238; }
[data-theme="dark"] .textbtn:hover{ background:#2a2238; color:#f0ecff; }
[data-theme="dark"] .danger{
  background:#4c1d24; color:#fca5a5; border-color:#7f1d1d;
}
[data-theme="dark"] .danger:hover{ background:#7f1d1d; }
[data-theme="dark"] .modalbox{ background:var(--surface); }
[data-theme="dark"] .modal{ background:rgba(0,0,0,.78); }
[data-theme="dark"] .page-head h1{
  background:linear-gradient(135deg,#f0ecff 30%,#c084fc 100%);
  -webkit-background-clip:text; background-clip:text;
  -webkit-text-fill-color:transparent;
}
[data-theme="dark"] .brandmark::after{
  border-color:rgba(168,85,247,.4);
}
[data-theme="dark"] .empty::before{ color:var(--line-strong); }
[data-theme="dark"] .swal2-popup,
[data-theme="dark"] .swal2-toast{
  background:#221b30 !important;
  color:#f0ecff !important;
  border-color:rgba(168,85,247,.25) !important;
}
[data-theme="dark"] .swal2-title{ color:#f0ecff !important; }
[data-theme="dark"] .swal2-html-container{ color:#a098c0 !important; }
</style></head>
<body>
<div class="app">
<div class="overlay" id="overlay" onclick="toggleNav(false)"></div>
<aside class="sidebar" id="sidebar">
  <div class="brand">
    <div class="brandmark">✦</div>
    <div>SERVER PANEL<div class="muted small" style="font-weight:500">Modern Console</div></div>
  </div>
  <div class="navlabel">MENU UTAMA</div>
  <nav class="nav">
    <button data-page="dashboard" class="active" onclick="navigate('dashboard')"><span class="ico">▦</span>Dashboard</button>
    <button data-page="ssh" onclick="navigate('ssh')"><span class="ico">♙</span>Buat Akun SSH</button>
    <button data-page="xray" onclick="navigate('xray')"><span class="ico">◉</span>Buat Akun Xray</button>
  </nav>
  <div class="sidefoot"><div class="status"><span class="dot"></span>Public Self-Service</div></div>
</aside>
<div class="main">
  <header class="topbar">
    <div class="top-left">
      <button class="btn textbtn hamb" onclick="toggleNav(true)">☰</button>
      <h2 id="topTitle">Dashboard</h2>
    </div>
    <div class="top-actions">
      <span class="chip good" id="serverState">● Connecting</span>
      <button class="btn theme-toggle" onclick="toggleTheme()" id="themeToggle"
              title="Ganti tema" aria-label="Ganti tema">🌙</button>
    </div>
  </header>
  <main class="content" id="view"></main>
</div></div>
<div class="modal hidden" id="detailModal" onclick="if(event.target===this)closeDetail()">
  <div class="modalbox">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px">
      <h3 id="detailTitle" style="margin:0">Detail Akun</h3>
      <button class="btn textbtn" onclick="closeDetail()" aria-label="Tutup"
              style="min-height:auto;padding:6px 12px;font-size:18px;border-radius:50%">✕</button>
    </div>
    <pre class="output" id="detailBody" style="max-height:420px;white-space:pre-wrap;margin:0"></pre>
    <button class="btn filled wide mt" onclick="copyDetail()">📋 Salin Akun</button>
  </div>
</div>

<!-- ✦ Widget animasi Takina ✦ -->
<div id="sakana-widget" class="sakana-widget"></div>

<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11" defer></script>
<script src="https://cdn.jsdelivr.net/npm/sakana-widget@2.7.0/lib/sakana.min.js" defer></script>
<script>
'use strict';
const $=id=>document.getElementById(id);
let stats=null,trafficStats=null,serverInfo=null,currentPage='dashboard',sshUsers=[],xrayAccounts=[],detailText='';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// -------------------- Theme switch --------------------
function applyTheme(theme){
  if(theme !== 'dark' && theme !== 'light') theme = 'light';
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('themeToggle');
  if(btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  const m = document.querySelector('meta[name="theme-color"]');
  if(m) m.setAttribute('content', theme === 'dark' ? '#1a1525' : '#7c3aed');
  try{ localStorage.setItem('panel-theme', theme); }catch(e){}
}
function toggleTheme(){
  const cur = document.documentElement.getAttribute('data-theme') || 'light';
  applyTheme(cur === 'dark' ? 'light' : 'dark');
}

// -------------------- SweetAlert2 toast wrapper --------------------
function toast(msg,type=''){
  const icon = type === 'error' ? 'error' : (type === 'success' ? 'success' : 'info');
  if (window.Swal) {
    Swal.fire({
      toast: true,
      position: 'top-end',
      icon: icon,
      title: msg,
      showConfirmButton: false,
      timer: 3000,
      timerProgressBar: true,
      didOpen: (el) => {
        el.addEventListener('mouseenter', Swal.stopTimer);
        el.addEventListener('mouseleave', Swal.resumeTimer);
      }
    });
  } else {
    console.log(`[${type||'info'}] ${msg}`);
  }
}

async function api(url,opts={}){const r=await fetch(url,opts);let d;try{d=await r.json()}catch{throw Error('Respons server tidak valid')}if(!r.ok&&d.status!=='error')throw Error(d.message||`HTTP ${r.status}`);return d}
function toggleNav(v){$('sidebar').classList.toggle('open',v);$('overlay').classList.toggle('show',v)}
function navigate(page){currentPage=page;document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===page));$('topTitle').textContent=({dashboard:'Dashboard',ssh:'Buat Akun SSH',xray:'Buat Akun Xray'})[page];toggleNav(false);render()}
function card(title,body){return `<section class="card"><h3>${title}</h3>${body}</section>`}

// -------------------- Detail modal --------------------
function openDetail(title,text){detailText=text;$('detailTitle').textContent=title;$('detailBody').textContent=text;$('detailModal').classList.remove('hidden')}
function closeDetail(){$('detailModal').classList.add('hidden');detailText=''}
function copyDetail(){copyText(detailText)}

function showSshDetail(i){
  const u=sshUsers[i];if(!u)return;
  const online=(stats?.online_users||[]).find(x=>x.user===u.username);
  const text=
`===========================
 Username   : ${u.username}
 Password   : ${u.password||'-'}
 Dibuat     : ${u.created_at||'-'}
 Status     : ${online?('ONLINE ('+online.ip+')'):'OFFLINE'}
 Domain     : ${serverInfo?.domain||'-'}
===========================`;
  openDetail('Detail Akun SSH',text);
}

// -------------------- Stats / dashboard --------------------
async function loadTraffic(){
  try{trafficStats=await api('/api/traffic');if(currentPage==='dashboard')renderDashboard();}
  catch(e){trafficStats={error:e.message};if(currentPage==='dashboard')renderDashboard();}
}

async function loadStats(){
  try{
    stats=await api('/api/stats');
    $('serverState').textContent='● '+(stats.status||'ONLINE');
    $('serverState').className='chip good';
    if(currentPage==='dashboard')render();
  }catch(e){
    $('serverState').textContent='● Offline';
    $('serverState').className='chip';
  }
}

function render(){
  if(currentPage==='dashboard')renderDashboard();
  if(currentPage==='ssh')renderSSH();
  if(currentPage==='xray')renderXray();
}

function fmtBytes(n){
  n=Math.max(0,Number(n)||0);const u=['B','KB','MB','GB','TB'];let i=0;
  while(n>=1024&&i<u.length-1){n/=1024;i++}return n.toFixed(i?2:0)+' '+u[i];
}
function fmtRate(n){
  n=Math.max(0,Number(n)||0);const u=['B/s','KB/s','MB/s','GB/s'];let i=0;
  while(n>=1024&&i<u.length-1){n/=1024;i++}return n.toFixed(2)+' '+u[i];
}

function renderDashboard(){
  const s=stats||{},t=trafficStats||{};
  const values=[
    ['CPU MODEL',s.cpu_model||'Memuat...','Processor server'],
    ['RAM USED / TOTAL',(s.ram_used||'--')+' / '+(s.ram_total||'--'),'Penggunaan memori'],
    ['DISK USAGE',s.disk_usage||'--','Storage root'],
    ['SERVER UPTIME',s.uptime||'--','Waktu aktif'],
  ];
  const statsHTML=values.map(v=>`<div class="stat"><div class="k">${v[0]}</div><div class="v">${esc(v[1])}</div><div class="sub">${esc(v[2])}</div></div>`).join('');
  const d=t.download||{},u=t.upload||{},total=t.total||{},daily=t.daily||{},monthly=t.monthly||{};

  // --- Card 1: Traffic Metrics (rate realtime) ---
  const trafficCard=`
    <div class="grid">
      <div class="stat"><div class="k">↓ DOWNLOAD · SERVER TX</div><div class="v">${fmtRate(d.rate_bytes_per_sec)}</div><div class="sub">Total sejak mulai: ${fmtBytes(total.download_bytes)}</div></div>
      <div class="stat"><div class="k">↑ UPLOAD · SERVER RX</div><div class="v">${fmtRate(u.rate_bytes_per_sec)}</div><div class="sub">Total sejak mulai: ${fmtBytes(total.upload_bytes)}</div></div>
    </div>`;

  // --- Card 2: Akumulasi Hari Ini ---
  const dailyCard=`
    <div class="grid">
      <div class="stat">
        <div class="k">↓ DOWNLOAD · HARI INI</div>
        <div class="v">${fmtBytes(daily.download_bytes)}</div>
        <div class="sub">Tanggal: ${esc(daily.date||'-')}</div>
      </div>
      <div class="stat">
        <div class="k">↑ UPLOAD · HARI INI</div>
        <div class="v">${fmtBytes(daily.upload_bytes)}</div>
        <div class="sub">Tanggal: ${esc(daily.date||'-')}</div>
      </div>
    </div>
    <div class="divider"></div>
    <div class="grid">
      <div><span class="muted small">TOTAL HARI INI</span><br><b>${fmtBytes((daily.download_bytes||0)+(daily.upload_bytes||0))}</b></div>
      <div><span class="muted small">TANGGAL</span><br><b>${esc(daily.date||'-')}</b></div>
    </div>`;

  // --- Card 3: Akumulasi Bulan Ini ---
  const monthlyCard=`
    <div class="grid">
      <div class="stat">
        <div class="k">↓ DOWNLOAD · BULAN INI</div>
        <div class="v">${fmtBytes(monthly.download_bytes)}</div>
        <div class="sub">Periode: ${esc(monthly.month||'-')}</div>
      </div>
      <div class="stat">
        <div class="k">↑ UPLOAD · BULAN INI</div>
        <div class="v">${fmtBytes(monthly.upload_bytes)}</div>
        <div class="sub">Periode: ${esc(monthly.month||'-')}</div>
      </div>
    </div>
    <div class="divider"></div>
    <div class="grid">
      <div><span class="muted small">TOTAL BULAN INI</span><br><b>${fmtBytes((monthly.download_bytes||0)+(monthly.upload_bytes||0))}</b></div>
      <div><span class="muted small">PERIODE</span><br><b>${esc(monthly.month||'-')}</b></div>
    </div>`;

  $('view').innerHTML=`
    <div class="page-head"><div><h1>Dashboard Server</h1><p>Ringkasan status dan performa server kamu.</p></div><span class="chip good">● Services Managed</span></div>
    <div class="grid four">${statsHTML}</div>
    ${card('Traffic Metrics',trafficCard)}
    ${card('Akumulasi Hari Ini',dailyCard)}
    ${card('Akumulasi Bulan Ini',monthlyCard)}
    ${card('Domain',`
      <div class="field">
        <label>Domain Server (auto-detect dari Cloudflare Tunnel)</label>
        <div class="row">
          <input readonly value="${esc(s.domain||'Menunggu ingress Cloudflare...')}">
          <button class="btn tonal" onclick="copyText(this.dataset.copy)" data-copy="${esc(s.domain||'')}">📋 Salin</button>
        </div>
    `)}`;
}

// -------------------- SSH account --------------------
async function loadSSH(){
  try{
    const d=await api('/api/list');sshUsers=d.users||[];
    const c=$('sshCount');if(c)c.textContent=sshUsers.length;
    const box=$('sshList');if(!box)return;
    box.innerHTML=sshUsers.length
      ?`<div class="tablewrap"><table><thead><tr>
          <th>No</th><th>Username</th><th>Dibuat</th><th>Aksi</th>
        </tr></thead><tbody>${sshUsers.map((u,i)=>
          `<tr>
            <td>${i+1}</td>
            <td><b>${esc(u.username)}</b></td>
            <td>${esc((u.created_at||'').slice(0,10)||'-')}</td>
            <td><button class="btn tonal" style="min-height:auto;padding:6px 14px;font-size:12px"
                 onclick="showSshDetail(${i})">Detail</button></td>
          </tr>`).join('')}</tbody></table></div>`
      :'<div class="empty">Belum ada akun SSH.</div>';
  }catch(e){
    const box=$('sshList');if(box)box.textContent='Gagal memuat daftar akun: '+e.message;
  }
}

async function renderSSH(){
  const head=`<div class="page-head"><div><h1>Daftar Akun SSH (<span id="sshCount">0</span>)</h1>
    <p>Kelola akun SSH dan buat akun baru.</p></div></div>`;
  const form=card('Tambah Akun SSH',`<div class="row">
    <div class="field"><label>Username</label><input id="sshUser" placeholder="contoh: user01" autocomplete="off" maxlength="32"></div>
    <div class="field"><label>Password</label><input id="sshPass" type="password" placeholder="Minimal 8 karakter" autocomplete="new-password"></div>
    <button class="btn filled" onclick="createSSH()">＋ Buat Akun</button></div>
    <div id="sshResult"></div>`);
  $('view').innerHTML=head+form+card('Daftar Akun SSH',`<div id="sshList" class="empty">Memuat daftar akun...</div>`);
  await loadSSH();
}

async function createSSH(){
  const u=$('sshUser').value.trim().toLowerCase(),p=$('sshPass').value;
  if(!u||!p)return toast('Isi username dan password','error');
  try{
    const d=await api('/api/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user:u,pass:p})});
    if(d.status==='success'){
      toast('Akun SSH berhasil dibuat','success');
      $('sshResult').innerHTML=`<div class="notice mt"><b>✓ Akun berhasil dibuat</b>
        <pre class="output">${esc(d.message)}</pre>
        <button class="btn tonal wide" onclick="copyText(this.dataset.copy)" data-copy="${esc(d.message)}">Salin Detail Akun</button></div>`;
      $('sshUser').value='';$('sshPass').value='';
      await loadSSH();
    }else toast(d.message,'error');
  }catch(e){toast(e.message,'error')}
}

// -------------------- Xray account --------------------
async function loadXray(){
  try{
    const d=await api('/api/xray/list');xrayAccounts=d.accounts||[];
    const c=$('xrayCount');if(c)c.textContent=xrayAccounts.length;
    const box=$('xrayList');if(box)box.innerHTML=xrayAccounts.length
      ?`<div class="tablewrap"><table><thead><tr>
          <th>No</th><th>Nama</th><th>UUID</th><th>Aksi</th>
        </tr></thead><tbody>${xrayAccounts.map((a,i)=>
          `<tr>
            <td>${i+1}</td>
            <td><b>${esc(a.name)}</b></td>
            <td class="mono small">${esc(a.id)}</td>
            <td><button class="btn tonal" style="min-height:auto;padding:6px 14px;font-size:12px"
                 onclick="showXrayDetail(${i})">Detail</button></td>
          </tr>`).join('')}</tbody></table></div>`
      :'<div class="empty">Belum ada akun Xray.</div>';
  }catch(e){
    const box=$('xrayList');if(box)box.textContent='Gagal memuat daftar akun: '+e.message;
  }
}

async function renderXray(){
  const head=`<div class="page-head"><div><h1>Daftar Akun Xray (<span id="xrayCount">0</span>)</h1>
    <p>Kelola akun VLESS, VMess, dan Trojan (XHTTP, HTTPUpgrade, WS).</p></div></div>`;
  const form=card('Tambah Akun Xray',`
    <div class="row"><div class="field"><label>Nama Akun</label><input id="xrayName" placeholder="user01" maxlength="24"></div>
    <button class="btn filled" onclick="createXray()">＋ Buat Akun</button></div>`);
  $('view').innerHTML=head+form+card('Daftar Akun Xray',`<div id="xrayList" class="empty">Memuat daftar akun...</div>`);
  await loadXray();
}

async function createXray(){
  const name=$('xrayName').value.trim().toLowerCase();
  if(!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,23}$/.test(name))return toast('Nama 1–24 karakter: huruf, angka, _ atau -','error');
  try{
    const d=await api('/api/xray/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
    if(d.status==='success'){
      toast(d.message,'success');$('xrayName').value='';
      await loadXray();showXray(d.account);
    }else toast(d.message,'error');
  }catch(e){toast(e.message,'error')}
}

// -------------------- Xray links (9 inbounds) --------------------
const XRAY_INBOUNDS=[
  {protocol:'vless',net:'xhttp',       path:'/xhttp',        mode:'auto',label:'XHTTP'},
  {protocol:'vless',net:'httpupgrade', path:'/httpup',                    label:'HTTPUpgrade'},
  {protocol:'vless',net:'ws',          path:'/vless',                     label:'WS'},
  {protocol:'vmess',net:'xhttp',       path:'/vmess-xhttp',  mode:'auto',label:'XHTTP'},
  {protocol:'vmess',net:'httpupgrade', path:'/vmess-httpup',              label:'HTTPUpgrade'},
  {protocol:'vmess',net:'ws',          path:'/vmess',                     label:'WS'},
  {protocol:'trojan',net:'xhttp',      path:'/trojan-xhttp', mode:'auto',label:'XHTTP'},
  {protocol:'trojan',net:'httpupgrade',path:'/trojan-httpup',             label:'HTTPUpgrade'},
  {protocol:'trojan',net:'ws',         path:'/trojan',                    label:'WS'},
];

function makeXrayLinks(a){
  const host=(serverInfo?.domain||stats?.domain||location.hostname).replace(/^https?:\\/\\//,'').split('/')[0];
  const sni=host;
  const variants=[{port:'443',security:'tls',label:'TLS ON'},{port:'80',security:'none',label:'TLS OFF'}];
  return XRAY_INBOUNDS.flatMap(ib=>variants.map(v=>{
    let link;
    if(ib.protocol==='vmess'){
      const o={v:'2',ps:`${a.name}-${ib.label}-${v.port}`,add:host,port:v.port,id:a.id,aid:'0',scy:'auto',net:ib.net,type:ib.mode?'auto':'none',host,path:ib.path,tls:v.security==='tls'?'tls':'',sni:v.security==='tls'?sni:''};
      if(ib.mode)o.mode=ib.mode;
      link='vmess://'+btoa(unescape(encodeURIComponent(JSON.stringify(o))));
    }else{
      const q=new URLSearchParams({security:v.security,type:ib.net,host,path:ib.path});
      if(v.security==='tls')q.set('sni',sni);
      if(ib.protocol==='vless')q.set('encryption','none');
      if(ib.mode)q.set('mode',ib.mode);
      link=`${ib.protocol}://${a.id}@${host}:${v.port}?${q}#${encodeURIComponent(`${a.name}-${ib.label}-${v.label}`)}`;
    }
    return {p:ib.protocol.toUpperCase(),t:ib.label,path:ib.path,port:v.port,security:v.label,link};
  }));
}

function showXrayDetail(i){
  const a=xrayAccounts[i];if(!a)return;
  const links=makeXrayLinks(a);
  const protocols=['VLESS','VMESS','TROJAN'];
  let text=`Nama   : ${a.name}\\nUUID   : ${a.id}\\n\\n`;
  protocols.forEach(p=>{
    text+=`===== ${p} =====\\n`;
    links.filter(x=>x.p===p).forEach(x=>{
      text+=`[${x.t} · ${x.path} · Port ${x.port} · ${x.security}]\\n${x.link}\\n\\n`;
    });
  });
  openDetail('Akun Xray: '+a.name,text);
}

function showXray(id){
  const a=(id&&typeof id==='object')?id:xrayAccounts.find(x=>x.id===id);
  if(!a)return;
  const links=makeXrayLinks(a);
  const protocols=['VLESS','VMESS','TROJAN'];
  let text=`Nama   : ${a.name}\\nUUID   : ${a.id}\\n\\n`;
  protocols.forEach(p=>{
    text+=`===== ${p} =====\\n`;
    links.filter(x=>x.p===p).forEach(x=>{text+=`[${x.t} · ${x.path} · Port ${x.port} · ${x.security}]\\n${x.link}\\n\\n`});
  });
  openDetail('Akun Xray: '+a.name,text);
}

// -------------------- Misc --------------------
async function loadInfo(){try{serverInfo=await api('/__info')}catch{serverInfo=null}}
async function copyText(text){
  try{await navigator.clipboard.writeText(String(text));toast('Berhasil disalin','success')}
  catch{
    try{
      const t=document.createElement('textarea');t.value=text;document.body.append(t);t.select();document.execCommand('copy');t.remove();
      toast('Berhasil disalin','success');
    }catch{toast('Gagal menyalin','error')}
  }
}

// -------------------- Widget animasi Takina --------------------
function initSakana(){
  if(!window.SakanaWidget)return;
  try{
    const base=SakanaWidget.getCharacter('chisato');
    base.image='https://i.ibb.co.com/M0N8h0C/takina.webp';
    SakanaWidget.registerCharacter('takina',base);
    new SakanaWidget({
      character:'takina',
      size:250,
      controls:false
    }).mount('#sakana-widget').setState({
      i:0.002,
      d:0.989,
      s:0.35
    });
  }catch(e){console.warn('Sakana widget failed:',e)}
}

(async()=>{
  // Sinkronkan tombol tema saat start
  applyTheme(document.documentElement.getAttribute('data-theme') || 'light');

  await loadInfo();
  await loadStats();
  await loadTraffic();
  render();

  // Sakana JS pakai defer, jadi tunggu sampai load.
  if(document.readyState==='complete') initSakana();
  else window.addEventListener('load',initSakana);

  setInterval(loadStats,300000);
  setInterval(loadTraffic,5000);
  setInterval(loadInfo,15000);
})();
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# File / JSON helpers
# ---------------------------------------------------------------------------

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def atomic_json(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def user_exists(username):
    return subprocess.run(["id", username], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


# ---------------------------------------------------------------------------
# SSH user management
# ---------------------------------------------------------------------------

def load_ssh_users():
    os.makedirs(SSH_DATA_DIR, exist_ok=True)
    data = read_json(SSH_USERS_FILE, {})
    return data if isinstance(data, dict) else {}


def add_ssh_user(username, password):
    if user_exists(username):
        raise ValueError("Username SSH sudah digunakan di sistem.")
    subprocess.run(["useradd", "-m", "-s", "/bin/bash", username],
                   check=True, capture_output=True, text=True)
    try:
        subprocess.run(["chpasswd"], input=f"{username}:{password}\n",
                       check=True, capture_output=True, text=True)
    except Exception:
        subprocess.run(["userdel", "-r", username],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise
    users = load_ssh_users()
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[username] = {"password": password, "created": created, "expired": "never"}
    atomic_json(SSH_USERS_FILE, users)
    return {"username": username, "password": password, "created_at": created, "expired": "never"}


def delete_ssh_user(username):
    if not user_exists(username):
        raise ValueError("User SSH tidak ditemukan.")
    result = subprocess.run(["userdel", "-r", username], capture_output=True, text=True)
    if result.returncode != 0 and user_exists(username):
        raise RuntimeError((result.stderr or "Gagal menghapus user SSH.").strip())
    users = load_ssh_users()
    users.pop(username, None)
    atomic_json(SSH_USERS_FILE, users)


def list_ssh_users():
    users = load_ssh_users()
    result = []
    for username, data in sorted(users.items()):
        result.append({
            "username": username,
            "password": data.get("password", ""),
            "created_at": data.get("created", data.get("created_at", "")),
            "expired": data.get("expired", "never"),
        })
    return result


# ---------------------------------------------------------------------------
# Xray user management
# ---------------------------------------------------------------------------

def load_xray_users():
    data = read_json(XRAY_USERS_FILE, [])
    return data if isinstance(data, list) else []


def save_xray_users(users):
    config = read_json(XRAY_CONFIG_FILE, None)
    if not isinstance(config, dict) or not isinstance(config.get("inbounds"), list):
        raise RuntimeError("config.json Xray tidak valid atau tidak ditemukan.")
    clients_by_protocol = {
        "vless":  [{"id": u["id"], "email": u["name"]} for u in users],
        "vmess":  [{"id": u["id"], "email": u["name"]} for u in users],
        "trojan": [{"password": u["id"], "email": u["name"]} for u in users],
    }
    for inbound in config["inbounds"]:
        protocol = inbound.get("protocol")
        if protocol in clients_by_protocol:
            inbound.setdefault("settings", {})["clients"] = clients_by_protocol[protocol]
    atomic_json(XRAY_CONFIG_FILE, config)
    atomic_json(XRAY_USERS_FILE, users)
    subprocess.run(["pkill", "-x", "xray"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# Online SSH users (accurate, with IP)
# ---------------------------------------------------------------------------

def _strip_brackets(s):
    s = (s or "").strip()
    if s.startswith("[") and "]" in s:
        return s[1:s.index("]")]
    return s


def _normalize_ip(ip):
    ip = _strip_brackets(ip)
    if ip.startswith("::ffff:"):
        ip = ip[7:]
    if "%" in ip:
        ip = ip.split("%", 1)[0]
    return ip


def _split_hostport(addr):
    addr = (addr or "").strip()
    if not addr:
        return "", ""
    if addr.startswith("["):
        end = addr.find("]")
        if end < 0:
            return _strip_brackets(addr), ""
        host = addr[1:end]
        rest = addr[end + 1:].lstrip(":")
        return host, rest
    if ":" in addr:
        host, port = addr.rsplit(":", 1)
        return _strip_brackets(host), port
    return addr, ""


def get_online_ssh_users():
    sessions = []
    seen = set()

    try:
        out = subprocess.run(["who", "-u"], capture_output=True,
                             text=True, timeout=3).stdout or ""
    except Exception:
        out = ""

    pat = re.compile(
        r'^(\S+)\s+(\S+)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s+'
        r'(?:(\S+)\s+(?:(\d+)\s+)?)?\(([^)]+)\)'
    )
    for line in out.splitlines():
        m = pat.match(line)
        if not m:
            continue
        user, tty, date, time_s, idle, pid, host = m.groups()
        ip = _normalize_ip(host)
        if not ip:
            continue
        key = (user, ip)
        if key in seen:
            continue
        seen.add(key)
        sessions.append({
            "user": user, "ip": ip, "tty": tty or "-",
            "since": f"{date} {time_s}", "idle": idle or "-",
            "pid": int(pid) if pid else None,
        })

    try:
        ss_out = subprocess.run(["ss", "-tnp"], capture_output=True,
                                text=True, timeout=3).stdout or ""
    except Exception:
        ss_out = ""

    for line in ss_out.splitlines():
        if "ESTAB" not in line:
            continue
        if "sshd" not in line and "dropbear" not in line:
            continue
        pm = re.search(r'pid=(\d+)', line)
        if not pm:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        peer = parts[4]
        host, _ = _split_hostport(peer)
        ip = _normalize_ip(host)
        if not ip:
            continue
        pid = int(pm.group(1))
        try:
            uid = os.stat(f"/proc/{pid}").st_uid
            uname = pwd.getpwuid(uid).pw_name
        except Exception:
            continue
        if uname == "root":
            continue
        key = (uname, ip)
        if key in seen:
            continue
        seen.add(key)
        sessions.append({
            "user": uname, "ip": ip, "tty": "-",
            "since": "active", "idle": "-", "pid": pid,
        })

    return sessions


# ---------------------------------------------------------------------------
# Domain resolution (Cloudflare Tunnel aware)
# ---------------------------------------------------------------------------

def server_domain(handler):
    with DOMAIN_STATE_LOCK:
        cached = (DOMAIN_STATE.get("domain") or "").strip()
    if cached:
        return cached

    host = (handler.headers.get("Host") or handler.headers.get("X-Forwarded-Host")
            or handler.headers.get("CF-Connecting-Host") or "").strip()
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    host = host.strip().rstrip(".")
    if host and host.lower() not in ("localhost", "127.0.0.1"):
        return host
    return ""


# ---------------------------------------------------------------------------
# Cloudflare Tunnel domain watcher
# ---------------------------------------------------------------------------

_CF_INGRESS_RE = re.compile(
    r'hostname\\?"\s*:\s*\\?"([^"\\]+)\\?"\s*,\s*'
    r'\\?"service\\?"\s*:\s*\\?"([^"\\]+)\\?"'
)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _parse_cloudflared_ingress(line):
    if "Updated to new configuration" not in line or "config=" not in line:
        return []
    line = _ANSI_ESCAPE.sub("", line)
    return _CF_INGRESS_RE.findall(line)


def _match_domain_for_port(pairs, port):
    for hostname, service in pairs:
        if not hostname or not service:
            continue
        if re.search(rf":{port}(?:[/?\"']|$)", service):
            return hostname.strip()
    return ""


def _save_domain_state_locked():
    try:
        os.makedirs(os.path.dirname(DOMAIN_STATE_FILE) or ".", exist_ok=True)
        tmp = DOMAIN_STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(DOMAIN_STATE, f)
        os.replace(tmp, DOMAIN_STATE_FILE)
    except OSError as exc:
        print(f"[domain] state save failed: {exc}")


def _load_domain_state():
    try:
        with open(DOMAIN_STATE_FILE, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return
    if isinstance(saved, dict) and saved.get("domain"):
        with DOMAIN_STATE_LOCK:
            DOMAIN_STATE["domain"] = str(saved["domain"]).strip()
            DOMAIN_STATE["updated_at"] = saved.get("updated_at")
        print(f"[domain] loaded cached domain: {DOMAIN_STATE['domain']}")


def _refresh_domain_from_cloudflared():
    if not os.path.exists(CLOUDFLARED_LOG_FILE):
        return
    try:
        with open(CLOUDFLARED_LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            read_size = min(size, 128 * 1024)
            f.seek(size - read_size)
            tail = f.read().decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"[domain] log read failed: {exc}")
        return

    latest_pairs = []
    for line in reversed(tail.splitlines()):
        if "Updated to new configuration" in line:
            latest_pairs = _parse_cloudflared_ingress(line)
            break
    if not latest_pairs:
        return

    hostname = _match_domain_for_port(latest_pairs, XRAY_PROXY_PORT)
    if not hostname:
        return

    with DOMAIN_STATE_LOCK:
        if DOMAIN_STATE.get("domain") == hostname:
            return
        DOMAIN_STATE["domain"] = hostname
        DOMAIN_STATE["updated_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        _save_domain_state_locked()
    print(f"[domain] detected from cloudflared: {hostname} (port {XRAY_PROXY_PORT})")


def domain_watcher_loop():
    _load_domain_state()
    while True:
        try:
            _refresh_domain_from_cloudflared()
        except Exception as exc:
            print(f"[domain] watcher error: {exc}")
        time.sleep(DOMAIN_REFRESH_SEC)


# ---------------------------------------------------------------------------
# Online Xray users
# ---------------------------------------------------------------------------

def get_online_xray_users():
    try:
        proc = subprocess.run(
            ["xray", "api", "statsquery", "--server=127.0.0.1:10085",
             "-pattern", "user>>>", "-reset=false"],
            capture_output=True, text=True, timeout=3,
        )
        if proc.returncode != 0:
            return []
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        online = {}
        for line in output.splitlines():
            match = re.search(r"user>>>(.+?)>>>online\s*:\s*(\d+)", line.strip())
            if match and int(match.group(2)) > 0:
                online[match.group(1)] = int(match.group(2))
        return [{"user": name, "connections": count,
                 "ip": "Tidak tersedia melalui Cloudflare Tunnel"}
                for name, count in sorted(online.items())]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Container network traffic metrics
# ---------------------------------------------------------------------------

TRAFFIC_DATA_DIR = os.environ.get("TRAFFIC_DATA_DIR", "/data")
TRAFFIC_STATE_FILE = os.path.join(TRAFFIC_DATA_DIR, "traffic_metrics.json")
TRAFFIC_SAMPLE_SECONDS = max(2, int(os.environ.get("TRAFFIC_SAMPLE_SECONDS", "5")))
TRAFFIC_LOCK = threading.Lock()
TRAFFIC_STATE = {
    "last_counters": {}, "total_rx": 0, "total_tx": 0,
    "daily": {}, "monthly": {}, "updated_at": None,
    "interfaces": [], "rate_rx": 0.0, "rate_tx": 0.0,
}


def read_network_counters():
    counters = {}
    try:
        with open("/proc/net/dev", encoding="utf-8") as f:
            lines = f.readlines()[2:]
        for line in lines:
            if ":" not in line:
                continue
            iface, raw = line.split(":", 1)
            iface = iface.strip()
            fields = raw.split()
            if iface and iface != "lo" and len(fields) >= 9:
                counters[iface] = {"rx": int(fields[0]), "tx": int(fields[8])}
    except (OSError, ValueError):
        return {}
    return counters


def _traffic_save_locked():
    try:
        os.makedirs(TRAFFIC_DATA_DIR, exist_ok=True)
        tmp = TRAFFIC_STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(TRAFFIC_STATE, f)
        os.replace(tmp, TRAFFIC_STATE_FILE)
    except OSError as exc:
        print(f"[traffic] state save failed: {exc}")


def _traffic_load():
    try:
        with open(TRAFFIC_STATE_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for key in TRAFFIC_STATE:
                if key in saved:
                    TRAFFIC_STATE[key] = saved[key]
    except (OSError, ValueError):
        pass


def sample_network_traffic():
    now = datetime.now().astimezone()
    current = read_network_counters()
    if not current:
        return
    rx_now = sum(v["rx"] for v in current.values())
    tx_now = sum(v["tx"] for v in current.values())
    day_key, month_key = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")

    with TRAFFIC_LOCK:
        previous = TRAFFIC_STATE.get("last_counters") or {}
        prev_rx = sum(int(v.get("rx", 0)) for v in previous.values())
        prev_tx = sum(int(v.get("tx", 0)) for v in previous.values())
        delta_rx = rx_now - prev_rx if rx_now >= prev_rx else rx_now
        delta_tx = tx_now - prev_tx if tx_now >= prev_tx else tx_now

        elapsed = TRAFFIC_SAMPLE_SECONDS
        stamp = TRAFFIC_STATE.get("updated_at")
        if stamp:
            try:
                elapsed = max(0.5, (now - datetime.fromisoformat(stamp)).total_seconds())
            except ValueError:
                pass

        TRAFFIC_STATE["total_rx"] = int(TRAFFIC_STATE.get("total_rx", 0)) + delta_rx
        TRAFFIC_STATE["total_tx"] = int(TRAFFIC_STATE.get("total_tx", 0)) + delta_tx
        daily = TRAFFIC_STATE.get("daily") or {}
        if daily.get("date") != day_key:
            daily = {"date": day_key, "rx": 0, "tx": 0}
        daily["rx"] = int(daily.get("rx", 0)) + delta_rx
        daily["tx"] = int(daily.get("tx", 0)) + delta_tx
        TRAFFIC_STATE["daily"] = daily
        monthly = TRAFFIC_STATE.get("monthly") or {}
        if monthly.get("month") != month_key:
            monthly = {"month": month_key, "rx": 0, "tx": 0}
        monthly["rx"] = int(monthly.get("rx", 0)) + delta_rx
        monthly["tx"] = int(monthly.get("tx", 0)) + delta_tx
        TRAFFIC_STATE["monthly"] = monthly
        TRAFFIC_STATE["rate_rx"] = delta_rx / elapsed
        TRAFFIC_STATE["rate_tx"] = delta_tx / elapsed
        TRAFFIC_STATE["last_counters"] = current
        TRAFFIC_STATE["interfaces"] = sorted(current)
        TRAFFIC_STATE["updated_at"] = now.isoformat(timespec="seconds")
        _traffic_save_locked()


def traffic_sampler_loop():
    _traffic_load()
    while True:
        try:
            sample_network_traffic()
        except Exception as exc:
            print(f"[traffic] sampling error: {exc}")
        time.sleep(TRAFFIC_SAMPLE_SECONDS)


def traffic_payload():
    with TRAFFIC_LOCK:
        d, m = TRAFFIC_STATE.get("daily") or {}, TRAFFIC_STATE.get("monthly") or {}
        return {
            "source": "container_network_interfaces",
            "interfaces": list(TRAFFIC_STATE.get("interfaces") or []),
            "download": {"rate_bytes_per_sec": round(float(TRAFFIC_STATE.get("rate_tx", 0)), 2)},
            "upload": {"rate_bytes_per_sec": round(float(TRAFFIC_STATE.get("rate_rx", 0)), 2)},
            "total": {"download_bytes": int(TRAFFIC_STATE.get("total_tx", 0)),
                      "upload_bytes": int(TRAFFIC_STATE.get("total_rx", 0))},
            "daily": {"date": d.get("date"), "download_bytes": int(d.get("tx", 0)),
                      "upload_bytes": int(d.get("rx", 0))},
            "monthly": {"month": m.get("month"), "download_bytes": int(m.get("tx", 0)),
                        "upload_bytes": int(m.get("rx", 0))},
            "updated_at": TRAFFIC_STATE.get("updated_at"),
            "sample_interval_seconds": TRAFFIC_SAMPLE_SECONDS,
        }


def stats_payload(handler):
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            cpu = next((line.split(":", 1)[1].strip()
                        for line in f if line.lower().startswith("model name")), "Unknown")
    except OSError:
        cpu = "Unknown"

    mem = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                key, val = line.split(":", 1)
                mem[key] = int(val.strip().split()[0])
        total = mem.get("MemTotal", 0) // 1024
        avail = mem.get("MemAvailable", 0) // 1024
        used = max(total - avail, 0)
        ram_used, ram_total = f"{used} MB", f"{total} MB"
    except Exception:
        ram_used, ram_total = "--", "--"

    try:
        disk = shutil.disk_usage("/")
        disk_usage = f"{(disk.used / disk.total * 100):.1f}%"
    except Exception:
        disk_usage = "--"

    uptime = "--"
    try:
        with open("/proc/uptime") as f:
            seconds = int(float(f.read().split()[0]))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        uptime = f"{days}d {hours}h {minutes}m"
    except Exception:
        pass

    online = get_online_ssh_users()
    xray_online = get_online_xray_users()
    online_count = len(online)
    online_brief = (
        ", ".join(f"{u['user']}@{u['ip']}" for u in online)
        if online else "Tidak ada koneksi SSH aktif"
    )

    return {
        "status": "ONLINE",
        "cpu_model": cpu,
        "ram_used": ram_used,
        "ram_total": ram_total,
        "disk_usage": disk_usage,
        "uptime": uptime,
        "ssh_online": str(online_count),
        "user_list_details": online_brief,
        "online_users": online,
        "xray_online_users": xray_online,
        "xray_online": str(sum(u.get("connections", 0) for u in xray_online)),
        "domain": server_domain(handler),
        "ui_port": PORT,
        "xray_proxy_port": XRAY_PROXY_PORT,
        "ssh_port": SSH_PUBLIC_PORT,
        "ws_proxy_cfg": {"sshPort": 22},
        "sys_settings": {"enable_bbr": ENABLE_BBR, "udpgw_port": UDPGW_PORT},
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ServerPanel/1.0"

    def log_message(self, fmt, *args):
        print("[app] " + fmt % args)

    def send_json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self, html, status=200):
        raw = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("Request terlalu besar.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                self.send_html(INDEX_HTML)
            elif path == "/api/list":
                self.send_json({"status": "success", "users": list_ssh_users()})
            elif path == "/api/xray/list":
                self.send_json({"status": "success", "accounts": load_xray_users()})
            elif path == "/api/stats":
                self.send_json(stats_payload(self))
            elif path == "/api/traffic":
                self.send_json(traffic_payload())
            elif path == "/api/online":
                self.send_json({"status": "success", "online_users": get_online_ssh_users()})
            elif path == "/__info":
                self.send_json({
                    "domain": server_domain(self),
                    "ui_port": PORT,
                    "xray_proxy_port": XRAY_PROXY_PORT,
                    "ssh_port": SSH_PUBLIC_PORT,
                    "udpgw_port": UDPGW_PORT,
                })
            else:
                self.send_json({"status": "error", "message": "Endpoint tidak ditemukan."}, 404)
        except Exception as exc:
            self.send_json({"status": "error", "message": str(exc)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.read_body()

            if path == "/api/add":
                user = str(data.get("user", "")).strip().lower()
                password = str(data.get("pass", ""))
                account = add_ssh_user(user, password)
                msg = (
                    "===========================\n"
                    f" Username   : {account['username']}\n"
                    f" Password   : {account['password']}\n"
                    f" Dibuat     : {account['created_at']}\n"
                    f" Domain     : {server_domain(self)}\n"
                    "==========================="
                )
                self.send_json({"status": "success", "message": msg, "user": account})

            elif path == "/api/delete":
                user = str(data.get("user", "")).strip()
                delete_ssh_user(user)
                self.send_json({"status": "success",
                                "message": f"Akun SSH {user} berhasil dihapus."})

            elif path == "/api/xray/add":
                name = str(data.get("name", "")).strip().lower()
                if not XRAY_NAME_RE.fullmatch(name):
                    raise ValueError("Nama 1–24 karakter: huruf, angka, _ atau -.")
                users = load_xray_users()
                if any(u.get("name") == name for u in users):
                    raise ValueError("Nama akun Xray sudah digunakan.")
                account = {"id": str(uuid.uuid4()), "name": name}
                users.append(account)
                save_xray_users(users)
                self.send_json({"status": "success",
                                "message": "Akun Xray berhasil dibuat.",
                                "account": account})

            elif path == "/api/xray/delete":
                uid = str(data.get("id", ""))
                users = load_xray_users()
                updated = [u for u in users if u.get("id") != uid]
                if len(updated) == len(users):
                    raise ValueError("Akun Xray tidak ditemukan.")
                save_xray_users(updated)
                self.send_json({"status": "success",
                                "message": "Akun Xray berhasil dihapus."})

            else:
                self.send_json({"status": "error", "message": "Endpoint tidak ditemukan."}, 404)

        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"status": "error", "message": str(exc)}, 400)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
            self.send_json({"status": "error",
                            "message": detail or "Perintah sistem gagal dijalankan."}, 500)
        except Exception as exc:
            self.send_json({"status": "error", "message": str(exc)}, 500)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[app] Panel berjalan di http://{HOST}:{PORT}")

    # Auto-detect domain from cloudflared log (ingress -> port 8080).
    threading.Thread(target=domain_watcher_loop,
                     name="domain-watcher", daemon=True).start()

    sampler = threading.Thread(target=traffic_sampler_loop,
                               name="traffic-sampler", daemon=True)
    sampler.start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()