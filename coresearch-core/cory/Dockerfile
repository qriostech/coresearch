FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps:
#   tmux          — cory.api spawns tmux sessions on demand for the cory agent
#   git           — claude/codex shell out to git for repo operations
#   curl, xz-utils, ca-certificates — needed to download Node from nodejs.org
#   file          — only used to verify the downloaded node binary architecture
RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    apt-get update && \
    apt-get install -y --no-install-recommends tmux git curl xz-utils ca-certificates file && \
    rm -rf /var/lib/apt/lists/*

# Node — required for the claude and codex CLIs (both are npm packages). Same
# version pin as the runner and controlplane images so behaviour is consistent
# across containers.
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

# Agent CLIs. The cory agent (and any human dropping into this container) uses
# these to talk to LLMs. Claude is also the consumer of the postgres MCP server
# defined at cory/mcp/postgres.py — which runs in this same container, so
# claude reaches it over loopback via the cory:8002 service hostname.
RUN npm install -g @anthropic-ai/claude-code @openai/codex

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coresearch-core/connections/ ./connections/
COPY coresearch-core/shared/ ./shared/
COPY coresearch-core/cory/ ./cory/

# Symlink the project-scoped .mcp.json into WORKDIR so `claude` invoked from
# /app auto-discovers the cory-postgres MCP server. The actual file lives in
# the cory source dir, which is volume-mounted from the host in
# docker-compose.yaml — so edits on the host take effect without a rebuild.
RUN ln -s /app/cory/.mcp.json /app/.mcp.json

# Create the runtime user, pre-set the claude `--dangerously-skip-permissions`
# alias, and seed the user-scope claude config so `claude` Just Works from any
# cwd inside the cory container:
#   - hasCompletedOnboarding   skips claude's first-run onboarding flow
#   - mcpServers               defines both MCP servers at user scope, so they
#                              load regardless of cwd. (Project-scope `.mcp.json`
#                              discovery only triggers at a git project root,
#                              which /home/coresearch is not.)
#   - allowedMcpServers        URL-glob trust list that suppresses the "trust
#                              this MCP server?" prompt on first use.
#   - projects.<path>.hasTrustDialogAccepted  pre-accepts the workspace trust
#                              dialog ("Do you trust the files in this folder?")
#                              for the dirs cory tmux sessions actually run in.
#                              `--dangerously-skip-permissions` covers tool
#                              prompts but NOT this trust dialog — they're
#                              separate gates.
RUN useradd -m -s /bin/bash coresearch && \
    echo 'alias claude="claude --dangerously-skip-permissions"' >> /home/coresearch/.bashrc && \
    echo 'set -g status off' > /home/coresearch/.tmux.conf && \
    printf '%s\n' '{"hasCompletedOnboarding":true,"mcpServers":{"coresearch-postgres":{"type":"http","url":"http://cory:8002/mcp"},"coresearch-ui":{"type":"http","url":"http://cory:8004/mcp"}},"allowedMcpServers":[{"serverUrl":"http://cory:8002/*"},{"serverUrl":"http://cory:8004/*"}],"projects":{"/home/coresearch":{"hasTrustDialogAccepted":true},"/app":{"hasTrustDialogAccepted":true}}}' > /home/coresearch/.claude.json && \
    chown -R coresearch:coresearch /app /home/coresearch

USER coresearch

# Three processes share this container:
#   - cory.mcp.postgres   port 8002 — postgres MCP server (read+write SQL)
#   - cory.api            port 8003 — session lifecycle HTTP API
#   - cory.mcp.cory_ui    port 8004 — UI action MCP server (highlights, etc.)
# The two MCP servers are backgrounded and the session API uvicorn runs in
# the foreground so it owns PID 1's signal handling (graceful shutdown of
# the API on `docker compose down`). Hard kill of the backgrounded children
# on uvicorn exit is acceptable for dev — docker-compose restarts the whole
# container anyway.
CMD ["bash", "-c", "python -m cory.mcp.postgres & python -m cory.mcp.cory_ui & exec uvicorn cory.api:app --host 0.0.0.0 --port 8003 --reload"]
