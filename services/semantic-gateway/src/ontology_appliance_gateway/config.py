"""Runtime configuration with secure production defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _project_root() -> Path:
    # .../services/semantic-gateway/src/package/config.py -> repository root
    return Path(__file__).resolve().parents[4]


def _as_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _optional_generation(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if not normalized.isdigit() or int(normalized) < 1:
        raise ValueError("OA_ACTIVE_POINTER_GENERATION must be a positive integer")
    return int(normalized)


@dataclass(frozen=True, slots=True)
class Settings:
    """Settings are deliberately small and environment-variable driven."""

    environment: str
    artifact_dir: Path
    last_valid_path: Path
    dev_tenant_id: str
    allow_dev_tenant_override: bool
    auth_mode: str
    firebase_project_id: str | None
    max_sparql_rows: int
    max_sparql_query_length: int
    artifact_bucket: str | None = None
    artifact_pointer: str = "tenants/{tenant_id}/ontology/active.json"
    active_pointer_generation: int | None = None
    allow_demo_candidate: bool = False
    semantic_timeout_seconds: float = 5.0
    max_semantic_concurrency: int = 2
    max_validation_triples: int = 10_000
    max_shape_triples: int = 2_000
    max_inferred_triples: int = 50_000
    service_audience: str | None = None
    trusted_service_accounts: frozenset[str] = frozenset()

    @property
    def is_development(self) -> bool:
        return self.environment in {"development", "dev", "test", "local"}

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("OA_ENV", "development").strip().lower()
        default_auth_mode = (
            "dev" if environment in {"development", "dev", "test", "local"} else "firebase-session"
        )
        return cls(
            environment=environment,
            # The repository-relative fallback must stay lazy: the deployed
            # function ships this package at a shallow path where
            # _project_root() cannot exist, and OA_ARTIFACT_DIR is always set
            # there.
            artifact_dir=Path(
                os.getenv("OA_ARTIFACT_DIR")
                or str(_project_root() / "semantic" / "artifacts")
            ).resolve(),
            last_valid_path=Path(
                os.getenv(
                    "OA_LAST_VALID_PATH",
                    "/tmp/ontology-appliance/last-valid.trig",
                )
            ).resolve(),
            dev_tenant_id=os.getenv(
                "OA_TENANT_ID", os.getenv("OA_DEV_TENANT_ID", "demo-bank")
            ).strip(),
            allow_dev_tenant_override=_as_bool(
                os.getenv("OA_ALLOW_DEV_TENANT_OVERRIDE"), default=False
            ),
            auth_mode=os.getenv("OA_AUTH_MODE", default_auth_mode).strip().lower(),
            firebase_project_id=os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT"),
            max_sparql_rows=max(1, min(int(os.getenv("OA_MAX_SPARQL_ROWS", "250")), 1_000)),
            max_sparql_query_length=max(
                256, min(int(os.getenv("OA_MAX_SPARQL_QUERY_LENGTH", "20000")), 20_000)
            ),
            semantic_timeout_seconds=max(
                0.25, min(float(os.getenv("OA_SEMANTIC_TIMEOUT_SECONDS", "5")), 30.0)
            ),
            max_semantic_concurrency=max(
                1, min(int(os.getenv("OA_MAX_SEMANTIC_CONCURRENCY", "2")), 4)
            ),
            max_validation_triples=max(
                100, min(int(os.getenv("OA_MAX_VALIDATION_TRIPLES", "10000")), 50_000)
            ),
            max_shape_triples=max(50, min(int(os.getenv("OA_MAX_SHAPE_TRIPLES", "2000")), 10_000)),
            max_inferred_triples=max(
                1_000, min(int(os.getenv("OA_MAX_INFERRED_TRIPLES", "50000")), 200_000)
            ),
            service_audience=os.getenv("OA_SERVICE_AUDIENCE") or None,
            trusted_service_accounts=frozenset(
                account.strip().lower()
                for account in os.getenv("OA_TRUSTED_SERVICE_ACCOUNTS", "").split(",")
                if account.strip()
            ),
            artifact_bucket=(
                os.getenv("OA_ARTIFACT_BUCKET") or os.getenv("ONTOLOGY_ARTIFACT_BUCKET") or None
            ),
            artifact_pointer=os.getenv(
                "OA_ARTIFACT_POINTER",
                os.getenv(
                    "ONTOLOGY_ARTIFACT_POINTER",
                    "tenants/{tenant_id}/ontology/active.json",
                ),
            ).strip("/"),
            active_pointer_generation=_optional_generation(
                os.getenv("OA_ACTIVE_POINTER_GENERATION")
            ),
            allow_demo_candidate=_as_bool(os.getenv("OA_ALLOW_DEMO_CANDIDATE"), default=False),
        )
