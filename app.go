package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	appDir            = "/app"
	configPath        = "/data/config.json"
	usersPath         = "/data/ssh-users.json"
	settingsPath      = "/data/system-settings.json"
	proxySettingsPath = "/data/proxy-settings.json"
)

func envOrDefault(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

type SSHUser struct {
	Username  string `json:"username"`
	IP        string `json:"ip"`
	Shell     string `json:"shell"`
	CreatedAt string `json:"created_at"`
}
type XrayAccount struct {
	ID        string    `json:"id"`
	Name      string    `json:"name"`
	CreatedAt time.Time `json:"created_at"`
}
type State struct {
	mu        sync.Mutex
	sshPort   int
	keepAlive int
	maxBuffer int
	banner    string
	bbr       string
	udpgwPort int
	udpgwMax  int
}

var state = State{sshPort: 22, keepAlive: 15000, maxBuffer: 32768, bbr: "true", udpgwPort: 7300, udpgwMax: 1000}
var userRE = regexp.MustCompile(`^[a-zA-Z0-9_-]{1,32}$`)
var registrationMu sync.Mutex
var registrationHits = map[string][]time.Time{}

func requestIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		return host
	}
	return r.RemoteAddr
}
func allowRegistration(r *http.Request) bool {
	ip := requestIP(r)
	now := time.Now()
	registrationMu.Lock()
	defer registrationMu.Unlock()
	hits := registrationHits[ip][:0]
	for _, t := range registrationHits[ip] {
		if now.Sub(t) < time.Hour {
			hits = append(hits, t)
		}
	}
	if len(hits) >= 5 {
		registrationHits[ip] = hits
		return false
	}
	hits = append(hits, now)
	registrationHits[ip] = hits
	return true
}

func readJSON(path string, dst any) error {
	b, e := os.ReadFile(path)
	if e != nil {
		return e
	}
	return json.Unmarshal(b, dst)
}
func writeJSON(path string, v any) error {
	b, e := json.MarshalIndent(v, "", "  ")
	if e != nil {
		return e
	}
	tmp := path + ".tmp"
	if e = os.WriteFile(tmp, b, 0600); e != nil {
		return e
	}
	return os.Rename(tmp, path)
}
func loadSSHUsers() []SSHUser {
	var u []SSHUser
	_ = readJSON(usersPath, &u)
	if u == nil {
		u = []SSHUser{}
	}
	return u
}
func saveSSHUsers(u []SSHUser) error { return writeJSON(usersPath, u) }
func loadXray() (map[string]any, error) {
	var v map[string]any
	e := readJSON(configPath, &v)
	return v, e
}
func saveXray(v map[string]any) error {
	if e := writeJSON(configPath, v); e != nil {
		return e
	}
	if p, e := exec.LookPath("pkill"); e == nil {
		_ = exec.Command(p, "-x", "xray").Run()
	}
	return nil
}
func randomUUID() string {
	b := make([]byte, 16)
	if _, e := rand.Read(b); e != nil {
		return ""
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	h := hex.EncodeToString(b)
	return h[:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:]
}

func respond(w http.ResponseWriter, status string, message string, extra map[string]any) {
	m := map[string]any{"status": status, "message": message}
	for k, v := range extra {
		m[k] = v
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(m)
}
func fail(w http.ResponseWriter, msg string) { respond(w, "error", msg, nil) }
func success(w http.ResponseWriter, msg string, extra map[string]any) {
	respond(w, "success", msg, extra)
}
func runInput(name string, args []string, input string) error {
	c := exec.Command(name, args...)
	c.Stdin = strings.NewReader(input)
	out, e := c.CombinedOutput()
	if e != nil {
		return fmt.Errorf("%s: %s", e, strings.TrimSpace(string(out)))
	}
	return nil
}

func statsHandler(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	defer state.mu.Unlock()
	u := loadSSHUsers()
	var x map[string]any
	_ = readJSON(settingsPath, &x)
	if x == nil {
		x = map[string]any{}
	}
	var cfg map[string]any
	_ = readJSON(configPath, &cfg)
	sshOnline := "0"
	if out, e := exec.Command("sh", "-c", `ps -eo comm | grep -c '^dropbear$'`).Output(); e == nil {
		sshOnline = strings.TrimSpace(string(out))
	}
	host, _ := os.Hostname()
	domain := strings.TrimSpace(os.Getenv("DOMAIN"))
	if domain == "" {
		domain = r.Host
		if h, _, e := net.SplitHostPort(domain); e == nil {
			domain = h
		}
	}
	if domain == "" {
		domain = host
	}
	var memUsed, memTotal string
	var memTotalRaw, memAvailRaw string
	if b, e := os.ReadFile("/proc/meminfo"); e == nil {
		for _, ln := range strings.Split(string(b), "\n") {
			f := strings.Fields(ln)
			if len(f) >= 2 && f[0] == "MemTotal:" {
				memTotalRaw = f[1]
				memTotal = fmt.Sprintf("%.0f MB", toFloat(f[1])/1024)
			}
			if len(f) >= 2 && f[0] == "MemAvailable:" {
				memAvailRaw = f[1]
			}
		}
	}
	if memTotalRaw != "" && memAvailRaw != "" {
		memUsed = fmt.Sprintf("%.0f MB", (toFloat(memTotalRaw)-toFloat(memAvailRaw))/1024)
	}
	up := "unknown"
	if b, e := os.ReadFile("/proc/uptime"); e == nil {
		f := strings.Fields(string(b))
		if len(f) > 0 {
			sec, _ := strconv.ParseFloat(f[0], 64)
			up = (time.Duration(sec) * time.Second).String()
		}
	}
	disk := "unknown"
	if out, e := exec.Command("df", "-h", "/").Output(); e == nil {
		lines := strings.Split(string(out), "\n")
		if len(lines) > 1 {
			f := strings.Fields(lines[1])
			if len(f) > 4 {
				disk = f[4]
			}
		}
	}
	ws := map[string]any{"sshPort": state.sshPort, "keepAlive": state.keepAlive, "maxBuffer": state.maxBuffer}
	sys := map[string]any{"banner": state.banner, "enable_bbr": state.bbr, "udpgw_port": state.udpgwPort, "udpgw_max_clients": state.udpgwMax}
	_ = u
	_ = cfg
	respond(w, "success", "ONLINE", map[string]any{"status": "ONLINE", "cpu_model": host, "ram_used": memUsed, "ram_total": memTotal, "disk_usage": disk, "uptime": up, "ssh_online": sshOnline, "user_list_details": fmt.Sprintf("%d akun dikelola", len(u)), "domain": domain, "ws_proxy_cfg": ws, "sys_settings": sys, "pass_configured": false})
}
func toFloat(s string) float64 { f, _ := strconv.ParseFloat(s, 64); return f }

func apiHandler(w http.ResponseWriter, r *http.Request) {
	switch r.URL.Path {
	case "/api/stats":
		statsHandler(w, r)
	case "/api/list":
		if r.Method != http.MethodGet {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		respond(w, "success", "OK", map[string]any{"count": len(loadSSHUsers())})
	case "/api/add":
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !allowRegistration(r) {
			fail(w, "Batas pembuatan akun: maksimal 5 akun per IP per jam")
			return
		}
		if len(loadSSHUsers()) >= 200 {
			fail(w, "Kuota akun SSH server penuh")
			return
		}
		var req struct {
			User string `json:"user"`
			Pass string `json:"pass"`
		}
		if e := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096)).Decode(&req); e != nil {
			fail(w, "Data akun tidak valid")
			return
		}
		user, pass := req.User, req.Pass
		if !userRE.MatchString(user) || len(pass) < 8 || len(pass) > 128 || strings.ContainsAny(pass, ":\r\n") {
			fail(w, "Username tidak valid atau password harus 8–128 karakter")
			return
		}
		if _, e := exec.LookPath("useradd"); e != nil {
			fail(w, "useradd tidak tersedia")
			return
		}
		if e := exec.Command("useradd", "-m", "-s", "/bin/bash", user).Run(); e != nil {
			fail(w, "Gagal membuat akun: "+e.Error())
			return
		}
		if e := runInput("chpasswd", nil, user+":"+pass+"\n"); e != nil {
			_ = exec.Command("userdel", "-r", user).Run()
			fail(w, "Gagal mengatur password: "+e.Error())
			return
		}
		u := loadSSHUsers()
		u = append(u, SSHUser{Username: user, IP: r.RemoteAddr, Shell: "/bin/bash", CreatedAt: time.Now().Format(time.RFC3339)})
		_ = saveSSHUsers(u)
		tcpHost := os.Getenv("RAILWAY_TCP_PROXY_DOMAIN")
		tcpPort := os.Getenv("RAILWAY_TCP_PROXY_PORT")
		tcpInfo := "TCP Proxy Railway belum diaktifkan"
		if tcpHost != "" && tcpPort != "" {
			tcpInfo = tcpHost + ":" + tcpPort
		}
		domain := strings.TrimSpace(os.Getenv("DOMAIN"))
		if domain == "" {
			domain = r.Host
		}
		success(w, "Akun SSH dibuat\nHost WebSocket: "+domain+"\nUsername: "+user+"\nPassword: "+pass+"\nSSH Direct/SSL TCP: "+tcpInfo+"\nSSH WebSocket: "+domain+":443 /ssh-ws", nil)
	case "/api/delete":
		http.Error(w, "Not Found", http.StatusNotFound)
		return
	case "/api/xray/list":
		if r.Method != http.MethodGet {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		accounts := loadXrayAccounts()
		respond(w, "success", "OK", map[string]any{"accounts": accounts})
	case "/api/xray/add":
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !allowRegistration(r) {
			fail(w, "Batas pembuatan akun: maksimal 5 akun per IP per jam")
			return
		}
		if len(loadXrayAccounts()) >= 200 {
			fail(w, "Kuota akun X-Ray server penuh")
			return
		}
		var req struct {
			Name string `json:"name"`
		}
		if e := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096)).Decode(&req); e != nil {
			fail(w, "Data akun tidak valid")
			return
		}
		if !regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_-]{0,23}$`).MatchString(req.Name) {
			fail(w, "Nama akun tidak valid")
			return
		}
		id := randomUUID()
		a := XrayAccount{ID: id, Name: req.Name, CreatedAt: time.Now()}
		if e := addXrayAccount(a); e != nil {
			fail(w, e.Error())
			return
		}
		success(w, "Akun Xray berhasil dibuat", map[string]any{"account": a})
	case "/api/xray/delete":
		http.Error(w, "Not Found", http.StatusNotFound)
		return
	default:
		http.NotFound(w, r)
	}
}

func parseInt(s string, d int) int {
	if n, e := strconv.Atoi(s); e == nil && n > 0 && n < 65536 {
		return n
	}
	return d
}
func loadXrayAccounts() []XrayAccount {
	var a []XrayAccount
	var raw []map[string]any
	_ = readJSON("/data/xray-accounts.json", &raw)
	for _, x := range raw {
		a = append(a, XrayAccount{ID: fmt.Sprint(x["id"]), Name: fmt.Sprint(x["name"]), CreatedAt: time.Now()})
	}
	return a
}
func addXrayAccount(a XrayAccount) error {
	cfg, e := loadXray()
	if e != nil {
		return e
	}
	in, ok := cfg["inbounds"].([]any)
	if !ok {
		return fmt.Errorf("inbounds config tidak ditemukan")
	}
	for _, v := range in {
		ib, ok := v.(map[string]any)
		if !ok {
			continue
		}
		proto := fmt.Sprint(ib["protocol"])
		settings, _ := ib["settings"].(map[string]any)
		if settings == nil {
			continue
		}
		clients, _ := settings["clients"].([]any)
		if proto == "trojan" {
			clients = append(clients, map[string]any{"password": a.ID, "email": a.Name})
		} else {
			clients = append(clients, map[string]any{"id": a.ID, "email": a.Name})
		}
		settings["clients"] = clients
	}
	if e = saveXray(cfg); e != nil {
		return e
	}
	all := loadXrayAccounts()
	all = append(all, a)
	return writeJSON("/data/xray-accounts.json", all)
}
func deleteXrayAccount(id string) error {
	cfg, e := loadXray()
	if e != nil {
		return e
	}
	in, _ := cfg["inbounds"].([]any)
	for _, v := range in {
		ib, ok := v.(map[string]any)
		if !ok {
			continue
		}
		settings, _ := ib["settings"].(map[string]any)
		if settings == nil {
			continue
		}
		clients, _ := settings["clients"].([]any)
		out := []any{}
		for _, c := range clients {
			m, _ := c.(map[string]any)
			if m != nil && fmt.Sprint(m["id"]) == id && m["id"] != nil {
				continue
			}
			if m != nil && fmt.Sprint(m["password"]) == id {
				continue
			}
			out = append(out, c)
		}
		settings["clients"] = out
	}
	if e = saveXray(cfg); e != nil {
		return e
	}
	all := loadXrayAccounts()
	out := all[:0]
	for _, a := range all {
		if a.ID != id {
			out = append(out, a)
		}
	}
	return writeJSON("/data/xray-accounts.json", out)
}

func newAppHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/", apiHandler)
	mux.HandleFunc("/__info", func(w http.ResponseWriter, r *http.Request) {
		id := ""
		accounts := loadXrayAccounts()
		if len(accounts) > 0 {
			id = accounts[0].ID
		}
		respond(w, "success", "OK", map[string]any{
			"uuid": id,
			"paths": map[string]string{
				"vless": "/vless", "vmess": "/vmess", "trojan": "/trojan",
			},
		})
	})
	mux.HandleFunc("/ssh-ws", serveSSHWS)
	mux.HandleFunc("/ssh-ws/", serveSSHWS)

	target, _ := url.Parse("http://127.0.0.1:8081")
	reverseProxy := httputil.NewSingleHostReverseProxy(target)
	for _, path := range []string{
		"/xhttp", "/httpup", "/vless",
		"/vmess-xhttp", "/vmess-httpup", "/vmess",
		"/trojan-xhttp", "/trojan-httpup", "/trojan",
	} {
		mux.Handle(path, reverseProxy)
	}

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/favicon.ico" {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		http.ServeFile(w, r, filepath.Join(appDir, "index.html"))
	})
	return mux
}
