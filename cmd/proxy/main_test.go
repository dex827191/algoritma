package main

import (
	"bytes"
	"io"
	"net"
	"testing"
	"time"
)

func TestRelayPreservesBytesBothDirections(t *testing.T) {
	clientRelay, clientPeer := net.Pipe()
	upstreamRelay, upstreamPeer := net.Pipe()
	finished := make(chan struct{})

	go func() {
		relay(clientRelay, upstreamRelay)
		close(finished)
	}()

	request := []byte("POST /xhttp HTTP/1.1\r\nHost: example.test\r\nContent-Length: 7\r\n\r\nPAYLOAD")
	writeDone := make(chan error, 1)
	go func() {
		_, err := clientPeer.Write(request)
		writeDone <- err
	}()
	gotRequest := make([]byte, len(request))
	if _, err := io.ReadFull(upstreamPeer, gotRequest); err != nil {
		t.Fatalf("read forwarded request: %v", err)
	}
	if err := <-writeDone; err != nil {
		t.Fatalf("write request: %v", err)
	}
	if !bytes.Equal(gotRequest, request) {
		t.Fatalf("request changed during relay: got %q, want %q", gotRequest, request)
	}

	response := []byte("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
	go func() { _, _ = upstreamPeer.Write(response) }()
	gotResponse := make([]byte, len(response))
	if _, err := io.ReadFull(clientPeer, gotResponse); err != nil {
		t.Fatalf("read forwarded response: %v", err)
	}
	if !bytes.Equal(gotResponse, response) {
		t.Fatalf("response changed during relay: got %q, want %q", gotResponse, response)
	}

	_ = clientPeer.Close()
	_ = upstreamPeer.Close()
	select {
	case <-finished:
	case <-time.After(2 * time.Second):
		t.Fatal("relay did not stop after both peers closed")
	}
}
