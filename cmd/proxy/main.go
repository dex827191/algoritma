package main

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"regexp"
	"strings"
	"time"
)

const (
	defaultPublicPort = "8080"
	nginxHost         = "127.0.0.1"
	nginxPort         = "8081"
	panelHost         = "127.0.0.1"
	panelPort         = "3000"
)

var (
	xrayPaths = []string{
		"/xhttp", "/httpup", "/vless",
		"/vmess-xhttp", "/vmess-httpup", "/vmess",
		"/trojan-xhttp", "/trojan-httpup", "/trojan",
	}
	statusPrefix = regexp.MustCompile(`^HTTP/[^\r\n]*\r\n\r\n`)
)

func stripLeadingHTTPHeader(data []byte) []byte {
	return statusPrefix.ReplaceAll(data, nil)
}

func isXrayPath(path string) bool {
	for _, prefix := range xrayPaths {
		if strings.HasPrefix(path, prefix) {
			return true
		}
	}
	return false
}

func isNginxWebSocketPath(path string) bool {
	return strings.HasPrefix(path, "/ssh")
}

func writeAll(w io.Writer, data []byte) error {
	for len(data) > 0 {
		n, err := w.Write(data)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		data = data[n:]
	}
	return nil
}

func readHeader(reader *bufio.Reader) ([]byte, error) {
	var header []byte
	for {
		line, err := reader.ReadBytes('\n')
		if err != nil {
			return nil, err
		}
		header = append(header, line...)
		if len(header) > 64*1024 {
			return nil, errors.New("HTTP header terlalu besar")
		}
		if bytes.Equal(line, []byte("\r\n")) {
			return header, nil
		}
	}
}

func headerValue(lines []string, prefix string, fallback string) string {
	for _, line := range lines {
		if strings.HasPrefix(strings.ToLower(line), strings.ToLower(prefix)) {
			return line
		}
	}
	return fallback
}

func buildWebSocketRequest(path string, lines []string) []byte {
	host := headerValue(lines, "host:", "Host: localhost")
	wsHeaders := make([]string, 0, 4)
	hasKey, hasVersion := false, false

	for _, line := range lines[1:] {
		lower := strings.ToLower(line)
		if strings.HasPrefix(lower, "sec-websocket-") {
			wsHeaders = append(wsHeaders, line)
			if strings.HasPrefix(lower, "sec-websocket-key:") {
				hasKey = true
			}
			if strings.HasPrefix(lower, "sec-websocket-version:") {
				hasVersion = true
			}
		}
	}
	if !hasKey {
		wsHeaders = append(wsHeaders, "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==")
	}
	if !hasVersion {
		wsHeaders = append(wsHeaders, "Sec-WebSocket-Version: 13")
	}

	var request strings.Builder
	fmt.Fprintf(&request, "GET %s HTTP/1.1\r\n%s\r\n", path, host)
	for _, h := range wsHeaders {
		request.WriteString(h)
		request.WriteString("\r\n")
	}
	request.WriteString("Upgrade: websocket\r\n")
	request.WriteString("Connection: Upgrade\r\n\r\n")
	return []byte(request.String())
}

func pipeClientToUp(reader *bufio.Reader, upstream net.Conn) {
	firstChunk := true
	buf := make([]byte, 8192)
	for {
		n, err := reader.Read(buf)
		if n > 0 {
			data := buf[:n]
			if firstChunk {
				firstChunk = false
				data = stripLeadingHTTPHeader(data)
			}
			if len(data) > 0 {
				if writeAll(upstream, data) != nil {
					return
				}
			}
		}
		if err != nil {
			return
		}
	}
}

func pipeUpToClient(reader *bufio.Reader, client net.Conn) {
	_, _ = io.Copy(client, reader)
}

func relay(clientReader *bufio.Reader, client net.Conn, upstreamReader *bufio.Reader, upstream net.Conn) {
	done := make(chan struct{}, 2)
	go func() {
		pipeClientToUp(clientReader, upstream)
		_ = upstream.Close()
		done <- struct{}{}
	}()
	go func() {
		pipeUpToClient(upstreamReader, client)
		_ = client.Close()
		done <- struct{}{}
	}()
	<-done
}

func handleClient(client net.Conn) {
	defer client.Close()
	clientReader := bufio.NewReaderSize(client, 64*1024)

	rawHeader, err := readHeader(clientReader)
	if err != nil {
		return
	}
	lines := strings.Split(string(rawHeader), "\r\n")
	if len(lines) == 0 || lines[0] == "" {
		return
	}
	parts := strings.Fields(lines[0])
	if len(parts) < 2 {
		return
	}
	path := parts[1]

	if isXrayPath(path) {
		upstream, err := net.DialTimeout("tcp", net.JoinHostPort(nginxHost, nginxPort), 8*time.Second)
		if err != nil {
			log.Printf("connect nginx for Xray: %v", err)
			return
		}
		upstreamReader := bufio.NewReaderSize(upstream, 64*1024)
		if err := writeAll(upstream, buildWebSocketRequest(path, lines)); err != nil {
			_ = upstream.Close()
			return
		}
		responseHeader, err := readHeader(upstreamReader)
		if err != nil {
			_ = upstream.Close()
			return
		}
		if err := writeAll(client, responseHeader); err != nil {
			_ = upstream.Close()
			return
		}
		if buffered := clientReader.Buffered(); buffered > 0 {
			buf, _ := clientReader.Peek(buffered)
			pending := append([]byte(nil), buf...)
			_, _ = clientReader.Discard(buffered)
			pending = stripLeadingHTTPHeader(pending)
			if len(pending) > 0 {
				if err := writeAll(upstream, pending); err != nil {
					_ = upstream.Close()
					return
				}
			}
		}
		relay(clientReader, client, upstreamReader, upstream)
		return
	}

	upstreamAddr := net.JoinHostPort(panelHost, panelPort)
	if isNginxWebSocketPath(path) {
		upstreamAddr = net.JoinHostPort(nginxHost, nginxPort)
	}
	upstream, err := net.DialTimeout("tcp", upstreamAddr, 8*time.Second)
	if err != nil {
		log.Printf("connect upstream %s: %v", upstreamAddr, err)
		return
	}
	upstreamReader := bufio.NewReaderSize(upstream, 64*1024)
	if err := writeAll(upstream, rawHeader); err != nil {
		_ = upstream.Close()
		return
	}
	relay(clientReader, client, upstreamReader, upstream)
}

func main() {
	publicPort := os.Getenv("PORT")
	if publicPort == "" {
		publicPort = defaultPublicPort
	}
	listenAddr := "0.0.0.0:" + publicPort
	listener, err := net.Listen("tcp", listenAddr)
	if err != nil {
		log.Fatalf("listen %s: %v", listenAddr, err)
	}
	defer listener.Close()

	log.Printf("Go HTTP/WebSocket proxy listening on %s -> %s:%s", listenAddr, nginxHost, nginxPort)
	for {
		conn, err := listener.Accept()
		if err != nil {
			log.Printf("accept: %v", err)
			continue
		}
		go handleClient(conn)
	}
}
