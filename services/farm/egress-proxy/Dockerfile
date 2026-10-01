# Egress proxy for farm agents: public internet over 80/443 only, private and local ranges denied, every request logged.
FROM debian:13-slim
RUN apt-get update && apt-get install -y --no-install-recommends squid && rm -rf /var/lib/apt/lists/*
COPY squid.conf /etc/squid/squid.conf
EXPOSE 3128
CMD ["squid", "-N", "-f", "/etc/squid/squid.conf"]
