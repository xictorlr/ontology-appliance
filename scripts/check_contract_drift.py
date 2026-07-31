#!/usr/bin/env python3
"""Check OpenAPI and immutable-record mirrors against canonical contracts."""

from __future__ import annotations

import json
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel
import yaml


ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = ROOT / "services" / "semantic-gateway" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from ontology_appliance_gateway.main import create_app  # noqa: E402
from ontology_appliance_gateway.models import (  # noqa: E402
    ContextRequest,
    ExplainRequest,
    PublicationState,
    QueryRequest,
    ResolveRequest,
    ResponseEnvelope,
    ResponseStatus,
    ServingMode,
    SparqlRequest,
    SparqlResult,
    ValidateRequest,
)
from ontology_appliance_gateway.contract_records import (  # noqa: E402
    ConnectorCapability,
    ConnectorEvidencePolicy,
    ConnectorField,
    ConnectorLimits,
    ConnectorManifestRecord,
    ConnectorSource,
    ConnectorSourceType,
    ProposalConfidenceVector,
    ProposalEvidenceRecord,
    ProposalGeneratorTrace,
    ProposalKind,
    ProposalRecordStatus,
    SemanticProposalRecord,
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require_equal(label: str, expected: object, actual: object) -> None:
    if expected != actual:
        raise SystemExit(f"{label} drift: canonical={expected!r}, mirror={actual!r}")


def property_names(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields)


def enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_type]


def validate_record_contracts() -> tuple[int, int]:
    connector_schema = load_json(
        ROOT / "contracts" / "schemas" / "connector-manifest.schema.json"
    )
    proposal_schema = load_json(ROOT / "contracts" / "schemas" / "proposal.schema.json")

    require_equal(
        "connector fields",
        set(connector_schema["properties"]),
        property_names(ConnectorManifestRecord),
    )
    require_equal(
        "connector required fields",
        set(connector_schema["required"]),
        set(ConnectorManifestRecord.model_json_schema()["required"]),
    )
    require_equal(
        "connector source types",
        connector_schema["properties"]["source_type"]["enum"],
        enum_values(ConnectorSourceType),
    )
    require_equal(
        "connector capabilities",
        connector_schema["properties"]["capabilities"]["items"]["enum"],
        enum_values(ConnectorCapability),
    )
    connector_defs = connector_schema["$defs"]
    for key, model in (
        ("source", ConnectorSource),
        ("field", ConnectorField),
        ("evidence_policy", ConnectorEvidencePolicy),
        ("limits", ConnectorLimits),
    ):
        require_equal(
            f"connector {key} fields",
            set(connector_defs[key]["properties"]),
            property_names(model),
        )
        require_equal(
            f"connector {key} required fields",
            set(connector_defs[key].get("required", [])),
            set(model.model_json_schema().get("required", [])),
        )

    connector_paths = sorted((ROOT / "data" / "contracts").glob("*.connector.json"))
    if len(connector_paths) != 7:
        raise SystemExit(
            f"expected 7 implemented connector fixtures, found {len(connector_paths)}"
        )
    for path in connector_paths:
        ConnectorManifestRecord.model_validate_json(path.read_text(encoding="utf-8"))

    require_equal(
        "proposal fields",
        set(proposal_schema["properties"]),
        property_names(SemanticProposalRecord),
    )
    require_equal(
        "proposal required fields",
        set(proposal_schema["required"]),
        set(SemanticProposalRecord.model_json_schema()["required"]),
    )
    require_equal(
        "proposal kinds",
        proposal_schema["properties"]["kind"]["enum"],
        enum_values(ProposalKind),
    )
    require_equal(
        "proposal statuses",
        proposal_schema["properties"]["status"]["enum"],
        enum_values(ProposalRecordStatus),
    )
    proposal_defs = proposal_schema["$defs"]
    for key, model in (
        ("evidence", ProposalEvidenceRecord),
        ("confidence", ProposalConfidenceVector),
        ("generator", ProposalGeneratorTrace),
    ):
        require_equal(
            f"proposal {key} fields",
            set(proposal_defs[key]["properties"]),
            property_names(model),
        )
        require_equal(
            f"proposal {key} required fields",
            set(proposal_defs[key].get("required", [])),
            set(model.model_json_schema().get("required", [])),
        )

    proposal = SemanticProposalRecord.model_validate(
        load_json(
            ROOT / "semantic" / "artifacts" / "proposals" / "mapping-crm-cif.json"
        )
    )
    if proposal.status is not ProposalRecordStatus.PENDING_VERIFICATION:
        raise SystemExit("canonical proposal fixture must remain PENDING_VERIFICATION")
    if proposal.generator.model_participated or proposal.confidence.model != 0:
        raise SystemExit(
            "deterministic proposal fixture must not claim model participation or agreement"
        )

    verification = load_json(
        ROOT / "semantic" / "artifacts" / "verification" / "mapping-crm-cif.mock.json"
    )
    if verification.get("models", {}).get("independent_agreement") is not None:
        raise SystemExit("mock verification must keep independent_agreement null")
    if verification.get("status") not in {"HUMAN_REVIEW", "ABSTAINED"}:
        raise SystemExit("mock verification must remain HUMAN_REVIEW or ABSTAINED")
    return len(connector_paths), 1


def checked_in_operations(text: str) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    current_path: str | None = None
    in_paths = False
    for line in text.splitlines():
        if line == "paths:":
            in_paths = True
            continue
        if in_paths and line and not line.startswith(" "):
            break
        path_match = re.fullmatch(r"  (/[^:]+):", line)
        if path_match:
            current_path = path_match.group(1)
            continue
        method_match = re.fullmatch(r"    (get|post|put|patch|delete):", line)
        if current_path and method_match:
            operations.add((current_path, method_match.group(1)))
    return operations


SCHEMA_CONSTRAINTS = (
    "type",
    "enum",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "format",
    "default",
)


def compact_property(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize the request constraints represented differently by YAML/Pydantic."""

    normalized: dict[str, Any] = {}
    types: set[str] = set()
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        types.add(raw_type)
    elif isinstance(raw_type, list):
        types.update(str(item) for item in raw_type)
    for branch in schema.get("anyOf", []):
        if not isinstance(branch, dict):
            continue
        branch_type = branch.get("type")
        if isinstance(branch_type, str):
            types.add(branch_type)
        for key in SCHEMA_CONSTRAINTS:
            if key != "type" and key in branch and key not in normalized:
                normalized[key] = branch[key]
    if types:
        normalized["type"] = sorted(types)
    for key in SCHEMA_CONSTRAINTS:
        if key != "type" and key in schema:
            normalized[key] = schema[key]
    return normalized


def validate_model_schema(
    canonical_schemas: dict[str, Any],
    schema_name: str,
    model: type[BaseModel],
) -> None:
    canonical = canonical_schemas[schema_name]
    runtime = model.model_json_schema(by_alias=True)
    require_equal(
        f"{schema_name} additionalProperties",
        False,
        canonical.get("additionalProperties"),
    )
    require_equal(
        f"{schema_name} fields",
        set(runtime["properties"]),
        set(canonical["properties"]),
    )
    require_equal(
        f"{schema_name} required fields",
        set(runtime.get("required", [])),
        set(canonical.get("required", [])),
    )
    for property_name in runtime["properties"]:
        require_equal(
            f"{schema_name}.{property_name} constraints",
            compact_property(runtime["properties"][property_name]),
            compact_property(canonical["properties"][property_name]),
        )


def validate_gateway_schemas(canonical: dict[str, Any]) -> None:
    schemas = canonical["components"]["schemas"]
    for schema_name, model in (
        ("ResolveRequest", ResolveRequest),
        ("ContextRequest", ContextRequest),
        ("QueryRequest", QueryRequest),
        ("ExplainRequest", ExplainRequest),
        ("ValidateRequest", ValidateRequest),
        ("SparqlRequest", SparqlRequest),
        ("SparqlResult", SparqlResult),
    ):
        validate_model_schema(schemas, schema_name, model)

    envelope = schemas["ResponseEnvelope"]
    runtime_envelope = ResponseEnvelope.model_json_schema(by_alias=True)
    require_equal(
        "ResponseEnvelope fields",
        set(runtime_envelope["properties"]),
        set(envelope["properties"]),
    )
    require_equal(
        "ResponseEnvelope serialized required fields",
        set(envelope["properties"]),
        set(envelope["required"]),
    )
    require_equal(
        "ResponseEnvelope publication states",
        enum_values(PublicationState),
        envelope["properties"]["publicationState"]["enum"],
    )
    require_equal(
        "ResponseEnvelope serving modes",
        enum_values(ServingMode),
        envelope["properties"]["servingMode"]["enum"],
    )
    require_equal(
        "ResponseEnvelope statuses",
        enum_values(ResponseStatus),
        envelope["properties"]["status"]["enum"],
    )

    typescript = (ROOT / "packages" / "contracts" / "src" / "index.ts").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"export const responseMetaFieldNames = \[(.*?)\] as const;",
        typescript,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit("TypeScript responseMetaFieldNames declaration is missing")
    typescript_fields = set(re.findall(r'"([A-Za-z][A-Za-z0-9]*)"', match.group(1)))
    require_equal(
        "TypeScript response metadata fields",
        set(envelope["required"]) - {"data"},
        typescript_fields,
    )


def main() -> None:
    checked_in_text = (ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8")
    checked = checked_in_operations(checked_in_text)
    canonical = yaml.safe_load(checked_in_text)
    generated = create_app().openapi()
    runtime = {
        (path, method)
        for path, methods in generated["paths"].items()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    }
    if checked != runtime:
        missing = sorted(runtime - checked)
        extra = sorted(checked - runtime)
        raise SystemExit(f"OpenAPI operation drift: missing={missing}, extra={extra}")
    if generated.get("openapi") != "3.1.0":
        raise SystemExit(
            f"runtime OpenAPI must be 3.1.0, got {generated.get('openapi')}"
        )
    validate_gateway_schemas(canonical)
    connector_count, proposal_count = validate_record_contracts()
    print(
        f"OpenAPI operations: {len(runtime)} synchronized; "
        f"canonical fixtures: {connector_count} connectors, {proposal_count} proposal"
    )


if __name__ == "__main__":
    main()
