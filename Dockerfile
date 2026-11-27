FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# ---- Base dependencies (build tools + library yang dibutuhkan BadVPN) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget unzip nginx python3 procps \
    dropbear-bin stunnel4 openssl sudo passwd \
    iproute2 util-linux \
    build-essential cmake make gcc g++ pkg-config \
    libssl-dev libnspr4-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# ---- Build badvpn udpgw (fix: binary ada di build/udpgw/) ----
RUN wget -q https://github.com/ambrop72/badvpn/archive/refs/tags/1.999.130.tar.gz -O /tmp/badvpn.tar.gz \
 && tar -xzf /tmp/badvpn.tar.gz -C /tmp \
 && cd /tmp/badvpn-1.999.130 \
 && mkdir build && cd build \
 && cmake .. \
      -DBUILD_NOTHING_BY_DEFAULT=1 \
      -DBUILD_UDPGW=1 \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
 && cmake --build . --target badvpn-udpgw -j"$(nproc)" \
 && find /tmp/badvpn-1.999.130/build -type f -name badvpn-udpgw -exec cp {} /usr/local/bin/ \; \
 && chmod +x /usr/local/bin/badvpn-udpgw \
 && rm -rf /tmp/badvpn-1.999.130 /tmp/badvpn.tar.gz

# ---- Xray ----
RUN curl -fsSL -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
 && unzip /tmp/xray.zip xray -d /usr/local/bin/ \
 && chmod +x /usr/local/bin/xray && rm -f /tmp/xray.zip

# ---- Cloudflared ----
RUN curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
 && chmod +x /usr/local/bin/cloudflared

COPY . /app/
RUN chmod +x /app/start.sh \
 && mkdir -p /var/run/dropbear /var/run/stunnel /etc/dropbear /etc/stunnel /etc/ssh-sni

EXPOSE 8080 8081 2053
CMD ["/app/start.sh"]