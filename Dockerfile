FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip nginx dropbear stunnel4 openssl procps iproute2 passwd jq \
    git build-essential \
    && rm -rf /var/lib/apt/lists/*

# Build only BadVPN UDPGW from upstream source.
RUN git clone --depth 1 https://github.com/ambrop72/badvpn.git /tmp/badvpn \
    && cd /tmp \
    && SRCDIR=/tmp/badvpn CC=gcc ENDIAN=little bash /tmp/badvpn/compile-udpgw.sh \
    && install -m 0755 /tmp/udpgw /usr/local/bin/badvpn-udpgw \
    && rm -rf /tmp/badvpn /tmp/udpgw *.o

# Xray core
RUN curl -fsSL -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
    && unzip /tmp/xray.zip xray -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray && rm -f /tmp/xray.zip

RUN curl -fsSL -o /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x /usr/local/bin/cloudflared

# Go compiler is used only at build time.
RUN curl -fsSL https://go.dev/dl/go1.23.4.linux-amd64.tar.gz | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:${PATH}"
COPY proxy_wrapper.go app.go wsproxy.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /usr/local/bin/mux ./proxy_wrapper.go ./app.go \
    && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /usr/local/bin/ssh-wsproxy ./wsproxy.go \
    && rm -rf /usr/local/go

COPY config.json nginx.conf index.html start.sh /app/
RUN chmod +x /app/start.sh \
    && mkdir -p /var/run/dropbear /etc/dropbear /var/lib/dropbear /data

EXPOSE 8080
CMD ["/app/start.sh"]
