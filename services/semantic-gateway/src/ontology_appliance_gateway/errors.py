"""Problem Details errors used by every endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiProblem(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str,
        *,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.code = code
        self.extra = extra or {}


async def problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    payload: dict[str, Any] = {
        "type": f"urn:ontology-appliance:problem:{exc.code}",
        "title": exc.title,
        "status": exc.status,
        "detail": exc.detail,
        "instance": str(request.url.path),
        "code": exc.code,
    }
    if trace_id:
        payload["traceId"] = trace_id
    payload.update(exc.extra)
    return JSONResponse(
        status_code=exc.status,
        content=payload,
        media_type="application/problem+json",
        headers={"X-Trace-Id": trace_id} if trace_id else None,
    )
