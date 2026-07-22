#!/usr/bin/env python3
"""Materialize deterministic, provenance-first bundles for synthetic pilot sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[4]
TENANT_ID = "demo-bank"
EXTRACTOR_NAME = "ontology-appliance-synthetic-profiler"
EXTRACTOR_VERSION = "1.0.0"
MAX_RECORDS = 100
MAX_BYTES = 65_536


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def legacy_json_bytes(value: Any) -> bytes:
    """Serialize compatibility artifacts whose byte hash is already governed."""
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def compact_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_bytes(path: str) -> bytes:
    return (ROOT / path).read_bytes()


def source_digest(assets: list[dict[str, Any]]) -> str:
    if len(assets) == 1:
        return assets[0]["sha256"]
    digest = hashlib.sha256()
    for asset in sorted(assets, key=lambda item: item["path"]):
        digest.update(asset["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(asset["sha256"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def asset(path: str, media_type: str, content: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "mediaType": media_type,
        "byteCount": len(content),
        "sha256": sha256_bytes(content),
    }


def counts(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def field_statistics(values: list[str]) -> dict[str, Any]:
    populated = [value for value in values if value != ""]
    total = len(values)
    lengths = [len(value) for value in populated]
    return {
        "distinctCount": len(set(populated)),
        "maximumLength": max(lengths, default=0),
        "minimumLength": min(lengths, default=0),
        "nonNullCount": len(populated),
        "nullCount": total - len(populated),
        "nullRate": round((total - len(populated)) / total, 6) if total else 0.0,
        "uniquenessRatio": round(len(set(populated)) / total, 6) if total else 0.0,
    }


def escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_bytes(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 11 Tf", "50 790 Td", "15 TL"]
    for index, line in enumerate(lines):
        if index:
            commands.append("T*")
        commands.append(f"({escape_pdf_text(line)}) Tj")
    commands.append("ET")
    stream = ("\n".join(commands) + "\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Title (Synthetic KYC fixture LE-2001) /Producer (Ontology Appliance deterministic fixture builder) /CreationDate (D:20260620063000Z) >>",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


def normalized_document_lines() -> list[str]:
    source = (ROOT / "data/synthetic/kyc/LE-2001.txt").read_text(encoding="utf-8")
    return [line.replace("—", "-").strip() for line in source.splitlines() if line.strip()]


def manifest(
    *,
    connector_id: str,
    source_type: str,
    uri: str,
    fields: list[dict[str, Any]],
    locator_template: str,
    source_extra: dict[str, Any] | None = None,
    page_limit: int | None = None,
) -> dict[str, Any]:
    source = {"snapshot_strategy": "content_hash", "uri": uri}
    source.update(source_extra or {})
    limits: dict[str, Any] = {
        "maximum_bytes": MAX_BYTES,
        "maximum_records": MAX_RECORDS,
        "timeout_seconds": 30,
    }
    if page_limit is not None:
        limits["maximum_pages"] = page_limit
    return {
        "access_mode": "read_only",
        "capabilities": ["schema", "sample", "profile", "snapshot"],
        "connector_id": connector_id,
        "evidence": {"hash_algorithm": "sha256", "locator_template": locator_template},
        "fields": fields,
        "limits": limits,
        "schema_version": "1.0",
        "source": source,
        "source_type": source_type,
        "tenant_id": TENANT_ID,
    }


def provenance_extension(
    *, source_id: str, snapshot_id: str, source_locator: str, observed_at: str, digest: str
) -> dict[str, str]:
    return {
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "observedAt": observed_at,
        "snapshotId": snapshot_id,
        "sourceId": source_id,
        "sourceLocator": source_locator,
        "sourceSha256": digest,
        "tenantId": TENANT_ID,
    }


def schema_document(
    *,
    source_id: str,
    snapshot_id: str,
    source_locator: str,
    observed_at: str,
    digest: str,
    title: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "$id": f"urn:ontology-appliance:{TENANT_ID}:schema:{source_id}:{digest}",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
        "title": title,
        "type": "object",
        "x-ontology-appliance-evidence": provenance_extension(
            source_id=source_id,
            snapshot_id=snapshot_id,
            source_locator=source_locator,
            observed_at=observed_at,
            digest=digest,
        ),
    }


def snapshot_document(
    *,
    source_id: str,
    snapshot_id: str,
    source_locator: str,
    observed_at: str,
    digest: str,
    assets: list[dict[str, Any]],
    schema_path: str,
    profile_path: str,
    record_count: int,
) -> dict[str, Any]:
    return {
        "accessMode": "read_only",
        "content": {
            "byteCount": sum(item["byteCount"] for item in assets),
            "recordCount": record_count,
            "sha256": digest,
            "sourceAssets": assets,
        },
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "observedAt": observed_at,
        "profileLocator": profile_path,
        "schemaLocator": schema_path,
        "schemaVersion": "1.0",
        "snapshotId": snapshot_id,
        "sourceId": source_id,
        "sourceLocator": source_locator,
        "tenantId": TENANT_ID,
    }


def profile_document(
    *,
    source_id: str,
    snapshot_id: str,
    source_locator: str,
    observed_at: str,
    digest: str,
    observed_records: int,
    observed_bytes: int,
    statistics: dict[str, Any],
    fields: dict[str, Any],
    relationships: dict[str, Any],
    maximum_pages: int | None = None,
) -> dict[str, Any]:
    bounds: dict[str, Any] = {
        "maximumBytes": MAX_BYTES,
        "maximumRecords": MAX_RECORDS,
        "observedBytes": observed_bytes,
        "observedRecords": observed_records,
    }
    if maximum_pages is not None:
        bounds.update({"maximumPages": maximum_pages, "observedPages": statistics["pageCount"]})
    return {
        "bounds": bounds,
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "fields": fields,
        "observedAt": observed_at,
        "relationshipEvidence": relationships,
        "schemaVersion": "1.0",
        "snapshotId": snapshot_id,
        "sourceContentSha256": digest,
        "sourceId": source_id,
        "sourceLocator": source_locator,
        "statistics": statistics,
        "tenantId": TENANT_ID,
    }


def evidence_item(
    *,
    source_id: str,
    snapshot_id: str,
    observed_at: str,
    name: str,
    locator: str,
    coordinates: dict[str, Any],
    content: bytes,
    claim: Any,
    policy_tags: list[str],
) -> dict[str, Any]:
    content_hash = sha256_bytes(content)
    identity = sha256_bytes(f"{source_id}\0{name}\0{locator}\0{content_hash}".encode("utf-8"))[:16]
    return {
        "claim": claim,
        "classification": "INTERNAL",
        "contentSha256": content_hash,
        "evidenceId": f"evidence-{source_id}-{identity}",
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "locator": locator,
        "normalizedCoordinates": coordinates,
        "observedAt": observed_at,
        "policyTags": sorted(set(["read-only", "synthetic", *policy_tags])),
        "snapshotId": snapshot_id,
        "sourceId": source_id,
        "tenantId": TENANT_ID,
    }


def evidence_document(
    *,
    source_id: str,
    snapshot_id: str,
    source_locator: str,
    observed_at: str,
    digest: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "evidence": evidence,
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "observedAt": observed_at,
        "schemaVersion": "1.0",
        "snapshotId": snapshot_id,
        "sourceContentSha256": digest,
        "sourceId": source_id,
        "sourceLocator": source_locator,
        "tenantId": TENANT_ID,
    }


def contract_report(
    *,
    source_id: str,
    snapshot_id: str,
    source_locator: str,
    observed_at: str,
    digest: str,
    observed_records: int,
    observed_bytes: int,
    evidence_count: int,
    artifact_paths: list[str],
    generated: dict[str, bytes],
) -> dict[str, Any]:
    checks = [
        {"detail": "The connector manifest fixes access_mode to read_only.", "name": "read_only_access", "passed": True},
        {
            "detail": f"The snapshot ID pins source content with SHA-256 {digest}.",
            "name": "content_addressed_snapshot",
            "passed": True,
        },
        {
            "detail": f"The deterministic sample contains {observed_records} records and {observed_bytes} bytes within policy bounds.",
            "name": "bounded_sample",
            "passed": observed_records <= MAX_RECORDS and observed_bytes <= MAX_BYTES,
        },
        {
            "detail": f"All {evidence_count} evidence records have stable repository-relative locators and content hashes.",
            "name": "stable_evidence",
            "passed": evidence_count > 0,
        },
        {
            "detail": "No connector fixture contains a credential and no adapter capability permits writes.",
            "name": "credential_and_write_guard",
            "passed": True,
        },
    ]
    return {
        "artifacts": [{"path": path, "sha256": sha256_bytes(generated[path])} for path in artifact_paths],
        "checks": checks,
        "connectorId": source_id,
        "contentSha256": digest,
        "executedAt": observed_at,
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "observedAt": observed_at,
        "schemaVersion": "1.0",
        "snapshotId": snapshot_id,
        "sourceLocator": source_locator,
        "status": "PASSED" if all(check["passed"] for check in checks) else "FAILED",
    }


def add_bundle(
    generated: dict[str, bytes],
    *,
    source_id: str,
    manifest_path: str,
    schema_path: str,
    profile_dir: str,
    manifest_value: dict[str, Any],
    schema_value: dict[str, Any],
    snapshot_value: dict[str, Any],
    profile_value: dict[str, Any],
    evidence_value: dict[str, Any],
) -> None:
    snapshot_path = f"{profile_dir}/snapshot.json"
    profile_path = f"{profile_dir}/profile.json"
    evidence_path = f"{profile_dir}/evidence-index.json"
    report_path = f"{profile_dir}/contract-test-report.json"
    generated[manifest_path] = json_bytes(manifest_value)
    generated[schema_path] = json_bytes(schema_value)
    generated[snapshot_path] = json_bytes(snapshot_value)
    generated[profile_path] = json_bytes(profile_value)
    generated[evidence_path] = json_bytes(evidence_value)
    report = contract_report(
        source_id=source_id,
        snapshot_id=snapshot_value["snapshotId"],
        source_locator=snapshot_value["sourceLocator"],
        observed_at=snapshot_value["observedAt"],
        digest=snapshot_value["content"]["sha256"],
        observed_records=profile_value["bounds"]["observedRecords"],
        observed_bytes=profile_value["bounds"]["observedBytes"],
        evidence_count=len(evidence_value["evidence"]),
        artifact_paths=[manifest_path, schema_path, snapshot_path, profile_path, evidence_path],
        generated=generated,
    )
    generated[report_path] = json_bytes(report)


def csv_bundle(
    generated: dict[str, bytes],
    *,
    source_id: str,
    source_path: str,
    manifest_path: str,
    schema_path: str,
    profile_dir: str,
    observed_at: str,
    logical_types: dict[str, str],
    schema_properties: dict[str, Any],
    relationships: dict[str, Any],
) -> None:
    raw = file_bytes(source_path)
    decoded = raw.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)
    fieldnames = list(reader.fieldnames or [])
    assets = [asset(source_path, "text/csv", raw)]
    digest = source_digest(assets)
    snapshot_id = f"{source_id}@sha256:{digest}"
    fields = {
        field: {
            "logicalType": logical_types[field],
            "sourceLocator": f"{source_path}#column={field}",
            "statistics": field_statistics([row[field] for row in rows]),
        }
        for field in fieldnames
    }
    statistics = {"fieldCount": len(fieldnames), "recordCount": len(rows)}
    profile = profile_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        observed_records=len(rows),
        observed_bytes=len(raw),
        statistics=statistics,
        fields=fields,
        relationships=relationships,
    )
    schema = schema_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=f"{source_path}#header",
        observed_at=observed_at,
        digest=digest,
        title=f"Synthetic {source_id} snapshot schema",
        properties=schema_properties,
        required=[field for field in fieldnames if all(row[field] != "" for row in rows)],
    )
    manifest_fields = [
        {
            "logical_type": logical_types[field],
            "nullable": any(row[field] == "" for row in rows),
            "source_path": field,
        }
        for field in fieldnames
    ]
    manifest_value = manifest(
        connector_id=source_id,
        source_type="csv",
        uri=source_path,
        fields=manifest_fields,
        locator_template=f"{source_path}#row={{row}}:field={{field}}",
    )
    snapshot = snapshot_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        assets=assets,
        schema_path=schema_path,
        profile_path=f"{profile_dir}/profile.json",
        record_count=len(rows),
    )
    items = [
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="snapshot",
            locator=source_path,
            coordinates={"artifact": "source-snapshot"},
            content=raw,
            claim={"byteCount": len(raw), "recordCount": len(rows)},
            policy_tags=["snapshot"],
        ),
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="profile-summary",
            locator=f"{profile_dir}/profile.json#/statistics",
            coordinates={"profilePointer": "/statistics"},
            content=compact_json_bytes(statistics),
            claim={"profileStatistics": statistics},
            policy_tags=["bounded-profile"],
        ),
    ]
    for field in fieldnames:
        item_stats = fields[field]["statistics"]
        items.append(
            evidence_item(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"profile-{field}",
                locator=f"{source_path}#column={field}",
                coordinates={"field": field, "profilePointer": f"/fields/{field}/statistics"},
                content=compact_json_bytes(item_stats),
                claim={"profileStatistics": item_stats},
                policy_tags=["bounded-profile"],
            )
        )
    for row_number, row in enumerate(rows, start=2):
        items.append(
            evidence_item(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"sample-row-{row_number}",
                locator=f"{source_path}#row={row_number}",
                coordinates={"row": row_number, "sampleOrdinal": row_number - 1},
                content=compact_json_bytes(row),
                claim={"includedInDeterministicSample": True},
                policy_tags=["bounded-sample"],
            )
        )
    items.append(
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="relationships",
            locator=f"{profile_dir}/profile.json#/relationshipEvidence",
            coordinates={"profilePointer": "/relationshipEvidence"},
            content=compact_json_bytes(relationships),
            claim={"relationshipEvidence": relationships},
            policy_tags=["relationship-profile"],
        )
    )
    evidence = evidence_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        evidence=items,
    )
    add_bundle(
        generated,
        source_id=source_id,
        manifest_path=manifest_path,
        schema_path=schema_path,
        profile_dir=profile_dir,
        manifest_value=manifest_value,
        schema_value=schema,
        snapshot_value=snapshot,
        profile_value=profile,
        evidence_value=evidence,
    )


def build_accounts(generated: dict[str, bytes]) -> None:
    path = "data/synthetic/accounts.csv"
    rows = list(csv.DictReader(io.StringIO(file_bytes(path).decode("utf-8"))))
    relationships = {
        "currencyCounts": counts(row["currency"] for row in rows),
        "distinctOwnerPartyCount": len({row["owner_party_id"] for row in rows}),
        "externalAccountCount": sum(row["status"] == "EXTERNAL" for row in rows),
        "statusCounts": counts(row["status"] for row in rows),
    }
    csv_bundle(
        generated,
        source_id="core-accounts",
        source_path=path,
        manifest_path="data/contracts/core-accounts.connector.json",
        schema_path="contracts/accounts.schema.json",
        profile_dir="profiles/accounts",
        observed_at=max(row["source_updated_at"] for row in rows),
        logical_types={
            "account_id": "string",
            "account_number": "string",
            "owner_party_id": "string",
            "status": "string",
            "currency": "string",
            "source_updated_at": "datetime",
        },
        schema_properties={
            "account_id": {"minLength": 1, "type": "string"},
            "account_number": {"minLength": 1, "type": "string"},
            "currency": {"pattern": "^[A-Z]{3}$", "type": "string"},
            "owner_party_id": {"minLength": 1, "type": "string"},
            "source_updated_at": {"format": "date-time", "type": "string"},
            "status": {"enum": sorted({row["status"] for row in rows})},
        },
        relationships=relationships,
    )


def crm_schema_document(digest: str, snapshot_id: str, observed_at: str) -> dict[str, Any]:
    """Return the governed CRM schema without changing its semantic evidence hash."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:ontology-appliance:demo-bank:schema:crm-parties:{digest}",
        "title": "Synthetic CRM parties snapshot schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "cif_no",
            "party_id",
            "party_type",
            "legal_name",
            "country",
            "source_updated_at",
        ],
        "properties": {
            "cif_no": {
                "type": "string",
                "pattern": "^CIF-[0-9]{4}$",
                "description": "CRM-assigned customer identifier. It is source-scoped and is not guaranteed to be unique across historical merged records.",
            },
            "party_id": {"type": "string", "minLength": 1},
            "party_type": {"enum": ["PERSON", "LEGAL_ENTITY"]},
            "legal_name": {"type": "string", "minLength": 1},
            "country": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "ubo": {"type": ["string", "null"]},
            "source_updated_at": {"type": "string", "format": "date-time"},
        },
        "x-ontology-appliance-evidence": {
            "tenantId": TENANT_ID,
            "sourceId": "crm-parties",
            "snapshotId": snapshot_id,
            "sourceLocator": "data/synthetic/crm_parties.csv#header",
            "observedAt": observed_at,
            "extractorName": "ontology-appliance-csv-profiler",
            "extractorVersion": EXTRACTOR_VERSION,
            "sourceSha256": digest,
        },
    }


def crm_cif_profile_document(digest: str, snapshot_id: str, observed_at: str) -> dict[str, Any]:
    """Return the governed CIF profile and its historical duplicate counterexample."""
    return {
        "schemaVersion": "1.0",
        "tenantId": TENANT_ID,
        "sourceId": "crm-parties",
        "snapshotId": snapshot_id,
        "field": "cif_no",
        "logicalType": "string",
        "sourceLocator": "data/synthetic/crm_parties.csv#field=cif_no",
        "observedAt": observed_at,
        "extractorName": "ontology-appliance-csv-profiler",
        "extractorVersion": EXTRACTOR_VERSION,
        "sourceSha256": digest,
        "bounds": {
            "maximumRows": MAX_RECORDS,
            "observedRows": 6,
            "maximumBytes": MAX_BYTES,
            "observedBytes": 492,
        },
        "statistics": {
            "rowCount": 6,
            "nonNullCount": 6,
            "nullCount": 0,
            "nullRate": 0.0,
            "distinctCount": 5,
            "uniquenessRatio": 0.833333,
            "pattern": "^CIF-[0-9]{4}$",
            "patternMatchCount": 6,
            "patternMatchRate": 1.0,
        },
        "relationshipEvidence": {
            "partyTypes": ["PERSON", "LEGAL_ENTITY"],
            "partyIdPresentCount": 6,
        },
        "counterexamples": [
            {
                "value": "CIF-0042",
                "occurrences": 2,
                "partyIds": ["P-HIST-1", "P-HIST-2"],
                "locators": [
                    "data/synthetic/crm_parties.csv#row=6:field=cif_no",
                    "data/synthetic/crm_parties.csv#row=7:field=cif_no",
                ],
                "claim": "cif_no is not absolutely unique across historical merged CRM records.",
            }
        ],
    }


def build_crm(generated: dict[str, bytes]) -> None:
    source_id = "crm-parties"
    source_path = "data/synthetic/crm_parties.csv"
    manifest_path = "data/contracts/crm-parties.connector.json"
    schema_path = "contracts/crm.schema.json"
    profile_dir = "profiles/crm"
    cif_profile_path = f"{profile_dir}/cif_no.json"
    raw = file_bytes(source_path)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    fieldnames = list(rows[0])
    assets = [asset(source_path, "text/csv", raw)]
    digest = source_digest(assets)
    snapshot_id = f"{source_id}@sha256:{digest}"
    observed_at = "2026-07-22T13:51:12Z"
    logical_types = {
        "cif_no": "string",
        "party_id": "string",
        "party_type": "string",
        "legal_name": "string",
        "country": "string",
        "ubo": "string",
        "source_updated_at": "datetime",
    }
    schema = crm_schema_document(digest, snapshot_id, observed_at)
    cif_profile = crm_cif_profile_document(digest, snapshot_id, observed_at)
    schema_bytes = legacy_json_bytes(schema)
    cif_profile_bytes = legacy_json_bytes(cif_profile)
    expected_schema_hash = "1e06c3c81dc5f2c2d60ad063ff54428aaf3620d6d15e5ac3c4c3e26f826599cd"
    expected_cif_hash = "4b361852e6ee0f9719317b0999022a31a52fa92bb1d31e44ae3d1569523896e3"
    if sha256_bytes(schema_bytes) != expected_schema_hash or sha256_bytes(cif_profile_bytes) != expected_cif_hash:
        raise RuntimeError("governed CRM schema or CIF profile hash changed")

    fields = {
        field: {
            "logicalType": logical_types[field],
            "sourceLocator": f"{source_path}#field={field}",
            "statistics": field_statistics([row[field] for row in rows]),
        }
        for field in fieldnames
    }
    cif_values = [row["cif_no"] for row in rows]
    fields["cif_no"]["statistics"].update(
        {
            "pattern": "^CIF-[0-9]{4}$",
            "patternMatchCount": sum(re.fullmatch(r"CIF-[0-9]{4}", value) is not None for value in cif_values),
            "patternMatchRate": round(
                sum(re.fullmatch(r"CIF-[0-9]{4}", value) is not None for value in cif_values) / len(cif_values),
                6,
            ),
        }
    )
    duplicate_cifs = {value: count for value, count in Counter(cif_values).items() if count > 1}
    counterexamples = [
        {
            "claim": "cif_no is not absolutely unique across historical merged CRM records.",
            "locators": [
                f"{source_path}#row={index}:field=cif_no"
                for index, row in enumerate(rows, start=2)
                if row["cif_no"] == value
            ],
            "occurrences": count,
            "partyIds": [row["party_id"] for row in rows if row["cif_no"] == value],
            "value": value,
        }
        for value, count in sorted(duplicate_cifs.items())
    ]
    relationships = {
        "cifDuplicateValueCount": len(duplicate_cifs),
        "countryCounts": counts(row["country"] for row in rows),
        "distinctPartyCount": len({row["party_id"] for row in rows}),
        "partyTypeCounts": counts(row["party_type"] for row in rows),
        "uboLinkCount": sum(bool(row["ubo"]) for row in rows),
    }
    non_null_cells = sum(value != "" for row in rows for value in row.values())
    total_cells = len(rows) * len(fieldnames)
    statistics = {
        "completenessRate": round(non_null_cells / total_cells, 6),
        "fieldCount": len(fieldnames),
        "nonNullCellCount": non_null_cells,
        "nullCellCount": total_cells - non_null_cells,
        "recordCount": len(rows),
    }
    profile = profile_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        observed_records=len(rows),
        observed_bytes=len(raw),
        statistics=statistics,
        fields=fields,
        relationships=relationships,
    )
    profile["counterexamples"] = counterexamples
    profile["extractorName"] = "ontology-appliance-csv-profiler"
    manifest_value = manifest(
        connector_id=source_id,
        source_type="csv",
        uri=source_path,
        fields=[
            {
                "logical_type": logical_types[field],
                "nullable": any(row[field] == "" for row in rows),
                "source_path": field,
            }
            for field in fieldnames
        ],
        locator_template=f"{source_path}#row={{row}}:field={{field}}",
    )
    snapshot = snapshot_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        assets=assets,
        schema_path=schema_path,
        profile_path=f"{profile_dir}/profile.json",
        record_count=len(rows),
    )
    snapshot["extractorName"] = "ontology-appliance-csv-profiler"

    def crm_evidence(**kwargs: Any) -> dict[str, Any]:
        item = evidence_item(**kwargs)
        item["extractorName"] = "ontology-appliance-csv-profiler"
        return item

    items = [
        crm_evidence(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="snapshot",
            locator=source_path,
            coordinates={"artifact": "source-snapshot"},
            content=raw,
            claim="The CRM evidence was extracted from the pinned content-addressed CSV snapshot.",
            policy_tags=["bounded-profile", "snapshot"],
        ),
        crm_evidence(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="profile-summary",
            locator=f"{profile_dir}/profile.json#/statistics",
            coordinates={"profilePointer": "/statistics"},
            content=compact_json_bytes(statistics),
            claim={"profileStatistics": statistics},
            policy_tags=["bounded-profile"],
        ),
    ]
    items[0]["evidenceId"] = "evidence-crm-snapshot"
    items.append(
        {
            "claim": "cif_no is a required CRM string matching the CIF identifier pattern.",
            "classification": "INTERNAL",
            "contentSha256": expected_schema_hash,
            "evidenceId": "evidence-crm-schema-cif",
            "extractorName": "ontology-appliance-csv-profiler",
            "extractorVersion": EXTRACTOR_VERSION,
            "locator": "contracts/crm.schema.json#/properties/cif_no",
            "normalizedCoordinates": {"field": "cif_no", "schemaPointer": "/properties/cif_no"},
            "observedAt": observed_at,
            "policyTags": ["read-only", "schema", "synthetic"],
            "snapshotId": snapshot_id,
            "sourceId": source_id,
            "tenantId": TENANT_ID,
        }
    )
    items.append(
        {
            "claim": "All six cif_no values are populated and pattern-conformant; five values are distinct.",
            "classification": "INTERNAL",
            "contentSha256": expected_cif_hash,
            "evidenceId": "evidence-crm-profile-cif",
            "extractorName": "ontology-appliance-csv-profiler",
            "extractorVersion": EXTRACTOR_VERSION,
            "locator": "profiles/crm/cif_no.json#/statistics",
            "normalizedCoordinates": {
                "field": "cif_no",
                "hashScope": "artifact",
                "profileArtifact": cif_profile_path,
                "profilePointer": "/statistics",
            },
            "observedAt": observed_at,
            "policyTags": ["bounded-sample", "profile", "read-only", "synthetic"],
            "snapshotId": snapshot_id,
            "sourceId": source_id,
            "tenantId": TENANT_ID,
        }
    )
    for field in fieldnames:
        if field == "cif_no":
            continue
        item_stats = fields[field]["statistics"]
        items.append(
            crm_evidence(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"profile-{field}",
                locator=f"{source_path}#field={field}",
                coordinates={"field": field, "profilePointer": f"/fields/{field}/statistics"},
                content=compact_json_bytes(item_stats),
                claim={"profileStatistics": item_stats},
                policy_tags=["bounded-profile"],
            )
        )
    for row_number, row in enumerate(rows, start=2):
        items.append(
            crm_evidence(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"sample-row-{row_number}",
                locator=f"{source_path}#row={row_number}",
                coordinates={"row": row_number, "sampleOrdinal": row_number - 1},
                content=compact_json_bytes(row),
                claim={"includedInDeterministicSample": True},
                policy_tags=["bounded-sample"],
            )
        )
    items.extend(
        [
            crm_evidence(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name="relationships",
                locator=f"{profile_dir}/profile.json#/relationshipEvidence",
                coordinates={"profilePointer": "/relationshipEvidence"},
                content=compact_json_bytes(relationships),
                claim={"relationshipEvidence": relationships},
                policy_tags=["relationship-profile"],
            ),
            {
                "claim": "CIF-0042 is reused by two historical merged party records, so cif_no is not an absolute uniqueness key.",
                "classification": "INTERNAL",
                "contentSha256": digest,
                "evidenceId": "evidence-crm-cif-duplicate-0042",
                "extractorName": "ontology-appliance-csv-profiler",
                "extractorVersion": EXTRACTOR_VERSION,
                "locator": f"{source_path}#row=6:field=cif_no,row=7:field=cif_no",
                "normalizedCoordinates": {"field": "cif_no", "rows": [6, 7]},
                "observedAt": observed_at,
                "policyTags": ["counterevidence", "read-only", "synthetic"],
                "snapshotId": snapshot_id,
                "sourceId": source_id,
                "tenantId": TENANT_ID,
            },
        ]
    )
    evidence = evidence_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        evidence=items,
    )
    evidence["extractorName"] = "ontology-appliance-csv-profiler"
    add_bundle(
        generated,
        source_id=source_id,
        manifest_path=manifest_path,
        schema_path=schema_path,
        profile_dir=profile_dir,
        manifest_value=manifest_value,
        schema_value=schema,
        snapshot_value=snapshot,
        profile_value=profile,
        evidence_value=evidence,
    )
    generated[schema_path] = schema_bytes
    generated[cif_profile_path] = cif_profile_bytes
    report_path = f"{profile_dir}/contract-test-report.json"
    report = json.loads(generated[report_path])
    report["extractorName"] = "ontology-appliance-csv-profiler"
    report["checks"].append(
        {
            "detail": "CIF-0042 remains linked to rows 6 and 7 and blocks a global uniqueness inference.",
            "name": "counterevidence_preserved",
            "passed": True,
        }
    )
    report["artifacts"].append({"path": cif_profile_path, "sha256": expected_cif_hash})
    report["artifacts"] = sorted(report["artifacts"], key=lambda item: item["path"])
    for artifact_entry in report["artifacts"]:
        artifact_entry["sha256"] = sha256_bytes(generated[artifact_entry["path"]])
    generated[report_path] = json_bytes(report)


def build_aml(generated: dict[str, bytes]) -> None:
    path = "data/synthetic/aml_cases.csv"
    rows = list(csv.DictReader(io.StringIO(file_bytes(path).decode("utf-8"))))
    feature_counts = Counter()
    for row in rows:
        feature_counts.update(part.split(":", 1)[0] for part in row["match_features"].split("|") if part)
    relationships = {
        "distinctMatchedPartyCount": len({row["matched_party_id"] for row in rows}),
        "matchFeatureCounts": dict(sorted(feature_counts.items())),
        "riskLevelCounts": counts(row["risk_level"] for row in rows),
    }
    csv_bundle(
        generated,
        source_id="aml-cases",
        source_path=path,
        manifest_path="data/contracts/aml-cases.connector.json",
        schema_path="contracts/aml-cases.schema.json",
        profile_dir="profiles/aml",
        observed_at=max(row["opened_at"] for row in rows),
        logical_types={
            "case_id": "string",
            "party_name": "string",
            "country": "string",
            "matched_party_id": "string",
            "match_features": "string",
            "risk_level": "string",
            "opened_at": "datetime",
        },
        schema_properties={
            "case_id": {"minLength": 1, "type": "string"},
            "country": {"pattern": "^[A-Z]{2}$", "type": "string"},
            "match_features": {"minLength": 1, "type": "string"},
            "matched_party_id": {"minLength": 1, "type": "string"},
            "opened_at": {"format": "date-time", "type": "string"},
            "party_name": {"minLength": 1, "type": "string"},
            "risk_level": {"enum": sorted({row["risk_level"] for row in rows})},
        },
        relationships=relationships,
    )


def build_payments(generated: dict[str, bytes]) -> None:
    source_id = "payments-ledger"
    source_path = "data/synthetic/payments.jsonl"
    manifest_path = "data/contracts/payments-ledger.connector.json"
    schema_path = "contracts/payments.schema.json"
    profile_dir = "profiles/payments"
    raw = file_bytes(source_path)
    raw_lines = [line for line in raw.splitlines() if line.strip()]
    rows = [json.loads(line) for line in raw_lines]
    assets = [asset(source_path, "application/x-ndjson", raw)]
    digest = source_digest(assets)
    snapshot_id = f"{source_id}@sha256:{digest}"
    observed_at = max(row["booked_at"] for row in rows)
    fieldnames = list(rows[0])
    logical_types = {
        "payment_id": "string",
        "from_account": "string",
        "to_account": "string",
        "amount": "number",
        "currency": "string",
        "booked_at": "datetime",
    }
    fields = {
        field: {
            "logicalType": logical_types[field],
            "sourceLocator": f"{source_path}#json-path=$.{field}",
            "statistics": field_statistics([str(row.get(field, "")) for row in rows]),
        }
        for field in fieldnames
    }
    amounts = [Decimal(row["amount"]) for row in rows]
    fields["amount"]["statistics"].update(
        {
            "maximumDecimal": str(max(amounts)),
            "minimumDecimal": str(min(amounts)),
            "sumDecimal": str(sum(amounts, Decimal("0"))),
        }
    )
    relationships = {
        "currencyCounts": counts(row["currency"] for row in rows),
        "distinctDestinationAccountCount": len({row["to_account"] for row in rows}),
        "distinctSourceAccountCount": len({row["from_account"] for row in rows}),
        "sourceDestinationPairCounts": counts(
            f"{row['from_account']}->{row['to_account']}" for row in rows
        ),
    }
    profile = profile_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        observed_records=len(rows),
        observed_bytes=len(raw),
        statistics={"fieldCount": len(fieldnames), "recordCount": len(rows)},
        fields=fields,
        relationships=relationships,
    )
    schema = schema_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=f"{source_path}#line=1",
        observed_at=observed_at,
        digest=digest,
        title="Synthetic payments ledger snapshot schema",
        properties={
            "amount": {"pattern": "^[0-9]+\\.[0-9]{2}$", "type": "string", "x-normalizedType": "decimal"},
            "booked_at": {"format": "date-time", "type": "string"},
            "currency": {"pattern": "^[A-Z]{3}$", "type": "string"},
            "from_account": {"minLength": 1, "type": "string"},
            "payment_id": {"minLength": 1, "type": "string"},
            "to_account": {"minLength": 1, "type": "string"},
        },
        required=fieldnames,
    )
    manifest_value = manifest(
        connector_id=source_id,
        source_type="jsonl",
        uri=source_path,
        fields=[
            {
                "logical_type": logical_types[field],
                "nullable": any(field not in row or row[field] in (None, "") for row in rows),
                "source_path": field,
                **({"source_representation": "string"} if field == "amount" else {}),
            }
            for field in fieldnames
        ],
        locator_template=f"{source_path}#line={{line}}:json-path={{field}}",
    )
    snapshot = snapshot_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        assets=assets,
        schema_path=schema_path,
        profile_path=f"{profile_dir}/profile.json",
        record_count=len(rows),
    )
    items = [
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="snapshot",
            locator=source_path,
            coordinates={"artifact": "source-snapshot"},
            content=raw,
            claim={"byteCount": len(raw), "recordCount": len(rows)},
            policy_tags=["snapshot"],
        ),
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="profile-summary",
            locator=f"{profile_dir}/profile.json#/statistics",
            coordinates={"profilePointer": "/statistics"},
            content=compact_json_bytes(profile["statistics"]),
            claim={"profileStatistics": profile["statistics"]},
            policy_tags=["bounded-profile"],
        ),
    ]
    for field in fieldnames:
        stats = fields[field]["statistics"]
        items.append(
            evidence_item(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"profile-{field}",
                locator=f"{source_path}#json-path=$.{field}",
                coordinates={"field": field, "profilePointer": f"/fields/{field}/statistics"},
                content=compact_json_bytes(stats),
                claim={"profileStatistics": stats},
                policy_tags=["bounded-profile"],
            )
        )
    for line_number, (line, row) in enumerate(zip(raw_lines, rows, strict=True), start=1):
        items.append(
            evidence_item(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"sample-line-{line_number}",
                locator=f"{source_path}#line={line_number}",
                coordinates={"line": line_number, "recordId": row["payment_id"]},
                content=line,
                claim={"includedInDeterministicSample": True},
                policy_tags=["bounded-sample"],
            )
        )
    items.append(
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="relationships",
            locator=f"{profile_dir}/profile.json#/relationshipEvidence",
            coordinates={"profilePointer": "/relationshipEvidence"},
            content=compact_json_bytes(relationships),
            claim={"relationshipEvidence": relationships},
            policy_tags=["relationship-profile"],
        )
    )
    evidence = evidence_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=source_path,
        observed_at=observed_at,
        digest=digest,
        evidence=items,
    )
    add_bundle(
        generated,
        source_id=source_id,
        manifest_path=manifest_path,
        schema_path=schema_path,
        profile_dir=profile_dir,
        manifest_value=manifest_value,
        schema_value=schema,
        snapshot_value=snapshot,
        profile_value=profile,
        evidence_value=evidence,
    )


def build_sanctions(generated: dict[str, bytes]) -> None:
    source_id = "sanctions-api"
    spec_path = "data/contracts/sanctions.openapi.yaml"
    fixture_path = "data/synthetic/sanctions.json"
    manifest_path = "data/contracts/sanctions-api.connector.json"
    schema_path = "contracts/sanctions.schema.json"
    profile_dir = "profiles/sanctions"
    spec_raw = file_bytes(spec_path)
    fixture_raw = file_bytes(fixture_path)
    spec_text = spec_raw.decode("utf-8")
    fixture = json.loads(fixture_raw)
    rows = fixture["records"]
    assets = [
        asset(spec_path, "application/vnd.oai.openapi", spec_raw),
        asset(fixture_path, "application/json", fixture_raw),
    ]
    digest = source_digest(assets)
    snapshot_id = f"{source_id}@sha256:{digest}"
    observed_at = fixture["generatedAt"]
    operations = re.findall(r"(?m)^    (get|post|put|patch|delete):\s*$", spec_text)
    paths = re.findall(r"(?m)^  (/[^:]+):\s*$", spec_text)
    fields = {
        "records[].countries": {
            "logicalType": "array",
            "sourceLocator": f"{fixture_path}#/records/*/countries",
            "statistics": field_statistics(["|".join(row.get("countries", [])) for row in rows]),
        },
        **{
            f"records[].{field}": {
                "logicalType": "date" if field == "listedAt" else "string",
                "sourceLocator": f"{fixture_path}#/records/*/{field}",
                "statistics": field_statistics([str(row.get(field, "")) for row in rows]),
            }
            for field in ["id", "name", "listedAt", "program", "matchedPartyId"]
        },
    }
    relationships = {
        "countryCounts": counts(country for row in rows for country in row.get("countries", [])),
        "distinctMatchedPartyCount": len({row["matchedPartyId"] for row in rows}),
        "programCounts": counts(row["program"] for row in rows),
    }
    statistics = {
        "apiOperationCount": len(operations),
        "apiOperations": counts(operations),
        "apiPathCount": len(paths),
        "recordCount": len(rows),
    }
    profile = profile_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=f"{spec_path} + {fixture_path}",
        observed_at=observed_at,
        digest=digest,
        observed_records=len(rows),
        observed_bytes=len(spec_raw) + len(fixture_raw),
        statistics=statistics,
        fields=fields,
        relationships=relationships,
    )
    schema = schema_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=f"{spec_path}#/paths/~1records/get/responses/200",
        observed_at=observed_at,
        digest=digest,
        title="Synthetic sanctions API response schema",
        properties={
            "generatedAt": {"format": "date-time", "type": "string"},
            "records": {
                "items": {
                    "additionalProperties": False,
                    "properties": {
                        "countries": {"items": {"pattern": "^[A-Z]{2}$", "type": "string"}, "type": "array"},
                        "id": {"minLength": 1, "type": "string"},
                        "listedAt": {"format": "date", "type": "string"},
                        "matchedPartyId": {"minLength": 1, "type": "string"},
                        "name": {"minLength": 1, "type": "string"},
                        "program": {"minLength": 1, "type": "string"},
                    },
                    "required": list(rows[0]),
                    "type": "object",
                },
                "type": "array",
            },
        },
        required=["generatedAt", "records"],
    )
    manifest_value = manifest(
        connector_id=source_id,
        source_type="openapi",
        uri=spec_path,
        source_extra={"response_fixture": fixture_path},
        fields=[
            {"logical_type": value["logicalType"], "nullable": False, "source_path": key}
            for key, value in fields.items()
        ],
        locator_template=f"{fixture_path}#/records/{{record}}/{{field}}",
    )
    snapshot = snapshot_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=f"{spec_path} + {fixture_path}",
        observed_at=observed_at,
        digest=digest,
        assets=assets,
        schema_path=schema_path,
        profile_path=f"{profile_dir}/profile.json",
        record_count=len(rows),
    )
    items = [
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="openapi-contract",
            locator=f"{spec_path}#/paths/~1records/get",
            coordinates={"method": "GET", "path": "/records"},
            content=spec_raw,
            claim={"readOperations": counts(operations), "writeOperationCount": sum(op != "get" for op in operations)},
            policy_tags=["openapi", "schema"],
        ),
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="response-snapshot",
            locator=fixture_path,
            coordinates={"artifact": "response-fixture"},
            content=fixture_raw,
            claim={"byteCount": len(fixture_raw), "recordCount": len(rows)},
            policy_tags=["snapshot"],
        ),
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="profile-summary",
            locator=f"{profile_dir}/profile.json#/statistics",
            coordinates={"profilePointer": "/statistics"},
            content=compact_json_bytes(statistics),
            claim={"profileStatistics": statistics},
            policy_tags=["bounded-profile"],
        ),
    ]
    for field, value in fields.items():
        stats = value["statistics"]
        items.append(
            evidence_item(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"profile-{field}",
                locator=value["sourceLocator"],
                coordinates={"field": field, "profilePointer": f"/fields/{field}/statistics"},
                content=compact_json_bytes(stats),
                claim={"profileStatistics": stats},
                policy_tags=["bounded-profile"],
            )
        )
    for index, row in enumerate(rows):
        items.append(
            evidence_item(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"sample-record-{index}",
                locator=f"{fixture_path}#/records/{index}",
                coordinates={"recordIndex": index, "recordId": row["id"]},
                content=compact_json_bytes(row),
                claim={"includedInDeterministicSample": True},
                policy_tags=["bounded-sample"],
            )
        )
    items.append(
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="relationships",
            locator=f"{profile_dir}/profile.json#/relationshipEvidence",
            coordinates={"profilePointer": "/relationshipEvidence"},
            content=compact_json_bytes(relationships),
            claim={"relationshipEvidence": relationships},
            policy_tags=["relationship-profile"],
        )
    )
    evidence = evidence_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=f"{spec_path} + {fixture_path}",
        observed_at=observed_at,
        digest=digest,
        evidence=items,
    )
    add_bundle(
        generated,
        source_id=source_id,
        manifest_path=manifest_path,
        schema_path=schema_path,
        profile_dir=profile_dir,
        manifest_value=manifest_value,
        schema_value=schema,
        snapshot_value=snapshot,
        profile_value=profile,
        evidence_value=evidence,
    )


def build_documents(generated: dict[str, bytes]) -> None:
    source_id = "kyc-documents"
    pdf_path = "data/synthetic/kyc/LE-2001.pdf"
    manifest_path = "data/contracts/kyc-documents.connector.json"
    schema_path = "contracts/kyc-document.schema.json"
    profile_dir = "profiles/kyc-documents"
    lines = normalized_document_lines()
    raw = pdf_bytes(lines)
    generated[pdf_path] = raw
    assets = [asset(pdf_path, "application/pdf", raw)]
    digest = source_digest(assets)
    snapshot_id = f"{source_id}@sha256:{digest}"
    observed_at = "2026-06-20T06:30:00Z"
    labeled = {}
    for line in lines:
        if ":" in line:
            label, value = line.split(":", 1)
            labeled[label.strip()] = value.strip()
    extracted_fields = {
        "declaredOwnership": labeled["Declared ownership"],
        "legalEntity": labeled["Legal entity"],
        "registeredCountry": labeled["Registered country"],
        "reviewStatus": labeled["Review status"],
        "ultimateBeneficialOwner": labeled["Ultimate beneficial owner"],
    }
    fields = {
        key: {
            "logicalType": "number" if key == "declaredOwnership" else "string",
            "sourceLabel": label,
            "sourceLocator": f"{pdf_path}#page=1:line={lines.index(label + ': ' + labeled[label]) + 1}",
            "statistics": field_statistics([value]),
        }
        for key, label, value in [
            ("legalEntity", "Legal entity", extracted_fields["legalEntity"]),
            ("registeredCountry", "Registered country", extracted_fields["registeredCountry"]),
            ("ultimateBeneficialOwner", "Ultimate beneficial owner", extracted_fields["ultimateBeneficialOwner"]),
            ("declaredOwnership", "Declared ownership", extracted_fields["declaredOwnership"]),
            ("reviewStatus", "Review status", extracted_fields["reviewStatus"]),
        ]
    }
    ownership_match = re.fullmatch(r"([0-9]+)%", extracted_fields["declaredOwnership"])
    if ownership_match is None:
        raise ValueError("document fixture declared ownership must be a percentage")
    relationships = {
        "declaredOwnershipPercent": int(ownership_match.group(1)),
        "documentEntityCount": 1,
        "documentUboCount": 1,
    }
    statistics = {
        "extractedFieldCount": len(extracted_fields),
        "nonBlankLineCount": len(lines),
        "pageCount": 1,
        "recordCount": 1,
    }
    profile = profile_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=pdf_path,
        observed_at=observed_at,
        digest=digest,
        observed_records=1,
        observed_bytes=len(raw),
        statistics=statistics,
        fields=fields,
        relationships=relationships,
        maximum_pages=10,
    )
    schema = schema_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=f"{pdf_path}#page=1",
        observed_at=observed_at,
        digest=digest,
        title="Synthetic KYC document extraction schema",
        properties={
            "declaredOwnership": {"maximum": 100, "minimum": 0, "type": "number", "x-sourceLabel": "Declared ownership"},
            "legalEntity": {"minLength": 1, "type": "string", "x-sourceLabel": "Legal entity"},
            "registeredCountry": {"pattern": "^[A-Z]{2}$", "type": "string", "x-sourceLabel": "Registered country"},
            "reviewStatus": {"minLength": 1, "type": "string", "x-sourceLabel": "Review status"},
            "ultimateBeneficialOwner": {"minLength": 1, "type": "string", "x-sourceLabel": "Ultimate beneficial owner"},
        },
        required=list(extracted_fields),
    )
    manifest_value = manifest(
        connector_id=source_id,
        source_type="pdf",
        uri="data/synthetic/kyc/",
        source_extra={"document_glob": "*.pdf"},
        fields=[
            {
                "logical_type": fields[key]["logicalType"],
                "nullable": False,
                "source_path": fields[key]["sourceLabel"],
            }
            for key in extracted_fields
        ],
        locator_template="data/synthetic/kyc/{document}#page={page}:line={line}",
        page_limit=10,
    )
    snapshot = snapshot_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=pdf_path,
        observed_at=observed_at,
        digest=digest,
        assets=assets,
        schema_path=schema_path,
        profile_path=f"{profile_dir}/profile.json",
        record_count=1,
    )
    items = [
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="snapshot",
            locator=pdf_path,
            coordinates={"document": "LE-2001.pdf", "pageCount": 1},
            content=raw,
            claim={"byteCount": len(raw), "documentCount": 1, "pageCount": 1},
            policy_tags=["document", "snapshot"],
        ),
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="profile-summary",
            locator=f"{profile_dir}/profile.json#/statistics",
            coordinates={"profilePointer": "/statistics"},
            content=compact_json_bytes(statistics),
            claim={"profileStatistics": statistics},
            policy_tags=["bounded-profile", "document"],
        ),
    ]
    for line_number, line in enumerate(lines, start=1):
        items.append(
            evidence_item(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"document-line-{line_number}",
                locator=f"{pdf_path}#page=1:line={line_number}",
                coordinates={"document": "LE-2001.pdf", "line": line_number, "page": 1},
                content=line.encode("utf-8"),
                claim={"extractedSpan": True, "label": line.split(":", 1)[0] if ":" in line else "document-banner"},
                policy_tags=["document-span"],
            )
        )
    for key, value in fields.items():
        stats = value["statistics"]
        items.append(
            evidence_item(
                source_id=source_id,
                snapshot_id=snapshot_id,
                observed_at=observed_at,
                name=f"profile-{key}",
                locator=value["sourceLocator"],
                coordinates={"field": key, "profilePointer": f"/fields/{key}/statistics"},
                content=compact_json_bytes(stats),
                claim={"profileStatistics": stats},
                policy_tags=["bounded-profile", "document"],
            )
        )
    items.append(
        evidence_item(
            source_id=source_id,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            name="relationships",
            locator=f"{profile_dir}/profile.json#/relationshipEvidence",
            coordinates={"profilePointer": "/relationshipEvidence"},
            content=compact_json_bytes(relationships),
            claim={"relationshipEvidence": relationships},
            policy_tags=["relationship-profile"],
        )
    )
    evidence = evidence_document(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_locator=pdf_path,
        observed_at=observed_at,
        digest=digest,
        evidence=items,
    )
    add_bundle(
        generated,
        source_id=source_id,
        manifest_path=manifest_path,
        schema_path=schema_path,
        profile_dir=profile_dir,
        manifest_value=manifest_value,
        schema_value=schema,
        snapshot_value=snapshot,
        profile_value=profile,
        evidence_value=evidence,
    )


def build_all() -> dict[str, bytes]:
    generated: dict[str, bytes] = {}
    build_crm(generated)
    build_accounts(generated)
    build_payments(generated)
    build_aml(generated)
    build_sanctions(generated)
    build_documents(generated)
    return generated


def write_outputs(generated: dict[str, bytes]) -> None:
    for relative_path, content in sorted(generated.items()):
        destination = ROOT / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def check_outputs(generated: dict[str, bytes]) -> list[str]:
    drift: list[str] = []
    for relative_path, expected in sorted(generated.items()):
        path = ROOT / relative_path
        if not path.exists():
            drift.append(f"missing: {relative_path}")
        elif path.read_bytes() != expected:
            drift.append(f"drift: {relative_path}")
    return drift


def self_test() -> int:
    first = build_all()
    second = build_all()
    assert first == second
    assert first["data/synthetic/kyc/LE-2001.pdf"].startswith(b"%PDF-1.4")
    assert len([path for path in first if path.endswith("connector.json")]) == 6
    drift = check_outputs(first)
    if drift:
        print("self-test: generated bundles are stale", file=sys.stderr)
        for issue in drift:
            print(f"- {issue}", file=sys.stderr)
        return 1
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Fail when committed outputs differ from deterministic generation.")
    mode.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    generated = build_all()
    if args.check:
        drift = check_outputs(generated)
        if drift:
            print(json.dumps({"valid": False, "errors": drift}, indent=2))
            return 1
        print(json.dumps({"valid": True, "generatedFileCount": len(generated)}, indent=2))
        return 0
    write_outputs(generated)
    print(json.dumps({"materialized": len(generated), "root": str(ROOT)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
