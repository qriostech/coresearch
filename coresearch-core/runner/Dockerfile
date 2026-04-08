FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    apt-get update && \
    apt-get install -y --no-install-recommends tmux git rsync curl xz-utils ca-certificates file && \
    rm -rf /var/lib/apt/lists/*

ARG TARGETOS
ARG TARGETARCH
ARG NODE_VERSION=22.22.2

RUN case "$TARGETARCH" in \
      amd64) NODE_ARCH="x64" ;; \
      arm64) NODE_ARCH="arm64" ;; \
      *) echo "Unsupported TARGETARCH: $TARGETARCH" && exit 1 ;; \
    esac && \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-${TARGETOS}-${NODE_ARCH}.tar.xz" \
    | tar -xJ -C /usr/local --strip-components=1 && \
    node --version && npm --version && file /usr/local/bin/node

RUN npm install -g @anthropic-ai/claude-code @openai/codex

RUN useradd -m -s /bin/bash coresearch && \
    echo 'alias claude="claude --dangerously-skip-permissions"' >> /home/coresearch/.bashrc && \
    echo 'set -g status off' > /home/coresearch/.tmux.conf

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coresearch-core/runner/ ./runner/
COPY coresearch-core/shared/ ./shared/

RUN chown -R coresearch:coresearch /app

USER coresearch

CMD ["uvicorn", "runner.api:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
