"""Cory — the database-aware research agent.

This package owns everything cory-related:
  - cory.mcp.postgres   the postgres MCP server (HTTP, port 8002 in the cory
                        container)
  - cory.api            FastAPI app for cory tmux session lifecycle (port 8003,
                        called by the controlplane to create/kill cory sessions)
  - cory.tmux           tmux helpers used by cory.api
  - cory/.mcp.json      project-scoped MCP client config that points the local
                        claude install at the running cory service
  - (future) cory.agent the LLM client that consumes the MCP server

Cory runs in her own sandbox container (`cory` in docker-compose), which
ships both the postgres MCP server and the claude/codex CLIs so the agent
can run end-to-end without leaning on the controlplane image.

Exposes a single shared StructuredLogger instance so all cory submodules
log under the same service name and share a ring buffer.
"""
from shared.logging import StructuredLogger

log = StructuredLogger("cory")
