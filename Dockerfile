
# =========================================================
# STAGE 1: GO BUILDER
# =========================================================
FROM --platform=$BUILDPLATFORM golang:1.23-bookworm AS gobuild

ARG TARGETOS
ARG TARGETARCH

WORKDIR /src

COPY proxy_wrapper.go app.go wsproxy.go ./

RUN set -eux; \
    GOOS="${TARGETOS:-linux}"; \
    GOARCH="${TARGETARCH:-amd64}"; \
    CGO_ENABLED=0 GOOS="$GOOS" GOARCH="$GOARCH" \
      go build -trimpath -ldflags="-s -w" \
      -o /out/mux ./proxy_wrapper.go ./app.go; \
    CGO_ENABLED=0 GOOS="$GOOS" GOARCH="$GOARCH" \
      go build -trimpath -ldflags="-s -w" \
      -o /out/ssh-wsproxy ./wsproxy.go


# =========================================================
# STAGE 2: RUNTIME
# =========================================================
FROM debian:bookworm-slim

ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Jakarta
ENV DATA_DIR=/data
ENV PORT=8080

WORKDIR /app


# =========================================================
# SYSTEM DEPENDENCIES
# =========================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    unzip \
    xz-utils \
    tar \
    bash \
    socat \
    openssl \
    net-tools \
    iproute2 \
    iputils-ping \
    procps \
    psmisc \
    supervisor \
    nginx \
    dropbear \
    stunnel4 \
    build-essential \
    cmake \
    git \
    pkg-config \
    libssl-dev \
    zlib1g-dev \
    && mkdir -p \
       /etc/stunnel \
       /var/run/stunnel \
       /etc/dropbear \
       /var/run/dropbear \
       /data \
    && chmod 0755 /etc/stunnel \
    && rm -rf /var/lib/apt/lists/*


# =========================================================
# ARCHITECTURE DETECTION
# =========================================================
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) \
        XRAY_ARCH="64"; \
        CF_ARCH="amd64"; \
        ;; \
      arm64) \
        XRAY_ARCH="arm64-v8a"; \
        CF_ARCH="arm64"; \
        ;; \
      *) \
        echo "Unsupported architecture: ${TARGETARCH}"; \
        exit 1; \
        ;; \
    esac; \
    echo "$XRAY_ARCH" > /tmp/xray_arch; \
    echo "$CF_ARCH" > /tmp/cf_arch


# =========================================================
# GO APPLICATION BINARIES
# =========================================================
COPY --from=gobuild /out/mux /usr/local/bin/mux
COPY --from=gobuild /out/ssh-wsproxy /usr/local/bin/ssh-wsproxy

RUN chmod 0755 \
    /usr/local/bin/mux \
    /usr/local/bin/ssh-wsproxy


# =========================================================
# XRAY CORE
# =========================================================
RUN set -eux; \
    XRAY_ARCH="$(cat /tmp/xray_arch)"; \
    mkdir -p /usr/local/bin/xray; \
    curl -fL --retry 3 \
      "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${XRAY_ARCH}.zip" \
      -o /tmp/xray.zip; \
    unzip -o /tmp/xray.zip -d /usr/local/bin/xray; \
    test -f /usr/local/bin/xray/xray; \
    chmod 0755 /usr/local/bin/xray/xray; \
    ln -sf /usr/local/bin/xray/xray /usr/local/bin/xray-core; \
    rm -f /tmp/xray.zip


# =========================================================
# CLOUDFLARED
# =========================================================
RUN set -eux; \
    CF_ARCH="$(cat /tmp/cf_arch)"; \
    curl -fL --retry 3 \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" \
      -o /usr/local/bin/cloudflared; \
    chmod 0755 /usr/local/bin/cloudflared; \
    /usr/local/bin/cloudflared --version


# =========================================================
# BADVPN UDPGW
# =========================================================
RUN set -eux; \
    git clone --depth 1 \
      https://github.com/ambrop72/badvpn.git /tmp/badvpn; \
    cmake -S /tmp/badvpn -B /tmp/badvpn-build \
      -DBUILD_NOTHING_BY_DEFAULT=ON \
      -DBUILD_UDPGW=ON \
      -DBUILD_EXAMPLES=OFF \
      -DBUILD_TESTS=OFF; \
    cmake --build /tmp/badvpn-build --parallel 2; \
    UDPGW_BIN="$(find /tmp/badvpn-build -type f -name badvpn-udpgw -perm /111 -print -quit)"; \
    test -n "$UDPGW_BIN"; \
    install -m 0755 "$UDPGW_BIN" /usr/local/bin/badvpn-udpgw; \
    rm -rf /tmp/badvpn /tmp/badvpn-build


# =========================================================
# DROPBEAR BANNER
# =========================================================
RUN printf '%s\n' \
'=================================================' \
'                  SELAMAT MENIKMATI' \
'             PREMIUM SSH SERVER DROPBEAR modssh3' \
'=================================================' \
'       Dilarang Torrent / DDOS / Hacking!' \
'                 Powered By: dedefathu' \
'=================================================' \
> /etc/dropbear_banner


# =========================================================
# STUNNEL DIRECTORIES
# =========================================================
RUN mkdir -p /etc/stunnel /var/run/stunnel \
    && chmod 0755 /etc/stunnel


# =========================================================
# NGINX CONFIGURATION
# =========================================================
COPY nginx.conf /etc/nginx/nginx.conf


# =========================================================
# APPLICATION FILES
# =========================================================
COPY index.html /app/index.html
COPY config.json /app/config.json
COPY start.sh /app/start.sh

RUN chmod 0755 /app/start.sh


# =========================================================
# PERSISTENT DATA
# =========================================================
RUN mkdir -p /data

VOLUME ["/data"]


# =========================================================
# EXPOSE PORTS
# =========================================================
EXPOSE 8080
EXPOSE 22
EXPOSE 443
EXPOSE 7300


# =========================================================
# START APPLICATION
# =========================================================
CMD ["/app/start.sh"]
