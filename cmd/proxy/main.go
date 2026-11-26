package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"
)

const (
	defaultPublicPort = "3000"
	panelHost         = "127.0.0.1"
	panelPort         = "3001"
	nginxHost         = "127.0.0.1"
	nginxPort         = "8081"
)

var nginxPaths = []string{
	"/ssh-ws", "/ssh",
	"/xhttp", "/httpup", "/vless",
	"/vmess-xhttp", "/vmess-httpup", "/vmess",
	"/trojan-xhttp", "/trojan-httpup", "/trojan",
}

func hasPathPrefix(path string, prefixes []string) bool {
	for _, prefix := range prefixes {
		if path == prefix || strings.HasPrefix(path, prefix+"/") || strings.HasPrefix(path, prefix+"?") {
			return true
		}
	}
	return false
}

func proxyTo(target string) *httputil.ReverseProxy {
	u, err := url.Parse(target)
	if err != nil {
		log.Fatalf("invalid upstream %q: %v", target, err)
	}
	p := httputil.NewSingleHostReverseProxy(u)
	p.FlushInterval = -1
	p.ErrorLog = log.Default()
	p.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("upstream %s error for %s: %v", target, r.URL.Path, err)
		http.Error(w, "upstream temporarily unavailable", http.StatusBadGateway)
	}
	return p
}

func main() {
	publicPort := os.Getenv("PORT")
	if publicPort == "" {
		publicPort = defaultPublicPort
	}

	panelProxy := proxyTo("http://" + panelHost + ":" + panelPort)
	nginxProxy := proxyTo("http://" + nginxHost + ":" + nginxPort)

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" {
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte("ok\n"))
			return
		}

		if hasPathPrefix(r.URL.Path, nginxPaths) {
			nginxProxy.ServeHTTP(w, r)
			return
		}

		// All normal web traffic (UI, assets, login and /api/*) goes to Node.
		panelProxy.ServeHTTP(w, r)
	})

	server := &http.Server{
		Addr:              "0.0.0.0:" + publicPort,
		Handler:           handler,
		ReadHeaderTimeout: 15 * time.Second,
		IdleTimeout:       90 * time.Second,
	}

	log.Printf("Go gateway listening on 0.0.0.0:%s; UI/API -> %s:%s; tunnel paths -> %s:%s", publicPort, panelHost, panelPort, nginxHost, nginxPort)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("gateway listen: %v", err)
	}
}
