"""Postgres MCP server for the cory agent.

HTTP-based. Runs as its own long-lived docker-compose service (``mcp-postgres``)
and exposes a streamable-HTTP MCP endpoint at ``/mcp`` on port 8002. Any MCP
client can connect:

  - From inside the docker network: ``http://mcp-postgres:8002/mcp``
    (the cory agent in controlplane, claude in the runner container, etc.)
  - From the host machine:          ``http://localhost:8002/mcp``
    (a developer's local claude install)

Tools execute against the controlplane database under the ``cory`` postgres
role, which has read+write but no DDL.

Why role-switching: the controlplane connection pool is configured for the
``coresearch`` user, so we can't just open a fresh connection as ``cory``
without duplicating connection config. Instead, each tool opens a transaction,
calls ``SET LOCAL ROLE cory`` (which is transaction-scoped), runs the SQL,
and commits. The role resets at transaction end. ``coresearch`` is granted
membership in ``cory`` (see storage_definition.sql) so the SET LOCAL is
allowed.
"""
import asyncio
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from connections.postgres.connection import get_cursor
from shared.logging import StructuredLogger

# Distinct service name so cory's log entries are attributable in
# `docker compose logs mcp-postgres` and don't get confused with controlplane's.
log = StructuredLogger("cory-mcp")

# host/port are keyword-only kwargs on FastMCP.__init__ (NOT on mcp.run()).
# Bind to 0.0.0.0 inside the container so other docker-compose services can
# reach us; port mapping in docker-compose.yaml restricts host-side access to
# 127.0.0.1:8002. Note: binding to 0.0.0.0 bypasses FastMCP's auto-enabled
# DNS-rebinding protection (which only triggers for 127.0.0.1/localhost/::1).
# Acceptable here because the only reachable network is the docker-compose
# private network plus host-localhost.
mcp = FastMCP("coresearch-postgres", host="0.0.0.0", port=8002)


def _run_as_cory(sql: str) -> list[dict[str, Any]]:
    """Run a SQL statement under the cory role inside one transaction.

    Returns the result rows as a list of dicts. For statements with no result
    set (INSERT/UPDATE/DELETE without RETURNING), returns an empty list. The
    transaction commits if the statement succeeds and rolls back on any
    exception (handled by get_cursor).
    """
    with get_cursor(autocommit=False) as cur:
        cur.execute("SET LOCAL ROLE cory")
        cur.execute(sql)
        if cur.description is None:
            return []
        return [dict(row) for row in cur.fetchall()]


@mcp.tool()
async def query(sql: str) -> str:
    """Execute a SQL statement against the coresearch database.

    Has read+write access to public-schema tables (SELECT/INSERT/UPDATE/DELETE).
    Cannot run DDL (CREATE/DROP/ALTER) or TRUNCATE — those will fail with a
    permission error returned in the ``error`` field.

    For INSERT/UPDATE/DELETE that should return the affected row, use a
    RETURNING clause — otherwise the result will be an empty list even on
    success.

    Args:
        sql: A single SQL statement.

    Returns:
        JSON-serialized object. On success: ``{"rows": [...]}`` where each
        item is a dict of column name to value. On failure: ``{"error": "..."}``
        — errors are returned rather than raised so the agent can recover and
        try a different query.
    """
    log.info("cory query", sql=sql)
    try:
        rows = await asyncio.to_thread(_run_as_cory, sql)
        return json.dumps({"rows": rows}, default=str)
    except Exception as e:
        log.warn("cory query failed", sql=sql, error=str(e))
        return json.dumps({"error": str(e)})


@mcp.tool()
async def describe_schema() -> str:
    """List every table in the public schema with column names and types.

    Use this when you need to know the database structure before composing a
    query. Returns table_name, column_name, data_type, is_nullable for every
    column, ordered by table and column position.

    Returns:
        JSON-serialized ``{"columns": [{"table_name": ..., "column_name": ...,
        "data_type": ..., "is_nullable": ...}, ...]}``.
    """
    sql = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    rows = await asyncio.to_thread(_run_as_cory, sql)
    return json.dumps({"columns": rows}, default=str)


def main():
    log.info("starting cory postgres MCP server", host="0.0.0.0", port=8002, path="/mcp")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
