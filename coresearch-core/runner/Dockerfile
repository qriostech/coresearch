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

# Trust-dialog bypass helper. Branch tmux sessions cd into dynamic per-branch
# dirs under /data/sessions/<uuid>/..., so we can't pre-populate the claude
# `projects` map at build time the way the cory image does. Instead, the
# `claude` bash function below primes the current cwd lazily on every
# invocation by calling this script before launching real claude. The script
# is idempotent — re-running for an already-trusted dir is a no-op write.
COPY coresearch-core/scripts/claude-trust-cwd.py /usr/local/bin/claude-trust-cwd
RUN chmod 0755 /usr/local/bin/claude-trust-cwd

# Create the runtime user, install the claude wrapper function, and silence
# tmux's status bar. The function:
#   - calls claude-trust-cwd "$(pwd)" to mark the current dir as trusted in
#     ~/.claude.json (suppresses the "do you trust this folder?" prompt)
#   - then invokes the real claude binary with --dangerously-skip-permissions
#     (using `command` to bypass the function and avoid infinite recursion)
# `--dangerously-skip-permissions` covers per-tool prompts; the trust dialog
# is a separate gate handled by the script.
RUN useradd -m -s /bin/bash coresearch && \
    printf '%s\n' \
      'claude() {' \
      '  /usr/local/bin/claude-trust-cwd "$(pwd)" 2>/dev/null || true' \
      '  command claude --dangerously-skip-permissions "$@"' \
      '}' \
      >> /home/coresearch/.bashrc && \
    echo 'set -g status off' > /home/coresearch/.tmux.conf

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coresearch-core/runner/ ./runner/
COPY coresearch-core/shared/ ./shared/

RUN chown -R coresearch:coresearch /app

USER coresearch

CMD ["uvicorn", "runner.api:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
