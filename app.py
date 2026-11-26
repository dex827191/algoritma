#!/usr/bin/env python3
"""Combined SSH + Xray web panel. The HTML UI is embedded at build time."""
import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse
from http.cookies import SimpleCookie

APP_DIR = "/app"
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
XRAY_USERS_PATH = os.path.join(APP_DIR, "users.json")
SSH_DATA_DIR = "/etc/ssh-sni"
SSH_USERS_PATH = os.path.join(SSH_DATA_DIR, "users.json")
HTML_PATH = os.path.join(APP_DIR, "index.html")
# Full UI from the supplied index.html is embedded here; the standalone file is kept for editing.
UI_HTML = '<!doctype html>\n<html lang="id">\n<head>\n<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n<meta name="theme-color" content="#6750a4"><title>Server Panel • Material 3</title>\n<style>\n:root{color-scheme:light;--primary:#6750a4;--on-primary:#fff;--primary-container:#eaddff;--on-primary-container:#21005d;--secondary:#625b71;--surface:#fffbfe;--surface-low:#f7f2fa;--surface-high:#ece6f0;--surface-highest:#e6e0e9;--outline:#79747e;--outline-soft:#cac4d0;--text:#1d1b20;--muted:#49454f;--success:#386a20;--success-bg:#d7f5c4;--error:#b3261e;--radius:18px;--shadow:0 1px 3px #0001,0 8px 24px #0000000a}\n*{box-sizing:border-box}body{margin:0;background:var(--surface-low);color:var(--text);font:14px/1.5 Inter,Roboto,"Segoe UI",sans-serif}button,input,select,textarea{font:inherit}button{cursor:pointer}.app{min-height:100vh}.sidebar{position:fixed;inset:0 auto 0 0;width:264px;background:var(--surface);border-right:1px solid var(--outline-soft);padding:18px 14px;display:flex;flex-direction:column;z-index:5;transition:transform .25s}.brand{display:flex;align-items:center;gap:12px;padding:8px 10px 22px;font-weight:750;font-size:17px}.brandmark{width:40px;height:40px;border-radius:14px;background:var(--primary);color:white;display:grid;place-items:center;font-size:21px}.navlabel{font-size:11px;letter-spacing:1.1px;color:var(--muted);font-weight:700;padding:10px 14px}.nav button{width:100%;border:0;background:transparent;color:var(--muted);padding:12px 16px;border-radius:30px;text-align:left;display:flex;gap:14px;align-items:center;margin:3px 0;font-weight:600}.nav button.active{background:var(--primary-container);color:var(--on-primary-container)}.nav button:hover{background:var(--surface-high)}.nav .ico{width:22px;text-align:center;font-size:18px}.sidefoot{margin-top:auto;border-top:1px solid var(--outline-soft);padding:16px 8px 4px}.status{display:inline-flex;align-items:center;gap:8px;border-radius:30px;padding:7px 12px;background:var(--surface-high);font-size:12px;font-weight:650}.dot{width:8px;height:8px;background:#2e7d32;border-radius:50%;box-shadow:0 0 0 4px #2e7d3218}.main{margin-left:264px;min-width:0}.topbar{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 30px;background:#fffbfeeF;border-bottom:1px solid #e6e0e9;position:sticky;top:0;z-index:3;backdrop-filter:blur(12px)}.top-left{display:flex;align-items:center;gap:14px}.topbar h2{font-size:16px;margin:0}.top-actions{display:flex;gap:10px;align-items:center}.content{max-width:1100px;margin:auto;padding:28px 30px 60px}.page-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:22px;gap:12px}.page-head h1{font-size:26px;letter-spacing:-.5px;margin:0 0 4px}.page-head p{color:var(--muted);margin:0}.card{background:var(--surface);border:1px solid #e7e1e9;border-radius:var(--radius);padding:20px;margin-bottom:16px;box-shadow:var(--shadow)}.card h3{font-size:16px;margin:0 0 15px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.grid.five{grid-template-columns:repeat(5,minmax(0,1fr))}.stat{padding:17px;border-radius:16px;background:var(--surface);border:1px solid #e7e1e9;min-width:0}.stat .k{color:var(--muted);font-size:11px;font-weight:750;letter-spacing:.7px;text-transform:uppercase}.stat .v{font-size:17px;font-weight:750;margin-top:8px;overflow-wrap:anywhere}.stat .sub{font-size:12px;color:var(--muted);margin-top:3px}.field{display:flex;flex-direction:column;gap:7px;margin-bottom:14px;min-width:0}.field label{font-size:12px;font-weight:700;color:var(--muted)}.field input,.field select,.field textarea{width:100%;border:1px solid var(--outline);background:var(--surface);border-radius:10px;padding:12px 13px;color:var(--text);outline:none;min-width:0}.field input:focus,.field select:focus,.field textarea:focus{border:2px solid var(--primary);padding:11px 12px}.row{display:flex;gap:12px;align-items:end}.row>*{flex:1;min-width:0}.btn{border:0;border-radius:28px;padding:11px 18px;min-height:42px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;gap:8px;transition:.15s}.btn:disabled{opacity:.55;cursor:not-allowed}.filled{background:var(--primary);color:white}.filled:hover{box-shadow:0 2px 8px #6750a455}.tonal{background:var(--primary-container);color:var(--on-primary-container)}.outlined{background:transparent;color:var(--primary);border:1px solid var(--outline-soft)}.danger{background:#f9dedc;color:#410e0b}.textbtn{background:transparent;color:var(--primary);padding:8px 12px}.wide{width:100%}.chip{display:inline-flex;align-items:center;border-radius:30px;background:var(--surface-high);padding:5px 10px;font-size:11px;font-weight:700;color:var(--muted)}.chip.good{background:var(--success-bg);color:var(--success)}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:460px}th,td{text-align:left;padding:12px 10px;border-bottom:1px solid #e7e1e9}th{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.6px}td{font-size:13px}.mono,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}.muted{color:var(--muted)}.output{background:#f3eff7;border-radius:12px;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:330px;overflow:auto;font-size:12px}.notice{background:#f1ebfa;color:#403653;padding:13px 15px;border-radius:13px;font-size:12px}.hidden{display:none!important}.hamb{display:none}.overlay{display:none}.toast{position:fixed;right:20px;bottom:20px;z-index:20;background:#302d35;color:white;padding:13px 18px;border-radius:14px;box-shadow:var(--shadow);max-width:min(90vw,420px)}.toast.error{background:#b3261e}.toast.success{background:#286b35}.modal{position:fixed;inset:0;background:#17131d77;z-index:15;display:grid;place-items:center;padding:20px}.modalbox{background:var(--surface);border-radius:24px;padding:24px;width:min(100%,420px);box-shadow:var(--shadow)}.modalbox h3{margin:0 0 8px}.bar{height:8px;border-radius:20px;background:var(--surface-high);overflow:hidden;margin-top:9px}.bar span{display:block;height:100%;background:var(--primary);border-radius:20px}.traffic{display:grid;grid-template-columns:1fr 1fr;gap:12px}.traffic>div{background:var(--surface-high);border-radius:14px;padding:14px}.genbuttons{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.genbuttons button{font-size:12px;padding:12px 6px}.linkbox{background:var(--surface-high);padding:12px;border-radius:12px;margin:8px 0}.linktop{display:flex;justify-content:space-between;gap:8px;align-items:center}.small{font-size:11px}.mt{margin-top:14px}.right{text-align:right}.empty{text-align:center;color:var(--muted);padding:25px}.mobile-only{display:none}\n@media(max-width:1000px){.grid.five{grid-template-columns:repeat(2,minmax(0,1fr))}.grid.five .stat:first-child{grid-column:span 2}}\n@media(max-width:760px){.sidebar{transform:translateX(-105%);width:285px;box-shadow:var(--shadow)}.sidebar.open{transform:translateX(0)}.overlay.show{display:block;position:fixed;inset:0;background:#17131d66;z-index:4}.main{margin-left:0}.topbar{height:62px;padding:0 16px}.content{padding:22px 15px 45px}.hamb,.mobile-only{display:inline-flex}.page-head h1{font-size:23px}.grid.five{grid-template-columns:repeat(2,minmax(0,1fr))}.row{flex-direction:column;align-items:stretch;gap:0}.row .btn{width:100%}.top-actions .admin-label{display:none}}\n@media(max-width:430px){.card{padding:16px}.stat{padding:14px}.stat .v{font-size:15px}.genbuttons{gap:6px}.genbuttons button{font-size:10px;padding:11px 3px}.page-head{flex-direction:column}.traffic{gap:8px}}\n</style></head>\n<body>\n<div class="app">\n<div class="overlay" id="overlay" onclick="toggleNav(false)"></div>\n<aside class="sidebar" id="sidebar"><div class="brand"><div class="brandmark">✦</div><div>SERVER PANEL<div class="muted small" style="font-weight:500">Management Console</div></div></div>\n<div class="navlabel">MENU UTAMA</div><nav class="nav">\n<button data-page="dashboard" class="active" onclick="navigate(\'dashboard\')"><span class="ico">▦</span>Dashboard</button>\n<button data-page="ssh" onclick="navigate(\'ssh\')"><span class="ico">♙</span>Buat Akun SSH</button>\n<button data-page="xray" onclick="navigate(\'xray\')"><span class="ico">◉</span>Buat Akun Xray</button>\n\n\n</nav><div class="sidefoot"><div class="status" id="sideStatus">● Public Self-Service</div></div></aside>\n<div class="main"><header class="topbar"><div class="top-left"><button class="btn textbtn hamb" onclick="toggleNav(true)">☰</button><h2 id="topTitle">Dashboard</h2></div><div class="top-actions"><span class="chip good" id="serverState">● Connecting</span></div></header>\n<main class="content" id="view"></main></div></div>\n<div id="toast" class="toast hidden"></div>\n<script>\n\'use strict\';\nconst $=id=>document.getElementById(id);let stats=null,adminToken=\'\',passConfigured=false,currentPage=\'dashboard\',sshUsers=[],xrayAccounts=[],selectedCreated=null,serverInfo=null,modalMode=\'login\',lastSSHResult=\'\';\nconst esc=s=>String(s??\'\').replace(/[&<>"\']/g,c=>({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'"\':\'&quot;\',"\'":\'&#39;\'}[c]));\nfunction toast(msg,type=\'\'){const el=$(\'toast\');el.textContent=msg;el.className=\'toast \'+type;clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>el.classList.add(\'hidden\'),3500)}\nasync function api(url,opts={}){const r=await fetch(url,opts);let d;try{d=await r.json()}catch{throw Error(\'Respons server tidak valid\')}if(!r.ok&&d.status!==\'error\')throw Error(d.message||`HTTP ${r.status}`);return d}\nfunction toggleNav(v){$(\'sidebar\').classList.toggle(\'open\',v);$(\'overlay\').classList.toggle(\'show\',v)}\nfunction navigate(page){currentPage=page;document.querySelectorAll(\'.nav button\').forEach(b=>b.classList.toggle(\'active\',b.dataset.page===page));$(\'topTitle\').textContent=({dashboard:\'Dashboard\',ssh:\'Buat Akun SSH\',xray:\'Buat Akun Xray\',settings:\'Pengaturan SSH\'})[page];toggleNav(false);render()}\nfunction adminUI(){$(\'sideStatus\').textContent=\'● Public Self-Service\';}\nfunction openModal(){}\nfunction closeModal(){}\nfunction openChangePass(){}\nfunction adminAction(){}\nasync function submitModal(){}\nasync function loadStats(){try{stats=await api(\'/api/stats\');passConfigured=false;$(\'serverState\').textContent=\'● \'+(stats.status||\'ONLINE\');$(\'serverState\').className=\'chip good\';adminUI();if(currentPage===\'dashboard\'||currentPage===\'settings\')render()}catch(e){$(\'serverState\').textContent=\'● Offline\';$(\'serverState\').className=\'chip\';}}\nfunction card(title,body){return `<section class="card"><h3>${title}</h3>${body}</section>`}\nfunction render(){if(currentPage===\'dashboard\')renderDashboard();if(currentPage===\'ssh\')renderSSH();if(currentPage===\'xray\')renderXray();if(currentPage===\'settings\')renderSettings();}\nfunction renderDashboard(){const s=stats||{};const values=[[\'CPU MODEL\',s.cpu_model||\'Memuat...\',\'Processor server\'],[\'RAM USED / TOTAL\',(s.ram_used||\'--\')+\' / \'+(s.ram_total||\'--\'),\'Penggunaan memori\'],[\'DISK USAGE\',s.disk_usage||\'--\',\'Storage root\'],[\'SERVER UPTIME\',s.uptime||\'--\',\'Waktu aktif\'],[\'SSH ONLINE\',(s.ssh_online||\'0\')+\' Active\',s.user_list_details||\'\']];$(\'view\').innerHTML=`<div class="page-head"><div><h1>Dashboard Server</h1><p>Ringkasan status dan performa server kamu.</p></div><span class="chip good">● Services Managed</span></div><div class="grid five">${values.map(v=>`<div class="stat"><div class="k">${v[0]}</div><div class="v">${esc(v[1])}</div><div class="sub">${esc(v[2])}</div></div>`).join(\'\')}</div>${card(\'Traffic Metrics\',`<div class="traffic"><div><div class="muted small">↓ DOWNLOAD</div><b style="font-size:22px">128.4 MB</b><div class="sub">Kecepatan simulasi: <span id="dlSpeed">${(100+Math.random()*100).toFixed(1)}</span> KB/s</div></div><div><div class="muted small">↑ UPLOAD</div><b style="font-size:22px">96.2 MB</b><div class="sub">Kecepatan simulasi: <span id="ulSpeed">${(100+Math.random()*150).toFixed(2)}</span> KB/s</div></div></div><div class="mt"><div class="muted small">NETWORK ACTIVITY · LIVE VISUAL</div><div style="height:65px;display:flex;gap:3px;align-items:end;margin-top:8px">${Array.from({length:35},()=>`<i style="display:block;flex:1;height:${10+Math.random()*90}%;border-radius:4px 4px 0 0;background:#8b78bd"></i>`).join(\'\')}</div></div>`)}${card(\'Info Pengaturan Server\',`<div class="grid">${[[\'SSH Port\',s.ws_proxy_cfg?.sshPort||22],[\'Go Proxy\',\'8080\'],[\'Nginx\',\'8081\'],[\'Panel API\',\'3000\'],[\'Xray\',\'data/config.json\'],[\'BBR\',s.sys_settings?.enable_bbr===\'true\'?\'ON\':\'OFF\'],[\'UDPGW\',s.sys_settings?.udpgw_port||7300]].map(x=>`<div><span class="muted">${x[0]}</span><br><b>${esc(x[1])}</b></div>`).join(\'\')}</div>`)}${card(\'Domain & Service Paths\',`<div class="field"><label>Domain Utama</label><div class="row"><input readonly value="${esc(s.domain||location.hostname)}"><button class="btn tonal" onclick="copyText(\'${esc(s.domain||location.hostname)}\')">Salin</button></div></div><div class="field"><label>SSH WebSocket Path</label><input readonly value="/ (kosong / tanpa path)"></div><div class="field"><label>Xray Paths</label><input readonly value="/vless · /vmess · /trojan"></div>`)}`}\nasync function loadSsh(){try{const d=await api(\'/api/list\');sshUsers=d.users||[]}catch(e){toast(e.message,\'error\')}}\nasync function renderSSH(){\n const head=`<div class="page-head"><div><h1>Daftar Akun SSH (<span id="sshCount">0</span>)</h1><p>Kelola akun SSH, buat akun baru, dan hapus akun yang tidak digunakan.</p></div><span class="chip">SSH WebSocket tanpa path</span></div>`;\n const form=card(\'Tambah Akun SSH\',`<div class="row"><div class="field"><label>Username</label><input id="sshUser" placeholder="contoh: user01" autocomplete="off" maxlength="32"></div><div class="field"><label>Password</label><input id="sshPass" type="password" placeholder="Minimal 8 karakter" autocomplete="new-password"></div><button class="btn filled" onclick="createSSH()">＋ Buat Akun</button></div><div id="sshResult"></div><p class="muted small">Akun menggunakan Dropbear. Koneksi WebSocket memakai domain utama pada port publik tanpa /path.</p>`);\n $(\'view\').innerHTML=head+form+card(\'Daftar Akun SSH\',`<div id="sshList" class="empty">Memuat daftar akun...</div>`);\n await loadSSH();\n}\nasync function loadSSH(){\n try{const d=await api(\'/api/list\');sshUsers=d.users||[];const c=$(\'sshCount\');if(c)c.textContent=sshUsers.length;const box=$(\'sshList\');if(!box)return;box.innerHTML=sshUsers.length?`<div class="tablewrap"><table><thead><tr><th>No</th><th>Username</th><th>Dibuat</th><th>Aksi</th></tr></thead><tbody>${sshUsers.map((u,i)=>`<tr><td>${i+1}</td><td><b>${esc(u.username)}</b></td><td>${esc((u.created_at||\'\').slice(0,10)||\'-\')}</td><td><button class="btn danger" onclick="deleteSSH(\'${esc(u.username)}\')">Hapus</button></td></tr>`).join(\'\')}</tbody></table></div>`:\'<div class="empty">Belum ada akun SSH.</div>\'}catch(e){const box=$(\'sshList\');if(box)box.textContent=\'Gagal memuat daftar akun: \'+e.message}\n}\nasync function createSSH(){const u=$(\'sshUser\').value.trim(),p=$(\'sshPass\').value;if(!u||!p)return toast(\'Isi username dan password\',\'error\');try{const d=await api(\'/api/add\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({user:u,pass:p})});if(d.status===\'success\'){toast(\'Akun SSH berhasil dibuat\',\'success\');lastSSHResult=d.message;$(\'sshResult\').innerHTML=`<div class="notice mt"><b>✓ Akun berhasil dibuat</b><pre class="output">${esc(d.message)}</pre><button class="btn tonal wide" onclick="copyText(${JSON.stringify(d.message).replace(/</g,\'\\\\u003c\')})">Salin Detail Akun</button></div>`;$(\'sshUser\').value=\'\';$(\'sshPass\').value=\'\';}else toast(d.message,\'error\')}catch(e){toast(e.message,\'error\')}}\nfunction showSSHDetail(name){const u=sshUsers.find(x=>x.username===name);if(!u)return;$(\'sshDetail\').innerHTML=`<div class="notice mt"><b>Detail Akun ${esc(u.username)}</b><p class="mono">Username: ${esc(u.username)}<br>Password: ${esc(u.password||\'-\')}<br>IP: ${esc(u.ip||\'Unknown\')}<br>Shell: ${esc(u.shell||\'-\')}</p><button class="btn tonal" onclick="copyText(${JSON.stringify(`Username: ${u.username}\\nPassword: ${u.password||\'-\'}\\nIP: ${u.ip||\'Unknown\'}\\nShell: ${u.shell||\'-\'}`).replace(/</g,\'\\\\u003c\')})">Salin Semua</button></div>`}\nasync function deleteSSH(name){if(!confirm(\'Hapus akun SSH \'+name+\'?\'))return;try{const d=await api(\'/api/delete\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({user:name})});toast(d.message,d.status===\'success\'?\'success\':\'error\');if(d.status===\'success\')loadSSH()}catch(e){toast(e.message,\'error\')}}\nasync function loadXray(){\n try{const d=await api(\'/api/xray/list\');xrayAccounts=d.accounts||[];const c=$(\'xrayCount\');if(c)c.textContent=xrayAccounts.length;const box=$(\'xrayList\');if(box)box.innerHTML=xrayAccounts.length?`<div class="tablewrap"><table><thead><tr><th>No</th><th>Nama</th><th>UUID</th><th>Aksi</th></tr></thead><tbody>${xrayAccounts.map((a,i)=>`<tr><td>${i+1}</td><td><b>${esc(a.name)}</b></td><td class="mono small">${esc(a.id)}</td><td><button class="btn danger" onclick="deleteXray(\'${esc(a.id)}\')">Hapus</button></td></tr>`).join(\'\')}</tbody></table></div>`:\'<div class="empty">Belum ada akun Xray.</div>\'}catch(e){const box=$(\'xrayList\');if(box)box.textContent=\'Gagal memuat daftar akun: \'+e.message}\n}\nasync function renderXray(){\n const head=`<div class="page-head"><div><h1>Daftar Akun Xray (<span id="xrayCount">0</span>)</h1><p>Kelola akun VLESS, VMess, dan Trojan.</p></div><span class="chip">Domain dari ENV</span></div>`;\n const form=card(\'Tambah Akun Xray\',`<p class="muted small">Satu akun akan ditambahkan ke semua inbound yang tersedia di config.json.</p><div class="row"><div class="field"><label>Nama Akun</label><input id="xrayName" placeholder="user01" maxlength="24"></div><button class="btn filled" onclick="createXray()">＋ Buat Akun</button></div><div id="xrayCreated"></div>`);\n $(\'view\').innerHTML=head+form+card(\'Daftar Akun Xray\',`<div id="xrayList" class="empty">Memuat daftar akun...</div>`);\n await loadXray();\n}\nasync function createXray(){const name=$(\'xrayName\').value.trim();if(!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,23}$/.test(name))return toast(\'Nama 1–24 karakter: huruf, angka, _ atau -\',\'error\');try{const d=await api(\'/api/xray/add\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({name})});if(d.status===\'success\'){toast(d.message,\'success\');showXray(d.account)}else toast(d.message,\'error\')}catch(e){toast(e.message,\'error\')}}\nfunction makeXrayLinks(a){\n const host=(serverInfo?.domain||stats?.domain||location.hostname).replace(/^https?:\\/\\//,\'\').split(\'/\')[0];\n const sni=host;\n const rows=[[\'VLESS\',\'WebSocket\',\'vless\',\'ws\',\'/vless\'],[\'VMess\',\'WebSocket\',\'vmess\',\'ws\',\'/vmess\'],[\'Trojan\',\'WebSocket\',\'trojan\',\'ws\',\'/trojan\']];\n const variants=[{port:\'443\',security:\'tls\',label:\'TLS ON\'},{port:\'80\',security:\'none\',label:\'TLS OFF\'}];\n return rows.flatMap(([p,t,scheme,net,path])=>variants.map(v=>{\n  let link;\n  if(scheme===\'vmess\'){\n   const o={v:\'2\',ps:`${a.name}-${p}-${t}-${v.port}`,add:host,port:v.port,id:a.id,aid:\'0\',scy:\'auto\',net,type:net===\'xhttp\'?\'auto\':\'none\',host,path,tls:v.security===\'tls\'?\'tls\':\'\',...(v.security===\'tls\'?{sni}:{}),...(net===\'xhttp\'?{mode:\'auto\'}:{})};\n   link=\'vmess://\'+btoa(unescape(encodeURIComponent(JSON.stringify(o))));\n  }else{\n   const q=new URLSearchParams({security:v.security,type:net,host,path});\n   if(v.security===\'tls\')q.set(\'sni\',sni);\n   if(scheme===\'vless\')q.set(\'encryption\',\'none\');\n   if(net===\'xhttp\')q.set(\'mode\',\'auto\');\n   link=`${scheme}://${a.id}@${host}:${v.port}?${q}#${encodeURIComponent(`${a.name}-${p}-${t}-${v.label}`)}`;\n  }\n  return {p,t,path,port:v.port,security:v.label,link};\n }));\n}\nfunction showXray(id){const a=(id && typeof id===\'object\')?id:xrayAccounts.find(x=>x.id===id);if(!a)return;const links=makeXrayLinks(a);$(\'xrayCreated\').innerHTML=`<section class="card"><h3>Akun Berhasil Dibuat: ${esc(a.name)}</h3><p class="small muted">UUID / Password Trojan</p><div class="row"><input readonly value="${esc(a.id)}"><button class="btn tonal" onclick="copyText(\'${esc(a.id)}\')">Salin UUID</button></div>${[\'VLESS\',\'VMess\',\'Trojan\'].map(p=>`<h3 class="mt">${p}</h3>${links.filter(x=>x.p===p).map(x=>`<div class="linkbox"><div class="linktop"><b>${x.t} · ${x.path} · Port ${x.port} · ${x.security}</b><button class="btn textbtn" onclick="copyText(${JSON.stringify(x.link).replace(/</g,\'\\\\u003c\')})">Salin</button></div><div class="mono small muted">${esc(x.link)}</div></div>`).join(\'\')}`).join(\'\')}</section>`;window.scrollTo({top:0,behavior:\'smooth\'})}\nasync function deleteXray(id){if(!confirm(\'Hapus akun Xray ini?\'))return;try{const d=await api(\'/api/xray/delete\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({id})});toast(d.message,d.status===\'success\'?\'success\':\'error\');if(d.status===\'success\')loadXray()}catch(e){toast(e.message,\'error\')}}\nasync function saveSettings(){if(!adminToken){openModal(\'login\');toast(\'Login admin diperlukan\',\'error\');return}const val=(sel,custom)=>$(sel).value===\'custom\'?$(custom).value:$(sel).value;const p=val(\'sshPort\',\'sshPortCustom\')||22,k=val(\'keepAlive\',\'keepCustom\')||15000,b=val(\'maxBuffer\',\'bufferCustom\')||32768;try{const a=await api(`/api/set-wsproxy?pass=${encodeURIComponent(adminToken)}&ssh_port=${p}&keep_alive=${k}&max_buffer=${b}`);const c=await api(`/api/set-system?pass=${encodeURIComponent(adminToken)}&banner=${encodeURIComponent($(\'banner\').value)}&enable_bbr=${$(\'bbr\').value}&udpgw_port=${$(\'udpgw\').value}&udpgw_max_clients=${$(\'udpgwMax\').value}`);toast(a.message+\' \'+c.message,a.status===\'success\'&&c.status===\'success\'?\'success\':\'error\');loadStats()}catch(e){toast(e.message,\'error\')}}\nasync function loadInfo(){try{serverInfo=await api(\'/__info\')}catch{serverInfo=null}}\nasync function copyText(text){try{await navigator.clipboard.writeText(String(text));toast(\'Berhasil disalin\',\'success\')}catch{const t=document.createElement(\'textarea\');t.value=text;document.body.append(t);t.select();document.execCommand(\'copy\');t.remove();toast(\'Berhasil disalin\',\'success\')}}\n(async()=>{await loadInfo();await loadStats();render();setInterval(loadStats,300000)})();\n</script></body></html>\n'
DOMAIN = os.environ.get("DOMAIN", "").strip()
LOCK = threading.RLock()

def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def load_xray_users():
    return read_json(XRAY_USERS_PATH, [])

def save_xray_users(users):
    write_json(XRAY_USERS_PATH, users)
    cfg = read_json(CONFIG_PATH, {})
    for inbound in cfg.get("inbounds", []):
        protocol = inbound.get("protocol")
        clients = [{"id": u["id"], "email": u["name"]} for u in users]
        if protocol == "trojan":
            clients = [{"password": u["id"], "email": u["name"]} for u in users]
        if isinstance(inbound.get("settings"), dict):
            inbound["settings"]["clients"] = clients
    write_json(CONFIG_PATH, cfg)
    subprocess.run(["pkill", "-x", "xray"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_domain(handler=None):
    if DOMAIN:
        return DOMAIN
    if handler:
        host = handler.headers.get("Host", "").split(":")[0].strip().lower()
        if host and host not in ("localhost", "127.0.0.1") and not host.endswith(".railway.app"):
            return host
    return ""

def ssh_users():
    os.makedirs(SSH_DATA_DIR, exist_ok=True)
    data = read_json(SSH_USERS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    return data

def make_vmess(uid, domain, port, network, path, tls, label):
    obj = {"v":"2","ps":label,"add":domain,"port":str(port),"id":uid,"aid":"0",
           "scy":"auto","net":network,"type":"auto" if network=="xhttp" else "none",
           "host":domain,"path":path,"tls":"tls" if tls else "",
           "sni":domain if tls else ""}
    return "vmess://" + base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()

def system_stats():
    def cmd(args, fallback="--"):
        try:
            return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return fallback
    cpu = cmd(["sh", "-c", "grep -m1 model\\ name /proc/cpuinfo | cut -d: -f2- | sed 's/^ //'"], "Unknown CPU")
    mem_used = cmd(["sh", "-c", "free -h | awk '/Mem:/ {print $3}'"])
    mem_total = cmd(["sh", "-c", "free -h | awk '/Mem:/ {print $2}'"])
    disk = cmd(["sh", "-c", "df -h / | tail -1 | awk '{print $3, \"/\", $2, \"(\", $5, \"used)\"}'"])
    try:
        seconds = int(float(open("/proc/uptime").read().split()[0]))
        uptime = f"{seconds//86400}d {(seconds%86400)//3600}h {(seconds%3600)//60}m"
    except Exception:
        uptime = "--"
    online = cmd(["sh", "-c", "who | wc -l"], "0")
    return {"status":"ONLINE","cpu_model":cpu,"ram_used":mem_used,"ram_total":mem_total,
            "disk_usage":disk,"uptime":uptime,"ssh_online":online,
            "user_list_details":"Live sessions (who)"}

class Handler(BaseHTTPRequestHandler):
    server_version = "ServerPanel/2.0"
    def log_message(self, *_):
        pass
    def send_json(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)
    def body_json(self):
        length = min(int(self.headers.get("Content-Length", "0") or 0), 65536)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            raise ValueError("JSON request tidak valid")
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            raw = UI_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        elif path == "/__info":
            self.send_json(200, {"domain":get_domain(self)})
        elif path == "/api/stats":
            stats = system_stats()
            stats["domain"] = get_domain(self)
            stats["ws_proxy_cfg"] = {"sshPort":22}
            stats["sys_settings"] = {"enable_bbr":"false","udpgw_port":"7300"}
            self.send_json(200, stats)
        elif path == "/api/list":
            users = ssh_users()
            result = []
            for name, meta in sorted(users.items()):
                result.append({"username":name,"created_at":meta.get("created",""),
                               "expired":meta.get("expired","never")})
            self.send_json(200, {"status":"success","users":result})
        elif path == "/api/xray/list":
            self.send_json(200, {"status":"success","accounts":load_xray_users()})
        else:
            self.send_json(404, {"status":"error","message":"Endpoint tidak ditemukan"})
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.body_json()
            if path == "/api/add":
                username = str(data.get("user","")).strip()
                password = str(data.get("pass",""))
                if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username):
                    return self.send_json(400, {"status":"error","message":"Username harus 1-32 karakter: huruf kecil, angka, _ atau -"})
                if len(password) < 8 or len(password) > 128 or "\n" in password or ":" in password:
                    return self.send_json(400, {"status":"error","message":"Password minimal 8 karakter dan maksimal 128 karakter"})
                with LOCK:
                    if username in ssh_users() or subprocess.run(["id", username], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                        return self.send_json(409, {"status":"error","message":"Username sudah digunakan"})
                    created_result = subprocess.run(
                        ["python3", "/usr/local/bin/addssh", username, password, "0"],
                        capture_output=True, text=True, env={**os.environ, "TERM":"xterm"}
                    )
                    if created_result.returncode:
                        raise RuntimeError((created_result.stderr or created_result.stdout or "Gagal membuat akun SSH").strip())
                    users = ssh_users()
                    created = users.get(username, {}).get("created", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                domain = get_domain(self) or self.headers.get("Host","").split(":")[0] or "SERVER"
                detail = f"Host: {domain}\nUsername: {username}\nPassword: {password}\nSSH Port: 22\nSSH WebSocket: {os.environ.get('PORT','8080')}\nTLS: {os.environ.get('PORT','8080')}\nCreated: {created}"
                return self.send_json(200, {"status":"success","message":detail})
            if path == "/api/delete":
                username = str(data.get("user","")).strip()
                if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username):
                    return self.send_json(400, {"status":"error","message":"Username tidak valid"})
                with LOCK:
                    users = ssh_users()
                    if username not in users:
                        return self.send_json(404, {"status":"error","message":"Akun SSH tidak ditemukan"})
                    result = subprocess.run(
                        ["python3", "/usr/local/bin/delssh", username, "--yes"],
                        capture_output=True, text=True, env={**os.environ, "TERM":"xterm"}
                    )
                    if result.returncode:
                        return self.send_json(500, {"status":"error","message":(result.stderr or result.stdout or "Gagal menghapus akun").strip()})
                    users.pop(username, None)
                    write_json(SSH_USERS_PATH, users)
                return self.send_json(200, {"status":"success","message":"Akun SSH berhasil dihapus"})
            if path == "/api/xray/add":
                name = str(data.get("name","")).strip()
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,23}", name):
                    return self.send_json(400, {"status":"error","message":"Nama akun tidak valid"})
                with LOCK:
                    users = load_xray_users()
                    if any(u.get("name") == name for u in users):
                        return self.send_json(409, {"status":"error","message":"Nama akun sudah digunakan"})
                    account = {"id":str(uuid.uuid4()),"name":name,"domain":get_domain(self)}
                    users.append(account)
                    save_xray_users(users)
                return self.send_json(200, {"status":"success","message":"Akun Xray berhasil dibuat","account":account})
            if path == "/api/xray/delete":
                uid = str(data.get("id",""))
                with LOCK:
                    users = load_xray_users()
                    new_users = [u for u in users if u.get("id") != uid]
                    if len(new_users) == len(users):
                        return self.send_json(404, {"status":"error","message":"Akun Xray tidak ditemukan"})
                    save_xray_users(new_users)
                return self.send_json(200, {"status":"success","message":"Akun Xray berhasil dihapus"})
            return self.send_json(404, {"status":"error","message":"Endpoint tidak ditemukan"})
        except subprocess.CalledProcessError as e:
            return self.send_json(500, {"status":"error","message":(e.stderr or str(e)).strip()})
        except Exception as e:
            return self.send_json(400, {"status":"error","message":str(e)})

if __name__ == "__main__":
    os.makedirs(SSH_DATA_DIR, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", 2053), Handler).serve_forever()
