"""HTTP proxy to the cory container.

Single-endpoint analogue of runner_proxy.py — there is only one cory container,
so we keep one process-wide httpx.Client pointed at CORY_URL (defaults to the
docker-compose service hostname). Used by the cory_sessions router.
"""
import os

import httpx
from fastapi import HTTPException

from shared.logging import request_id_var

from controlplane import log

CORY_URL = os.environ.get("CORY_URL", "http://cory:8003")

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=CORY_URL, timeout=120)
    return _client


def cory_call(method: str, path: str, **kwargs):
    rid = request_id_var.get()
    headers = kwargs.pop("headers", {})
    if rid:
        headers["x-request-id"] = rid
    kwargs["headers"] = headers

    client = _get_client()
    log.debug("cory call", cory_method=method, cory_path=path)
    try:
        resp = client.request(method, path, **kwargs)
    except httpx.RequestError as e:
        log.error("cory call connection failed", cory_path=path, error=str(e))
        raise HTTPException(status_code=503, detail=f"cory unreachable: {e}")
    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json().get("detail", detail)
        except Exception:
            pass
        log.error("cory call failed", cory_path=path, status=resp.status_code, detail=detail)
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp
