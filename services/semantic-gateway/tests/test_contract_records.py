from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ontology_appliance_gateway.contract_records import (
    ConnectorManifestRecord,
    ConnectorSourceType,
    ProposalConfidenceVector,
    ProposalKind,
    ProposalRecordStatus,
    SemanticProposalRecord,
)


ROOT = Path(__file__).resolve().parents[3]


def load(path: str) -> object:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_all_implemented_connector_fixtures_match_pydantic_contract() -> None:
    paths = sorted((ROOT / "data" / "contracts").glob("*.connector.json"))
    assert len(paths) == 7
    records = [ConnectorManifestRecord.model_validate_json(path.read_text()) for path in paths]
    assert {record.source_type for record in records} == {
        ConnectorSourceType.CSV,
        ConnectorSourceType.JSONL,
        ConnectorSourceType.PDF,
        ConnectorSourceType.OPENAPI,
        ConnectorSourceType.POSTGRES,
    }
    assert all(record.access_mode == "read_only" for record in records)


def test_committed_proposal_matches_pydantic_contract_without_approval() -> None:
    proposal = SemanticProposalRecord.model_validate(
        load("semantic/artifacts/proposals/mapping-crm-cif.json")
    )
    assert proposal.status == ProposalRecordStatus.PENDING_VERIFICATION
    assert proposal.generator.model_participated is False
    assert proposal.confidence.model == 0


def test_contract_enums_and_required_fields_match_canonical_json_schemas() -> None:
    connector_schema = load("contracts/schemas/connector-manifest.schema.json")
    proposal_schema = load("contracts/schemas/proposal.schema.json")
    assert isinstance(connector_schema, dict)
    assert isinstance(proposal_schema, dict)

    assert set(connector_schema["required"]) == set(
        ConnectorManifestRecord.model_json_schema()["required"]
    )
    assert connector_schema["properties"]["source_type"]["enum"] == [
        item.value for item in ConnectorSourceType
    ]
    assert set(proposal_schema["required"]) == set(
        SemanticProposalRecord.model_json_schema()["required"]
    )
    assert proposal_schema["properties"]["kind"]["enum"] == [item.value for item in ProposalKind]
    assert proposal_schema["properties"]["status"]["enum"] == [
        item.value for item in ProposalRecordStatus
    ]
    assert proposal_schema["$defs"]["confidence"]["required"] == list(
        ProposalConfidenceVector.model_fields
    )


def test_proposal_contract_rejects_scalar_confidence_and_unknown_fields() -> None:
    proposal = load("semantic/artifacts/proposals/mapping-crm-cif.json")
    assert isinstance(proposal, dict)
    proposal["confidence"] = 0.96
    proposal["publisher"] = "not-authorized"
    with pytest.raises(ValidationError):
        SemanticProposalRecord.model_validate(proposal)
