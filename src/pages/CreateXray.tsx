import { useCallback, useEffect, useMemo, useState } from 'react';
import { Copy, Plus, Radio, RefreshCw, Trash2, ShieldAlert } from 'lucide-react';
import { Card, Input, SectionTitle } from '@/components/ui';
import { PageHeader } from '@/components/PageHeader';
import { CopyButton } from '@/components/CopyButton';
import { createXrayAccount, deleteXrayAccount, fetchXrayAccounts, type XrayAccount } from '@/lib/api';

interface Props {
  isAdmin: boolean;
  adminToken: string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

type LinkRow = { protocol: string; transport: string; path: string; link: string };

function makeLinks(account: XrayAccount, host: string): LinkRow[] {
  const domain = host.split(':')[0] || 'domain-anda.com';
  const entries = [
    { protocol: 'VLESS', scheme: 'vless', transport: 'XHTTP', net: 'xhttp', path: '/xhttp' },
    { protocol: 'VLESS', scheme: 'vless', transport: 'HTTPUpgrade', net: 'httpupgrade', path: '/httpup' },
    { protocol: 'VLESS', scheme: 'vless', transport: 'WebSocket', net: 'ws', path: '/vless' },
    { protocol: 'VMess', scheme: 'vmess', transport: 'XHTTP', net: 'xhttp', path: '/vmess-xhttp' },
    { protocol: 'VMess', scheme: 'vmess', transport: 'HTTPUpgrade', net: 'httpupgrade', path: '/vmess-httpup' },
    { protocol: 'VMess', scheme: 'vmess', transport: 'WebSocket', net: 'ws', path: '/vmess' },
    { protocol: 'Trojan', scheme: 'trojan', transport: 'XHTTP', net: 'xhttp', path: '/trojan-xhttp' },
    { protocol: 'Trojan', scheme: 'trojan', transport: 'HTTPUpgrade', net: 'httpupgrade', path: '/trojan-httpup' },
    { protocol: 'Trojan', scheme: 'trojan', transport: 'WebSocket', net: 'ws', path: '/trojan' },
  ];
  return entries.map((item) => {
    let link = '';
    if (item.scheme === 'vmess') {
      const payload = {
        v: '2', ps: `${account.name}-${item.protocol}-${item.transport}`, add: domain,
        port: '443', id: account.id, aid: '0', scy: 'auto', net: item.net,
        type: item.net === 'xhttp' ? 'auto' : 'none', host: domain, path: item.path,
        tls: 'tls', sni: domain, ...(item.net === 'xhttp' ? { mode: 'auto' } : {}),
      };
      link = `vmess://${btoa(unescape(encodeURIComponent(JSON.stringify(payload))))}`;
    } else {
      const query = new URLSearchParams({ security: 'tls', sni: domain, type: item.net, host: domain, path: item.path });
      if (item.scheme === 'vless') query.set('encryption', 'none');
      if (item.net === 'xhttp') query.set('mode', 'auto');
      link = `${item.scheme}://${account.id}@${domain}:443?${query.toString()}#${encodeURIComponent(`${account.name}-${item.protocol}-${item.transport}`)}`;
    }
    return { protocol: item.protocol, transport: item.transport, path: item.path, link };
  });
}

export function CreateXray({ isAdmin, adminToken, showToast }: Props) {
  const [accounts, setAccounts] = useState<XrayAccount[]>([]);
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [created, setCreated] = useState<XrayAccount | null>(null);
  const host = useMemo(() => window.location.hostname, []);

  const load = useCallback(async () => {
    if (!adminToken) return;
    try {
      const data = await fetchXrayAccounts(adminToken);
      if (data.status === 'success') setAccounts(data.accounts || []);
      else showToast(data.message || 'Gagal mengambil akun Xray', 'error');
    } catch { showToast('Gagal terhubung ke API Xray', 'error'); }
  }, [adminToken, showToast]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!isAdmin || !adminToken) return showToast('Login admin terlebih dahulu.', 'error');
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,23}$/.test(name.trim())) {
      return showToast('Nama 1–24 karakter: huruf, angka, _ atau -.', 'error');
    }
    setLoading(true);
    try {
      const data = await createXrayAccount(name.trim(), adminToken);
      if (data.status === 'success' && data.account) {
        setCreated(data.account);
        setName('');
        await load();
        showToast('Akun Xray berhasil dibuat dan konfigurasi Xray diperbarui.', 'success');
      } else showToast(data.message || 'Gagal membuat akun Xray', 'error');
    } catch { showToast('Gagal menghubungi API Xray', 'error'); }
    setLoading(false);
  };

  const handleDelete = async (account: XrayAccount) => {
    if (!isAdmin || !adminToken) return;
    if (!window.confirm(`Hapus akun Xray ${account.name}?`)) return;
    try {
      const data = await deleteXrayAccount(account.id, adminToken);
      if (data.status === 'success') {
        if (created?.id === account.id) setCreated(null);
        await load();
        showToast(data.message, 'success');
      } else showToast(data.message, 'error');
    } catch { showToast('Gagal menghapus akun Xray', 'error'); }
  };

  const links = created ? makeLinks(created, host) : [];

  return (
    <div className="animate-slide-up space-y-5">
      <PageHeader title="Buat Akun Xray" subtitle="Kelola akun VLESS, VMess, dan Trojan" icon={<Radio size={20} />} />
      {!isAdmin ? (
        <Card><div className="flex items-center gap-2 text-error-50"><ShieldAlert size={18} /><b>Login admin diperlukan untuk membuat, melihat, atau menghapus akun Xray.</b></div></Card>
      ) : <>
        <Card>
          <SectionTitle>Buat Akun Baru</SectionTitle>
          <p className="text-xs text-neutral-60 mb-3">Satu akun akan otomatis ditambahkan ke seluruh inbound VLESS, VMess, dan Trojan yang tersedia di data/config.json.</p>
          <div className="flex flex-col sm:flex-row gap-3">
            <Input value={name} onChange={setName} placeholder="Nama akun, contoh: user01" className="flex-1" />
            <button onClick={handleCreate} disabled={loading} className="m3-btn m3-btn-filled state-layer whitespace-nowrap"><Plus size={16} /> {loading ? 'Memproses...' : 'Buat Akun'}</button>
          </div>
        </Card>

        {created && <Card>
          <SectionTitle>Akun Berhasil Dibuat: {created.name}</SectionTitle>
          <p className="text-xs text-neutral-60 break-all mb-3">UUID / Password Trojan: <span className="font-mono text-neutral-10">{created.id}</span></p>
          <CopyButton text={created.id} label="Salin UUID" className="w-full mb-3" />
          <div className="space-y-3">
            {['VLESS', 'VMess', 'Trojan'].map((protocol) => <div key={protocol} className="space-y-2">
              <h3 className="text-xs font-bold text-neutral-10">{protocol}</h3>
              {links.filter((row) => row.protocol === protocol).map((row) => <div key={row.path} className="rounded-m3-sm bg-surface-container-high p-3 space-y-1">
                <div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold">{row.transport} <span className="text-neutral-60">{row.path}</span></span><CopyButton text={row.link} label="Copy" variant="text" /></div>
                <p className="text-[10px] font-mono text-neutral-60 break-all">{row.link}</p>
              </div>)}
            </div>)}
          </div>
        </Card>}

        <Card>
          <div className="flex items-center justify-between gap-2 mb-3"><SectionTitle>Daftar Akun Xray</SectionTitle><button onClick={load} className="m3-btn m3-btn-text"><RefreshCw size={14} /> Refresh</button></div>
          {accounts.length === 0 ? <p className="text-center text-sm text-neutral-60 py-5">Belum ada akun Xray.</p> : <div className="space-y-2">
            {accounts.map((account) => <div key={account.id} className="flex items-center gap-3 rounded-m3-sm bg-surface-container-high p-3">
              <div className="min-w-0 flex-1"><button onClick={() => setCreated(account)} className="text-sm font-bold text-primary-50 text-left hover:underline">{account.name} · Tampilkan konfigurasi</button><p className="text-[10px] font-mono text-neutral-60 break-all">{account.id}</p><p className="text-[10px] text-neutral-60">{new Date(account.created_at).toLocaleString()}</p></div>
              <button onClick={() => navigator.clipboard.writeText(account.id).then(() => showToast('UUID disalin', 'success'))} className="m3-btn m3-btn-text" title="Salin UUID"><Copy size={15} /></button>
              <button onClick={() => handleDelete(account)} className="m3-btn m3-btn-text text-error-50" title="Hapus akun"><Trash2 size={15} /></button>
            </div>)}
          </div>}
        </Card>
      </>}
    </div>
  );
}
