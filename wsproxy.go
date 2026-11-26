package main

import (
	"bufio"
	"bytes"
	"crypto/sha1"
	"encoding/base64"
	"io"
	"log"
	"net"
	"os"
	"strings"
	"time"
)

const magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

func tune(c net.Conn) {
	if t, ok := c.(*net.TCPConn); ok {
		_ = t.SetNoDelay(true)
		_ = t.SetKeepAlive(true)
		_ = t.SetKeepAlivePeriod(30 * time.Second)
	}
}

func main() {
	port := os.Getenv("WS_PORT")
	if port == "" {
		port = "8880"
	}
	ssh := os.Getenv("SSH_TARGET")
	if ssh == "" {
		ssh = "127.0.0.1:22"
	}
	ln, err := net.Listen("tcp", "127.0.0.1:"+port)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("SSH WebSocket proxy on 127.0.0.1:%s -> %s", port, ssh)
	for {
		c, err := ln.Accept()
		if err != nil {
			continue
		}
		go handle(c, ssh)
	}
}

func handle(client net.Conn, target string) {
	tune(client)
	defer client.Close()
	_ = client.SetReadDeadline(time.Now().Add(15 * time.Second))
	br := bufio.NewReaderSize(client, 16*1024)
	var header bytes.Buffer
	for header.Len() < 16*1024 {
		line, err := br.ReadString('\n')
		if err != nil {
			return
		}
		header.WriteString(line)
		if strings.HasSuffix(header.String(), "\r\n\r\n") {
			break
		}
	}
	_ = client.SetReadDeadline(time.Time{})
	raw := header.String()
	lower := strings.ToLower(raw)
	if !strings.Contains(lower, "upgrade: websocket") {
		_, _ = io.WriteString(client, "HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
		return
	}
	key := ""
	for _, line := range strings.Split(raw, "\r\n") {
		if strings.HasPrefix(strings.ToLower(line), "sec-websocket-key:") {
			key = strings.TrimSpace(strings.SplitN(line, ":", 2)[1])
			break
		}
	}
	if key == "" {
		_, _ = io.WriteString(client, "HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
		return
	}
	sshConn, err := net.DialTimeout("tcp", target, 5*time.Second)
	if err != nil {
		_, _ = io.WriteString(client, "HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
		return
	}
	defer sshConn.Close()
	tune(sshConn)
	sum := sha1.Sum([]byte(key + magic))
	accept := base64.StdEncoding.EncodeToString(sum[:])
	_, _ = io.WriteString(client, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: "+accept+"\r\n\r\n")

	// The SSH3 client transport used by the supplied project sends its SSH
	// identification after the HTTP upgrade; retain the original SSH- prefix
	// preamble handling while preserving bytes already buffered by bufio.
	buf := make([]byte, 64*1024)
	found := false
	for !found {
		n, e := br.Read(buf)
		if n > 0 {
			chunk := buf[:n]
			if i := bytes.Index(chunk, []byte("SSH-")); i >= 0 {
				if _, e2 := sshConn.Write(chunk[i:]); e2 != nil {
					return
				}
				found = true
			}
		}
		if e != nil {
			return
		}
	}
	done := make(chan struct{}, 2)
	go func() {
		_, _ = io.Copy(sshConn, br)
		if t, ok := sshConn.(*net.TCPConn); ok {
			_ = t.CloseWrite()
		}
		done <- struct{}{}
	}()
	go func() {
		_, _ = io.Copy(client, sshConn)
		if t, ok := client.(*net.TCPConn); ok {
			_ = t.CloseWrite()
		}
		done <- struct{}{}
	}()
	<-done
}
