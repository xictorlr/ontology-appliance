from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontology_appliance_gateway.artifacts import ArtifactStore
from ontology_appliance_gateway.config import Settings
from ontology_appliance_gateway.semantic import COMPETENCY_QUESTIONS


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_SUITE = json.loads(
    (REPOSITORY_ROOT / "semantic/artifacts/competency-questions.json").read_text(encoding="utf-8")
)

SEMANTIC_OPERATION_IDS = {
    "/v1/resolve": "resolveTerm",
    "/v1/context": "getContext",
    "/v1/query": "semanticQuery",
    "/v1/explain": "explainAssertion",
    "/v1/validate": "validateProposal",
    "/v1/sparql": "readOnlySparql",
}


def test_health_and_openapi_contract(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["ontologyVersion"] == "2026.07.1-demo-bank"
    assert payload["publicationState"] == "CANDIDATE"
    assert payload["servingMode"] == "DEMO_ONLY"
    assert payload["isPublished"] is False
    assert payload["tripleCount"] > 100
    assert response.headers["x-trace-id"]

    openapi = client.get("/openapi.json").json()
    expected = {
        "/healthz",
        "/v1/resolve",
        "/v1/context",
        "/v1/query",
        "/v1/explain",
        "/v1/validate",
        "/v1/sparql",
    }
    assert expected.issubset(openapi["paths"])
    assert openapi["openapi"].startswith("3.1")


def test_openapi_documents_governed_envelopes_and_read_only_sparql(
    client: TestClient,
) -> None:
    openapi = client.get("/openapi.json").json()
    schemas = openapi["components"]["schemas"]
    assert {"ResponseEnvelope", "ProblemDetails"}.issubset(schemas)

    expected_problem = {"$ref": "#/components/schemas/ProblemDetails"}
    for path, operation_id in SEMANTIC_OPERATION_IDS.items():
        operation = openapi["paths"][path]["post"]
        assert operation["operationId"] == operation_id
        assert (
            operation["responses"]["default"]["content"]["application/problem+json"]["schema"]
            == expected_problem
        )

    assert openapi["paths"]["/v1/sparql"]["post"]["x-read-only"] is True


def test_resolve_and_context_include_trace_and_provenance(client: TestClient) -> None:
    resolved = client.post("/v1/resolve", json={"term": "UBO", "limit": 3})
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "OK"
    assert body["tenantId"] == "demo-bank"
    assert body["traceId"] == resolved.headers["x-trace-id"]
    assert body["tenantId"] == "demo-bank"
    assert body["generatedAt"].endswith("Z")
    assert body["publicationState"] == "CANDIDATE"
    assert body["servingMode"] == "DEMO_ONLY"
    assert body["isPublished"] is False
    assert any("NON-PUBLISHED DEMO CANDIDATE" in warning for warning in body["warnings"])
    assert body["data"]["concepts"][0]["label"] == "Ultimate Beneficial Owner"
    assert len(body["evidence"]) == 5
    assert all(len(item["sha256"]) == 64 for item in body["evidence"])

    context = client.post("/v1/context", json={"term": "Customer Identifier"})
    assert context.status_code == 200
    context_body = context.json()["data"]
    assert context_body["label"] == "Customer Identifier"
    assert context_body["mappings"][0]["fieldName"] == "cif_no"


@pytest.mark.parametrize(
    "golden",
    GOLDEN_SUITE["questions"],
    ids=[question["id"] for question in GOLDEN_SUITE["questions"]],
)
def test_competency_questions_match_golden_exactly(
    client: TestClient, settings: Settings, golden: dict[str, object]
) -> None:
    question_id = str(golden["id"])
    expected = golden["expectedOutcome"]
    assert isinstance(expected, dict)
    response = client.post(
        "/v1/query",
        json={"competencyQuestionId": question_id},
        headers={"X-Trace-Id": str(expected["traceId"])},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "OK"
    assert body["data"]["competencyQuestionId"] == question_id
    assert body["data"]["rows"] == expected["rows"]
    assert body["data"]["sparql"] == golden["sparql"]
    assert body["ontologyVersion"] == expected["bundleVersion"]
    assert body["traceId"] == expected["traceId"]
    assert golden["status"] == "PASS"

    runtime_definition = COMPETENCY_QUESTIONS[question_id]
    assert runtime_definition["sparql"] == golden["sparql"]
    assert list(runtime_definition["evidence_iris"]) == golden["evidenceIris"]
    snapshot = ArtifactStore(settings).initialize()
    actual_evidence = []
    for coordinate in snapshot.evidence_coordinates(runtime_definition["evidence_iris"]):
        item = asdict(coordinate)
        actual_evidence.append(
            {
                "evidenceIri": item["evidence_iri"],
                "sourceId": item["source_id"],
                "snapshotId": item["snapshot_id"],
                "locator": item["locator"],
                "contentSha256": item["content_sha256"],
            }
        )
    assert actual_evidence == expected["evidence"]


def test_unrecognized_question_abstains(client: TestClient) -> None:
    response = client.post("/v1/query", json={"question": "What will the weather be?"})
    assert response.status_code == 200
    assert response.json()["status"] == "ABSTAINED"
    assert response.json()["data"]["rows"] == []


def test_explain_cif_mapping(client: TestClient) -> None:
    response = client.post("/v1/explain", json={"mappingId": "mapping-crm-cif"})
    assert response.status_code == 200, response.text
    explanation = response.json()["data"]
    assert explanation["label"] == "CRM cif_no → Customer Identifier"
    assert explanation["confidence"]["lexical"] == pytest.approx(0.96)
    assert any(
        "historical merged records" in item.lower() for item in explanation["counterexamples"]
    )
    assert any(step.get("evidenceIri") for step in explanation["steps"])


def test_validate_active_graph_and_report_invalid_candidate(client: TestClient) -> None:
    valid = client.post("/v1/validate", json={"includeOwlRlClosure": False})
    assert valid.status_code == 200
    assert valid.json()["data"]["conforms"] is True

    invalid_turtle = """
        @prefix oa: <urn:ontology-appliance:vocab:> .
        @prefix ex: <urn:test:> .
        ex:broken a oa:Account .
    """
    invalid = client.post(
        "/v1/validate",
        json={"dataTurtle": invalid_turtle, "includeOwlRlClosure": False},
    )
    assert invalid.status_code == 200
    body = invalid.json()
    assert body["status"] == "PARTIAL"
    assert body["data"]["conforms"] is False
    assert len(body["data"]["issues"]) >= 2


def test_sparql_is_read_only_and_bounded(client: TestClient) -> None:
    select = client.post(
        "/v1/sparql",
        json={
            "query": "PREFIX oa: <urn:ontology-appliance:vocab:> SELECT ?p WHERE { ?p a oa:Payment } ORDER BY ?p",
            "maxRows": 1,
        },
    )
    assert select.status_code == 200, select.text
    result = select.json()["data"]
    assert set(result) == {"queryType", "variables", "rows", "boolean", "truncated"}
    assert result["queryType"] == "SELECT"
    assert len(result["rows"]) == 1
    assert result["truncated"] is True

    update = client.post(
        "/v1/sparql",
        json={"query": "DELETE WHERE { ?s ?p ?o }"},
    )
    assert update.status_code == 403
    assert update.headers["content-type"].startswith("application/problem+json")
    assert update.json()["code"] == "sparql-read-only"

    rdf_prefix = client.post(
        "/v1/sparql",
        json={
            "query": (
                "# a legitimate comment\n"
                "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> "
                "ASK { ?resource rdf:type ?type }"
            )
        },
    )
    assert rdf_prefix.status_code == 200, rdf_prefix.text
    assert rdf_prefix.json()["data"]["boolean"] is True

    external_dataset = client.post(
        "/v1/sparql",
        json={"query": "SELECT * FROM <https://example.invalid/data> WHERE { ?s ?p ?o }"},
    )
    assert external_dataset.status_code == 403


def test_openapi_request_limits_are_runtime_limits(client: TestClient) -> None:
    assert client.post("/v1/resolve", json={"term": "x" * 201}).status_code == 422
    assert client.post("/v1/resolve", json={"term": "Party", "limit": 21}).status_code == 422
    assert client.post("/v1/sparql", json={"query": "x" * 20_001}).status_code == 422


def test_sparql_rejects_unreviewed_expensive_aggregations(client: TestClient) -> None:
    response = client.post(
        "/v1/sparql",
        json={"query": "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "query-too-complex"


def test_request_validation_uses_problem_details(client: TestClient) -> None:
    response = client.post("/v1/context", json={})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("request-validation")


def test_development_tenant_cannot_be_overridden(client: TestClient) -> None:
    response = client.post(
        "/v1/resolve",
        json={"term": "Party"},
        headers={"Authorization": "Bearer dev:other-bank:user-1:admin"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "tenant-not-allowed"


def test_safe_trace_header_is_propagated(client: TestClient) -> None:
    trace_id = "integration-test-12345"
    response = client.post(
        "/v1/resolve",
        json={"term": "Payment"},
        headers={"X-Trace-Id": trace_id},
    )
    assert response.headers["x-trace-id"] == trace_id
    assert response.json()["traceId"] == trace_id
