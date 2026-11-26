#!/usr/bin/env node
'use strict';

const http = require('http');
const os = require('os');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync, exec } = require('child_process');

const DATA_DIR = process.env.DATA_DIR || process.env.FILE_PATH || path.join(__dirname, 'data');
const PORT = Number(process.env.PANEL_PORT || 3000);
const DB_FILE = path.join(DATA_DIR, 'ssh_accounts.json');
const XRAY_DB_FILE = path.join(DATA_DIR, 'xray_accounts.json');
const XRAY_CONFIG_FILE = process.env.XRAY_CONFIG || path.join(DATA_DIR, 'config.json');
const ADMIN_FILE = '/tmp/admin_pass.txt';
const WS_FILE = '/tmp/ws_proxy_config.json';
const SYS_FILE = '/tmp/system_config.json';
const UUID_FILE = path.join(DATA_DIR, 'uuid.txt');
const RESERVED = new Set(['root','daemon','bin','sys','sync','games','man','lp','mail','news','uucp','proxy','www-data','backup','list','irc','gnats','nobody','ubuntu','sshd','dropbear','stunnel']);

fs.mkdirSync(DATA_DIR, { recursive: true });

function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { return fallback; }
}
function writeJson(file, value) {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2), { mode: 0o600 });
  fs.renameSync(tmp, file);
}
function loadDb() { return readJson(DB_FILE, {}); }
function saveDb(db) { writeJson(DB_FILE, db); }
function run(command, args, options = {}) {
  return execFileSync(command, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], ...options });
}
function linuxUid(username) {
  try { return Number.parseInt(run('id', ['-u', username]).trim(), 10); } catch (_) { return null; }
}
function validUsername(value) { return typeof value === 'string' && /^[a-z_][a-z0-9_-]{0,31}$/i.test(value); }
function validPassword(value) { return typeof value === 'string' && value.length > 0 && !/[\r\n:]/.test(value); }
function createLinuxUser(username) { run('useradd', ['-m', '-s', '/bin/bash', '--', username]); }
function setLinuxPassword(username, password) { run('chpasswd', [], { input: `${username}:${password}\n`, stdio: ['pipe', 'ignore', 'pipe'] }); }
function removeLinuxUser(username) {
  try { execFileSync('pkill', ['-9', '-u', username], { stdio: 'ignore' }); } catch (_) {}
  run('userdel', ['-r', '--', username]);
}
function listSsh() {
  const db = loadDb();
  let passwd = '';
  try { passwd = fs.readFileSync('/etc/passwd', 'utf8'); } catch (_) {}
  const users = [];
  for (const line of passwd.split('\n')) {
    if (!line) continue;
    const f = line.split(':');
    const uid = Number.parseInt(f[2], 10);
    const username = f[0];
    if (!Number.isInteger(uid) || uid < 1000 || RESERVED.has(username.toLowerCase())) continue;
    const row = db[username] || {};
    users.push({ username, uid, shell: f[f.length - 1], password: row.password || '-', ip: row.ip_address || 'Unknown', user_agent: row.user_agent || 'Unknown', created_at: row.created_at || null, has_db_entry: !!db[username] });
  }
  users.sort((a,b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
  return { status: 'success', total: users.length, users };
}
function addSsh(username, password, ip, agent) {
  if (!validUsername(username)) return { status: 'error', message: 'Username tidak valid. Gunakan huruf, angka, _ atau -.' };
  if (!validPassword(password)) return { status: 'error', message: 'Password kosong atau mengandung karakter yang tidak didukung.' };
  const db = loadDb();
  if (db[username] || linuxUid(username) !== null) return { status: 'error', message: 'Username sudah digunakan.' };
  let created = false;
  try {
    createLinuxUser(username); created = true;
    setLinuxPassword(username, password);
    db[username] = { password, ip_address: String(ip || 'Unknown').slice(0,255), user_agent: String(agent || 'Unknown').slice(0,1000), created_at: new Date().toISOString() };
    saveDb(db);
    return { status: 'success', username, password, message: `Akun SSH berhasil dibuat\nHost: ${process.env.DOMAIN || 'gunakan domain panel'}\nPort: 80/443\nPath: /ssh-ws\nUsername: ${username}\nPassword: ${password}` };
  } catch (error) {
    if (created) { try { removeLinuxUser(username); } catch (_) {} }
    const detail = error.stderr ? error.stderr.toString().trim() : error.message;
    return { status: 'error', message: `Gagal membuat akun: ${detail}` };
  }
}
function deleteSsh(username) {
  if (!validUsername(username)) return { status: 'error', message: 'Username tidak valid.' };
  const db = loadDb();
  if (!db[username]) return { status: 'error', message: 'Akun tidak ditemukan di database SSH.' };
  try {
    const uid = linuxUid(username);
    if (uid !== null) {
      if (uid < 1000) return { status: 'error', message: 'Akun sistem dilindungi.' };
      removeLinuxUser(username);
    }
    delete db[username]; saveDb(db);
    return { status: 'success', message: `Akun ${username} berhasil dihapus.` };
  } catch (error) { return { status: 'error', message: `Gagal menghapus akun: ${error.message}` }; }
}
function restoreAccounts() {
  const db = loadDb(); let restored = 0, exists = 0; const failures = [];
  for (const [username, entry] of Object.entries(db)) {
    try {
      if (!validUsername(username) || !validPassword(entry.password)) throw new Error('data akun tidak valid');
      let uid = linuxUid(username);
      if (uid === null) { createLinuxUser(username); uid = linuxUid(username); if (uid === null) throw new Error('useradd gagal'); restored++; }
      else { if (uid < 1000) throw new Error('UID sistem dilindungi'); exists++; }
      setLinuxPassword(username, entry.password);
    } catch (error) { failures.push({ username, error: error.message }); }
  }
  return { total: Object.keys(db).length, restored, exists, failures };
}
function validXrayName(value) {
  return typeof value === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,23}$/.test(value);
}
function loadXrayAccounts() {
  const rows = readJson(XRAY_DB_FILE, []);
  return Array.isArray(rows) ? rows : [];
}
function saveXrayAccounts(rows) { writeJson(XRAY_DB_FILE, rows); }
function xrayClientFor(protocol, account) {
  if (protocol === 'trojan') return { password: account.id, email: account.name };
  if (protocol === 'vmess') return { id: account.id, alterId: 0, email: account.name };
  return { id: account.id, email: account.name, level: 0 };
}
function buildXrayConfig(accounts) {
  const config = readJson(XRAY_CONFIG_FILE, null);
  if (!config || !Array.isArray(config.inbounds)) throw new Error('data/config.json tidak valid atau tidak ditemukan');
  let changed = 0;
  for (const inbound of config.inbounds) {
    const protocol = String(inbound.protocol || '').toLowerCase();
    if (!['vless', 'vmess', 'trojan'].includes(protocol)) continue;
    inbound.settings = inbound.settings || {};
    inbound.settings.clients = accounts.map(account => xrayClientFor(protocol, account));
    changed++;
  }
  if (!changed) throw new Error('Tidak ada inbound VLESS, VMess, atau Trojan di konfigurasi Xray');
  return config;
}
function applyXrayAccounts(accounts) {
  const nextConfig = buildXrayConfig(accounts);
  const tmp = `${XRAY_CONFIG_FILE}.${process.pid}.tmp.json`;
  fs.writeFileSync(tmp, JSON.stringify(nextConfig, null, 2), { mode: 0o600 });
  try {
    const xrayBin = process.env.XRAY_BIN || '/usr/local/bin/xray';
    execFileSync(xrayBin, ['run', '-test', '-c', tmp], { stdio: ['ignore', 'pipe', 'pipe'] });
    fs.renameSync(tmp, XRAY_CONFIG_FILE);
  } catch (error) {
    try { fs.unlinkSync(tmp); } catch (_) {}
    const detail = error.stderr ? error.stderr.toString().trim() : error.message;
    throw new Error(`Validasi konfigurasi Xray gagal: ${detail}`);
  }
  try { execFileSync('pkill', ['-x', 'xray'], { stdio: 'ignore' }); } catch (_) {}
}
function migrateXrayAccounts() {
  if (fs.existsSync(XRAY_DB_FILE)) return;
  const config = readJson(XRAY_CONFIG_FILE, null);
  const seen = new Map();
  for (const inbound of (config && config.inbounds) || []) {
    const protocol = String(inbound.protocol || '').toLowerCase();
    if (!['vless', 'vmess', 'trojan'].includes(protocol)) continue;
    for (const client of (inbound.settings && inbound.settings.clients) || []) {
      const id = protocol === 'trojan' ? client.password : client.id;
      if (typeof id === 'string' && id.trim() && !seen.has(id)) {
        seen.set(id, { id, name: `legacy-${seen.size + 1}`, created_at: new Date().toISOString() });
      }
    }
  }
  saveXrayAccounts([...seen.values()]);
}
function addXrayAccount(name) {
  if (!validXrayName(name)) return { status: 'error', message: 'Nama akun harus 1–24 karakter: huruf, angka, _ atau -.' };
  const accounts = loadXrayAccounts();
  if (accounts.some(row => row.name.toLowerCase() === name.toLowerCase())) return { status: 'error', message: 'Nama akun Xray sudah digunakan.' };
  const account = { id: crypto.randomUUID(), name, created_at: new Date().toISOString() };
  const next = [...accounts, account];
  try {
    applyXrayAccounts(next);
    saveXrayAccounts(next);
    return { status: 'success', account, total: next.length, message: `Akun Xray ${name} berhasil dibuat.` };
  } catch (error) { return { status: 'error', message: error.message }; }
}
function deleteXrayAccount(id) {
  if (typeof id !== 'string' || !/^[0-9a-f-]{36}$/i.test(id)) return { status: 'error', message: 'ID akun tidak valid.' };
  const accounts = loadXrayAccounts();
  if (!accounts.some(row => row.id === id)) return { status: 'error', message: 'Akun Xray tidak ditemukan.' };
  const next = accounts.filter(row => row.id !== id);
  try {
    applyXrayAccounts(next);
    saveXrayAccounts(next);
    return { status: 'success', total: next.length, message: 'Akun Xray berhasil dihapus.' };
  } catch (error) { return { status: 'error', message: error.message }; }
}

function getAdminPassword() { try { return fs.readFileSync(ADMIN_FILE, 'utf8').trim() || null; } catch (_) { return process.env.ADMIN_PASSWORD || null; } }
function verifyAdmin(value) { const current = getAdminPassword(); return !!current && value === current; }
function getSettings(file, fallback) { return readJson(file, fallback); }
function json(res, value, status = 200) { res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); }
function text(res, value, status = 200) { res.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end(value); }

const uuid = (() => {
  if (process.env.UUID) return process.env.UUID.trim();
  try { const old = fs.readFileSync(UUID_FILE, 'utf8').trim(); if (old) return old; } catch (_) {}
  const value = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&3|8)).toString(16); });
  fs.writeFileSync(UUID_FILE, value); return value;
})();

function readRequestBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', chunk => {
      raw += chunk;
      if (raw.length > 1024 * 1024) { reject(new Error('Request terlalu besar')); req.destroy(); }
    });
    req.on('end', () => {
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); } catch (_) { reject(new Error('JSON request tidak valid')); }
    });
    req.on('error', reject);
  });
}

const INDEX_FILE = path.join(__dirname, 'index.html');
function serveFrontend(req, res, pathname) {
  if (pathname.startsWith('/api/') || pathname === '/__info' || pathname === '/healthz') return false;
  if (pathname !== '/' && pathname !== '/index.html') return false;
  try {
    const body = fs.readFileSync(INDEX_FILE);
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Content-Length': body.length, 'Cache-Control': 'no-cache' });
    return req.method === 'HEAD' ? res.end() : res.end(body);
  } catch (error) {
    console.error('[UI] index.html tidak dapat dibaca:', error.message);
    res.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('index.html tidak ditemukan.');
    return true;
  }
}

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://localhost');
  const q = u.searchParams;
  const ip = req.headers['cf-connecting-ip'] || req.socket.remoteAddress || 'Unknown';
  const agent = req.headers['user-agent'] || 'Unknown';
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') { res.writeHead(204, { 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type' }); return res.end(); }

  if (u.pathname === '/healthz') return text(res, 'ok\n');
  if (u.pathname === '/__info') return json(res, { uuid, domain: process.env.DOMAIN || req.headers.host || '', paths: { vless: '/vless', vmess: '/vmess', trojan: '/trojan' }, xray_accounts: loadXrayAccounts().length });
  if (u.pathname === '/api/setup-pass') {
    const next = (q.get('pass') || '').trim(); const old = (q.get('old_pass') || '').trim(); const current = getAdminPassword();
    if (current && old !== current) return json(res, { status: 'error', message: 'Password admin lama salah.' });
    if (next.length < 4) return json(res, { status: 'error', message: 'Password minimal 4 karakter.' });
    fs.writeFileSync(ADMIN_FILE, next, { mode: 0o600 }); return json(res, { status: 'success', message: 'Password admin berhasil disimpan.' });
  }
  if (u.pathname === '/api/login') {
    if (!getAdminPassword()) return json(res, { status: 'not_configured', message: 'Password admin belum dibuat.' });
    return json(res, verifyAdmin(q.get('pass')) ? { status: 'success', token: q.get('pass') } : { status: 'error', message: 'Password salah.' });
  }
  if (u.pathname === '/api/xray/list') {
    if (!verifyAdmin(q.get('token'))) return json(res, { status: 'error', message: 'Akses ditolak.' }, 403);
    return json(res, { status: 'success', total: loadXrayAccounts().length, accounts: loadXrayAccounts() });
  }
  if (u.pathname === '/api/xray/add' && req.method === 'POST') {
    readRequestBody(req).then(body => {
      if (!verifyAdmin(body.token)) return json(res, { status: 'error', message: 'Akses ditolak.' }, 403);
      return json(res, addXrayAccount(String(body.name || '').trim()));
    }).catch(error => json(res, { status: 'error', message: error.message }, 400));
    return;
  }
  if (u.pathname === '/api/xray/delete' && req.method === 'POST') {
    readRequestBody(req).then(body => {
      if (!verifyAdmin(body.token)) return json(res, { status: 'error', message: 'Akses ditolak.' }, 403);
      return json(res, deleteXrayAccount(String(body.id || '')));
    }).catch(error => json(res, { status: 'error', message: error.message }, 400));
    return;
  }

  if (u.pathname === '/api/add') return json(res, addSsh(q.get('user') || '', q.get('pass') || '', ip, agent));
  if (u.pathname === '/api/list') return json(res, listSsh());
  if (u.pathname === '/api/delete') {
    if (!verifyAdmin(q.get('token'))) return json(res, { status: 'error', message: 'Akses ditolak.' }, 403);
    return json(res, deleteSsh(q.get('user') || ''));
  }
  if (u.pathname === '/api/set-wsproxy') {
    if (!verifyAdmin(q.get('pass'))) return json(res, { status: 'error', message: 'Akses ditolak.' }, 403);
    const sshPort = Number(q.get('ssh_port') || 22);
    const keepAlive = Number(q.get('keep_alive') || 15000);
    const maxBuffer = Number(q.get('max_buffer') || 32768);
    if (!Number.isInteger(sshPort) || sshPort < 1 || sshPort > 65535) return json(res, { status: 'error', message: 'Port SSH harus 1–65535.' }, 400);
    if (!Number.isInteger(keepAlive) || keepAlive < 1000 || keepAlive > 300000) return json(res, { status: 'error', message: 'KeepAlive harus 1000–300000 ms.' }, 400);
    if (!Number.isInteger(maxBuffer) || maxBuffer < 4096 || maxBuffer > 1048576) return json(res, { status: 'error', message: 'MaxBuffer harus 4096–1048576 byte.' }, 400);
    writeJson(WS_FILE, { sshPort, keepAlive, maxBuffer });
    return json(res, { status: 'success', message: 'WSProxy dan SSH config diterapkan otomatis tanpa restart container.' });
  }
  if (u.pathname === '/api/set-system') {
    if (!verifyAdmin(q.get('pass'))) return json(res, { status: 'error', message: 'Akses ditolak.' }, 403);
    const requestedPort = Number(q.get('udpgw_port') || 7300);
    const requestedClients = Number(q.get('udpgw_max_clients') || 1000);
    if (!Number.isInteger(requestedPort) || requestedPort < 1 || requestedPort > 65535) {
      return json(res, { status: 'error', message: 'Port UDPGW harus 1–65535.' }, 400);
    }
    if (!Number.isInteger(requestedClients) || requestedClients < 1 || requestedClients > 100000) {
      return json(res, { status: 'error', message: 'Max clients UDPGW harus 1–100000.' }, 400);
    }
    const settings = {
      banner: q.get('banner') || '',
      enable_bbr: q.get('enable_bbr') === 'false' ? 'false' : 'true',
      udpgw_port: String(requestedPort),
      udpgw_max_clients: String(requestedClients)
    };
    writeJson(SYS_FILE, settings);
    const defaultBanner = '<p style="text-align:center;"><b>\\n<font color="#800080">─── SERVER PREMIUM ───</font><br>\\n<font color="#8A2BE2">! TERM OF SERVICE !</font><br>\\n<font color="#9370DB">NO MULTI LOGIN / NO TORRENT</font><br>\\n<font color="#8A2BE2">NO SPAM, NO DDOS, NO HACKING</font><br></b>\\n</p>\\n';
    try { fs.writeFileSync('/etc/app_motd', settings.banner || defaultBanner, { mode: 0o644 }); } catch (_) {}
    const kernelCommands = [
      'sysctl -w net.ipv4.tcp_tw_reuse=1',
      'sysctl -w net.ipv4.tcp_fin_timeout=10',
      'sysctl -w net.core.default_qdisc=fq',
      settings.enable_bbr === 'true'
        ? 'sysctl -w net.ipv4.tcp_congestion_control=bbr'
        : 'sysctl -w net.ipv4.tcp_congestion_control=cubic',
      "sysctl -w 'net.ipv4.tcp_rmem=4096 8388608 16777216'",
      "sysctl -w 'net.ipv4.tcp_wmem=4096 8388608 16777216'",
      'sysctl -w net.core.rmem_max=16777216',
      'sysctl -w net.core.wmem_max=16777216',
      'sysctl -w net.core.netdev_max_backlog=50000',
      'sysctl -w net.ipv4.tcp_max_syn_backlog=8192'
    ];
    for (const command of kernelCommands) exec(`${command} >/dev/null 2>&1`);
    return json(res, { status: 'success', message: 'Pengaturan tersimpan. Banner, kernel, dan UDPGW diterapkan otomatis.' });
  }
  if (u.pathname === '/api/stats') {
    const cpus = os.cpus(); const ws = getSettings(WS_FILE, { sshPort: 22, keepAlive: 15000, maxBuffer: 32768 });
    const sys = getSettings(SYS_FILE, { banner: '', enable_bbr: 'true', udpgw_port: '7300', udpgw_max_clients: '1000' });
    let disk = 'N/A'; try { disk = execFileSync('df', ['-h', '/'], { encoding: 'utf8' }).split('\n')[1].split(/\s+/)[4]; } catch (_) {}
    let active = 0; try { active = Number(execFileSync('sh', ['-c', "ss -tn state established '( sport = :22 )' | tail -n +2 | wc -l"], { encoding: 'utf8' }).trim()) || 0; } catch (_) {}
    return json(res, { pass_configured: !!getAdminPassword(), status: 'ONLINE', domain: process.env.DOMAIN || req.headers.host || '', railway_public: process.env.RAILWAY_PUBLIC_DOMAIN || 'Tidak Aktif', railway_sni: process.env.RAILWAY_TCP_PROXY_DOMAIN ? `${process.env.RAILWAY_TCP_PROXY_DOMAIN}:${process.env.RAILWAY_TCP_PROXY_PORT || ''}` : 'Tidak Aktif', ws_proxy_cfg: ws, sys_settings: sys, cpu_model: cpus[0]?.model || 'Unknown', ram_total: `${(os.totalmem()/1073741824).toFixed(2)} GB`, ram_used: `${((os.totalmem()-os.freemem())/1073741824).toFixed(2)} GB`, disk_usage: disk, uptime: `${(os.uptime()/3600).toFixed(2)} Hours`, ssh_online: String(active), user_list_details: active ? `${active} koneksi SSH aktif` : 'Semua user offline' });
  }
  if (serveFrontend(req, res, u.pathname)) return;
  return text(res, 'Not Found', 404);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[PANEL] UI + API server listening on 127.0.0.1:${PORT}`);
  migrateXrayAccounts();
  const summary = restoreAccounts();
  console.log(`[SSH] Restore: total=${summary.total}, created=${summary.restored}, existing=${summary.exists}, failed=${summary.failures.length}`);
  if (summary.failures.length) console.error('[SSH] Restore failures:', summary.failures);
});
