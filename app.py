#!/usr/bin/env python3
"""Combined web panel + SSH/Xray account API."""

import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APP_PORT", "2053"))          # <-- default 2053
SSH_DATA_DIR = os.environ.get("SSH_DATA_DIR", "/etc/ssh-sni")
SSH_USERS_FILE = os.path.join(SSH_DATA_DIR, "users.json")
XRAY_USERS_FILE = "/app/users.json"
XRAY_CONFIG_FILE = "/app/config.json"
XRAY_DOMAIN = os.environ.get("XRAY_DOMAIN", "").strip()
SSH_DOMAIN = os.environ.get("SSH_DOMAIN", "").strip()
XRAY_PROXY_PORT = int(os.environ.get("XRAY_PROXY_PORT", "8080"))
SSH_PUBLIC_PORT = int(os.environ.get("SSH_PORT", "8081"))
SSH_UDPGW_PORT = int(os.environ.get("SSH_UDPGW_PORT", os.environ.get("UDPGW_PORT", "7300")))
ENABLE_BBR = os.environ.get("ENABLE_BBR", "false").lower() == "true"

XRAY_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,23}")


# ---------------------------------------------------------------------------
# Embedded Web UI
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#6750a4"><title>Server Panel • Material 3</title>
<style>
:root{color-scheme:light;--primary:#6750a4;--on-primary:#fff;--primary-container:#eaddff;--on-primary-container:#21005d;--secondary:#625b71;--surface:#fffbfe;--surface-low:#f7f2fa;--surface-high:#ece6f0;--surface-highest:#e6e0e9;--outline:#79747e;--outline-soft:#cac4d0;--text:#1d1b20;--muted:#49454f;--success:#386a20;--success-bg:#d7f5c4;--error:#b3261e;--radius:18px;--shadow:0 1px 3px #0001,0 8px 24px #0000000a}
*{box-sizing:border-box}body{margin:0;background:var(--surface-low);color:var(--text);font:14px/1.5 Inter,Roboto,"Segoe UI",sans-serif}button,input,select,textarea{font:inherit}button{cursor:pointer}.app{min-height:100vh}.sidebar{position:fixed;inset:0 auto 0 0;width:264px;background:var(--surface);border-right:1px solid var(--outline-soft);padding:18px 14px;display:flex;flex-direction:column;z-index:5;transition:transform .25s}.brand{display:flex;align-items:center;gap:12px;padding:8px 10px 22px;font-weight:750;font-size:17px}.brandmark{width:40px;height:40px;border-radius:14px;background:var(--primary);color:white;display:grid;place-items:center;font-size:21px}.navlabel{font-size:11px;letter-spacing:1.1px;color:var(--muted);font-weight:700;padding:10px 14px}.nav button{width:100%;border:0;background:transparent;color:var(--muted);padding:12px 16px;border-radius:30px;text-align:left;display:flex;gap:14px;align-items:center;margin:3px 0;font-weight:600}.nav button.active{background:var(--primary-container);color:var(--on-primary-container)}.nav button:hover{background:var(--surface-high)}.nav .ico{width:22px;text-align:center;font-size:18px}.sidefoot{margin-top:auto;border-top:1px solid var(--outline-soft);padding:16px 8px 4px}.status{display:inline-flex;align-items:center;gap:8px;border-radius:30px;padding:7px 12px;background:var(--surface-high);font-size:12px;font-weight:650}.dot{width:8px;height:8px;background:#2e7d32;border-radius:50%;box-shadow:0 0 0 4px #2e7d3218}.main{margin-left:264px;min-width:0}.topbar{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 30px;background:#fffbfeeF;border-bottom:1px solid #e6e0e9;position:sticky;top:0;z-index:3;backdrop-filter:blur(12px)}.top-left{display:flex;align-items:center;gap:14px}.topbar h2{font-size:16px;margin:0}.top-actions{display:flex;gap:10px;align-items:center}.content{max-width:1100px;margin:auto;padding:28px 30px 60px}.page-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:22px;gap:12px}.page-head h1{font-size:26px;letter-spacing:-.5px;margin:0 0 4px}.page-head p{color:var(--muted);margin:0}.card{background:var(--surface);border:1px solid #e7e1e9;border-radius:var(--radius);padding:20px;margin-bottom:16px;box-shadow:var(--shadow)}.card h3{font-size:16px;margin:0 0 15px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.grid.five{grid-template-columns:repeat(5,minmax(0,1fr))}.stat{padding:17px;border-radius:16px;background:var(--surface);border:1px solid #e7e1e9;min-width:0}.stat .k{color:var(--muted);font-size:11px;font-weight:750;letter-spacing:.7px;text-transform:uppercase}.stat .v{font-size:17px;font-weight:750;margin-top:8px;overflow-wrap:anywhere}.stat .sub{font-size:12px;color:var(--muted);margin-top:3px}.field{display:flex;flex-direction:column;gap:7px;margin-bottom:14px;min-width:0}.field label{font-size:12px;font-weight:700;color:var(--muted)}.field input,.field select,.field textarea{width:100%;border:1px solid var(--outline);background:var(--surface);border-radius:10px;padding:12px 13px;color:var(--text);outline:none;min-width:0}.field input:focus,.field select:focus,.field textarea:focus{border:2px solid var(--primary);padding:11px 12px}.row{display:flex;gap:12px;align-items:end}.row>*{flex:1;min-width:0}.btn{border:0;border-radius:28px;padding:11px 18px;min-height:42px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;gap:8px;transition:.15s}.btn:disabled{opacity:.55;cursor:not-allowed}.filled{background:var(--primary);color:white}.filled:hover{box-shadow:0 2px 8px #6750a455}.tonal{background:var(--primary-container);color:var(--on-primary-container)}.outlined{background:transparent;color:var(--primary);border:1px solid var(--outline-soft)}.danger{background:#f9dedc;color:#410e0b}.textbtn{background:transparent;color:var(--primary);padding:8px 12px}.wide{width:100%}.chip{display:inline-flex;align-items:center;border-radius:30px;background:var(--surface-high);padding:5px 10px;font-size:11px;font-weight:700;color:var(--muted)}.chip.good{background:var(--success-bg);color:var(--success)}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:460px}th,td{text-align:left;padding:12px 10px;border-bottom:1px solid #e7e1e9}th{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.6px}td{font-size:13px}.mono,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}.muted{color:var(--muted)}.output{background:#f3eff7;border-radius:12px;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:330px;overflow:auto;font-size:12px}.notice{background:#f1ebfa;color:#403653;padding:13px 15px;border-radius:13px;font-size:12px}.hidden{display:none!important}.hamb{display:none}.overlay{display:none}.toast{position:fixed;right:20px;bottom:20px;z-index:20;background:#302d35;color:white;padding:13px 18px;border-radius:14px;box-shadow:var(--shadow);max-width:min(90vw,420px)}.toast.error{background:#b3261e}.toast.success{background:#286b35}.modal{position:fixed;inset:0;background:#17131d77;z-index:15;display:grid;place-items:center;padding:20px}.modalbox{background:var(--surface);border-radius:24px;padding:24px;width:min(100%,420px);box-shadow:var(--shadow)}.modalbox h3{margin:0 0 8px}.bar{height:8px;border-radius:20px;background:var(--surface-high);overflow:hidden;margin-top:9px}.bar span{display:block;height:100%;background:var(--primary);border-radius:20px}.traffic{display:grid;grid-template-columns:1fr 1fr;gap:12px}.traffic>div{background:var(--surface-high);border-radius:14px;padding:14px}.genbuttons{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.genbuttons button{font-size:12px;padding:12px 6px}.linkbox{background:var(--surface-high);padding:12px;border-radius:12px;margin:8px 0}.linktop{display:flex;justify-content:space-between;gap:8px;align-items:center}.small{font-size:11px}.mt{margin-top:14px}.right{text-align:right}.empty{text-align:center;color:var(--muted);padding:25px}.mobile-only{display:none}
@media(max-width:1000px){.grid.five{grid-template-columns:repeat(2,minmax(0,1fr))}.grid.five .stat:first-child{grid-column:span 2}}
@media(max-width:760px){.sidebar{transform:translateX(-105%);width:285px;box-shadow:var(--shadow)}.sidebar.open{transform:translateX(0)}.overlay.show{display:block;position:fixed;inset:0;background:#17131d66;z-index:4}.main{margin-left:0}.topbar{height:62px;padding:0 16px}.content{padding:22px 15px 45px}.hamb,.mobile-only{display:inline-flex}.page-head h1{font-size:23px}.grid.five{grid-template-columns:repeat(2,minmax(0,1fr))}.row{flex-direction:column;align-items:stretch;gap:0}.row .btn{width:100%}.top-actions .admin-label{display:none}}
@media(max-width:430px){.card{padding:16px}.stat{padding:14px}.stat .v{font-size:15px}.genbuttons{gap:6px}.genbuttons button{font-size:10px;padding:11px 3px}.page-head{flex-direction:column}.traffic{gap:8px}}
</style></head>
<body>
<div class="app">
<div class="overlay" id="overlay" onclick="toggleNav(false)"></div>
<aside class="sidebar" id="sidebar"><div class="brand"><div class="brandmark">✦</div><div>SERVER PANEL<div class="muted small" style="font-weight:500">Management Console</div></div></div>
<div class="navlabel">MENU UTAMA</div><nav class="nav">
<button data-page="dashboard" class="active" onclick="navigate('dashboard')"><span class="ico">▦</span>Dashboard</button>
<button data-page="ssh" onclick="navigate('ssh')"><span class="ico">♙</span>Buat Akun SSH</button>
<button data-page="xray" onclick="navigate('xray')"><span class="ico">◉</span>Buat Akun Xray</button>
</nav><div class="sidefoot"><div class="status" id="sideStatus">● Public Self-Service</div></div></aside>
<div class="main"><header class="topbar"><div class="top-left"><button class="btn textbtn hamb" onclick="toggleNav(true)">☰</button><h2 id="topTitle">Dashboard</h2></div><div class="top-actions"><span class="chip good" id="serverState">● Connecting</span></div></header>
<main class="content" id="view"></main></div></div>
<div id="toast" class="toast hidden"></div>
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
<script>
'use strict';
const $=id=>document.getElementById(id);
let stats=null,serverInfo=null,currentPage='dashboard',sshUsers=[],xrayAccounts=[],detailText='';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function toast(msg,type=''){const el=$('toast');el.textContent=msg;el.className='toast '+type;clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>el.classList.add('hidden'),3500)}
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
 SSH Domain : ${serverInfo?.ssh_domain||'-'}
===========================`;
  openDetail('Detail Akun SSH',text);
}

function showXrayDetail(i){
  const a=xrayAccounts[i];if(!a)return;
  const links=makeXrayLinks(a);
  const protocols=['VLESS','VMESS','TROJAN'];
  let text=`Nama   : ${a.name}\nUUID   : ${a.id}\n\n`;
  protocols.forEach(p=>{
    text+=`===== ${p} =====\n`;
    links.filter(x=>x.p===p).forEach(x=>{
      text+=`[${x.t} · ${x.path} · Port ${x.port} · ${x.security}]\n${x.link}\n\n`;
    });
  });
  openDetail('Akun Xray: '+a.name,text);
}

// -------------------- Stats / dashboard --------------------
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

async function refreshDashboard(){
  try{
    const d=await api('/api/stats');
    stats=d;
    if(currentPage!=='dashboard')return;
    const c=document.getElementById('sshOnlineCount');
    const b=document.getElementById('sshOnlineBrief');
    const box=document.getElementById('onlineCardInner');
    if(c)c.textContent=d.ssh_online||'0';
    if(b)b.textContent=(d.online_users||[]).length?`${(d.online_users||[]).length} koneksi aktif`:'Tidak ada koneksi';
    if(box)box.innerHTML=renderOnlineTable(d.online_users||[]);
  }catch(e){}
}

function render(){
  if(currentPage==='dashboard')renderDashboard();
  if(currentPage==='ssh')renderSSH();
  if(currentPage==='xray')renderXray();
}

function renderOnlineTable(users){
  users=users||[];
  if(!users.length)return '<div class="empty">Tidak ada koneksi SSH aktif saat ini.</div>';
  return `<div class="tablewrap"><table>
    <thead><tr><th>User</th><th>IP Address</th><th>TTY</th><th>Login</th><th>Idle</th></tr></thead>
    <tbody>${users.map(u=>`<tr>
      <td><b>${esc(u.user)}</b></td>
      <td class="mono">${esc(u.ip)}</td>
      <td class="mono small">${esc(u.tty||'-')}</td>
      <td class="small">${esc(u.since||'-')}</td>
      <td class="small">${esc(u.idle||'-')}</td>
    </tr>`).join('')}</tbody>
  </table></div>`;
}

function renderDashboard(){
  const s=stats||{};
  const online=s.online_users||[];
  const values=[
    ['CPU MODEL',s.cpu_model||'Memuat...','Processor server'],
    ['RAM USED / TOTAL',(s.ram_used||'--')+' / '+(s.ram_total||'--'),'Penggunaan memori'],
    ['DISK USAGE',s.disk_usage||'--','Storage root'],
    ['SERVER UPTIME',s.uptime||'--','Waktu aktif'],
  ];
  const statsHTML=values.map(v=>`<div class="stat"><div class="k">${v[0]}</div><div class="v">${esc(v[1])}</div><div class="sub">${esc(v[2])}</div></div>`).join('')
    +`<div class="stat">
       <div class="k">SSH ONLINE</div>
       <div class="v"><span id="sshOnlineCount">${esc(s.ssh_online||'0')}</span> Active</div>
       <div class="sub" id="sshOnlineBrief">${online.length?`${online.length} koneksi aktif`:'Tidak ada koneksi'}</div>
     </div>`;

  $('view').innerHTML=`
    <div class="page-head">
      <div><h1>Dashboard Server</h1><p>Ringkasan status dan performa server kamu.</p></div>
      <span class="chip good">● Services Managed</span>
    </div>
    <div class="grid five">${statsHTML}</div>
    ${card('SSH Online Users <button class="btn textbtn" style="float:right;font-size:12px;min-height:auto;padding:4px 10px" onclick="refreshDashboard()">↻ Refresh</button>',
      `<div id="onlineCardInner">${renderOnlineTable(online)}</div>`)}
    ${card('Traffic Metrics',`<div class="traffic">
      <div><div class="muted small">↓ DOWNLOAD</div><b style="font-size:22px">128.4 MB</b>
        <div class="sub">Kecepatan simulasi: <span>${(100+Math.random()*100).toFixed(1)}</span> KB/s</div></div>
      <div><div class="muted small">↑ UPLOAD</div><b style="font-size:22px">96.2 MB</b>
        <div class="sub">Kecepatan simulasi: <span>${(100+Math.random()*150).toFixed(2)}</span> KB/s</div></div>
    </div><div class="mt"><div class="muted small">NETWORK ACTIVITY · LIVE VISUAL</div>
      <div style="height:65px;display:flex;gap:3px;align-items:end;margin-top:8px">
        ${Array.from({length:35},()=>`<i style="display:block;flex:1;height:${10+Math.random()*90}%;border-radius:4px 4px 0 0;background:#8b78bd"></i>`).join('')}
      </div></div>`)}
    ${card('Info Pengaturan Server',`<div class="grid">
      ${[['SSH Backend Port',s.ws_proxy_cfg?.sshPort||22],['UI Panel',s.ui_port||2053],
         ['Xray Proxy',s.xray_proxy_port||8080],['SSH Mux',s.ssh_port||8081],
         ['Xray','data/config.json'],['BBR',s.sys_settings?.enable_bbr==='true'?'ON':'OFF'],
         ['SSH UDPGW (TCP)',s.sys_settings?.ssh_udpgw_port||7300]]
        .map(x=>`<div><span class="muted">${x[0]}</span><br><b>${esc(x[1])}</b></div>`).join('')}
    </div>`)}
    ${card('Domain & Service Paths',`
      <div class="field"><label>Domain Xray (XRAY_DOMAIN)</label>
        <div class="row"><input readonly value="${esc(s.xray_domain||s.domain||'Belum diatur di ENV')}">
        <button class="btn tonal" onclick="copyText(this.dataset.copy)" data-copy="${esc(s.xray_domain||s.domain||'')}">Salin</button></div></div>
      <div class="field"><label>Domain SSH (SSH_DOMAIN)</label>
        <div class="row"><input readonly value="${esc(s.ssh_domain||'Belum diatur di ENV')}">
        <button class="btn tonal" onclick="copyText(this.dataset.copy)" data-copy="${esc(s.ssh_domain||'')}">Salin</button></div></div>`)}`;
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
    <div id="sshResult"></div>
    <p class="muted small">Akun menggunakan Dropbear. Domain SSH: <b>${esc(serverInfo?.ssh_domain||'Atur SSH_DOMAIN di ENV')}</b> · Port mux: <b>${esc(serverInfo?.ssh_port||8081)}</b>.</p>`);
  $('view').innerHTML=head+form+card('Daftar Akun SSH',`<div id="sshList" class="empty">Memuat daftar akun...</div>`);
  await loadSSH();
}

async function createSSH(){
  const u=$('sshUser').value.trim(),p=$('sshPass').value;
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
  const form=card('Tambah Akun Xray',`<p class="muted small">Satu akun akan ditambahkan ke <b>semua inbound</b> (VLESS/VMess/Trojan × XHTTP/HTTPUpgrade/WS) di config.json.</p>
    <div class="row"><div class="field"><label>Nama Akun</label><input id="xrayName" placeholder="user01" maxlength="24"></div>
    <button class="btn filled" onclick="createXray()">＋ Buat Akun</button></div>`);
  $('view').innerHTML=head+form+card('Daftar Akun Xray',`<div id="xrayList" class="empty">Memuat daftar akun...</div>`);
  await loadXray();
}

async function createXray(){
  const name=$('xrayName').value.trim();
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
  const host=(serverInfo?.xray_domain||serverInfo?.domain||stats?.domain||location.hostname).replace(/^https?:\/\//,'').split('/')[0];
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

function showXray(id){
  const a=(id&&typeof id==='object')?id:xrayAccounts.find(x=>x.id===id);
  if(!a)return;
  const links=makeXrayLinks(a);
  const protocols=['VLESS','VMESS','TROJAN'];
  let text=`Nama   : ${a.name}\nUUID   : ${a.id}\n\n`;
  protocols.forEach(p=>{
    text+=`===== ${p} =====\n`;
    links.filter(x=>x.p===p).forEach(x=>{text+=`[${x.t} · ${x.path} · Port ${x.port} · ${x.security}]\n${x.link}\n\n`});
  });
  openDetail('Akun Xray: '+a.name,text);
}

// -------------------- Misc --------------------
async function loadInfo(){try{serverInfo=await api('/__info')}catch{serverInfo=null}}
async function copyText(text){
  try{await navigator.clipboard.writeText(String(text));toast('Berhasil disalin','success')}
  catch{const t=document.createElement('textarea');t.value=text;document.body.append(t);t.select();document.execCommand('copy');t.remove();toast('Berhasil disalin','success')}
}

(async()=>{
  await loadInfo();
  await loadStats();
  render();
  setInterval(refreshDashboard,20000);   // live online users (20s)
  setInterval(loadStats,300000);         // full refresh (5min)
})();
</script></body></html>
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


def _pid_user(pid):
    """Username pemilik proses, atau None."""
    try:
        uid = os.stat(f"/proc/{pid}").st_uid
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return None


def _resolve_session_user(pid):
    """Kalau process pemegang socket adalah root (dropbear parent),
    telusuri child process-nya untuk menemukan shell user."""
    uname = _pid_user(pid)
    if uname and uname != "root":
        return uname
    # root dropbear parent — cari child yang dimiliki user non-root
    try:
        children_file = f"/proc/{pid}/task/{pid}/children"
        if os.path.exists(children_file):
            with open(children_file) as f:
                for cp in f.read().split():
                    c_uname = _pid_user(int(cp))
                    if c_uname and c_uname != "root":
                        return c_uname
    except Exception:
        pass
    return uname


def get_online_ssh_users():
    """Gabungan `who -u` + `ss -tnp` (filter sshd/dropbear).

    Returns list of dict: user, ip, tty, since, idle, pid.
    """
    sessions = []
    seen = set()  # (user, ip)

    # 1) who -u : sesi terminal aktif (ip di kolom FROM)
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
            "user": user,
            "ip": ip,
            "tty": tty or "-",
            "since": f"{date} {time_s}",
            "idle": idle or "-",
            "pid": int(pid) if pid else None,
        })

    # 2) ss : koneksi ESTAB milik sshd/dropbear child (owner = user)
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
        if not ip or ip in ("127.0.0.1", "::1"):
            continue
        pid = int(pm.group(1))

        uname = _resolve_session_user(pid)
        if not uname:
            continue
        key = (uname, ip)
        if key in seen:
            continue
        seen.add(key)
        sessions.append({
            "user": uname,
            "ip": ip,
            "tty": "-",
            "since": "active",
            "idle": "-",
            "pid": pid,
        })

    return sessions


# ---------------------------------------------------------------------------
# Domain / stats helpers
# ---------------------------------------------------------------------------

def server_domain(handler):
    if XRAY_DOMAIN:
        return XRAY_DOMAIN
    host = handler.headers.get("Host", "").split(":", 1)[0].strip()
    if host and host not in ("localhost", "127.0.0.1") and not host.endswith(".railway.app"):
        return host
    return ""


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
        "domain": server_domain(handler),
        "xray_domain": XRAY_DOMAIN or server_domain(handler),
        "ssh_domain": SSH_DOMAIN,
        "ui_port": PORT,
        "xray_proxy_port": XRAY_PROXY_PORT,
        "ssh_port": SSH_PUBLIC_PORT,
        "ws_proxy_cfg": {"sshPort": 22},
        "sys_settings": {
            "enable_bbr": "true" if ENABLE_BBR else "false",
            "ssh_udpgw_port": SSH_UDPGW_PORT,
        },
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
            elif path == "/api/online":
                self.send_json({"status": "success", "online_users": get_online_ssh_users()})
            elif path == "/__info":
                self.send_json({
                    "domain": server_domain(self),
                    "xray_domain": XRAY_DOMAIN or server_domain(self),
                    "ssh_domain": SSH_DOMAIN,
                    "ui_port": PORT,
                    "xray_proxy_port": XRAY_PROXY_PORT,
                    "ssh_port": SSH_PUBLIC_PORT,
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
                user = str(data.get("user", "")).strip()
                password = str(data.get("pass", ""))
                account = add_ssh_user(user, password)
                msg = (
                    "===========================\n"
                    f" Username   : {account['username']}\n"
                    f" Password   : {account['password']}\n"
                    f" Dibuat     : {account['created_at']}\n"
                    f" SSH Domain : {SSH_DOMAIN}\n"
                    "==========================="
                )
                self.send_json({"status": "success", "message": msg, "user": account})

            elif path == "/api/delete":
                user = str(data.get("user", "")).strip()
                delete_ssh_user(user)
                self.send_json({"status": "success",
                                "message": f"Akun SSH {user} berhasil dihapus."})

            elif path == "/api/xray/add":
                name = str(data.get("name", "")).strip()
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
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()