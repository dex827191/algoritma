package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestIsXrayPath(t *testing.T) {
	for _, path := range []string{
		"/xhttp", "/xhttp/abc", "/httpup", "/vless",
		"/vmess-xhttp", "/vmess-httpup", "/vmess",
		"/trojan-xhttp", "/trojan-httpup", "/trojan",
	} {
		if !isXrayPath(path) {
			t.Errorf("expected Xray path %q to match", path)
		}
	}
	for _, path := range []string{"/", "/api/stats", "/ssh-ws"} {
		if isXrayPath(path) {
			t.Errorf("unexpected Xray path match for %q", path)
		}
	}
}

func TestIsNginxWebSocketPath(t *testing.T) {
	for _, path := range []string{"/ssh", "/ssh/", "/ssh-ws", "/ssh-ws/connect"} {
		if !isNginxWebSocketPath(path) {
			t.Errorf("expected Nginx WebSocket path %q to match", path)
		}
	}
	for _, path := range []string{"/", "/api/stats", "/assets/app.js"} {
		if isNginxWebSocketPath(path) {
			t.Errorf("unexpected Nginx WebSocket path match for %q", path)
		}
	}
}

func TestBuildWebSocketRequest(t *testing.T) {
	lines := []string{
		"POST /vless?ed=256 HTTP/1.1",
		"Host: example.test",
		"Sec-WebSocket-Protocol: binary",
		"",
	}
	got := string(buildWebSocketRequest("/vless?ed=256", lines))
	for _, want := range []string{
		"GET /vless?ed=256 HTTP/1.1\r\n",
		"Host: example.test\r\n",
		"Sec-WebSocket-Protocol: binary\r\n",
		"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n",
		"Sec-WebSocket-Version: 13\r\n",
		"Upgrade: websocket\r\n",
		"Connection: Upgrade\r\n",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("rewritten request missing %q:\n%s", want, got)
		}
	}
	if strings.Contains(got, "POST ") {
		t.Errorf("request method was not rewritten to GET: %s", got)
	}
}

func TestStripLeadingHTTPHeader(t *testing.T) {
	input := []byte("HTTP/1.1 101 Switching Protocols\r\n\r\nPAYLOAD")
	want := []byte("PAYLOAD")
	if got := stripLeadingHTTPHeader(input); !bytes.Equal(got, want) {
		t.Fatalf("stripLeadingHTTPHeader() = %q, want %q", got, want)
	}
}
