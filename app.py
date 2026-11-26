#!/usr/bin/env python3
import os,json,uuid,subprocess,urllib.parse, http.server, socketserver, pathlib, shutil, platform, time
BASE=pathlib.Path(__file__).resolve().parent
DATA=pathlib.Path(os.getenv('DATA_DIR') or os.getenv('FILE_PATH') or BASE/'data'); DATA.mkdir(parents=True,exist_ok=True)
PORT=int(os.getenv('PANEL_PORT','3000')); DB=DATA/'ssh_accounts.json'; XDB=DATA/'xray_accounts.json'; XCFG=pathlib.Path(os.getenv('XRAY_CONFIG',DATA/'config.json')); ADMIN=pathlib.Path('/tmp/admin_pass.txt'); WS=pathlib.Path('/tmp/ws_proxy_config.json'); SYS=pathlib.Path('/tmp/system_config.json')
RESERVED=set('root daemon bin sys sync games man lp mail news uucp proxy www-data backup list irc gnats nobody ubuntu sshd dropbear stunnel'.split())
def readj(p,d):
 try:return json.loads(p.read_text())
 except:return d
def writej(p,v):
 p.parent.mkdir(parents=True,exist_ok=True); t=pathlib.Path(str(p)+'.tmp'); t.write_text(json.dumps(v,indent=2)); os.chmod(t,0o600); t.replace(p)
def run(args, input=None): return subprocess.run(args,input=input,text=True,capture_output=True,check=True).stdout
def db():return readj(DB,{})
def xdb():
 v=readj(XDB,[]); return v if isinstance(v,list) else []
def validuser(s):return isinstance(s,str) and __import__('re').fullmatch(r'[a-z_][a-z0-9_-]{0,31}',s,re.I)
def validpass(s):return isinstance(s,str) and bool(s) and not any(c in s for c in '\r\n:')
def uid(s):
 try:return int(run(['id','-u',s]).strip())
 except:return None
def admin():
 try:return ADMIN.read_text().strip() or None
 except:return None
def verify(p):return bool(admin()) and p==admin()
def listssh():
 d=db(); users=[]
 try: lines=pathlib.Path('/etc/passwd').read_text().splitlines()
 except:lines=[]
 for line in lines:
  f=line.split(':'); name=f[0]
  try:u=int(f[2])
  except:continue
  if u<1000 or name.lower() in RESERVED:continue
  r=d.get(name,{ }); users.append(dict(username=name,uid=u,shell=f[-1],password=r.get('password','-'),ip=r.get('ip_address','Unknown'),user_agent=r.get('user_agent','Unknown'),created_at=r.get('created_at'),has_db_entry=name in d))
 users.sort(key=lambda x:x.get('created_at') or '',reverse=True); return {'status':'success','total':len(users),'users':users}
def addssh(user,pw,ip,agent):
 if not validuser(user):return {'status':'error','message':'Username tidak valid. Gunakan huruf, angka, _ atau -.'}
 if not validpass(pw):return {'status':'error','message':'Password kosong atau mengandung karakter yang tidak didukung.'}
 d=db()
 if user in d or uid(user) is not None:return {'status':'error','message':'Username sudah digunakan.'}
 made=False
 try:
  run(['useradd','-m','-s','/bin/bash','--',user]); made=True; run(['chpasswd'],f'{user}:{pw}\n'); d[user]={'password':pw,'ip_address':str(ip)[:255],'user_agent':str(agent)[:1000],'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}; writej(DB,d)
  return {'status':'success','username':user,'password':pw,'message':f'Akun SSH berhasil dibuat\nHost: {os.getenv("DOMAIN","gunakan domain panel")}\nPort: 80/443\nPath: /ssh-ws\nUsername: {user}\nPassword: {pw}'}
 except Exception as e:
  if made: subprocess.run(['userdel','-r','--',user],capture_output=True)
  return {'status':'error','message':'Gagal membuat akun: '+str(e)}
def delssh(user):
 if not validuser(user):return {'status':'error','message':'Username tidak valid.'}
 d=db()
 if user not in d:return {'status':'error','message':'Akun tidak ditemukan di database SSH.'}
 try:
  u=uid(user)
  if u is not None:
   if u<1000:return {'status':'error','message':'Akun sistem dilindungi.'}
   subprocess.run(['pkill','-9','-u',user],capture_output=True); run(['userdel','-r','--',user])
  del d[user];writej(DB,d);return {'status':'success','message':f'Akun {user} berhasil dihapus.'}
 except Exception as e:return {'status':'error','message':'Gagal menghapus akun: '+str(e)}
def xray_apply(rows):
 c=readj(XCFG,None)
 if not isinstance(c,dict) or not isinstance(c.get('inbounds'),list):raise ValueError('data/config.json tidak valid atau tidak ditemukan')
 n=0
 for ib in c['inbounds']:
  p=str(ib.get('protocol','')).lower()
  if p not in ('vless','vmess','trojan'):continue
  ib.setdefault('settings',{})['clients']=[({'password':a['id'],'email':a['name']} if p=='trojan' else ({'id':a['id'],'alterId':0,'email':a['name']} if p=='vmess' else {'id':a['id'],'email':a['name'],'level':0})) for a in rows];n+=1
 if not n:raise ValueError('Tidak ada inbound VLESS, VMess, atau Trojan di konfigurasi Xray')
 tmp=pathlib.Path(str(XCFG)+'.tmp.json');writej(tmp,c)
 try:run([os.getenv('XRAY_BIN','/usr/local/bin/xray'),'run','-test','-c',str(tmp)]);tmp.replace(XCFG)
 except Exception as e:tmp.unlink(missing_ok=True);raise ValueError('Validasi konfigurasi Xray gagal: '+str(e))
 subprocess.run(['pkill','-x','xray'],capture_output=True)
def xadd(name):
 import re
 if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,23}',name):return {'status':'error','message':'Nama akun harus 1–24 karakter: huruf, angka, _ atau -.'}
 rows=xdb()
 if any(a['name'].lower()==name.lower() for a in rows):return {'status':'error','message':'Nama akun Xray sudah digunakan.'}
 a={'id':str(uuid.uuid4()),'name':name,'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}; nxt=rows+[a]
 try:xray_apply(nxt);writej(XDB,nxt);return {'status':'success','account':a,'total':len(nxt),'message':f'Akun Xray {name} berhasil dibuat.'}
 except Exception as e:return {'status':'error','message':str(e)}
def xdel(ident):
 rows=xdb(); nxt=[a for a in rows if a.get('id')!=ident]
 if len(rows)==len(nxt):return {'status':'error','message':'Akun Xray tidak ditemukan.'}
 try:xray_apply(nxt);writej(XDB,nxt);return {'status':'success','total':len(nxt),'message':'Akun Xray berhasil dihapus.'}
 except Exception as e:return {'status':'error','message':str(e)}
def migrate():
 if XDB.exists():return
 c=readj(XCFG,{});seen={}
 for ib in c.get('inbounds',[]):
  p=ib.get('protocol','').lower()
  if p not in ('vless','vmess','trojan'):continue
  for a in ib.get('settings',{}).get('clients',[]):
   ident=a.get('password') if p=='trojan' else a.get('id')
   if ident and ident not in seen:seen[ident]={'id':ident,'name':f'legacy-{len(seen)+1}','created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
 writej(XDB,list(seen.values()))
class Handler(http.server.BaseHTTPRequestHandler):
 def sendj(self,obj,status=200):
  b=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Access-Control-Allow-Origin','*');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def body(self):
  try:return json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'{}')
  except:return {}
 def do_OPTIONS(self):self.send_response(204);self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type');self.end_headers()
 def do_GET(self):
  u=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(u.query);g=lambda k,d='':q.get(k,[d])[0]
  if u.path=='/healthz':return self.sendj({'status':'ok'})
  if u.path=='/__info':return self.sendj({'uuid':(DATA/'uuid.txt').read_text().strip() if (DATA/'uuid.txt').exists() else '', 'domain':os.getenv('DOMAIN',self.headers.get('Host','')),'paths':{'vless':'/vless','vmess':'/vmess','trojan':'/trojan'},'xray_accounts':len(xdb())})
  if u.path=='/api/setup-pass':
   cur=admin(); pw=g('pass').strip()
   if cur and g('old_pass').strip()!=cur:return self.sendj({'status':'error','message':'Password admin lama salah.'})
   if len(pw)<4:return self.sendj({'status':'error','message':'Password minimal 4 karakter.'})
   ADMIN.write_text(pw);os.chmod(ADMIN,0o600);return self.sendj({'status':'success','message':'Password admin berhasil disimpan.'})
  if u.path=='/api/login':
   if not admin():return self.sendj({'status':'not_configured','message':'Password admin belum dibuat.'})
   return self.sendj({'status':'success','token':g('pass')} if verify(g('pass')) else {'status':'error','message':'Password salah.'})
  if u.path=='/api/list':return self.sendj(listssh())
  if u.path=='/api/add':return self.sendj(addssh(g('user'),g('pass'),self.client_address[0],self.headers.get('User-Agent','Unknown')))
  if u.path=='/api/delete':
   if not verify(g('token')):return self.sendj({'status':'error','message':'Akses ditolak.'},403)
   return self.sendj(delssh(g('user')))
  if u.path=='/api/xray/list':
   if not verify(g('token')):return self.sendj({'status':'error','message':'Akses ditolak.'},403)
   return self.sendj({'status':'success','total':len(xdb()),'accounts':xdb()})
  if u.path=='/api/stats':
   try:disk=shutil.disk_usage('/').used/shutil.disk_usage('/').total*100;disk=f'{disk:.0f}%'
   except:disk='N/A'
   try:active=max(0,len(run(['ss','-tn','state','established']).splitlines())-1)
   except:active=0
   mem=readj(pathlib.Path('/proc/meminfo'),{})
   try:
    lines=pathlib.Path('/proc/meminfo').read_text().splitlines(); vals={x.split(':')[0]:int(x.split()[1]) for x in lines}; total=vals['MemTotal']/1048576;used=(vals['MemTotal']-vals.get('MemAvailable',0))/1048576
   except:total=used=0
   return self.sendj({'pass_configured':bool(admin()),'status':'ONLINE','domain':os.getenv('DOMAIN',self.headers.get('Host','')),'railway_public':os.getenv('RAILWAY_PUBLIC_DOMAIN','Tidak Aktif'),'railway_sni':(os.getenv('RAILWAY_TCP_PROXY_DOMAIN','')+':'+os.getenv('RAILWAY_TCP_PROXY_PORT','')) if os.getenv('RAILWAY_TCP_PROXY_DOMAIN') else 'Tidak Aktif','ws_proxy_cfg':readj(WS,{'sshPort':22,'keepAlive':15000,'maxBuffer':32768}),'sys_settings':readj(SYS,{'banner':'','enable_bbr':'true','udpgw_port':'7300','udpgw_max_clients':'1000'}),'cpu_model':platform.processor() or 'Unknown','ram_total':f'{total:.2f} GB','ram_used':f'{used:.2f} GB','disk_usage':disk,'uptime':f'{time.monotonic()/3600:.2f} Hours','ssh_online':str(active),'user_list_details':f'{active} koneksi SSH aktif' if active else 'Semua user offline'})
  if u.path=='/':
   try:b=(BASE/'index.html').read_bytes()
   except:b=b'<h1>index.html tidak ditemukan</h1>'
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();return self.wfile.write(b)
  p=(BASE/u.path.lstrip('/')).resolve()
  if BASE.resolve() in p.parents and p.is_file():
   b=p.read_bytes();self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();return self.wfile.write(b)
  self.sendj({'status':'error','message':'Not Found'},404)
 def do_POST(self):
  u=urllib.parse.urlsplit(self.path);b=self.body()
  if u.path in ('/api/xray/add','/api/xray/delete'):
   if not verify(b.get('token')):return self.sendj({'status':'error','message':'Akses ditolak.'},403)
   return self.sendj(xadd(str(b.get('name','')).strip()) if u.path.endswith('/add') else xdel(str(b.get('id',''))))
  if u.path=='/api/set-wsproxy':
   if not verify(b.get('pass')):return self.sendj({'status':'error','message':'Akses ditolak.'},403)
   try: vals={'sshPort':int(b.get('ssh_port',22)),'keepAlive':int(b.get('keep_alive',15000)),'maxBuffer':int(b.get('max_buffer',32768))};assert 1<=vals['sshPort']<=65535 and 1000<=vals['keepAlive']<=300000 and 4096<=vals['maxBuffer']<=1048576
   except:return self.sendj({'status':'error','message':'Pengaturan WSProxy tidak valid.'},400)
   writej(WS,vals);return self.sendj({'status':'success','message':'WSProxy dan SSH config tersimpan.'})
  if u.path=='/api/set-system':
   if not verify(b.get('pass')):return self.sendj({'status':'error','message':'Akses ditolak.'},403)
   s={'banner':b.get('banner',''),'enable_bbr':'false' if b.get('enable_bbr')=='false' else 'true','udpgw_port':str(b.get('udpgw_port','7300')),'udpgw_max_clients':str(b.get('udpgw_max_clients','1000'))};writej(SYS,s);return self.sendj({'status':'success','message':'Pengaturan tersimpan.'})
  self.sendj({'status':'error','message':'Not Found'},404)
 def log_message(self,*args):print('[PANEL]',*args)
if __name__=='__main__':
 migrate()
 print(f'[PANEL] Python API + HTML listening on 0.0.0.0:{PORT}')
 http.server.ThreadingHTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
