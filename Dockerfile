# syntax=docker/dockerfile:1.7

# =================================================================
# STAGE 1: Builder BadVPN
# =================================================================
FROM ubuntu:22.04 AS badvpn-builder
ENV DEBIAN_FRONTEND=noninteractive

RUN rm -rf /var/lib/apt/lists/* \
 && apt-get clean \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        cmake make gcc g++ curl tar \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN curl -fsSL https://github.com/ambrop72/badvpn/archive/refs/tags/1.999.130.tar.gz | tar -xz \
 && cd badvpn-1.999.130 && mkdir build && cd build \
 && cmake .. -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 \
 && make -j"$(nproc)" badvpn-udpgw

# =================================================================
# STAGE 3: Go binaries (proxy wrapper + SSH WebSocket)
# =================================================================
FROM --platform=$BUILDPLATFORM golang:1.22-bookworm AS go-builder
ARG TARGETOS
ARG TARGETARCH
WORKDIR /build

COPY go.mod go.sum* ./
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download

COPY cmd/ ./cmd/
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -ldflags="-s -w" -o /out/wsproxy ./cmd/wsproxy && \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -ldflags="-s -w" -o /out/proxy-wrapper ./cmd/proxy

# =================================================================
# STAGE 4: Runtime
# =================================================================
FROM ubuntu:22.04 AS runtime
ENV DEBIAN_FRONTEND=noninteractive
ENV PANEL_PORT=2053
WORKDIR /app

# ── Paket sistem ──
RUN rm -rf /var/lib/apt/lists/* \
 && apt-get clean \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && apt-get install -y --no-install-recommends \
        dropbear \
        nginx-full \
        procps \
        psmisc \
        net-tools \
        iproute2 \
        bash \
        jq \
        sudo \
        curl \
        wget \
        unzip \
        python3 \
 && rm -rf /var/lib/apt/lists/*



ARG TARGETARCH
RUN case "${TARGETARCH}" in \
        amd64) CF_ARCH=amd64 ;; \
        arm64) CF_ARCH=arm64 ;; \
        *) echo "Unsupported arch: ${TARGETARCH}" && exit 1 ;; \
    esac && \
    curl -fsSL -o /usr/local/bin/cloudflared \
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" \
 && chmod +x /usr/local/bin/cloudflared

# Official Xray-core release from XTLS/Xray-core (architecture-aware).
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) XRAY_ASSET="Xray-linux-64.zip" ;; \
      arm64) XRAY_ASSET="Xray-linux-arm64-v8a.zip" ;; \
      *) echo "Unsupported Xray architecture: ${TARGETARCH}"; exit 1 ;; \
    esac; \
    mkdir -p /tmp/xray-dist; \
    curl -fsSL "https://github.com/XTLS/Xray-core/releases/latest/download/${XRAY_ASSET}" -o /tmp/xray.zip; \
    unzip -q /tmp/xray.zip -d /tmp/xray-dist; \
    install -m 0755 /tmp/xray-dist/xray /usr/local/bin/xray; \
    /usr/local/bin/xray version; \
    rm -rf /tmp/xray.zip /tmp/xray-dist

# ── Rename binary ──
COPY --from=badvpn-builder /src/badvpn-1.999.130/build/udpgw/badvpn-udpgw /tmp/raw-net
COPY --from=go-builder /out/wsproxy /tmp/raw-stream
COPY --from=go-builder /out/proxy-wrapper /usr/local/bin/proxy-wrapper

RUN cp /usr/sbin/dropbear /usr/local/bin/svc-helper && \
    cp /tmp/raw-net       /usr/local/bin/net-worker && \
    cp /tmp/raw-stream    /usr/local/bin/stream-worker && \
    rm -f /tmp/raw-net /tmp/raw-stream /usr/sbin/dropbear && \
    chmod +x /usr/local/bin/svc-helper /usr/local/bin/net-worker /usr/local/bin/stream-worker

# ── Dropbear host key ──
RUN mkdir -p /etc/dropbear && \
    /usr/local/bin/svc-helper -R && \
    test -f /etc/dropbear/dropbear_rsa_host_key \
    && chmod 600 /etc/dropbear/dropbear_rsa_host_key \
    || (echo "❌ Gagal membuat dropbear host key!" && exit 1)

# ── App code ──
COPY server.py ./server.py
COPY index.html ./index.html
COPY start.sh ./

COPY data/ ./data/

# ── Nginx ──
RUN rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/*.conf
COPY nginx/nginx.conf /etc/nginx/nginx.conf

RUN mkdir -p /var/run /var/log/nginx /var/run/dropbear

RUN nginx -t -c /etc/nginx/nginx.conf 2>&1 || \
    (echo "❌ nginx.conf tidak valid!" && exit 1)

RUN ln -sf /dev/stdout /var/log/nginx/access.log \
 && ln -sf /dev/stderr /var/log/nginx/error.log

RUN chmod +x /app/start.sh /usr/local/bin/proxy-wrapper

EXPOSE 8080 8081 2053 8880 7300
CMD ["bash", "/app/start.sh"]
