from __future__ import annotations

from fastapi.testclient import TestClient


def _proposal_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "proposalId": "map-01882",
        "statement": "core_banking.customer_master.cif_no realizes enterprise:Customer identifier",
        "evidenceIds": ["ev-schema-description", "ev-data-profile"],
        "counterevidenceIds": [],
        "risk": "MEDIUM",
        "modelDependent": False,
        "generatorProvider": "deterministic-control-plane",
        "generatorModel": "profiling-v1",
        "promptVersion": "not-applicable",
    }
    body.update(overrides)
    return body


def test_verify_is_present_in_openapi_contract(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()
    operation = openapi["paths"]["/v1/verify"]["post"]
    assert operation["operationId"] == "verifyIndependently"
    assert (
        operation["responses"]["default"]["content"]["application/problem+json"]["schema"]
        == {"$ref": "#/components/schemas/ProblemDetails"}
    )


def test_verify_requires_privileged_role(client: TestClient) -> None:
    response = client.post(
        "/v1/verify",
        json=_proposal_body(),
        headers={"Authorization": "Bearer dev:demo-bank:user-1:auditor"},
    )
    assert response.status_code == 403


def test_verify_with_mock_verifier_abstains_and_keeps_governance_envelope(
    client: TestClient,
) -> None:
    response = client.post("/v1/verify", json=_proposal_body())
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ABSTAINED"
    assert body["tenantId"] == "demo-bank"
    assert body["publicationState"] == "CANDIDATE"
    assert body["isPublished"] is False
    assert body["traceId"]

    outcome = body["data"]
    assert outcome["proposalId"] == "map-01882"
    assert outcome["status"] == "ABSTAINED"
    assert outcome["modelAgreement"] is None
    assert outcome["requiresHumanReview"] is False

    decision = outcome["decision"]
    assert decision["verdict"] == "ABSTAINED"
    assert decision["provider"] == "deterministic-mock"
    assert decision["independentModel"] is False
    assert decision["evidenceIds"] == ["ev-schema-description", "ev-data-profile"]


def test_verify_routes_high_risk_to_human_review(client: TestClient) -> None:
    response = client.post("/v1/verify", json=_proposal_body(risk="HIGH"))
    assert response.status_code == 200
    outcome = response.json()["data"]
    assert outcome["status"] == "HUMAN_REVIEW"
    assert outcome["requiresHumanReview"] is True
    assert "human decision" in outcome["policyReason"]


def test_verify_rejects_contract_violations(client: TestClient) -> None:
    response = client.post("/v1/verify", json=_proposal_body(evidenceIds=[]))
    assert response.status_code == 422
    problem = response.json()
    assert problem["code"] == "request-validation"
