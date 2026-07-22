#!/usr/bin/env python3
"""Materialize a deterministic publication-review ledger from Firestore receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from check_semantic_publication import (
    AUTHORIZED_HUMAN_ROLES,
    PUBLISHABLE_MAPPING_STATES,
    REVIEW_EXPORT_NORMALIZATION,
    REVIEW_EXPORT_TRUST_BOUNDARY,
    SHA256,
    UTC_SECOND,
    _canonical_sha256,
    _mapping_record,
    _mapping_states,
    _safe_path,
    _sha256,
)


ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCHEMA = "urn:ontology-appliance:schema:firestore-review-receipts-export:1"
LEDGER_SCHEMA = "urn:ontology-appliance:schema:publication-review:1"
EVIDENCE_INDEX_SCHEMA = "urn:ontology-appliance:schema:evidence-index:1"
DECISION_STATUSES = {
    "APPROVED": "APPROVED",
    "REVIEW_REQUIRED": "HUMAN_REVIEW",
    "ABSTAINED": "ABSTAINED",
    "REJECTED": "REJECTED",
}


class ExportError(ValueError):
    """Raised when exported review evidence cannot be trusted."""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExportError(f"{label} must be a JSON object")
    return value


def _first_value(document: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in document:
            return document[key]
    return None


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExportError(f"{label} must be a non-empty string")
    return value


def _required_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ExportError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _artifact(
    manifest: dict[str, Any], root: Path, role: str, proposal_id: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    records = manifest.get("supportingArtifacts")
    if not isinstance(records, list):
        raise ExportError("manifest supportingArtifacts must be an array")
    matches = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("role") == role
        and record.get("proposalId") == proposal_id
    ]
    if len(matches) != 1:
        raise ExportError(
            f"{proposal_id}: manifest must contain exactly one {role} artifact"
        )
    record = matches[0]
    errors: list[str] = []
    path = _safe_path(root, record.get("path"), f"{proposal_id} {role} path", errors)
    if errors or path is None:
        raise ExportError("; ".join(errors))
    digest = _required_digest(record.get("sha256"), f"{proposal_id} {role} sha256")
    if not path.is_file():
        raise ExportError(f"{proposal_id}: {role} artifact is missing: {path}")
    actual = _sha256(path)
    if actual != digest:
        raise ExportError(
            f"{proposal_id}: {role} artifact hash mismatch: expected {digest}, got {actual}"
        )
    document = _load_object(path, f"{proposal_id} {role} artifact")
    return record, document, digest


def _model_subject(
    record: Any, subject_kind: str, label: str, proposal_id: str
) -> str:
    if not isinstance(record, dict):
        raise ExportError(f"{proposal_id}: {label} identity is missing")
    provider = _required_text(record.get("provider"), f"{proposal_id} {label}.provider")
    model = _required_text(record.get("model"), f"{proposal_id} {label}.model")
    return f"{subject_kind}:{provider}/{model}"


def _reviewer_role(receipt: dict[str, Any], proposal_id: str) -> str:
    roles = receipt.get("reviewerRoles")
    if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
        raise ExportError(f"{proposal_id}: reviewerRoles must be a string array")
    authorized = sorted(set(roles) & AUTHORIZED_HUMAN_ROLES)
    if len(authorized) != 1:
        raise ExportError(
            f"{proposal_id}: receipt must contain exactly one authorized reviewer role"
        )
    return authorized[0]


def _decision(
    receipt: dict[str, Any],
    manifest: dict[str, Any],
    root: Path,
    mappings: dict[str, str],
) -> dict[str, Any]:
    proposal_id = _required_text(receipt.get("proposalId"), "receipt proposalId")
    if proposal_id not in mappings:
        raise ExportError(f"receipt references unknown mapping {proposal_id}")
    tenant_id = manifest.get("tenantId")
    if receipt.get("tenantId") != tenant_id:
        raise ExportError(f"{proposal_id}: receipt identifies another tenant")

    _proposal_record, proposal, proposal_sha = _artifact(
        manifest, root, "proposal", proposal_id
    )
    _verification_record, verification, verification_sha = _artifact(
        manifest, root, "verification", proposal_id
    )
    _evidence_record, evidence_index, evidence_sha = _artifact(
        manifest, root, "evidence-index", proposal_id
    )

    for label, document in (
        ("proposal", proposal),
        ("verification", verification),
        ("evidence-index", evidence_index),
    ):
        if _first_value(document, "proposal_id", "proposalId") != proposal_id:
            raise ExportError(f"{proposal_id}: {label} artifact identifies another proposal")
        if _first_value(document, "tenant_id", "tenantId") != tenant_id:
            raise ExportError(f"{proposal_id}: {label} artifact identifies another tenant")
    if evidence_index.get("$schema") != EVIDENCE_INDEX_SCHEMA:
        raise ExportError(f"{proposal_id}: unsupported evidence-index schema")
    frozen_evidence_sha = _required_digest(
        evidence_index.get("sourceEvidenceIndexSha256", evidence_sha),
        f"{proposal_id} evidence-index frozen source sha256",
    )

    for field in ("evidence", "counterevidence"):
        if evidence_index.get(field) != proposal.get(field):
            raise ExportError(
                f"{proposal_id}: evidence-index {field} differs from the proposal"
            )
        if evidence_index.get(field) != verification.get(field):
            raise ExportError(
                f"{proposal_id}: evidence-index {field} differs from verification"
            )

    if _required_digest(
        receipt.get("frozenProposalSha256"),
        f"{proposal_id} frozenProposalSha256",
    ) != proposal_sha:
        raise ExportError(f"{proposal_id}: receipt does not freeze the proposal artifact")
    if _required_digest(
        receipt.get("frozenEvidenceIndexSha256"),
        f"{proposal_id} frozenEvidenceIndexSha256",
    ) != frozen_evidence_sha:
        raise ExportError(
            f"{proposal_id}: receipt does not freeze the source represented by the "
            "evidence index"
        )
    if verification.get("frozen_proposal_sha256") != proposal_sha:
        raise ExportError(f"{proposal_id}: verification does not freeze the proposal")
    if verification.get("frozen_evidence_index_sha256") != frozen_evidence_sha:
        raise ExportError(
            f"{proposal_id}: verification does not freeze the source represented by "
            "the evidence index"
        )

    verification_run_id = _required_text(
        receipt.get("verificationRunId"), f"{proposal_id} verificationRunId"
    )
    if verification.get("verification_run_id") != verification_run_id:
        raise ExportError(f"{proposal_id}: receipt identifies another verification run")
    recorded_run_sha = _required_digest(
        receipt.get("verificationRunSha256"),
        f"{proposal_id} verificationRunSha256",
    )
    artifact_run_sha = _required_digest(
        verification.get("verification_run_sha256"),
        f"{proposal_id} verification artifact verification_run_sha256",
    )
    canonical_run_sha = _canonical_sha256(
        {
            key: value
            for key, value in verification.items()
            if key != "verification_run_sha256"
        }
    )
    if artifact_run_sha != canonical_run_sha:
        raise ExportError(
            f"{proposal_id}: verification_run_sha256 does not match canonical run content"
        )
    if recorded_run_sha != artifact_run_sha:
        raise ExportError(
            f"{proposal_id}: receipt verification hash does not match the linked run"
        )

    policy_version = _required_text(
        receipt.get("policyVersion"), f"{proposal_id} policyVersion"
    )
    if verification.get("policy_version") != policy_version:
        raise ExportError(f"{proposal_id}: receipt identifies another verifier policy")
    ontology_version = _required_text(
        receipt.get("activeOntologyVersion"),
        f"{proposal_id} activeOntologyVersion",
    )
    if (
        verification.get("active_ontology_version") != ontology_version
        or ontology_version != manifest.get("ontologyVersion")
    ):
        raise ExportError(f"{proposal_id}: receipt identifies another ontology version")

    status = _required_text(
        receipt.get("resultingStatus"), f"{proposal_id} resultingStatus"
    ).upper()
    review_decision = _required_text(
        receipt.get("decision"), f"{proposal_id} decision"
    ).upper()
    if DECISION_STATUSES.get(review_decision) != status:
        raise ExportError(
            f"{proposal_id}: decision {review_decision} cannot produce status {status}"
        )
    if status != mappings[proposal_id]:
        raise ExportError(
            f"{proposal_id}: receipt status {status} does not match mappings.ttl "
            f"status {mappings[proposal_id]}"
        )
    reviewed_at = _required_text(receipt.get("createdAt"), f"{proposal_id} createdAt")
    if not UTC_SECOND.fullmatch(reviewed_at):
        raise ExportError(f"{proposal_id}: createdAt must use UTC second precision")
    receipt_id = _required_text(receipt.get("receiptId"), f"{proposal_id} receiptId")
    reviewer_uid = _required_text(
        receipt.get("reviewerUid"), f"{proposal_id} reviewerUid"
    )
    reviewer_role = _reviewer_role(receipt, proposal_id)

    generator = proposal.get("generator")
    generator_subject = _model_subject(
        generator,
        "model" if isinstance(generator, dict) and generator.get("model_participated") else "service",
        "generator",
        proposal_id,
    )
    models = verification.get("models")
    verifier = models.get("verifier") if isinstance(models, dict) else None
    verifier_subject = _model_subject(verifier, "model", "verifier", proposal_id)
    gate_result = verification.get("gate_result")
    reason_codes = gate_result.get("reason_codes", []) if isinstance(gate_result, dict) else []
    if not isinstance(reason_codes, list) or any(
        not isinstance(reason, str) or not reason for reason in reason_codes
    ):
        raise ExportError(f"{proposal_id}: verification reason codes are invalid")

    rationale_sha = receipt.get("rationaleSha256")
    if rationale_sha is not None:
        _required_digest(rationale_sha, f"{proposal_id} rationaleSha256")
    decision = {
        "mappingId": proposal_id,
        "status": status,
        "decisionId": receipt_id,
        "verificationRunId": verification_run_id,
        "verificationRunSha256": artifact_run_sha,
        "generatorSubject": generator_subject,
        "verifierSubject": verifier_subject,
        "reviewer": {
            "subject": f"firebase:{reviewer_uid}",
            "kind": "HUMAN",
            "role": reviewer_role,
            "reviewedAt": reviewed_at,
        },
        "reasonCodes": reason_codes,
        "reviewEvidence": {
            "proposalSha256": proposal_sha,
            "verificationSha256": verification_sha,
            "evidenceIndexSha256": evidence_sha,
        },
        "sourceReceiptSha256": _canonical_sha256(receipt),
    }
    if rationale_sha is not None:
        decision["rationaleSha256"] = rationale_sha
    return decision


def build_ledger(
    manifest: dict[str, Any], manifest_path: Path, exported: dict[str, Any]
) -> dict[str, Any]:
    if exported.get("$schema") != EXPORT_SCHEMA:
        raise ExportError("review receipt export uses an unsupported schema")
    tenant_id = _required_text(exported.get("tenantId"), "export tenantId")
    if tenant_id != manifest.get("tenantId"):
        raise ExportError("review receipt export identifies another tenant")
    expected_collection = f"tenants/{tenant_id}/reviewReceipts"
    if exported.get("collectionPath") != expected_collection:
        raise ExportError(
            f"collectionPath must be the tenant-bound path {expected_collection}"
        )
    exported_at = _required_text(exported.get("exportedAt"), "exportedAt")
    if not UTC_SECOND.fullmatch(exported_at):
        raise ExportError("exportedAt must use UTC second precision")

    errors: list[str] = []
    mapping_record = _mapping_record(manifest)
    if mapping_record is None:
        raise ExportError("manifest must contain exactly one mappings.ttl artifact")
    mappings_path = _safe_path(
        manifest_path.parent,
        mapping_record.get("path"),
        "mappings path",
        errors,
    )
    if errors or mappings_path is None:
        raise ExportError("; ".join(errors))
    expected_mapping_sha = _required_digest(
        mapping_record.get("sha256"), "mappings sha256"
    )
    if _sha256(mappings_path) != expected_mapping_sha:
        raise ExportError("mappings.ttl hash does not match the manifest")
    mapping_errors: list[str] = []
    mappings = _mapping_states(mappings_path, mapping_errors)
    if mapping_errors:
        raise ExportError("; ".join(mapping_errors))

    receipts = exported.get("receipts")
    if not isinstance(receipts, list):
        raise ExportError("receipts must be an array")
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, dict):
            raise ExportError(f"receipts[{index}] must be an object")
        decision = _decision(receipt, manifest, manifest_path.parent, mappings)
        mapping_id = decision["mappingId"]
        if mapping_id in seen:
            raise ExportError(f"duplicate review receipt for {mapping_id}")
        seen.add(mapping_id)
        decisions.append(decision)
    decisions.sort(key=lambda item: (item["mappingId"], item["decisionId"]))

    counts = Counter(mappings.values())
    full_coverage = set(mappings) == seen
    publication = manifest.get("publication")
    state = publication.get("state") if isinstance(publication, dict) else None
    if state not in {"CANDIDATE", "PUBLISHABLE"}:
        raise ExportError("source manifest must be CANDIDATE or PUBLISHABLE")
    if state == "PUBLISHABLE" and (
        not full_coverage
        or any(status not in PUBLISHABLE_MAPPING_STATES for status in mappings.values())
    ):
        raise ExportError(
            "a PUBLISHABLE manifest requires full receipt coverage and publishable mappings"
        )

    return {
        "$schema": LEDGER_SCHEMA,
        "bundleVersion": manifest.get("version"),
        "tenantId": tenant_id,
        "ontologyVersion": manifest.get("ontologyVersion"),
        "state": state,
        "coverage": "FULL" if full_coverage else "PARTIAL",
        "mappingPopulation": {
            "total": len(mappings),
            "approved": counts["APPROVED"],
            "published": counts["PUBLISHED"],
            "humanReview": counts["HUMAN_REVIEW"],
        },
        "decisions": decisions,
        "exportProvenance": {
            "sourceSchema": EXPORT_SCHEMA,
            "normalizationVersion": REVIEW_EXPORT_NORMALIZATION,
            "sourceExportSha256": _canonical_sha256(exported),
            "digestAlgorithm": "SHA-256",
            "collectionPath": expected_collection,
            "exportedAt": exported_at,
            "trustBoundary": REVIEW_EXPORT_TRUST_BOUNDARY,
        },
        "unresolvedPolicy": (
            "Every mapping without an independent review decision remains ineligible "
            "for publication."
        ),
    }


def _ledger_bytes(ledger: dict[str, Any]) -> bytes:
    return (json.dumps(ledger, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def export_ledger(manifest_path: Path, receipts_path: Path, output_path: Path) -> str:
    manifest_path = manifest_path.resolve()
    receipts_path = receipts_path.resolve()
    output_path = output_path.resolve()
    if output_path.exists():
        raise ExportError(f"output already exists: {output_path}")
    manifest = _load_object(manifest_path, "manifest")
    exported = _load_object(receipts_path, "review receipt export")
    ledger = build_ledger(manifest, manifest_path, exported)
    payload = _ledger_bytes(ledger)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("xb") as handle:
            handle.write(payload)
    except OSError as exc:
        raise ExportError(f"cannot create output: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="oa-review-export-self-test-") as temporary:
        root = Path(temporary)
        mappings_path = root / "mappings.ttl"
        mappings_path.write_text(
            "@prefix oa: <urn:ontology-appliance:vocab:> .\n"
            "@prefix ex: <urn:test:> .\n"
            'ex:m1 a oa:MappingProposal ; oa:mappingId "m1" ; '
            'oa:proposalStatus "APPROVED" .\n',
            encoding="utf-8",
        )
        proposal_path = root / "proposal.json"
        proposal = {
            "proposal_id": "m1",
            "tenant_id": "demo-bank",
            "evidence": [],
            "counterevidence": [],
            "generator": {
                "provider": "ontology-appliance",
                "model": "rules-v1",
                "model_participated": False,
            },
        }
        _write_json(proposal_path, proposal)
        evidence_path = root / "evidence-index.json"
        _write_json(
            evidence_path,
            {
                "$schema": EVIDENCE_INDEX_SCHEMA,
                "proposalId": "m1",
                "tenantId": "demo-bank",
                "sourceEvidenceIndexSha256": "e" * 64,
                "evidence": [],
                "counterevidence": [],
            },
        )
        verification_path = root / "verification.json"
        verification = {
            "verification_run_id": "run-m1",
            "proposal_id": "m1",
            "tenant_id": "demo-bank",
            "policy_version": "policy-v1",
            "active_ontology_version": "fixture",
            "frozen_proposal_sha256": _sha256(proposal_path),
            "frozen_evidence_index_sha256": "e" * 64,
            "evidence": [],
            "counterevidence": [],
            "models": {
                "verifier": {"provider": "independent", "model": "verifier-v1"}
            },
            "gate_result": {"reason_codes": ["STEWARD_APPROVED"]},
        }
        verification["verification_run_sha256"] = _canonical_sha256(verification)
        _write_json(verification_path, verification)
        manifest_path = root / "manifest.json"
        manifest = {
            "version": "fixture-1",
            "tenantId": "demo-bank",
            "ontologyVersion": "fixture",
            "publication": {"state": "PUBLISHABLE"},
            "artifacts": [
                {
                    "path": "mappings.ttl",
                    "sha256": _sha256(mappings_path),
                    "format": "turtle",
                    "kind": "graph",
                }
            ],
            "supportingArtifacts": [
                {
                    "role": "proposal",
                    "proposalId": "m1",
                    "path": "proposal.json",
                    "sha256": _sha256(proposal_path),
                },
                {
                    "role": "verification",
                    "proposalId": "m1",
                    "path": "verification.json",
                    "sha256": _sha256(verification_path),
                },
                {
                    "role": "evidence-index",
                    "proposalId": "m1",
                    "path": "evidence-index.json",
                    "sha256": _sha256(evidence_path),
                },
            ],
        }
        _write_json(manifest_path, manifest)
        exported = {
            "$schema": EXPORT_SCHEMA,
            "tenantId": "demo-bank",
            "collectionPath": "tenants/demo-bank/reviewReceipts",
            "exportedAt": "2026-07-22T15:00:00Z",
            "receipts": [
                {
                    "receiptId": "review-m1",
                    "proposalId": "m1",
                    "tenantId": "demo-bank",
                    "reviewerUid": "steward-1",
                    "reviewerRoles": ["steward"],
                    "decision": "APPROVED",
                    "resultingStatus": "APPROVED",
                    "rationaleSha256": "a" * 64,
                    "verificationRunId": "run-m1",
                    "verificationRunSha256": verification[
                        "verification_run_sha256"
                    ],
                    "frozenProposalSha256": _sha256(proposal_path),
                    "frozenEvidenceIndexSha256": "e" * 64,
                    "policyVersion": "policy-v1",
                    "activeOntologyVersion": "fixture",
                    "createdAt": "2026-07-22T14:59:00Z",
                }
            ],
        }
        first = build_ledger(manifest, manifest_path, exported)
        second = build_ledger(manifest, manifest_path, json.loads(json.dumps(exported)))
        assert _ledger_bytes(first) == _ledger_bytes(second)
        decision = first["decisions"][0]
        assert decision["reviewEvidence"]["proposalSha256"] == _sha256(proposal_path)
        assert decision["reviewEvidence"]["verificationSha256"] == _sha256(
            verification_path
        )
        assert decision["reviewEvidence"]["evidenceIndexSha256"] == _sha256(
            evidence_path
        )
        assert decision["verificationRunSha256"] == verification[
            "verification_run_sha256"
        ]
        assert SHA256.fullmatch(decision["sourceReceiptSha256"])
        assert first["exportProvenance"] == {
            "sourceSchema": EXPORT_SCHEMA,
            "normalizationVersion": REVIEW_EXPORT_NORMALIZATION,
            "sourceExportSha256": _canonical_sha256(exported),
            "digestAlgorithm": "SHA-256",
            "collectionPath": "tenants/demo-bank/reviewReceipts",
            "exportedAt": "2026-07-22T15:00:00Z",
            "trustBoundary": REVIEW_EXPORT_TRUST_BOUNDARY,
        }

        tampered = json.loads(json.dumps(exported))
        tampered["receipts"][0]["frozenProposalSha256"] = "b" * 64
        try:
            build_ledger(manifest, manifest_path, tampered)
        except ExportError as exc:
            assert "does not freeze the proposal" in str(exc)
        else:
            raise AssertionError("tampered proposal hash was accepted")

        tampered_run = json.loads(json.dumps(verification))
        tampered_run["risk"] = "high"
        _write_json(verification_path, tampered_run)
        manifest["supportingArtifacts"][1]["sha256"] = _sha256(verification_path)
        try:
            build_ledger(manifest, manifest_path, exported)
        except ExportError as exc:
            assert "does not match canonical run content" in str(exc)
        else:
            raise AssertionError("tampered verification run was accepted")
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "semantic/artifacts/manifest.json",
    )
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.receipts is None or args.output is None:
        parser.error("--receipts and --output are required unless --self-test is used")
    try:
        digest = export_ledger(args.manifest, args.receipts, args.output)
    except (ExportError, OSError) as exc:
        print(json.dumps({"exported": False, "error": str(exc)}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "exported": True,
                "path": str(args.output.resolve()),
                "sha256": digest,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
