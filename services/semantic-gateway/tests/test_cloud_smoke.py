from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.request import Request

import pytest

from ontology_appliance_gateway.cloud_smoke import HttpResponse, RequestFunction, run_smoke


GATEWAY_URL = "https://oa-dev-semantic-gateway-example.europe-west4.run.app"


def response_sequence(
    responses: list[HttpResponse],
) -> tuple[list[Request], RequestFunction]:
    requests: list[Request] = []
    response_iterator: Iterator[HttpResponse] = iter(responses)

    def requester(request: Request, timeout: float) -> HttpResponse:
        assert timeout == 15.0
        requests.append(request)
        return next(response_iterator)

    return requests, requester


def test_in_cloud_smoke_proves_health_privacy_and_application_authentication() -> None:
    health = {
        "status": "ok",
        "ontologyVersion": "2026.07.1-candidate",
        "publicationState": "CANDIDATE",
        "servingMode": "DEMO_ONLY",
        "isPublished": False,
    }
    requests, requester = response_sequence(
        [
            HttpResponse(200, b"header.payload.signature"),
            HttpResponse(200, json.dumps(health).encode()),
            HttpResponse(404, b"private"),
            HttpResponse(401, b'{"detail":"invalid session"}'),
        ]
    )

    run_smoke(
        {
            "GATEWAY_URL": GATEWAY_URL,
            "EXPECTED_PUBLICATION_STATE": "CANDIDATE",
            "EXPECTED_ONTOLOGY_VERSION": "2026.07.1-candidate",
        },
        requester=requester,
    )

    assert requests[0].headers["Metadata-flavor"] == "Google"
    assert requests[1].headers["X-serverless-authorization"].startswith("Bearer ")
    assert requests[2].headers.get("X-serverless-authorization") is None
    assert requests[3].headers["Authorization"] == (
        "Bearer deliberately-invalid-firebase-session"
    )
    assert requests[3].data == b'{"term":"Party"}'


def test_in_cloud_smoke_rejects_public_gateway_health() -> None:
    requests, requester = response_sequence(
        [
            HttpResponse(200, b"header.payload.signature"),
            HttpResponse(
                200,
                json.dumps(
                    {
                        "status": "ok",
                        "publicationState": "PUBLISHED",
                        "servingMode": "ACTIVE",
                        "isPublished": True,
                    }
                ).encode(),
            ),
            HttpResponse(200, b"unexpectedly public"),
        ]
    )

    with pytest.raises(RuntimeError, match="Unauthenticated gateway health returned HTTP 200"):
        run_smoke(
            {
                "GATEWAY_URL": GATEWAY_URL,
                "EXPECTED_PUBLICATION_STATE": "PUBLISHED",
            },
            requester=requester,
        )
    assert len(requests) == 3


@pytest.mark.parametrize(
    "gateway_url",
    [
        "http://gateway.run.app",
        "https://gateway.example.com",
        "https://gateway.run.app/extra-path",
        "https://gateway.run.app?tenant=untrusted",
    ],
)
def test_in_cloud_smoke_rejects_non_cloud_run_origins(gateway_url: str) -> None:
    with pytest.raises(RuntimeError, match="HTTPS Cloud Run service origin"):
        run_smoke({"GATEWAY_URL": gateway_url})
