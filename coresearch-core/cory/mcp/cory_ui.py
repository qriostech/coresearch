"""UI action MCP server for the cory agent.

HTTP-based, runs as its own long-lived process inside the cory container on
port 8004 (sibling of cory.mcp.postgres which owns 8002). Exposes tools that
let cory influence what the user sees in the frontend — currently limited to
highlighting iterations on the canvas.

Architecture
------------
This server holds NO state. Each tool call translates to a single POST to the
controlplane's ``/internal/cory/ui-event`` endpoint, which emits an event on
the controlplane event bus. Connected frontend WebSocket clients receive the
event and update a transient set of highlighted iterations in their canvas
store. There is no DB row, no audit trail, no persistence — reload the page
and the highlights are gone. This is intentional: cory's UI hints are
ephemeral attention nudges, not part of the experiment record.

Why a separate MCP server (instead of more tools on cory.mcp.postgres):
the postgres server's mental model is "SQL access scoped to the cory role".
UI actions have nothing to do with postgres, so mixing them in would be
misleading to both readers and to the agent reading tool descriptions. A
second server with its own focused surface is clearer — and the cost is just
one extra port and one extra entry in ``~/.claude.json``.
"""
import json
import os
import uuid
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from shared.logging import StructuredLogger

log = StructuredLogger("cory-ui-mcp")

CONTROLPLANE_URL = os.environ.get("CONTROLPLANE_URL", "http://controlplane:8000")

# Bind to 0.0.0.0 inside the container so other docker-compose services can
# reach us; port mapping in docker-compose.yaml restricts host-side access to
# 127.0.0.1:8004. Same DNS-rebinding bypass note as cory.mcp.postgres applies.
mcp = FastMCP("coresearch-ui", host="0.0.0.0", port=8004)

# One module-level async client, reused across tool calls. Lifetime is the
# lifetime of the process — FastMCP doesn't expose a shutdown hook so we let
# the OS clean up on exit.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=CONTROLPLANE_URL, timeout=10)
    return _client


async def _emit(payload: dict[str, Any]) -> dict[str, Any]:
    """POST a ui-event to the controlplane.

    Returns a JSON-serializable result dict for the agent. Errors are returned
    rather than raised so the agent can recover and continue the conversation.
    """
    try:
        resp = await _get_client().post("/internal/cory/ui-event", json=payload)
        if resp.status_code >= 400:
            return {"ok": False, "error": f"controlplane returned {resp.status_code}: {resp.text}"}
        return {"ok": True}
    except Exception as e:
        log.warn("cory_ui emit failed", payload=payload, error=str(e))
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def highlight_iteration(iteration_id: int, reason: str = "") -> str:
    """Highlight a single iteration in the user's canvas to draw attention.

    Use this when you have identified an iteration the user should look at —
    for example, the best result on a metric, an unexpected regression, an
    outlier worth investigating, or the iteration that answers the user's
    question. The highlight is a pulsing border on the iteration node plus a
    small chip showing ``reason`` next to it.

    Highlights are ephemeral and transient: they live in the frontend only,
    are visible to all connected tabs, and disappear on page reload. They do
    NOT modify the iteration row in the database. The user can dismiss any
    highlight by clicking it; you can dismiss your own with
    ``unhighlight_iteration`` or wipe the slate with ``clear_highlights``.

    Args:
        iteration_id: The ``iterations.id`` (integer primary key) of the row
            you want to highlight. Use the postgres MCP server to look it up
            if you only have a hash.
        reason: Short text shown on the chip next to the iteration. Aim for
            under ~40 characters; this is read at a glance, not as prose.
            Examples: "best F1", "regression vs parent", "outlier loss".

    Returns:
        JSON ``{"ok": true}`` on success or ``{"ok": false, "error": "..."}``
        if the controlplane was unreachable.
    """
    log.info("highlight_iteration", iteration_id=iteration_id, reason=reason)
    return json.dumps(await _emit({
        "kind": "highlight",
        "iteration_id": iteration_id,
        "reason": reason,
    }))


@mcp.tool()
async def highlight_iterations(iteration_ids: list[int], reason: str = "") -> str:
    """Highlight several iterations at once with a shared reason.

    Use this when you want to draw the user's attention to a group — for
    example, "compare these three approaches" or "all iterations where the
    accuracy dropped". Each iteration gets the same ``reason`` chip; under
    the hood this is just N independent highlight events, so individual
    iterations can be dismissed independently afterwards.

    Args:
        iteration_ids: List of ``iterations.id`` integers. Reasonable upper
            bound is ~10; highlighting dozens of iterations defeats the
            purpose of "drawing attention" and makes the canvas noisy.
        reason: Short text shown on the chip next to each iteration. See
            ``highlight_iteration`` for guidance.

    Returns:
        JSON ``{"ok": true, "count": N}`` on success, with ``count`` being
        the number of highlights successfully emitted. On any failure the
        result includes ``"errors": [...]`` with one entry per failed event.
    """
    log.info("highlight_iterations", iteration_ids=iteration_ids, reason=reason)
    results = []
    errors = []
    for iid in iteration_ids:
        r = await _emit({"kind": "highlight", "iteration_id": iid, "reason": reason})
        if r.get("ok"):
            results.append(iid)
        else:
            errors.append({"iteration_id": iid, "error": r.get("error")})
    out: dict[str, Any] = {"ok": len(errors) == 0, "count": len(results)}
    if errors:
        out["errors"] = errors
    return json.dumps(out)


@mcp.tool()
async def unhighlight_iteration(iteration_id: int) -> str:
    """Remove the highlight from a single iteration.

    Use when you've moved on from an iteration you previously flagged and
    don't want to leave stale chips on the user's canvas. No-op (still
    returns ok) if the iteration wasn't highlighted in the first place.

    Args:
        iteration_id: The ``iterations.id`` to unhighlight.
    """
    log.info("unhighlight_iteration", iteration_id=iteration_id)
    return json.dumps(await _emit({
        "kind": "unhighlight",
        "iteration_id": iteration_id,
    }))


@mcp.tool()
async def clear_highlights() -> str:
    """Remove ALL active highlights from the user's canvas.

    Use this between distinct topics in a conversation, or when the user
    explicitly asks you to start fresh. There is no undo — if you wipe
    highlights you wanted to keep, you'll need to re-emit them.

    Note: this only clears highlights, not fork suggestions. Use
    ``clear_suggestions`` for those.
    """
    log.info("clear_highlights")
    return json.dumps(await _emit({"kind": "clear"}))


# --- Fork suggestions ---------------------------------------------------------
#
# Suggestions are a richer attention channel than highlights: they pair an
# iteration (the source) with an idea (what to try next). They surface in the
# frontend as a separate "cory suggestions" pill — clicking an entry pre-fills
# the existing fork dialog so the user can review and submit. The suggestion
# itself does NOT create a fork on its own; the user always has the final say.

@mcp.tool()
async def suggest_fork(iteration_id: int, idea: str) -> str:
    """Suggest that the user fork from a specific iteration to explore an idea.

    Use this whenever you've identified a promising direction the experiment
    hasn't tried yet. The suggestion appears in a sidebar pill on the user's
    canvas with the iteration hash and your ``idea`` text; the user can click
    "fork" to open the fork dialog pre-populated with the iteration and a
    name derived from your idea, or dismiss the suggestion entirely.

    Suggestions are ephemeral (lost on page reload) and do NOT modify the
    database. They're a hint to the user, not a commitment — the user always
    decides whether to actually create the fork.

    Args:
        iteration_id: The ``iterations.id`` to fork FROM. Look it up via the
            postgres MCP server if you only have a hash.
        idea: A short description of what the fork should explore. One or two
            sentences is ideal — this is what the user sees when deciding
            whether to act on the suggestion. Examples: "Try a deeper network
            with dropout 0.3 to see if the overfitting at iter 12 was about
            capacity." / "Switch to focal loss to handle the class imbalance
            we observed in the metrics."

    Returns:
        JSON ``{"ok": true, "suggestion_id": "..."}`` on success. Save the
        ``suggestion_id`` if you might want to retract it later via
        ``unsuggest_fork``. On failure: ``{"ok": false, "error": "..."}``.
    """
    suggestion_id = str(uuid.uuid4())
    log.info("suggest_fork", iteration_id=iteration_id, suggestion_id=suggestion_id, idea=idea)
    result = await _emit({
        "kind": "suggest_fork",
        "iteration_id": iteration_id,
        "idea": idea,
        "suggestion_id": suggestion_id,
    })
    if result.get("ok"):
        result["suggestion_id"] = suggestion_id
    return json.dumps(result)


@mcp.tool()
async def unsuggest_fork(suggestion_id: str) -> str:
    """Retract a specific fork suggestion.

    Use when you've changed your mind about a suggestion you made earlier in
    the conversation, or when the user has implicitly addressed it by doing
    something else. Pass the ``suggestion_id`` returned from the original
    ``suggest_fork`` call.

    Args:
        suggestion_id: The UUID returned by ``suggest_fork``. No-op if the
            suggestion was already dismissed by the user or never existed.
    """
    log.info("unsuggest_fork", suggestion_id=suggestion_id)
    return json.dumps(await _emit({
        "kind": "unsuggest_fork",
        "suggestion_id": suggestion_id,
    }))


@mcp.tool()
async def clear_suggestions() -> str:
    """Remove ALL active fork suggestions from the user's canvas.

    Use between distinct conversation topics or when the user explicitly
    asks for a clean slate. Only clears suggestions — highlights are
    unaffected. Use ``clear_highlights`` for those.
    """
    log.info("clear_suggestions")
    return json.dumps(await _emit({"kind": "clear_suggestions"}))


def main():
    log.info(
        "starting cory ui MCP server",
        host="0.0.0.0", port=8004, path="/mcp",
        controlplane_url=CONTROLPLANE_URL,
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
