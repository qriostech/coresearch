import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shared.logging import StructuredLogger, request_id_var


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger: StructuredLogger, generate_request_id: bool = False):
        super().__init__(app)
        self.logger = logger
        self.generate_request_id = generate_request_id

    async def dispatch(self, request: Request, call_next):
        # Get or generate request ID
        if self.generate_request_id:
            rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:8]
        else:
            rid = request.headers.get("x-request-id")

        request_id_var.set(rid)

        method = request.method
        path = request.url.path

        # Skip logging for polling and health endpoints
        skip_log = (
            path in ("/health", "/internal/health", "/internal/branches", "/internal/sessions/active")
            or path.startswith("/seeds/") and method == "GET"  # branch list polling
            or "/iterations" in path and method == "GET"  # iteration polling
            or "/session-alive" in path  # session liveness polling
            or "/sessions/alive" in path  # runner-side liveness check
        )

        if not skip_log:
            self.logger.debug("request started", method=method, path=path)

        start = time.monotonic()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000)
            self.logger.error(
                "request failed",
                method=method,
                path=path,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise

        duration_ms = round((time.monotonic() - start) * 1000)

        if not skip_log:
            log_fn = self.logger.error if response.status_code >= 500 else self.logger.info
            log_fn(
                "request completed",
                method=method,
                path=path,
                status=response.status_code,
                duration_ms=duration_ms,
            )

        # Add request ID to response headers
        if rid:
            response.headers["x-request-id"] = rid

        return response
