package main

import (
	"bufio"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

var (
	wsAddr  = "127.0.0.1:8880"
	sslAddr = "127.0.0.1:2443"
)

type bufferedConn struct {
	net.Conn
	reader *bufio.Reader
}

func (c *bufferedConn) Read(p []byte) (int, error) { return c.reader.Read(p) }

type rawConnListener struct {
	conns  chan net.Conn
	closed chan struct{}
}

func newRawConnListener() *rawConnListener {
	return &rawConnListener{conns: make(chan net.Conn, 256), closed: make(chan struct{})}
}
func (l *rawConnListener) Accept() (net.Conn, error) {
	select {
	case c := <-l.conns:
		return c, nil
	case <-l.closed:
		return nil, net.ErrClosed
	}
}
func (l *rawConnListener) Close() error {
	select {
	case <-l.closed:
	default:
		close(l.closed)
	}
	return nil
}
func (l *rawConnListener) Addr() net.Addr { return localAddr("public-http") }

type localAddr string

func (a localAddr) Network() string { return "tcp" }
func (a localAddr) String() string  { return string(a) }

func copyDuplex(a, b net.Conn) {
	done := make(chan struct{}, 2)
	go func() {
		_, _ = io.Copy(b, a)
		if tcp, ok := b.(*net.TCPConn); ok {
			_ = tcp.CloseWrite()
		}
		done <- struct{}{}
	}()
	go func() {
		_, _ = io.Copy(a, b)
		if tcp, ok := a.(*net.TCPConn); ok {
			_ = tcp.CloseWrite()
		}
		done <- struct{}{}
	}()
	<-done
}

func serveSSHWS(w http.ResponseWriter, r *http.Request) {
	hijacker, ok := w.(http.Hijacker)
	if !ok {
		http.Error(w, "hijacking unavailable", http.StatusInternalServerError)
		return
	}
	client, rw, err := hijacker.Hijack()
	if err != nil {
		return
	}
	backend, err := net.DialTimeout("tcp", wsAddr, 5*time.Second)
	if err != nil {
		_, _ = rw.WriteString("HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
		_ = rw.Flush()
		_ = client.Close()
		return
	}
	_ = r.Write(backend)
	if rw.Reader.Buffered() > 0 {
		_, _ = io.CopyN(backend, rw.Reader, int64(rw.Reader.Buffered()))
	}
	copyDuplex(client, backend)
	_ = client.Close()
	_ = backend.Close()
}

func main() {
	port := strings.TrimSpace(os.Getenv("PORT"))
	if port == "" {
		port = "8080"
	}
	wsAddr = net.JoinHostPort(envDefault("WS_MUX_TARGET_HOST", "127.0.0.1"), envDefault("WS_MUX_TARGET_PORT", "8880"))
	sslAddr = net.JoinHostPort(envDefault("SSL_TARGET_HOST", "127.0.0.1"), envDefault("SSL_TARGET_PORT", "2443"))

	listener, err := net.Listen("tcp", ":"+port)
	if err != nil {
		log.Fatal(err)
	}
	defer listener.Close()

	httpListener := newRawConnListener()
	server := &http.Server{Handler: newAppHandler(), ReadHeaderTimeout: 10 * time.Second}
	go func() {
		if err := server.Serve(httpListener); err != nil && err != http.ErrServerClosed {
			log.Printf("HTTP app server: %v", err)
		}
	}()

	log.Printf("Go TCP multiplexer listening on :%s", port)
	for {
		client, err := listener.Accept()
		if err != nil {
			continue
		}
		go func(c net.Conn) {
			_ = c.SetReadDeadline(time.Now().Add(6 * time.Second))
			reader := bufio.NewReaderSize(c, 16*1024)
			peek, peekErr := reader.Peek(4)
			_ = c.SetReadDeadline(time.Time{})

			target := ""
			if peekErr == nil && string(peek) == "SSH-" {
				target = "127.0.0.1:22"
			} else if peekErr == nil && len(peek) > 0 && peek[0] == 0x16 {
				target = sslAddr
			}

			if target != "" {
				upstream, dialErr := net.DialTimeout("tcp", target, 5*time.Second)
				if dialErr != nil {
					_ = c.Close()
					return
				}
				copyDuplex(&bufferedConn{Conn: c, reader: reader}, upstream)
				_ = c.Close()
				_ = upstream.Close()
				return
			}

			wrapped := &bufferedConn{Conn: c, reader: reader}
			select {
			case httpListener.conns <- wrapped:
			case <-httpListener.closed:
				_ = c.Close()
			}
		}(client)
	}
}

func envDefault(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}
