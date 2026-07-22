#!/usr/bin/env python3
"""Build a generation-guarded, evidence-backed semantic rollback pointer."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from check_semantic_publication import (
    UTC_SECOND,
    _sha256,
    _write_fixture,
    create_active_pointer,
    promote,
    validate,
)


SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_TICKET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _validate_pointer(pointer: dict[str, Any], label: str) -> None:
    if pointer.get("$schema") != "urn:ontology-appliance:schema:active-pointer:1":
        raise ValueError(f"{label} uses an unsupported schema")
    for field in (
        "tenantId",
        "bundleVersion",
        "ontologyVersion",
        "manifestObject",
        "publisherSubject",
        "authorizedAt",
        "activatedAt",
        "releaseSha",
        "releaseId",
    ):
        if not isinstance(pointer.get(field), str) or not pointer[field].strip():
            raise ValueError(f"{label}.{field} is required")
    for field in ("manifestSha256", "publicationReceiptSha256"):
        if not isinstance(pointer.get(field), str) or not SHA256.fullmatch(
            pointer[field]
        ):
            raise ValueError(f"{label}.{field} must be a SHA-256 digest")
    for field in ("authorizedAt", "activatedAt"):
        if not UTC_SECOND.fullmatch(pointer[field]):
            raise ValueError(f"{label}.{field} must be a UTC timestamp")
    if pointer["authorizedAt"] > pointer["activatedAt"]:
        raise ValueError(f"{label} authorization cannot follow activation")
    if pointer.get("operation") not in {"PUBLISH", "ROLLBACK"}:
        raise ValueError(f"{label}.operation must be PUBLISH or ROLLBACK")
    expected_prefix = f"tenants/{pointer['tenantId']}/ontology/releases/"
    manifest_object = pointer["manifestObject"]
    if (
        not manifest_object.startswith(expected_prefix)
        or not manifest_object.endswith("/manifest.json")
        or any(part in {"", ".", ".."} for part in manifest_object.split("/"))
    ):
        raise ValueError(f"{label}.manifestObject is not a safe immutable release path")


def build_rollback(
    *,
    current_pointer_path: Path,
    prior_pointer_path: Path,
    target_manifest_path: Path,
    target_manifest_object: str,
    expected_generation: str,
    observed_generation: str,
    publisher_subject: str,
    authorized_at: str,
    activated_at: str,
    reason: str,
    ticket: str,
    workflow_run: str,
    prior_pointer_generation: str,
    audit_object: str,
    audit_output: Path,
    pointer_output: Path,
) -> tuple[Path, Path]:
    if not expected_generation.isdigit() or not observed_generation.isdigit():
        raise ValueError("pointer generations must be unsigned decimal integers")
    if expected_generation != observed_generation:
        raise ValueError(
            "generation precondition failed before rollback build: "
            f"expected {expected_generation}, observed {observed_generation}"
        )
    if not prior_pointer_generation.isdigit():
        raise ValueError("prior pointer generation must be an unsigned decimal integer")
    if int(prior_pointer_generation) >= int(observed_generation):
        raise ValueError("prior pointer generation must precede the current generation")
    if not UTC_SECOND.fullmatch(authorized_at) or not UTC_SECOND.fullmatch(
        activated_at
    ):
        raise ValueError(
            "authorization and activation times must use UTC second precision"
        )
    if authorized_at > activated_at:
        raise ValueError("authorized-at cannot be later than activated-at")
    normalized_reason = " ".join(reason.split())
    if len(normalized_reason) < 10 or len(normalized_reason) > 500:
        raise ValueError(
            "rollback reason must contain 10-500 non-whitespace characters"
        )
    if not SAFE_TICKET.fullmatch(ticket):
        raise ValueError("rollback ticket must be a safe 3-128 character identifier")
    if (
        not workflow_run.startswith("https://github.com/")
        or "/actions/runs/" not in workflow_run
    ):
        raise ValueError("workflow-run must be an HTTPS GitHub Actions run URL")

    current = _load(current_pointer_path, "current pointer")
    prior = _load(prior_pointer_path, "prior activation pointer")
    _validate_pointer(current, "current pointer")
    _validate_pointer(prior, "prior activation pointer")

    published_errors, _summary = validate(target_manifest_path, "published")
    if published_errors:
        raise ValueError(
            "rollback target is not a valid published bundle: "
            + "; ".join(published_errors)
        )
    target = _load(target_manifest_path, "target manifest")
    publication = target["publication"]
    expected_target_object = (
        f"tenants/{target['tenantId']}/ontology/releases/"
        f"{target['version']}-{publication['releaseId']}/manifest.json"
    )
    if target_manifest_object != expected_target_object:
        raise ValueError(f"target manifest object must be {expected_target_object}")
    target_manifest_sha = _sha256(target_manifest_path)
    if target_manifest_object == current["manifestObject"]:
        raise ValueError("rollback target is already active")
    if (
        current["tenantId"] != target["tenantId"]
        or prior["tenantId"] != target["tenantId"]
    ):
        raise ValueError("current, prior, and target tenant identities must match")
    if (
        prior["manifestObject"] != target_manifest_object
        or prior["manifestSha256"] != target_manifest_sha
        or prior["publicationReceiptSha256"] != publication["receiptSha256"]
    ):
        raise ValueError(
            "historical pointer does not prove that the rollback target was active"
        )
    if publisher_subject != publication["publisherSubject"]:
        raise ValueError("rollback actor must be the configured Publisher identity")

    expected_audit_prefix = f"tenants/{target['tenantId']}/ontology/rollbacks/"
    if (
        not audit_object.startswith(expected_audit_prefix)
        or not audit_object.endswith("/rollback-audit.json")
        or any(part in {"", ".", ".."} for part in audit_object.split("/"))
    ):
        raise ValueError("audit object must be an immutable tenant rollback audit path")
    if audit_output.exists() or pointer_output.exists():
        raise ValueError("rollback outputs must not already exist")

    audit = {
        "$schema": "urn:ontology-appliance:schema:rollback-audit:1",
        "operation": "ROLLBACK",
        "tenantId": target["tenantId"],
        "publisherSubject": publisher_subject,
        "authorizedAt": authorized_at,
        "activatedAt": activated_at,
        "reason": normalized_reason,
        "ticket": ticket,
        "workflowRun": workflow_run,
        "generationCas": {
            "expected": expected_generation,
            "observed": observed_generation,
        },
        "from": {
            "manifestObject": current["manifestObject"],
            "manifestSha256": current["manifestSha256"],
            "bundleVersion": current["bundleVersion"],
            "ontologyVersion": current["ontologyVersion"],
            "pointerGeneration": observed_generation,
        },
        "to": {
            "manifestObject": target_manifest_object,
            "manifestSha256": target_manifest_sha,
            "bundleVersion": target["version"],
            "ontologyVersion": target["ontologyVersion"],
            "publicationReceiptSha256": publication["receiptSha256"],
        },
        "priorActivationEvidence": {
            "pointerGeneration": prior_pointer_generation,
            "pointerSha256": _sha256(prior_pointer_path),
        },
    }
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    audit_output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    audit_sha = _sha256(audit_output)

    pointer = {
        "$schema": "urn:ontology-appliance:schema:active-pointer:1",
        "operation": "ROLLBACK",
        "tenantId": target["tenantId"],
        "bundleVersion": target["version"],
        "ontologyVersion": target["ontologyVersion"],
        "manifestObject": target_manifest_object,
        "manifestSha256": target_manifest_sha,
        "publicationReceiptSha256": publication["receiptSha256"],
        "publisherSubject": publication["publisherSubject"],
        "authorizedAt": authorized_at,
        "activatedAt": activated_at,
        "releaseSha": publication["releaseSha"],
        "releaseId": publication["releaseId"],
        "replacesGeneration": observed_generation,
        "previousManifestObject": current["manifestObject"],
        "previousManifestSha256": current["manifestSha256"],
        "rollbackAuthorizedBy": publisher_subject,
        "rollbackAuditObject": audit_object,
        "rollbackAuditSha256": audit_sha,
    }
    pointer_output.parent.mkdir(parents=True, exist_ok=True)
    pointer_output.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    return audit_output, pointer_output


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="oa-rollback-self-test-") as temporary:
        root = Path(temporary)
        candidate_root = root / "candidate"
        candidate_root.mkdir()
        candidate = _write_fixture(candidate_root, publishable=True)
        release_id = "a" * 40 + "-100-1"
        target_root = root / "published"
        target_object = (
            f"tenants/demo-bank/ontology/releases/fixture-1-{release_id}/manifest.json"
        )
        target = promote(
            candidate,
            target_root,
            "serviceAccount:publisher@example.invalid",
            "a" * 40,
            release_id,
            "2026-07-22T14:00:00Z",
            "2026-07-22T14:01:00Z",
            target_object,
        )
        prior_path = create_active_pointer(
            target,
            root / "prior.json",
            target_object,
            "2026-07-22T14:02:00Z",
        )
        current = json.loads(prior_path.read_text(encoding="utf-8"))
        current.update(
            {
                "bundleVersion": "newer",
                "ontologyVersion": "newer",
                "manifestObject": "tenants/demo-bank/ontology/releases/newer-current/manifest.json",
                "manifestSha256": "b" * 64,
                "releaseId": "current",
            }
        )
        current_path = root / "current.json"
        current_path.write_text(json.dumps(current), encoding="utf-8")
        audit, pointer = build_rollback(
            current_pointer_path=current_path,
            prior_pointer_path=prior_path,
            target_manifest_path=target,
            target_manifest_object=target_object,
            expected_generation="42",
            observed_generation="42",
            publisher_subject="serviceAccount:publisher@example.invalid",
            authorized_at="2026-07-22T15:00:00Z",
            activated_at="2026-07-22T15:01:00Z",
            reason="Regression confirmed in the current semantic release",
            ticket="INC-1234",
            workflow_run="https://github.com/example/repo/actions/runs/123",
            prior_pointer_generation="40",
            audit_object="tenants/demo-bank/ontology/rollbacks/123-1/rollback-audit.json",
            audit_output=root / "rollback-audit.json",
            pointer_output=root / "rollback-active.json",
        )
        built = json.loads(pointer.read_text(encoding="utf-8"))
        assert built["operation"] == "ROLLBACK"
        assert (
            built["rollbackAuditSha256"]
            == hashlib.sha256(audit.read_bytes()).hexdigest()
        )
        try:
            build_rollback(
                current_pointer_path=current_path,
                prior_pointer_path=prior_path,
                target_manifest_path=target,
                target_manifest_object=target_object,
                expected_generation="41",
                observed_generation="42",
                publisher_subject="serviceAccount:publisher@example.invalid",
                authorized_at="2026-07-22T15:00:00Z",
                activated_at="2026-07-22T15:01:00Z",
                reason="Regression confirmed in the current semantic release",
                ticket="INC-1234",
                workflow_run="https://github.com/example/repo/actions/runs/123",
                prior_pointer_generation="40",
                audit_object="tenants/demo-bank/ontology/rollbacks/123-2/rollback-audit.json",
                audit_output=root / "unused-audit.json",
                pointer_output=root / "unused-pointer.json",
            )
        except ValueError as exc:
            assert "generation precondition" in str(exc)
        else:
            raise AssertionError("generation mismatch must fail closed")
    print("rollback self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--current-pointer", type=Path)
    parser.add_argument("--prior-pointer", type=Path)
    parser.add_argument("--target-manifest", type=Path)
    parser.add_argument("--target-manifest-object")
    parser.add_argument("--expected-generation")
    parser.add_argument("--observed-generation")
    parser.add_argument("--publisher-subject")
    parser.add_argument("--authorized-at")
    parser.add_argument("--activated-at")
    parser.add_argument("--reason")
    parser.add_argument("--ticket")
    parser.add_argument("--workflow-run")
    parser.add_argument("--prior-pointer-generation")
    parser.add_argument("--audit-object")
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--pointer-output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = {
        "current-pointer": args.current_pointer,
        "prior-pointer": args.prior_pointer,
        "target-manifest": args.target_manifest,
        "target-manifest-object": args.target_manifest_object,
        "expected-generation": args.expected_generation,
        "observed-generation": args.observed_generation,
        "publisher-subject": args.publisher_subject,
        "authorized-at": args.authorized_at,
        "activated-at": args.activated_at,
        "reason": args.reason,
        "ticket": args.ticket,
        "workflow-run": args.workflow_run,
        "prior-pointer-generation": args.prior_pointer_generation,
        "audit-object": args.audit_object,
        "audit-output": args.audit_output,
        "pointer-output": args.pointer_output,
    }
    missing = [name for name, value in required.items() if value in {None, ""}]
    if missing:
        parser.error("missing required arguments: " + ", ".join(missing))
    try:
        audit, pointer = build_rollback(
            current_pointer_path=args.current_pointer,
            prior_pointer_path=args.prior_pointer,
            target_manifest_path=args.target_manifest,
            target_manifest_object=args.target_manifest_object,
            expected_generation=args.expected_generation,
            observed_generation=args.observed_generation,
            publisher_subject=args.publisher_subject,
            authorized_at=args.authorized_at,
            activated_at=args.activated_at,
            reason=args.reason,
            ticket=args.ticket,
            workflow_run=args.workflow_run,
            prior_pointer_generation=args.prior_pointer_generation,
            audit_object=args.audit_object,
            audit_output=args.audit_output,
            pointer_output=args.pointer_output,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 1
    print(
        json.dumps(
            {"valid": True, "audit": str(audit), "pointer": str(pointer)}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
