package main

import (
	"io"
	"log"
	"net"
	"os"
	"time"
)

const (
	defaultPublicPort = "3000"
	nginxAddress      = "127.0.0.1:8081"
)

func relay(client, upstream net.Conn) {
	done := make(chan struct{}, 2)

	// Copy every byte unchanged in both directions. Nginx handles HTTP
	// routing for the UI, SSH WebSocket, and Xray transports.
	go func() {
		_, _ = io.Copy(upstream, client)
		if conn, ok := upstream.(*net.TCPConn); ok {
			_ = conn.CloseWrite()
		}
		done <- struct{}{}
	}()

	go func() {
		_, _ = io.Copy(client, upstream)
		if conn, ok := client.(*net.TCPConn); ok {
			_ = conn.CloseWrite()
		}
		done <- struct{}{}
	}()

	<-done
	<-done
}

func handleClient(client net.Conn) {
	defer client.Close()

	upstream, err := net.DialTimeout("tcp", nginxAddress, 10*time.Second)
	if err != nil {
		log.Printf("connect nginx %s: %v", nginxAddress, err)
		return
	}
	defer upstream.Close()
	relay(client, upstream)
}

func main() {
	publicPort := os.Getenv("PORT")
	if publicPort == "" {
		publicPort = defaultPublicPort
	}
	listenAddr := net.JoinHostPort("0.0.0.0", publicPort)

	listener, err := net.Listen("tcp", listenAddr)
	if err != nil {
		log.Fatalf("listen %s: %v", listenAddr, err)
	}
	defer listener.Close()

	log.Printf("Go transparent TCP relay listening on %s -> Nginx %s", listenAddr, nginxAddress)
	for {
		conn, err := listener.Accept()
		if err != nil {
			log.Printf("accept: %v", err)
			continue
		}
		go handleClient(conn)
	}
}
