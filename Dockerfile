FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget unzip cmake build-essential nginx python3 procps dropbear stunnel4 openssl sudo passwd \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
    && unzip /tmp/xray.zip xray -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray && rm -f /tmp/xray.zip

# Build BADVPN UDPGW (dedicated UDP gateway for SSH clients)
RUN wget -q \
    https://github.com/ambrop72/badvpn/archive/refs/tags/1.999.130.tar.gz \
    -O /tmp/badvpn.tar.gz \
    && tar -xzf /tmp/badvpn.tar.gz -C /tmp \
    && cd /tmp/badvpn-1.999.130 \
    && mkdir build \
    && cd build \
    && cmake .. \
        -DBUILD_NOTHING_BY_DEFAULT=1 \
        -DBUILD_UDPGW=1 \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
    && cmake --build . --target badvpn-udpgw -j"$(nproc)" \
    && find /tmp/badvpn-1.999.130/build -type f -name badvpn-udpgw \
        -exec cp {} /usr/local/bin/badvpn-udpgw \; \
    && test -x /usr/local/bin/badvpn-udpgw \
    && chmod +x /usr/local/bin/badvpn-udpgw \
    && rm -rf /tmp/badvpn-1.999.130 /tmp/badvpn.tar.gz

# Install official Ookla Speedtest CLI for the panel's speed test feature.
RUN curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash \
    && apt-get update && apt-get install -y --no-install-recommends speedtest \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x /usr/local/bin/cloudflared
COPY . /app/
RUN chmod +x /app/start.sh \
    && mkdir -p /var/run/dropbear /var/run/stunnel /etc/dropbear /etc/stunnel /etc/ssh-sni
EXPOSE 2053 8080 8081 7300/udp
CMD ["/app/start.sh"]
