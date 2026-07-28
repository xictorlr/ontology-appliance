from __future__ import annotations

import asyncio
from types import SimpleNamespace

from flask import Flask, Response
from httpx import Headers

from ontology_appliance_gateway import cloud_function


def test_cloud_function_adapter_preserves_gateway_path_query_and_response() -> None:
    framework = Flask(__name__)

    with framework.test_request_context("/healthz?probe=1", method="GET") as context:
        async def invoke_from_event_loop_thread() -> Response:
            return cloud_function.semantic_gateway(context.request)

        response = asyncio.run(invoke_from_event_loop_thread())

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.content_type == "application/json"
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["publicationState"] == "CANDIDATE"
    assert payload["servingMode"] == "DEMO_ONLY"


def test_cloud_function_adapter_preserves_application_authorization(monkeypatch) -> None:
    framework = Flask(__name__)
    captured: dict[str, object] = {}

    class CapturingClient:
        def request(self, method, target, *, headers, content):
            captured.update(
                method=method,
                target=target,
                headers=headers,
                content=content,
            )
            return SimpleNamespace(
                content=b'{"accepted":true}',
                status_code=202,
                headers=Headers({"content-type": "application/json"}),
            )

    monkeypatch.setattr(cloud_function, "_client", CapturingClient())

    with framework.test_request_context(
        "/v1/resolve",
        method="POST",
        headers={
            "Authorization": "Bearer deliberately-invalid-firebase-session",
            "Content-Type": "application/json",
        },
        data=b'{"term":"Party"}',
    ) as context:
        response = cloud_function.semantic_gateway(context.request)

    assert response.status_code == 202
    assert captured["method"] == "POST"
    assert captured["target"] == "/v1/resolve"
    assert captured["content"] == b'{"term":"Party"}'
    assert captured["headers"]["Authorization"] == (
        "Bearer deliberately-invalid-firebase-session"
    )


def test_cloud_function_adapter_drops_hop_by_hop_request_headers(monkeypatch) -> None:
    framework = Flask(__name__)
    captured: dict[str, object] = {}

    class CapturingClient:
        def request(self, method, target, *, headers, content):
            captured["headers"] = headers
            return SimpleNamespace(
                content=b"ok",
                status_code=200,
                headers=Headers(
                    {
                        "content-type": "text/plain",
                        "connection": "close",
                    }
                ),
            )

    monkeypatch.setattr(cloud_function, "_client", CapturingClient())

    with framework.test_request_context(
        "/healthz",
        method="GET",
        headers={"Connection": "close", "Host": "untrusted.example"},
    ) as context:
        response = cloud_function.semantic_gateway(context.request)

    assert response.status_code == 200
    assert "connection" not in {
        name.lower() for name in captured["headers"]
    }
    assert "host" not in {name.lower() for name in captured["headers"]}
    assert "connection" not in {name.lower() for name in response.headers.keys()}
