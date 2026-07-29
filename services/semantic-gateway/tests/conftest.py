from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontology_appliance_gateway.config import Settings
from ontology_appliance_gateway.main import create_app


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        artifact_dir=REPOSITORY_ROOT / "semantic" / "artifacts",
        last_valid_path=tmp_path / "last-valid.trig",
        dev_tenant_id="demo-bank",
        allow_dev_tenant_override=False,
        auth_mode="dev",
        firebase_project_id=None,
        max_sparql_rows=250,
        max_sparql_query_length=20_000,
    )


@pytest.fixture()
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    # The verifier is selected from the process environment at app creation;
    # pin the deterministic mock so endpoint tests stay hermetic even if
    # another module leaked provider settings.
    monkeypatch.setenv("VERIFIER_PROVIDER", "mock")
    monkeypatch.delenv("OPENAI_VERIFIER_MODE", raising=False)
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client
