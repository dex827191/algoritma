
# =========================================================
# STAGE 1: BUILD GO APPLICATION (NATIVE BUILD PLATFORM)
# =========================================================
FROM --platform=$BUILDPLATFORM golang:1.23-bookworm AS gobuild

ARG TARGETOS
ARG TARGETARCH

WORKDIR /src

COPY proxy_wrapper.go app.go wsproxy.go ./

RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH:-amd64} \
    go build -trimpath -ldflags="-s -w" \
    -o /out/mux ./proxy_wrapper.go ./app.go \
    && CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH:-amd64} \
    go build -trimpath -ldflags="-s -w" \
    -o /out/ssh-wsproxy ./wsproxy.go


# =========================================================
# STAGE 2: RUNTIME
# =========================================================
FROM debian:bookworm-slim

ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Jakarta

WORKDIR /app

# ---------------------------------------------------------
# SYSTEM DEPENDENCIES
# ---------------------------------------------------------
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
    build-essential \
    cmake \
    git \
    pkg-config \
    libssl-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*


# ---------------------------------------------------------
# ARCHITECTURE DETECTION
# ---------------------------------------------------------
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) \
            XRAY_ARCH="64"; \
            CF_ARCH="amd64"; \
            BADVPN_ARCH="x86_64"; \
            ;; \
        arm64) \
            XRAY_ARCH="arm64-v8a"; \
            CF_ARCH="arm64"; \
            BADVPN_ARCH="aarch64"; \
            ;; \
        *) \
            echo "Unsupported architecture: ${TARGETARCH}"; \
            exit 1; \
            ;; \
    esac; \
    echo "${XRAY_ARCH}" > /tmp/xray_arch; \
    echo "${CF_ARCH}" > /tmp/cf_arch; \
    echo "${BADVPN_ARCH}" > /tmp/badvpn_arch


# ---------------------------------------------------------
# GO APPLICATION BINARIES
# ---------------------------------------------------------
COPY --from=gobuild /out/mux /usr/local/bin/mux
COPY --from=gobuild /out/ssh-wsproxy /usr/local/bin/ssh-wsproxy

RUN chmod +x /usr/local/bin/mux /usr/local/bin/ssh-wsproxy


# ---------------------------------------------------------
# XRAY CORE
# ---------------------------------------------------------
RUN set -eux; \
    XRAY_ARCH="$(cat /tmp/xray_arch)"; \
    mkdir -p /usr/local/bin/xray; \
    curl -fL \
      "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${XRAY_ARCH}.zip" \
      -o /tmp/xray.zip; \
    unzip -o /tmp/xray.zip -d /usr/local/bin/xray; \
    chmod +x /usr/local/bin/xray/xray; \
    ln -sf /usr/local/bin/xray/xray /usr/local/bin/xray-core; \
    rm -f /tmp/xray.zip


# ---------------------------------------------------------
# CLOUDFLARED
# ---------------------------------------------------------
RUN set -eux; \
    CF_ARCH="$(cat /tmp/cf_arch)"; \
    curl -fL \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" \
      -o /usr/local/bin/cloudflared; \
    chmod +x /usr/local/bin/cloudflared


# ---------------------------------------------------------
# DROPBEAR CONFIGURATION
# ---------------------------------------------------------
RUN mkdir -p /etc/dropbear /var/run/dropbear /data

RUN printf '%s\n' \
'=================================================' \
'                  SELAMAT MENIKMATI' \
'             PREMIUM SSH SERVER DROPBEAR modssh3        ' \
'=================================================' \
'       Dilarang Torrent / DDOS / Hacking! ' \
'                 Powered By: dedefathu' \
'=================================================' \
> /etc/dropbear_banner

RUN mkdir -p /etc/dropbear

# ---------------------------------------------------------
# BADVPN UDPGW
# ---------------------------------------------------------
RUN set -eux; \
    git clone --depth 1 https://github.com/ambrop72/badvpn.git /tmp/badvpn; \
    cmake -S /tmp/badvpn -B /tmp/badvpn/build \
      -DBUILD_NOTHING_BY_DEFAULT=1 \
      -DBUILD_UDPGW=1; \
    cmake --build /tmp/badvpn/build --target badvpn-udpgw -j2; \
    install -m 0755 /tmp/badvpn/build/apps/udpgw/badvpn-udpgw /usr/local/bin/badvpn-udpgw; \
    rm -rf /tmp/badvpn


# ---------------------------------------------------------
# NGINX CONFIGURATION
# ---------------------------------------------------------
COPY nginx.conf /etc/nginx/nginx.conf


# ---------------------------------------------------------
# APPLICATION FILES
# ---------------------------------------------------------
COPY app.go /app/app.go
COPY proxy_wrapper.go /app/proxy_wrapper.go
COPY wsproxy.go /app/wsproxy.go
COPY index.html /app/index.html
COPY config.json /app/config.json
COPY start.sh /app/start.sh

RUN chmod +x /app/start.sh


# ---------------------------------------------------------
# PERSISTENT DATA
# ---------------------------------------------------------
VOLUME ["/data"]

ENV DATA_DIR=/data
ENV PORT=8080

EXPOSE 8080
EXPOSE 22
EXPOSE 443
EXPOSE 7300

# ---------------------------------------------------------
# START
# ---------------------------------------------------------
CMD ["/app/start.sh"]
