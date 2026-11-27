
# ============================================================
# BASE IMAGE - AMD64
# ============================================================

FROM --platform=linux/amd64 debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ============================================================
# SYSTEM DEPENDENCIES
# ============================================================

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    unzip \
    nginx \
    python3 \
    procps \
    dropbear-bin \
    stunnel4 \
    openssl \
    sudo \
    passwd \
    iproute2 \
    util-linux \
    file \
    build-essential \
    cmake \
    make \
    gcc \
    g++ \
    pkg-config \
    libssl-dev \
    libnspr4-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# BUILD BADVPN UDPGW
# ============================================================

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
    && cmake --build . \
        --target badvpn-udpgw \
        -j"$(nproc)" \
    && find /tmp/badvpn-1.999.130/build \
        -type f \
        -name badvpn-udpgw \
        -exec cp {} /usr/local/bin/badvpn-udpgw \; \
    && chmod +x /usr/local/bin/badvpn-udpgw \
    && rm -rf /tmp/badvpn-1.999.130 /tmp/badvpn.tar.gz

# ============================================================
# INSTALL XRAY CORE - AMD64
# ============================================================

RUN curl -fSL --retry 3 \
    https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
    -o /tmp/xray.zip \
    && unzip -o /tmp/xray.zip xray -d /usr/local/bin/ \
    && chmod 755 /usr/local/bin/xray \
    && rm -f /tmp/xray.zip

# ============================================================
# INSTALL CLOUDFLARED - AMD64
# ============================================================

RUN curl -fSL --retry 3 \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o /usr/local/bin/cloudflared \
    && chmod 755 /usr/local/bin/cloudflared

# ============================================================
# COPY PROJECT FILES
# ============================================================

COPY . /app/

# ============================================================
# PREPARE DIRECTORIES AND PERMISSIONS
# ============================================================

RUN chmod 755 /app/start.sh \
    && mkdir -p \
        /var/run/dropbear \
        /var/run/stunnel \
        /var/log \
        /etc/dropbear \
        /etc/stunnel \
        /etc/ssh-sni \
        /var/cache/nginx \
        /var/lib/nginx \
    && chmod 755 /usr/local/bin/xray \
    && chmod 755 /usr/local/bin/cloudflared \
    && chmod 755 /usr/local/bin/badvpn-udpgw

# ============================================================
# VERIFY EXECUTABLE FORMATS
# ============================================================

RUN echo "===== VERIFY ARCHITECTURE =====" \
    && uname -m \
    && file /usr/local/bin/xray \
    && file /usr/local/bin/cloudflared \
    && file /usr/local/bin/badvpn-udpgw \
    && /usr/local/bin/xray version \
    && /usr/local/bin/cloudflared --version

# ============================================================
# PUBLIC PORTS
# ============================================================

# 8080 = Railway HTTP gateway / UI / Xray
# 8081 = SSH Mux
# 8880 = SSH WebSocket
# 7300/TCP = SSH UDPGW (BadVPN UDP-over-TCP relay); not used by Xray

EXPOSE 8080
EXPOSE 8081
EXPOSE 8880
EXPOSE 7300/tcp

# ============================================================
# START APPLICATION
# ============================================================

CMD ["/bin/bash", "/app/start.sh"]
