#!/usr/bin/env python3
"""Validate a read-only evidence connector manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

SOURCE_TYPES = {"csv", "jsonl", "pdf", "openapi"}
CAPABILITIES = {"schema", "sample", "profile", "snapshot"}
LOGICAL_TYPES = {"string", "integer", "number", "boolean", "date", "datetime", "object", "array", "binary"}
SECRET_REF = re.compile(r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$")
SENSITIVE_KEYS = {"password", "token", "api_key", "apikey", "secret", "client_secret", "private_key"}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "connector_id",
    "tenant_id",
    "source_type",
    "access_mode",
    "source",
    "credential_ref",
    "capabilities",
    "fields",
    "evidence",
    "limits",
}


def walk(value: Any, path: str = "$") -> Iterator[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, str(key).lower(), child
            yield from walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def validate(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["manifest must be a JSON object"]

    required = (
        "schema_version",
        "connector_id",
        "tenant_id",
        "source_type",
        "access_mode",
        "source",
        "capabilities",
        "fields",
        "evidence",
    )
    for key in required:
        if key not in data:
            errors.append(f"missing required field: {key}")
    unknown_fields = set(data) - TOP_LEVEL_FIELDS
    if unknown_fields:
        errors.append(f"unsupported top-level fields: {sorted(unknown_fields)}")
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    for key in ("connector_id", "tenant_id"):
        if not isinstance(data.get(key), str) or not data.get(key, "").strip():
            errors.append(f"{key} must be a non-empty string")
    if data.get("source_type") not in SOURCE_TYPES:
        errors.append(f"source_type must be one of {sorted(SOURCE_TYPES)}")
    if data.get("access_mode") != "read_only":
        errors.append("access_mode must be 'read_only'")

    for path, key, value in walk(data):
        if key in SENSITIVE_KEYS and value not in (None, "", "***"):
            errors.append(f"inline secret-like value is forbidden at {path}")

    credential_ref = data.get("credential_ref")
    if credential_ref is not None and (not isinstance(credential_ref, str) or not SECRET_REF.fullmatch(credential_ref)):
        errors.append("credential_ref must be a Secret Manager version resource")

    source = data.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        unknown_source_fields = set(source) - {
            "uri",
            "snapshot_strategy",
            "response_fixture",
            "document_glob",
        }
        if unknown_source_fields:
            errors.append(f"unsupported source fields: {sorted(unknown_source_fields)}")
        uri = source.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            errors.append("source.uri must be a non-empty URI")
        elif "://" in uri:
            parsed = urlsplit(uri)
            if parsed.username or parsed.password:
                errors.append("source.uri must not contain embedded credentials")
        if source.get("snapshot_strategy") not in {"immutable", "watermark", "content_hash"}:
            errors.append("source.snapshot_strategy must be immutable, watermark, or content_hash")

    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        errors.append("capabilities must be a non-empty array")
    else:
        unknown = set(capabilities) - CAPABILITIES
        if unknown:
            errors.append(f"unsupported capabilities: {sorted(unknown)}")
        if len(capabilities) != len(set(capabilities)):
            errors.append("capabilities must not contain duplicates")

    fields = data.get("fields")
    if not isinstance(fields, list):
        errors.append("fields must be an array")
    else:
        seen: set[str] = set()
        for index, field in enumerate(fields):
            label = f"fields[{index}]"
            if not isinstance(field, dict):
                errors.append(f"{label} must be an object")
                continue
            unknown_field_metadata = set(field) - {
                "source_path",
                "logical_type",
                "nullable",
                "source_representation",
            }
            if unknown_field_metadata:
                errors.append(f"{label} has unsupported fields: {sorted(unknown_field_metadata)}")
            source_path = field.get("source_path")
            if not isinstance(source_path, str) or not source_path:
                errors.append(f"{label}.source_path must be a non-empty string")
            elif source_path in seen:
                errors.append(f"duplicate field source_path: {source_path}")
            else:
                seen.add(source_path)
            if field.get("logical_type") not in LOGICAL_TYPES:
                errors.append(f"{label}.logical_type must be one of {sorted(LOGICAL_TYPES)}")
            if not isinstance(field.get("nullable"), bool):
                errors.append(f"{label}.nullable must be boolean")

    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
    else:
        unknown_evidence_fields = set(evidence) - {"locator_template", "hash_algorithm"}
        if unknown_evidence_fields:
            errors.append(f"unsupported evidence fields: {sorted(unknown_evidence_fields)}")
        if not isinstance(evidence.get("locator_template"), str) or not evidence.get("locator_template"):
            errors.append("evidence.locator_template must be a non-empty string")
        if evidence.get("hash_algorithm") != "sha256":
            errors.append("evidence.hash_algorithm must be 'sha256'")

    limits = data.get("limits")
    if limits is not None:
        if not isinstance(limits, dict):
            errors.append("limits must be an object")
        else:
            allowed_limits = {
                "maximum_bytes",
                "maximum_records",
                "maximum_pages",
                "timeout_seconds",
            }
            unknown_limits = set(limits) - allowed_limits
            if unknown_limits:
                errors.append(f"unsupported limit fields: {sorted(unknown_limits)}")
            for key, value in limits.items():
                if key in allowed_limits and (
                    not isinstance(value, int) or isinstance(value, bool) or value < 1
                ):
                    errors.append(f"limits.{key} must be a positive integer")
    return errors


def valid_example() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "connector_id": "crm-parties",
        "tenant_id": "demo-bank",
        "source_type": "csv",
        "access_mode": "read_only",
        "source": {"uri": "gs://oa-dev-inputs/crm.csv", "snapshot_strategy": "immutable"},
        "capabilities": ["schema", "sample", "profile"],
        "fields": [{"source_path": "cif_no", "logical_type": "string", "nullable": False}],
        "evidence": {"locator_template": "row:{row}:field:{field}", "hash_algorithm": "sha256"},
    }


def self_test() -> int:
    assert validate(valid_example()) == []
    broken = valid_example()
    broken["access_mode"] = "read_write"
    broken["password"] = "leak"
    errors = validate(broken)
    assert any("read_only" in error for error in errors)
    assert any("inline secret" in error for error in errors)
    assert any("unsupported top-level" in error for error in errors)
    roadmap = valid_example()
    roadmap["source_type"] = "postgres"
    assert any("source_type" in error for error in validate(roadmap))
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.manifest is None:
        parser.error("manifest is required unless --self-test is used")
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 2
    errors = validate(data)
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
