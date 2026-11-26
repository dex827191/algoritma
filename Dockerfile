FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip nginx python3 procps sudo dropbear-bin stunnel4 openssl passwd \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
    && unzip /tmp/xray.zip xray -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && rm -f /tmp/xray.zip

RUN curl -fsSL -o /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x /usr/local/bin/cloudflared

COPY config.json nginx.conf app.py proxy_wrapper.py index.html start.sh /app/
COPY addssh delssh listssh mux.py ws-proxy.py /usr/local/bin/
RUN chmod +x /app/start.sh /usr/local/bin/addssh /usr/local/bin/delssh \
    /usr/local/bin/listssh /usr/local/bin/mux.py /usr/local/bin/ws-proxy.py \
    && mkdir -p /etc/ssh-sni /etc/dropbear /etc/stunnel

EXPOSE 8080
CMD ["/app/start.sh"]
