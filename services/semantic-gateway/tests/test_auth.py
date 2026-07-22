from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient

from ontology_appliance_gateway.config import Settings
from ontology_appliance_gateway.main import create_app


def _production_settings(settings: Settings, tmp_path: Path, *, auth_mode: str) -> Settings:
    artifact_dir = tmp_path / "published-artifacts"
    shutil.copytree(settings.artifact_dir, artifact_dir)
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publication"].update(
        {
            "state": "PUBLISHED",
            "servingMode": "ACTIVE",
            "isPublished": True,
            "publisherSubject": "serviceAccount:publisher@example.invalid",
            "authorizedAt": "2026-07-22T14:04:00Z",
            "publishedAt": "2026-07-22T14:05:00Z",
            "releaseSha": "d" * 40,
            "releaseId": "d" * 40 + "-123-1",
            "sourceManifestSha256": "e" * 64,
            "receiptPath": "publication-receipt.json",
            "receiptSha256": "f" * 64,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return replace(
        settings,
        environment="production",
        auth_mode=auth_mode,
        artifact_dir=artifact_dir,
        last_valid_path=tmp_path / "published-cache.trig",
    )


def test_explicit_dev_principal_keeps_fixed_tenant(client: TestClient) -> None:
    response = client.post(
        "/v1/sparql",
        json={"query": "ASK { ?s ?p ?o }"},
        headers={"Authorization": "Bearer dev:demo-bank:auditor-1:auditor"},
    )
    assert response.status_code == 200
    assert response.json()["tenantId"] == "demo-bank"
    assert response.json()["data"]["boolean"] is True


def test_malformed_development_authorization_never_falls_back_to_admin(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/resolve",
        json={"term": "Party"},
        headers={"Authorization": "Basic accidental-credential"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid-dev-token"


def test_firebase_mode_requires_token_without_contacting_cloud(
    settings: Settings, tmp_path: Path
) -> None:
    production = _production_settings(settings, tmp_path, auth_mode="firebase-session")
    with TestClient(create_app(production)) as client:
        response = client.post("/v1/resolve", json={"term": "Party"})
    assert response.status_code == 401
    assert response.json()["code"] == "missing-token"


def test_firebase_claim_is_bound_to_gateway_tenant(
    settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    claims = {
        "uid": "firebase-user-1",
        "tenant_id": "other-bank",
        "roles": ["auditor"],
    }

    def verify_session_cookie(_token: str, *, check_revoked: bool):
        assert check_revoked is True
        return claims

    def verify_id_token(_token: str, *, check_revoked: bool):
        assert check_revoked is True
        return claims

    initialized = {"value": False}

    def get_app():
        if not initialized["value"]:
            raise ValueError("not initialized")
        return object()

    def initialize_app(*, options):
        assert options is None
        initialized["value"] = True
        return object()

    fake_module = ModuleType("firebase_admin")
    fake_module.auth = SimpleNamespace(
        verify_session_cookie=verify_session_cookie,
        verify_id_token=verify_id_token,
    )
    fake_module.get_app = get_app
    fake_module.initialize_app = initialize_app
    monkeypatch.setitem(sys.modules, "firebase_admin", fake_module)

    production = _production_settings(settings, tmp_path, auth_mode="firebase-session")
    with TestClient(create_app(production)) as client:
        denied = client.post(
            "/v1/resolve",
            json={"term": "Party"},
            headers={"Authorization": "Bearer firebase-token"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "tenant-not-allowed"

        claims.pop("tenant_id")
        claims["firebase"] = {"tenant": "demo-bank"}
        nested_tenant_only = client.post(
            "/v1/resolve",
            json={"term": "Party"},
            headers={"Authorization": "Bearer firebase-token"},
        )
        assert nested_tenant_only.status_code == 403
        assert nested_tenant_only.json()["code"] == "missing-tenant-claim"

        claims["tenant_id"] = "demo-bank"
        allowed = client.post(
            "/v1/resolve",
            json={"term": "Party"},
            headers={"Authorization": "Bearer firebase-token"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["tenantId"] == "demo-bank"

    id_token_mode = replace(production, auth_mode="firebase-id-token")
    with TestClient(create_app(id_token_mode)) as client:
        allowed = client.post(
            "/v1/resolve",
            json={"term": "Party"},
            headers={"Authorization": "Bearer firebase-id-token"},
        )
    assert allowed.status_code == 200


def test_hybrid_mode_verifies_allowlisted_service_identity(
    settings: Settings, monkeypatch, tmp_path: Path
) -> None:
    from google.oauth2 import id_token as google_id_token

    def verify_service_token(token: str, _request, *, audience: str):
        assert token == "service-token"
        assert audience == "https://gateway.example.run.app"
        return {
            "iss": "https://accounts.google.com",
            "email": "oa-functions@example.iam.gserviceaccount.com",
            "email_verified": True,
            "sub": "123456789",
        }

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", verify_service_token)
    hybrid = replace(
        _production_settings(settings, tmp_path, auth_mode="hybrid"),
        service_audience="https://gateway.example.run.app",
        trusted_service_accounts=frozenset({"oa-functions@example.iam.gserviceaccount.com"}),
    )
    headers = {
        "authorization": "Bearer service-token",
        "x-ontology-service-auth": "google-id-token",
        "x-ontology-tenant-id": "demo-bank",
    }
    with TestClient(create_app(hybrid)) as client:
        allowed = client.post("/v1/resolve", json={"term": "Party"}, headers=headers)
        assert allowed.status_code == 200
        assert allowed.json()["tenantId"] == "demo-bank"

        denied = client.post(
            "/v1/resolve",
            json={"term": "Party"},
            headers={**headers, "x-ontology-tenant-id": "other-bank"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "tenant-not-allowed"
