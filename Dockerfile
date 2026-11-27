FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip nginx python3 procps bash \
    dropbear-bin openssl passwd \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
    && unzip /tmp/xray.zip xray -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray && rm -f /tmp/xray.zip

RUN curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x /usr/local/bin/cloudflared

RUN mkdir -p /etc/dropbear /etc/ssh-sni \
    && openssl req -new -newkey rsa:2048 -days 3650 -nodes -x509 \
       -subj "/C=ID/ST=Jakarta/L=Jakarta/O=SSHProxy/CN=localhost" \
       -keyout /tmp/stunnel.pem -out /tmp/stunnel.pem

COPY app.py config.json nginx.conf mux.py ws-proxy.py ws-xray.py start.sh /app/
RUN chmod +x /app/start.sh /app/mux.py /app/ws-proxy.py /app/ws-xray.py \
    && printf '{}\n' > /etc/ssh-sni/users.json

EXPOSE 8080 8881
CMD ["/app/start.sh"]