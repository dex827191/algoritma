FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip nginx python3 procps \
    dropbear-bin stunnel4 openssl sudo passwd \
    iproute2 util-linux \
    build-essential cmake make gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Build badvpn udpgw
RUN curl -fsSL https://github.com/ambrop72/badvpn/archive/refs/tags/1.999.130.tar.gz | tar -xz \
 && cd badvpn-1.999.130 && mkdir build && cd build \
 && cmake .. -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 \
 && make -j"$(nproc)" badvpn-udpgw \
 && cp badvpn-udpgw /usr/local/bin/ \
 && cd / && rm -rf /badvpn-1.999.130

# Xray
RUN curl -fsSL -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
 && unzip /tmp/xray.zip xray -d /usr/local/bin/ \
 && chmod +x /usr/local/bin/xray && rm -f /tmp/xray.zip

# Cloudflared
RUN curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
 && chmod +x /usr/local/bin/cloudflared

COPY . /app/
RUN chmod +x /app/start.sh \
 && mkdir -p /var/run/dropbear /var/run/stunnel /etc/dropbear /etc/stunnel /etc/ssh-sni

EXPOSE 8080 8081
CMD ["/app/start.sh"]