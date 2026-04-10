FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps:
#   git           — claude/codex shell out to git for repo operations
#   curl, xz-utils, ca-certificates — needed to download Node from nodejs.org
#   file          — only used to verify the downloaded node binary architecture
RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    apt-get update && \
    apt-get install -y --no-install-recommends git curl xz-utils ca-certificates file && \
    rm -rf /var/lib/apt/lists/*

# Node — required for the claude and codex CLIs (both are npm packages). Same
# version pin as the runner image so behaviour is consistent across containers.
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

# Agent CLIs. The cory agent (and any human dropping into the container) uses
# these to talk to LLMs. Claude is also the consumer of the postgres MCP server
# defined at controlplane/mcp/postgres.py.
RUN npm install -g @anthropic-ai/claude-code @openai/codex

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coresearch-core/controlplane/ ./controlplane/
COPY coresearch-core/connections/ ./connections/
COPY coresearch-core/shared/ ./shared/
COPY coresearch-core/cory/ ./cory/

# Symlink the project-scoped .mcp.json into WORKDIR so `claude` invoked from
# /app auto-discovers the cory-postgres MCP server. The actual file lives in
# the cory source dir, which is volume-mounted from the host in
# docker-compose.yaml — so edits on the host take effect without a rebuild.
RUN ln -s /app/cory/.mcp.json /app/.mcp.json

# Create the runtime user, pre-set the claude `--dangerously-skip-permissions`
# alias, and pre-approve the cory-postgres MCP server in the user-level config
# so `claude -p "..."` runs non-interactively — no "trust this project's MCP
# servers?" prompt on first use. The allowedMcpServers entry uses a URL glob
# so any HTTP MCP server at mcp-postgres:8002/* is auto-approved.
RUN useradd -m -s /bin/bash coresearch && \
    echo 'alias claude="claude --dangerously-skip-permissions"' >> /home/coresearch/.bashrc && \
    printf '%s\n' '{"allowedMcpServers":[{"serverUrl":"http://mcp-postgres:8002/*"}]}' > /home/coresearch/.claude.json && \
    chown -R coresearch:coresearch /app /home/coresearch

USER coresearch

CMD ["uvicorn", "controlplane.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
