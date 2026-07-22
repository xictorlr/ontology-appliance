"""Pydantic mirrors of the canonical immutable record contracts.

The JSON Schemas in ``contracts/schemas`` remain canonical. These models parse
the same committed connector and proposal fixtures at runtime and in drift
tests. They are intentionally separate from API envelopes and from the internal
provider DTOs used while generating or verifying a proposal.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConnectorSourceType(StrEnum):
    CSV = "csv"
    JSONL = "jsonl"
    PDF = "pdf"
    OPENAPI = "openapi"


class ConnectorCapability(StrEnum):
    SCHEMA = "schema"
    SAMPLE = "sample"
    PROFILE = "profile"
    SNAPSHOT = "snapshot"


class ConnectorLogicalType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    OBJECT = "object"
    ARRAY = "array"
    BINARY = "binary"


class ConnectorSource(ContractRecord):
    uri: str = Field(min_length=1)
    snapshot_strategy: str = Field(pattern=r"^(immutable|watermark|content_hash)$")
    response_fixture: str | None = Field(default=None, min_length=1)
    document_glob: str | None = Field(default=None, min_length=1)


class ConnectorField(ContractRecord):
    source_path: str = Field(min_length=1)
    logical_type: ConnectorLogicalType
    nullable: bool
    source_representation: str | None = Field(default=None, min_length=1)


class ConnectorEvidencePolicy(ContractRecord):
    locator_template: str = Field(min_length=1)
    hash_algorithm: str = Field(pattern=r"^sha256$")


class ConnectorLimits(ContractRecord):
    maximum_bytes: int | None = Field(default=None, ge=1)
    maximum_records: int | None = Field(default=None, ge=1)
    maximum_pages: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1)


class ConnectorManifestRecord(ContractRecord):
    schema_version: str = Field(pattern=r"^1\.0$")
    connector_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    tenant_id: str = Field(min_length=1, max_length=128)
    source_type: ConnectorSourceType
    access_mode: str = Field(pattern=r"^read_only$")
    source: ConnectorSource
    credential_ref: str | None = Field(
        default=None,
        pattern=r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$",
    )
    capabilities: list[ConnectorCapability] = Field(min_length=1)
    fields: list[ConnectorField]
    evidence: ConnectorEvidencePolicy
    limits: ConnectorLimits | None = None

    @model_validator(mode="after")
    def unique_manifest_lists(self) -> "ConnectorManifestRecord":
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities must be unique")
        source_paths = [field.source_path for field in self.fields]
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("field source_path values must be unique")
        return self


class ProposalKind(StrEnum):
    CONCEPT = "concept"
    RELATION = "relation"
    ALIAS = "alias"
    MAPPING = "mapping"
    DUPLICATE = "duplicate"
    CONSTRAINT = "constraint"
    ASSERTION = "assertion"
    DRIFT = "drift"


class ProposalRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProposalRecordStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    AUTO_APPROVED = "AUTO_APPROVED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    ABSTAINED = "ABSTAINED"


class ProposalEvidenceRecord(ContractRecord):
    evidence_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    observed_at: datetime
    extractor_version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    claim: str | None = Field(default=None, max_length=2_000)


class ProposalConfidenceVector(ContractRecord):
    lexical: float = Field(ge=0, le=1)
    structural: float = Field(ge=0, le=1)
    instance: float = Field(ge=0, le=1)
    external: float = Field(ge=0, le=1)
    model: float = Field(ge=0, le=1)
    evidence_coverage: float = Field(ge=0, le=1)


class ProposalGeneratorTrace(ContractRecord):
    mode: str = Field(pattern=r"^(deterministic|live)$")
    model_participated: bool
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    provider_returned_model_id: str | None
    prompt_version: str = Field(min_length=1)
    parameters: dict[str, Any]
    token_usage: dict[str, Any] | None
    latency_ms: int = Field(ge=0)
    response_status: str = Field(min_length=1)


class SemanticProposalRecord(ContractRecord):
    schema_version: str = Field(pattern=r"^1\.0$")
    proposal_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    kind: ProposalKind
    risk: ProposalRisk
    source_snapshot_ids: list[str] = Field(min_length=1)
    active_ontology_version: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    target_iri: str = Field(min_length=1)
    transformation: str = Field(min_length=1)
    evidence: list[ProposalEvidenceRecord] = Field(min_length=1)
    counterevidence: list[ProposalEvidenceRecord]
    confidence: ProposalConfidenceVector
    generator: ProposalGeneratorTrace
    algorithm_version: str = Field(min_length=1)
    deterministic_input: dict[str, Any]
    deterministic_input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: ProposalRecordStatus
    reason_codes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def preserve_record_invariants(self) -> "SemanticProposalRecord":
        if len(self.source_snapshot_ids) != len(set(self.source_snapshot_ids)):
            raise ValueError("source_snapshot_ids must be unique")
        if any(not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must not contain blank values")
        return self
