package main

import "testing"

func TestNginxPaths(t *testing.T) {
	for _, path := range []string{
		"/ssh", "/ssh/", "/ssh-ws", "/ssh-ws/connect",
		"/xhttp", "/xhttp/abc", "/httpup", "/vless",
		"/vmess-xhttp", "/vmess-httpup", "/vmess",
		"/trojan-xhttp", "/trojan-httpup", "/trojan",
	} {
		if !hasPathPrefix(path, nginxPaths) {
			t.Errorf("expected Nginx path %q to match", path)
		}
	}
}

func TestPanelPathsDoNotMatchNginx(t *testing.T) {
	for _, path := range []string{"/", "/api/stats", "/assets/app.js", "/login"} {
		if hasPathPrefix(path, nginxPaths) {
			t.Errorf("panel path %q unexpectedly matched Nginx", path)
		}
	}
}

func TestPathPrefixDoesNotMatchSimilarPrefix(t *testing.T) {
	if hasPathPrefix("/ssh-other", nginxPaths) {
		t.Fatal("/ssh-other must not match /ssh")
	}
}
