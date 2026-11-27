# ---------- Stage 1: build badvpn-udpgw ----------
FROM debian:bookworm-slim AS badvpn-builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential cmake \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL https://github.com/ambrop72/badvpn/archive/refs/tags/1.999.130.tar.gz | tar -xz \
 && cd badvpn-1.999.130 && mkdir build && cd build \
 && cmake .. -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 \
 && make -j"$(nproc)" badvpn-udpgw

# ---------- Stage 2: runtime ----------
FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip nginx python3 procps dropbear stunnel4 \
    openssl sudo passwd jq socat iproute2 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
    && unzip /tmp/xray.zip xray geoip.dat geosite.dat -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray && rm -f /tmp/xray.zip

RUN curl -fsSL -o /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x /usr/local/bin/cloudflared

# badvpn-udpgw → net-worker (alias kamu)
COPY --from=badvpn-builder /src/badvpn-1.999.130/build/udpgw/badvpn-udpgw /usr/local/bin/net-worker

COPY . /app/
RUN chmod +x /app/start.sh /usr/local/bin/net-worker \
    && mkdir -p /var/run/dropbear /var/run/stunnel /etc/dropbear /etc/stunnel /etc/ssh-sni /run

EXPOSE 2053 8080 8081 7300
EXPOSE 7300/udp

CMD ["/app/start.sh"]