from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


METADATA_IDENTITY_URL: Final = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/identity"
)
RequestFunction = Callable[[Request, float], "HttpResponse"]


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


def _request(request: Request, timeout: float) -> HttpResponse:
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return HttpResponse(status=response.status, body=response.read())
    except HTTPError as error:
        return HttpResponse(status=error.code, body=error.read())


def _required_environment(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value


def _validate_gateway_url(raw_url: str) -> str:
    gateway_url = raw_url.rstrip("/")
    parsed = urlparse(gateway_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".run.app")
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("GATEWAY_URL must be an HTTPS Cloud Run service origin.")
    return gateway_url


def _expected_publication(environment: Mapping[str, str]) -> tuple[str, str, bool]:
    publication_state = environment.get("EXPECTED_PUBLICATION_STATE", "CANDIDATE").strip()
    if publication_state == "CANDIDATE":
        return publication_state, "DEMO_ONLY", False
    if publication_state == "PUBLISHED":
        return publication_state, "ACTIVE", True
    raise RuntimeError("EXPECTED_PUBLICATION_STATE must be CANDIDATE or PUBLISHED.")


def _identity_token(
    gateway_url: str,
    requester: RequestFunction,
    timeout: float,
) -> str:
    metadata_request = Request(
        f"{METADATA_IDENTITY_URL}?audience={quote(gateway_url, safe='')}",
        headers={"Metadata-Flavor": "Google"},
    )
    response = requester(metadata_request, timeout)
    token = response.body.decode("utf-8", errors="strict").strip()
    if response.status != 200 or token.count(".") != 2:
        raise RuntimeError("The Cloud Run metadata server did not issue a valid ID token.")
    return token


def _json_object(response: HttpResponse, operation: str) -> dict[str, object]:
    try:
        payload = json.loads(response.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(f"{operation} did not return JSON.") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"{operation} did not return a JSON object.")
    return payload


def run_smoke(
    environment: Mapping[str, str] | None = None,
    requester: RequestFunction | None = None,
) -> None:
    environment = os.environ if environment is None else environment
    requester = _request if requester is None else requester
    gateway_url = _validate_gateway_url(_required_environment(environment, "GATEWAY_URL"))
    expected_state, expected_mode, expected_published = _expected_publication(environment)
    timeout = 15.0
    token = _identity_token(gateway_url, requester, timeout)

    health = requester(
        Request(
            f"{gateway_url}/healthz",
            headers={"X-Serverless-Authorization": f"Bearer {token}"},
        ),
        timeout,
    )
    if health.status != 200:
        raise RuntimeError(f"Authenticated gateway health returned HTTP {health.status}.")
    health_payload = _json_object(health, "Authenticated gateway health")
    if not (
        health_payload.get("status") == "ok"
        and health_payload.get("publicationState") == expected_state
        and health_payload.get("servingMode") == expected_mode
        and health_payload.get("isPublished") is expected_published
    ):
        raise RuntimeError("Gateway health does not match the governed publication state.")

    expected_version = environment.get("EXPECTED_ONTOLOGY_VERSION", "").strip()
    if expected_version and health_payload.get("ontologyVersion") != expected_version:
        raise RuntimeError("Gateway health does not expose the expected ontology version.")

    unauthenticated = requester(Request(f"{gateway_url}/healthz"), timeout)
    if unauthenticated.status not in {401, 403, 404}:
        raise RuntimeError(
            f"Unauthenticated gateway health returned HTTP {unauthenticated.status}."
        )

    invalid_session = requester(
        Request(
            f"{gateway_url}/v1/resolve",
            data=b'{"term":"Party"}',
            method="POST",
            headers={
                "Authorization": "Bearer deliberately-invalid-firebase-session",
                "Content-Type": "application/json",
                "X-Serverless-Authorization": f"Bearer {token}",
            },
        ),
        timeout,
    )
    if invalid_session.status != 401:
        raise RuntimeError(
            f"Invalid Firebase session returned HTTP {invalid_session.status}, expected 401."
        )

    print(
        "In-cloud gateway smoke passed "
        f"(publicationState={expected_state}, servingMode={expected_mode})."
    )


if __name__ == "__main__":
    run_smoke()
