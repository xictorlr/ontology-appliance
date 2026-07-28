from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.request import Request

import pytest

from ontology_appliance_gateway.cloud_smoke import HttpResponse, RequestFunction, run_smoke


GATEWAY_URL = "https://oa-dev-semantic-gateway-example.europe-west4.run.app"
FUNCTION_GATEWAY_URL = (
    "https://europe-west4-ontology-apliance.cloudfunctions.net/semanticGatewayHttp"
)


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


def test_in_cloud_smoke_accepts_owned_cloud_function_endpoint() -> None:
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
            HttpResponse(403, b"private"),
            HttpResponse(401, b'{"detail":"invalid session"}'),
        ]
    )

    run_smoke(
        {
            "GATEWAY_URL": FUNCTION_GATEWAY_URL,
            "EXPECTED_PUBLICATION_STATE": "CANDIDATE",
        },
        requester=requester,
    )

    assert requests[0].full_url.endswith(
        "audience=https%3A%2F%2Feurope-west4-ontology-apliance.cloudfunctions.net"
        "%2FsemanticGatewayHttp"
    )
    assert requests[1].full_url == f"{FUNCTION_GATEWAY_URL}/healthz"


@pytest.mark.parametrize(
    "gateway_url",
    [
        "http://gateway.run.app",
        "https://gateway.example.com",
        "https://gateway.run.app/extra-path",
        "https://gateway.run.app?tenant=untrusted",
        "https://europe-west4-project.cloudfunctions.net",
        "https://europe-west4-project.cloudfunctions.net/function/extra",
        "https://europe-west4-project.cloudfunctions.net/function?tenant=untrusted",
    ],
)
def test_in_cloud_smoke_rejects_untrusted_gateway_urls(gateway_url: str) -> None:
    with pytest.raises(RuntimeError, match="HTTPS Cloud Run origin or Cloud Functions"):
        run_smoke({"GATEWAY_URL": gateway_url})
