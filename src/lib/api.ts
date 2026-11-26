import type {
  ServerStats,
  SshUser,
  ServerInfo,
  ConfigFormat,
  ProtocolType,
  ConfigType,
  GenerateConfigParams,
} from '@/types';

const API_BASE = '';

async function apiFetch(path: string): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`);
  return res.json();
}

export async function fetchStats(): Promise<ServerStats> {
  return apiFetch('/api/stats');
}

export async function fetchServerInfo(): Promise<ServerInfo> {
  const res = await fetch('/__info');
  if (!res.ok) throw new Error('Failed to fetch server info');
  return res.json();
}

export async function fetchAccounts(): Promise<{ status: string; users: SshUser[] }> {
  return apiFetch('/api/list');
}

export async function createSshAccount(
  user: string,
  pass: string
): Promise<{ status: string; message: string }> {
  return apiFetch(
    `/api/add?user=${encodeURIComponent(user)}&pass=${encodeURIComponent(pass)}`
  );
}

export async function deleteSshAccount(
  username: string,
  token: string
): Promise<{ status: string; message: string }> {
  return apiFetch(
    `/api/delete?user=${encodeURIComponent(username)}&token=${encodeURIComponent(token)}`
  );
}

export async function loginAdmin(
  pass: string
): Promise<{ status: string; token?: string; message?: string }> {
  return apiFetch(`/api/login?pass=${encodeURIComponent(pass)}`);
}

export async function setupPass(
  pass: string,
  oldPass?: string
): Promise<{ status: string; message: string }> {
  const params = oldPass
    ? `old_pass=${encodeURIComponent(oldPass)}&pass=${encodeURIComponent(pass)}`
    : `pass=${encodeURIComponent(pass)}`;
  return apiFetch(`/api/setup-pass?${params}`);
}

export async function saveWsProxySetting(
  token: string,
  sshPort: string,
  keepAlive: string,
  maxBuffer: string
): Promise<{ status: string; message: string }> {
  return apiFetch(
    `/api/set-wsproxy?pass=${encodeURIComponent(token)}&ssh_port=${sshPort}&keep_alive=${keepAlive}&max_buffer=${maxBuffer}`
  );
}

export async function saveSystemSetting(
  token: string,
  banner: string,
  enableBbr: string,
  udpgwPort: string,
  udpgwMaxClients: string
): Promise<{ status: string; message: string }> {
  return apiFetch(
    `/api/set-system?pass=${encodeURIComponent(token)}&banner=${encodeURIComponent(banner)}&enable_bbr=${enableBbr}&udpgw_port=${udpgwPort}&udpgw_max_clients=${udpgwMaxClients}`
  );
}

export type {
  ServerStats,
  SshUser,
  ServerInfo,
  ConfigFormat,
  ProtocolType,
  ConfigType,
  GenerateConfigParams,
};


export interface XrayAccount {
  id: string;
  name: string;
  created_at: string;
}

export async function fetchXrayAccounts(token: string): Promise<{ status: string; accounts: XrayAccount[]; message?: string }> {
  const res = await fetch(`/api/xray/list?token=${encodeURIComponent(token)}`);
  return res.json();
}

export async function createXrayAccount(name: string, token: string): Promise<{ status: string; account?: XrayAccount; message: string }> {
  const res = await fetch('/api/xray/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, token }),
  });
  return res.json();
}

export async function deleteXrayAccount(id: string, token: string): Promise<{ status: string; message: string }> {
  const res = await fetch('/api/xray/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, token }),
  });
  return res.json();
}
