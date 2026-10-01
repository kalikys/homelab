# Claude Code headless runner for farm agents. No secrets baked in; no direct internet (egress proxy only).
FROM debian:13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl python3 git ripgrep jq \
    weasyprint python3-matplotlib fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 agent && install -d -o agent -g agent /work
USER agent
ARG CLAUDE_VERSION=2.1.286
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_VERSION}"
ENV PATH=/home/agent/.local/bin:$PATH
COPY runner.py render_deck.py panel.py /app/
# The server runs as root (capabilities limited in compose) and starts every agent as uid 1000.
USER root
EXPOSE 8080
CMD ["python3", "/app/runner.py"]
