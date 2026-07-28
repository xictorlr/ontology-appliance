"""Expose the governed FastAPI gateway through Cloud Functions v2."""

from __future__ import annotations

from collections.abc import Iterable

from flask import Request, Response
from starlette.testclient import TestClient

from ontology_appliance_gateway.main import app


_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "content-encoding",
        "content-length",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
app.state.artifact_store.initialize()
_client = TestClient(app)


def _request_headers(request: Request) -> dict[str, str]:
    return {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in _HOP_BY_HOP_HEADERS and name.lower() != "host"
    }


def _response_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        (name, value)
        for name, value in headers
        if name.lower() not in _HOP_BY_HOP_HEADERS
    ]


def semantic_gateway(request: Request) -> Response:
    """Forward one Functions Framework request into the immutable ASGI app."""

    path = request.path or "/"
    query = request.query_string.decode("ascii", errors="strict")
    target = f"{path}?{query}" if query else path
    response = _client.request(
        request.method,
        target,
        headers=_request_headers(request),
        content=request.get_data(cache=True),
    )
    return Response(
        response.content,
        status=response.status_code,
        headers=_response_headers(response.headers.multi_items()),
    )
