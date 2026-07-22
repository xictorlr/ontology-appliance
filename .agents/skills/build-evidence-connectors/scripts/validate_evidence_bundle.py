#!/usr/bin/env python3
"""Validate connector manifests and their reproducible evidence bundle sidecars."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from validate_connector_manifest import validate as validate_manifest


ROOT = Path(__file__).resolve().parents[4]
BUNDLES = ("crm", "accounts", "payments", "aml", "sanctions", "kyc-documents")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MANIFESTS = {
    "crm": "data/contracts/crm-parties.connector.json",
    "accounts": "data/contracts/core-accounts.connector.json",
    "payments": "data/contracts/payments-ledger.connector.json",
    "aml": "data/contracts/aml-cases.connector.json",
    "sanctions": "data/contracts/sanctions-api.connector.json",
    "kyc-documents": "data/contracts/kyc-documents.connector.json",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65_536):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with '/'")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        else:
            current = current[token]
    return current


def composite_digest(assets: list[dict[str, Any]]) -> str:
    if len(assets) == 1:
        return assets[0]["sha256"]
    digest = hashlib.sha256()
    for asset in sorted(assets, key=lambda item: item["path"]):
        digest.update(asset["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(asset["sha256"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def safe_repository_path(root: Path, relative: Any) -> tuple[Path | None, str | None]:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None, "must be a non-empty repository-relative path"
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, "escapes repository root"
    return candidate, None


def check_common_provenance(
    value: dict[str, Any], label: str, errors: list[str], *, require_source_hash: bool
) -> None:
    required = ["snapshotId", "sourceLocator", "observedAt", "extractorVersion"]
    if require_source_hash:
        required.append("sourceContentSha256")
    for key in required:
        if key not in value:
            errors.append(f"{label}: missing {key}")
    observed_at = value.get("observedAt")
    if not isinstance(observed_at, str) or not UTC_TIMESTAMP.fullmatch(observed_at):
        errors.append(f"{label}: observedAt must be a second-precision UTC timestamp")
    version = value.get("extractorVersion")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.append(f"{label}: extractorVersion must be semantic version text")
    locator = value.get("sourceLocator")
    if not isinstance(locator, str) or not locator or ".." in locator.split("/"):
        errors.append(f"{label}: sourceLocator must be stable and repository-relative")
    if require_source_hash and not SHA256.fullmatch(str(value.get("sourceContentSha256", ""))):
        errors.append(f"{label}: sourceContentSha256 must be a lowercase SHA-256")


def validate_bundle(bundle_dir: Path, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    label = bundle_dir.name
    required_files = {
        "snapshot": bundle_dir / "snapshot.json",
        "profile": bundle_dir / "profile.json",
        "evidence": bundle_dir / "evidence-index.json",
        "report": bundle_dir / "contract-test-report.json",
    }
    for name, path in required_files.items():
        if not path.is_file():
            errors.append(f"{label}: missing {name} at {path.relative_to(root)}")
    if errors:
        return errors

    try:
        snapshot = read_json(required_files["snapshot"])
        profile = read_json(required_files["profile"])
        evidence_index = read_json(required_files["evidence"])
        report = read_json(required_files["report"])
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{label}: invalid JSON: {exc}"]

    check_common_provenance(snapshot, f"{label}/snapshot", errors, require_source_hash=False)
    check_common_provenance(profile, f"{label}/profile", errors, require_source_hash=True)
    check_common_provenance(evidence_index, f"{label}/evidence-index", errors, require_source_hash=True)
    check_common_provenance(report, f"{label}/contract-test-report", errors, require_source_hash=False)

    source_id = snapshot.get("sourceId")
    snapshot_id = snapshot.get("snapshotId")
    observed_at = snapshot.get("observedAt")
    extractor_version = snapshot.get("extractorVersion")
    content = snapshot.get("content")
    if not isinstance(content, dict):
        errors.append(f"{label}/snapshot: content must be an object")
        return errors
    assets = content.get("sourceAssets")
    if not isinstance(assets, list) or not assets:
        errors.append(f"{label}/snapshot: sourceAssets must be a non-empty array")
        return errors

    observed_total_bytes = 0
    for index, item in enumerate(assets):
        item_label = f"{label}/snapshot: sourceAssets[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        source_path, path_error = safe_repository_path(root, item.get("path"))
        if path_error:
            errors.append(f"{item_label}.path {path_error}")
            continue
        assert source_path is not None
        if not source_path.is_file():
            errors.append(f"{item_label}: source asset does not exist")
            continue
        actual_size = source_path.stat().st_size
        actual_hash = sha256_file(source_path)
        observed_total_bytes += actual_size
        if item.get("byteCount") != actual_size:
            errors.append(f"{item_label}: byteCount does not match source")
        if item.get("sha256") != actual_hash:
            errors.append(f"{item_label}: sha256 does not match source")

    expected_digest = composite_digest(assets)
    if content.get("sha256") != expected_digest:
        errors.append(f"{label}/snapshot: content.sha256 is not the content-addressed asset digest")
    if content.get("byteCount") != observed_total_bytes:
        errors.append(f"{label}/snapshot: content.byteCount is not the source asset total")
    if snapshot_id != f"{source_id}@sha256:{expected_digest}":
        errors.append(f"{label}/snapshot: snapshotId does not pin sourceId and content digest")

    common_documents = {
        "profile": profile,
        "evidence-index": evidence_index,
        "contract-test-report": report,
    }
    for name, document in common_documents.items():
        if document.get("snapshotId") != snapshot_id:
            errors.append(f"{label}/{name}: snapshotId differs from snapshot")
        if document.get("observedAt") != observed_at:
            errors.append(f"{label}/{name}: observedAt differs from snapshot")
        if document.get("extractorVersion") != extractor_version:
            errors.append(f"{label}/{name}: extractorVersion differs from snapshot")
    for name, document in {"profile": profile, "evidence-index": evidence_index}.items():
        if document.get("sourceContentSha256") != expected_digest:
            errors.append(f"{label}/{name}: sourceContentSha256 differs from snapshot")
    if report.get("contentSha256") != expected_digest:
        errors.append(f"{label}/contract-test-report: contentSha256 differs from snapshot")

    bounds = profile.get("bounds")
    if not isinstance(bounds, dict):
        errors.append(f"{label}/profile: bounds must be an object")
    else:
        if bounds.get("observedBytes") != observed_total_bytes:
            errors.append(f"{label}/profile: observedBytes differs from source asset total")
        if not isinstance(bounds.get("maximumBytes"), int) or bounds.get("observedBytes", 0) > bounds.get(
            "maximumBytes", -1
        ):
            errors.append(f"{label}/profile: byte bound exceeded or malformed")
        if not isinstance(bounds.get("maximumRecords"), int) or bounds.get("observedRecords", 0) > bounds.get(
            "maximumRecords", -1
        ):
            errors.append(f"{label}/profile: record bound exceeded or malformed")

    fields = profile.get("fields")
    if not isinstance(fields, dict) or not fields:
        errors.append(f"{label}/profile: fields must be a non-empty object")
        fields = {}
    evidence = evidence_index.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{label}/evidence-index: evidence must be a non-empty array")
        evidence = []
    evidence_ids: set[str] = set()
    profiled_fields: set[str] = set()
    has_profile_summary = False
    has_relationship_profile = False
    for index, item in enumerate(evidence):
        item_label = f"{label}/evidence-index: evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        required = (
            "evidenceId",
            "tenantId",
            "sourceId",
            "snapshotId",
            "locator",
            "normalizedCoordinates",
            "observedAt",
            "extractorName",
            "extractorVersion",
            "contentSha256",
            "classification",
            "policyTags",
            "claim",
        )
        missing = [key for key in required if key not in item]
        if missing:
            errors.append(f"{item_label}: missing {', '.join(missing)}")
        evidence_id = item.get("evidenceId")
        if not isinstance(evidence_id, str) or not evidence_id:
            errors.append(f"{item_label}: evidenceId must be non-empty")
        elif evidence_id in evidence_ids:
            errors.append(f"{item_label}: duplicate evidenceId")
        else:
            evidence_ids.add(evidence_id)
        if item.get("sourceId") != source_id or item.get("snapshotId") != snapshot_id:
            errors.append(f"{item_label}: sourceId or snapshotId differs from snapshot")
        if item.get("observedAt") != observed_at or item.get("extractorVersion") != extractor_version:
            errors.append(f"{item_label}: observation or extractor version differs from snapshot")
        if not SHA256.fullmatch(str(item.get("contentSha256", ""))):
            errors.append(f"{item_label}: contentSha256 must be a lowercase SHA-256")
        locator = item.get("locator")
        if not isinstance(locator, str) or not locator or ".." in locator.split("/"):
            errors.append(f"{item_label}: locator must be stable and repository-relative")
        coordinates = item.get("normalizedCoordinates")
        if isinstance(coordinates, dict) and isinstance(coordinates.get("profilePointer"), str):
            if coordinates.get("hashScope") == "artifact":
                artifact_path, path_error = safe_repository_path(root, coordinates.get("profileArtifact"))
                if path_error:
                    errors.append(f"{item_label}: profileArtifact {path_error}")
                elif artifact_path is None or not artifact_path.is_file():
                    errors.append(f"{item_label}: profileArtifact does not exist")
                elif item.get("contentSha256") != sha256_file(artifact_path):
                    errors.append(f"{item_label}: contentSha256 differs from profileArtifact")
            else:
                try:
                    profiled_value = resolve_json_pointer(profile, coordinates["profilePointer"])
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    errors.append(f"{item_label}: invalid profilePointer: {exc}")
                else:
                    if item.get("contentSha256") != canonical_hash(profiled_value):
                        errors.append(f"{item_label}: contentSha256 differs from profilePointer content")
        if isinstance(coordinates, dict) and coordinates.get("profilePointer") == "/statistics":
            has_profile_summary = True
        if isinstance(coordinates, dict) and coordinates.get("profilePointer") == "/relationshipEvidence":
            has_relationship_profile = True
        if isinstance(coordinates, dict) and isinstance(coordinates.get("field"), str):
            if "profilePointer" in coordinates:
                profiled_fields.add(coordinates["field"])
    missing_field_evidence = set(fields) - profiled_fields
    if missing_field_evidence:
        errors.append(f"{label}/evidence-index: no profile evidence for fields {sorted(missing_field_evidence)}")
    if not has_profile_summary:
        errors.append(f"{label}/evidence-index: profile summary statistics have no evidence record")
    if profile.get("relationshipEvidence") and not has_relationship_profile:
        errors.append(f"{label}/evidence-index: relationship statistics have no evidence record")

    if report.get("status") != "PASSED":
        errors.append(f"{label}/contract-test-report: status must be PASSED")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks or not all(check.get("passed") is True for check in checks):
        errors.append(f"{label}/contract-test-report: every declared check must pass")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append(f"{label}/contract-test-report: artifacts must be a non-empty array")
    else:
        for index, item in enumerate(artifacts):
            item_label = f"{label}/contract-test-report: artifacts[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{item_label} must be an object")
                continue
            artifact_path, path_error = safe_repository_path(root, item.get("path"))
            if path_error:
                errors.append(f"{item_label}.path {path_error}")
                continue
            assert artifact_path is not None
            if not artifact_path.is_file():
                errors.append(f"{item_label}: artifact does not exist")
            elif item.get("sha256") != sha256_file(artifact_path):
                errors.append(f"{item_label}: sha256 does not match artifact")

    manifest_relative = MANIFESTS.get(label)
    if manifest_relative is None:
        errors.append(f"{label}: no manifest routing is registered")
    else:
        manifest_path = root / manifest_relative
        try:
            manifest_value = read_json(manifest_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{label}/manifest: invalid JSON: {exc}")
        else:
            for manifest_error in validate_manifest(manifest_value):
                errors.append(f"{label}/manifest: {manifest_error}")
            if manifest_value.get("connector_id") != source_id:
                errors.append(f"{label}/manifest: connector_id differs from snapshot sourceId")
            if manifest_value.get("access_mode") != "read_only":
                errors.append(f"{label}/manifest: access_mode must be read_only")
    return errors


def self_test() -> int:
    assert SHA256.fullmatch("a" * 64)
    assert not SHA256.fullmatch("A" * 64)
    _, traversal_error = safe_repository_path(ROOT, "../outside")
    assert traversal_error == "escapes repository root"
    all_errors: list[str] = []
    for bundle in BUNDLES:
        all_errors.extend(validate_bundle(ROOT / "profiles" / bundle))
    if all_errors:
        print(json.dumps({"valid": False, "errors": all_errors}, indent=2))
        return 1
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", nargs="*", type=Path, help="Profile bundle directories; defaults to all synthetic bundles.")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    bundles = args.bundles or [ROOT / "profiles" / name for name in BUNDLES]
    errors: list[str] = []
    for bundle in bundles:
        path = bundle if bundle.is_absolute() else ROOT / bundle
        errors.extend(validate_bundle(path))
    print(json.dumps({"valid": not errors, "bundleCount": len(bundles), "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
