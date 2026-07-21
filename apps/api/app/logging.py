import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_ID_HEADER = "X-Request-ID"
api_logger = logging.getLogger("gate_challenger.api")
worker_logger = logging.getLogger("gate_challenger.worker")
provider_logger = logging.getLogger("gate_challenger.provider")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        request.state.request_id = request_id
        started = time.monotonic()
        response = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            actor_id = getattr(request.state, "actor_id", None)
            api_logger.info(
                "api_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "actor_id": str(actor_id) if actor_id is not None else None,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                },
            )
            if response is not None:
                response.headers[REQUEST_ID_HEADER] = request_id
