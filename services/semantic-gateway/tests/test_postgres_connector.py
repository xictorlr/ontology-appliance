"""Deterministic tests for the metadata-first PostgreSQL connector."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ontology_appliance_gateway.connectors import postgres
from ontology_appliance_gateway.contract_records import (
    ConnectorCapability,
    ConnectorManifestRecord,
    ConnectorSourceType,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = ROOT / "data" / "synthetic" / "postgres-catalog.json"
BUNDLE_DIR = ROOT / "profiles" / "postgres-demo"
BUNDLE_FILES = ("evidence-index.json", "profile.json", "snapshot.json")


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def normalize_fixture_bytes() -> dict[str, bytes]:
    artifacts = postgres.normalize_catalog_bytes(
        CATALOG_PATH.read_bytes(),
        catalog_locator="data/synthetic/postgres-catalog.json",
    )
    return {name: postgres.json_bytes(content) for name, content in artifacts.items()}


def test_checked_in_bundle_matches_regeneration_byte_for_byte() -> None:
    regenerated = normalize_fixture_bytes()
    assert set(regenerated) == set(BUNDLE_FILES)
    for name in BUNDLE_FILES:
        assert (BUNDLE_DIR / name).read_bytes() == regenerated[name], (
            f"profiles/postgres-demo/{name} drifted from the deterministic normalizer; "
            "regenerate it with python -m ontology_appliance_gateway.connectors.postgres"
        )


def test_normalization_is_deterministic_and_hash_stable() -> None:
    first = normalize_fixture_bytes()
    second = normalize_fixture_bytes()
    assert first == second
    profile = json.loads(first["profile.json"])
    catalog_sha256 = postgres.sha256_hex(CATALOG_PATH.read_bytes())
    assert profile["sourceContentSha256"] == catalog_sha256
    assert profile["snapshotId"] == f"postgres-demo@sha256:{catalog_sha256}"
    evidence_index = json.loads(first["evidence-index.json"])
    for entry in evidence_index["evidence"]:
        assert entry["snapshotId"] == profile["snapshotId"]
        assert len(entry["contentSha256"]) == 64


def test_profile_is_metadata_only_with_sampling_disabled() -> None:
    profile = json.loads(normalize_fixture_bytes()["profile.json"])
    assert profile["valueSampling"] == "disabled"
    assert profile["readOnlyEnforcement"]["default_transaction_read_only"] == "on"
    assert profile["readOnlyEnforcement"]["statement_timeout"] == "30000"
    accounts = profile["tables"]["kyc.accounts"]
    assert accounts["primaryKey"] == {
        "constraintName": "accounts_pkey",
        "columns": ["account_id"],
    }
    assert accounts["foreignKeys"][0]["referencedTable"] == "kyc.customers"
    assert accounts["rowEstimate"] == 1810
    payments = profile["tables"]["kyc.payments"]
    assert payments["columns"]["amount"]["logicalType"] == "number"
    assert payments["columns"]["screening_flags"]["logicalType"] == "object"
    assert payments["columns"]["executed_at"]["logicalType"] == "datetime"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda catalog: catalog.update({"rows": [["ACME GmbH", "DE44...."]]}),
        lambda catalog: catalog.update({"sample": {"kyc.customers": ["Jane Doe"]}}),
        lambda catalog: catalog["columns"][0].update({"sample_values": ["C-1001"]}),
        lambda catalog: catalog["tables"][0].update({"preview": {"full_name": "Jane"}}),
        lambda catalog: catalog["columns"][1].update({"most_common_vals": ["DE"]}),
    ],
)
def test_value_bearing_catalog_input_is_refused(mutate) -> None:
    catalog = copy.deepcopy(load_catalog())
    mutate(catalog)
    with pytest.raises(postgres.CatalogPolicyError, match="refused|unsupported"):
        postgres.normalize_catalog(
            catalog,
            catalog_locator="inline",
            catalog_sha256="0" * 64,
            catalog_byte_count=1,
        )


def test_unknown_keys_are_refused_fail_closed() -> None:
    catalog = copy.deepcopy(load_catalog())
    catalog["extensions"] = {"anything": True}
    with pytest.raises(postgres.CatalogPolicyError, match="unsupported top-level keys"):
        postgres.validate_catalog(catalog)
    catalog = copy.deepcopy(load_catalog())
    catalog["columns"][0]["comment"] = "smuggled annotation"
    with pytest.raises(postgres.CatalogPolicyError, match="unsupported keys"):
        postgres.validate_catalog(catalog)


def test_metadata_limits_are_enforced() -> None:
    catalog = load_catalog()
    with pytest.raises(postgres.CatalogPolicyError, match="table limit"):
        postgres.validate_catalog(catalog, limits=postgres.CatalogLimits(maximum_tables=2))
    with pytest.raises(postgres.CatalogPolicyError, match="column limit"):
        postgres.validate_catalog(catalog, limits=postgres.CatalogLimits(maximum_columns=5))


def test_referential_integrity_of_catalog_is_required() -> None:
    catalog = copy.deepcopy(load_catalog())
    catalog["foreign_keys"][0]["referenced_table"] = "ghost_table"
    with pytest.raises(postgres.CatalogPolicyError, match="unlisted column"):
        postgres.validate_catalog(catalog)


def test_catalog_sql_constants_are_read_only_and_parameter_free() -> None:
    forbidden = (
        "INSERT", "UPDATE ", "DELETE", "DROP", "ALTER", "TRUNCATE",
        "GRANT", "REVOKE", "CREATE", "COPY", "CALL", "DO ",
    )
    for name, statement in postgres.CATALOG_SQL.items():
        normalized = statement.strip()
        assert normalized.upper().startswith("SELECT"), name
        assert normalized.count(";") == 1 and normalized.endswith(";"), name
        assert "%s" not in normalized and "$1" not in normalized, name
        upper = normalized.upper()
        for verb in forbidden:
            assert verb not in upper, (name, verb)


def test_manifest_fixture_is_metadata_first_and_secret_ref_only() -> None:
    manifest = ConnectorManifestRecord.model_validate_json(
        (ROOT / "data" / "contracts" / "postgres.connector.json").read_text(encoding="utf-8")
    )
    assert manifest.source_type is ConnectorSourceType.POSTGRES
    assert manifest.access_mode == "read_only"
    assert ConnectorCapability.SAMPLE not in manifest.capabilities
    assert ConnectorCapability.SCHEMA in manifest.capabilities
    assert manifest.credential_ref is not None
    assert manifest.credential_ref.startswith("projects/")
    assert manifest.limits is not None
    assert manifest.limits.maximum_schemas == postgres.DEFAULT_LIMITS.maximum_schemas
    assert manifest.limits.maximum_tables == postgres.DEFAULT_LIMITS.maximum_tables
    assert manifest.limits.maximum_columns == postgres.DEFAULT_LIMITS.maximum_columns
    assert "default_transaction_read_only%3Don" in manifest.source.uri
    assert "statement_timeout" in manifest.source.uri
    assert "@" not in manifest.source.uri  # no embedded credentials
    assert manifest.source.response_fixture == "data/synthetic/postgres-catalog.json"


def test_cli_writes_the_bundle(tmp_path: Path) -> None:
    output = tmp_path / "postgres-demo"
    exit_code = postgres.main(
        [
            str(CATALOG_PATH),
            str(output),
            "--catalog-locator",
            "data/synthetic/postgres-catalog.json",
        ]
    )
    assert exit_code == 0
    for name in BUNDLE_FILES:
        assert (output / name).read_bytes() == (BUNDLE_DIR / name).read_bytes()


def test_cli_refuses_value_bearing_catalog(tmp_path: Path) -> None:
    catalog = copy.deepcopy(load_catalog())
    catalog["rows"] = [["smuggled", "values"]]
    poisoned = tmp_path / "catalog.json"
    poisoned.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(postgres.CatalogPolicyError):
        postgres.main([str(poisoned), str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()
