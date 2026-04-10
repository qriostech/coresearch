"""Cory — the controlplane's database-aware agent.

This package owns everything cory-related:
  - cory.mcp.postgres   the postgres MCP server (HTTP, runs as docker-compose
                        service `mcp-postgres`)
  - cory/.mcp.json      project-scoped MCP client config that points the local
                        claude install at the running mcp-postgres service
  - (future) cory.agent the LLM client that consumes the MCP server
  - (future) cory.router the FastAPI router exposing /agent/ask

Cory is logically a sibling of controlplane (and runner) — her own concern,
not embedded inside controlplane's package layout — even though her runtime
home is the controlplane container today.
"""
