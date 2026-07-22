#!/usr/bin/env python3
"""Validate the runtime KYC package manifest and its governed sidecars."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

RUNTIME_ARTIFACTS = {
    "ontology.ttl": ("turtle", "graph"),
    "demo-data.ttl": ("turtle", "graph"),
    "mappings.ttl": ("turtle", "graph"),
    "provenance.nq": ("nquads", "provenance"),
    "shapes.ttl": ("turtle", "shapes"),
}
REQUIRED_SUPPORTING_ROLES = {
    "questions",
    "proposal",
    "verification",
    "publication-review",
}
SUPPORTING_ROLES = REQUIRED_SUPPORTING_ROLES | {"publication-receipt"}
CONFIDENCE_DIMENSIONS = (
    "lexical",
    "structural",
    "instance",
    "external",
    "model",
    "evidence_coverage",
)
EVIDENCE_FIELDS = (
    "evidence_id",
    "tenant_id",
    "source_id",
    "snapshot_id",
    "locator",
    "observed_at",
    "extractor_version",
    "content_sha256",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _safe_relative_path(value: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{label} must be a non-empty relative path")
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        errors.append(f"{label} must be a safe relative path")
        return None
    return path


def _validate_hash(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        errors.append(f"{label} must be a lowercase SHA-256 digest")


def _verify_file(
    base_dir: Path | None,
    path: Path | None,
    digest: Any,
    label: str,
    errors: list[str],
) -> None:
    if base_dir is None or path is None or not isinstance(digest, str) or not SHA256.fullmatch(digest):
        return
    target = (base_dir / path).resolve()
    root = base_dir.resolve()
    if not target.is_relative_to(root):
        errors.append(f"{label}.path escapes the package root")
        return
    try:
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        errors.append(f"{label}.path is unreadable: {exc}")
        return
    if actual != digest:
        errors.append(f"{label}.sha256 mismatch: expected {digest}, got {actual}")


def _load_json(path: Path, label: str, errors: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read {label}: {exc}")
        return None


def _validate_questions(
    data: Any,
    stats: dict[str, Any],
    pilot: bool,
    errors: list[str],
) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        errors.append("competency-questions.json must contain a questions array")
        return
    questions = data["questions"]
    ids: set[str] = set()
    passed = 0
    for index, item in enumerate(questions):
        label = f"questions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        question_id = item.get("id")
        if not isinstance(question_id, str) or not question_id:
            errors.append(f"{label}.id must be a non-empty string")
        elif question_id in ids:
            errors.append(f"duplicate competency question id: {question_id}")
        else:
            ids.add(question_id)
        for field in ("question", "evaluationRef"):
            if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                errors.append(f"{label}.{field} must be a non-empty string")
        if not isinstance(item.get("expectedOutcome"), dict):
            errors.append(f"{label}.expectedOutcome must be an object")
        if item.get("status") not in {"PASS", "FAIL"}:
            errors.append(f"{label}.status must be PASS or FAIL")
        elif item["status"] == "PASS":
            passed += 1
    if stats.get("competencyQuestions") != len(questions):
        errors.append("stats.competencyQuestions does not match competency-questions.json")
    if stats.get("passedCompetencyQuestions") != passed:
        errors.append("stats.passedCompetencyQuestions does not match competency-questions.json")
    if pilot:
        required = {f"CQ-{number:03d}" for number in range(1, 6)}
        missing = required - ids
        if missing:
            errors.append(f"pilot is missing competency questions: {sorted(missing)}")
        if len(questions) < 5:
            errors.append("pilot requires at least five competency questions")
        if passed < 4:
            errors.append("pilot requires at least four passing competency questions")


def _validate_proposal(
    proposal: Any,
    manifest: dict[str, Any],
    manifest_dir: Path | None,
    errors: list[str],
) -> None:
    if not isinstance(proposal, dict):
        errors.append("proposal sidecar must be a JSON object")
        return
    if proposal.get("tenant_id") != manifest.get("tenantId"):
        errors.append("proposal tenant_id does not match manifest tenantId")
    if proposal.get("active_ontology_version") != manifest.get("ontologyVersion"):
        errors.append("proposal active_ontology_version does not match manifest ontologyVersion")
    if proposal.get("risk") not in {"low", "medium", "high"}:
        errors.append("proposal risk must be low, medium, or high")
    confidence = proposal.get("confidence")
    if not isinstance(confidence, dict):
        errors.append("proposal confidence must be an object")
    else:
        for dimension in CONFIDENCE_DIMENSIONS:
            value = confidence.get(dimension)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                errors.append(f"proposal confidence.{dimension} must be between 0 and 1")

    repository_root = manifest_dir.parents[1] if manifest_dir is not None else None
    for collection in ("evidence", "counterevidence"):
        items = proposal.get(collection)
        if not isinstance(items, list) or not items:
            errors.append(f"proposal {collection} must be a non-empty array")
            continue
        for index, item in enumerate(items):
            label = f"proposal {collection}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{label} must be an object")
                continue
            for field in EVIDENCE_FIELDS:
                if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                    errors.append(f"{label}.{field} must be a non-empty string")
            digest = item.get("content_sha256")
            _validate_hash(digest, f"{label}.content_sha256", errors)
            if repository_root is not None and isinstance(item.get("locator"), str):
                locator_path = Path(item["locator"].split("#", 1)[0])
                if locator_path.is_absolute() or ".." in locator_path.parts:
                    errors.append(f"{label}.locator must stay inside the repository")
                    continue
                target = (repository_root / locator_path).resolve()
                if not target.is_relative_to(repository_root.resolve()):
                    errors.append(f"{label}.locator escapes the repository")
                    continue
                try:
                    actual = hashlib.sha256(target.read_bytes()).hexdigest()
                except OSError as exc:
                    errors.append(f"{label}.locator is unreadable: {exc}")
                else:
                    if isinstance(digest, str) and SHA256.fullmatch(digest) and actual != digest:
                        errors.append(f"{label}.content_sha256 does not match {locator_path}")

    deterministic_input = proposal.get("deterministic_input")
    deterministic_hash = proposal.get("deterministic_input_hash")
    if not isinstance(deterministic_input, dict):
        errors.append("proposal deterministic_input must be an object")
    else:
        actual_input_hash = hashlib.sha256(
            json.dumps(deterministic_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if deterministic_hash != actual_input_hash:
            errors.append("proposal deterministic_input_hash does not match deterministic_input")

    generator = proposal.get("generator")
    if not isinstance(generator, dict):
        errors.append("proposal generator must be an object")
    elif generator.get("model_participated") is False and generator.get("provider_returned_model_id") is not None:
        errors.append("deterministic generation cannot claim a provider-returned model ID")
    if proposal.get("status") not in {"PENDING_VERIFICATION", "ABSTAINED"}:
        errors.append("discovery proposal status must be PENDING_VERIFICATION or ABSTAINED")


def _validate_verification(
    verification: Any,
    proposal: Any,
    proposal_path: Path,
    manifest: dict[str, Any],
    manifest_dir: Path,
    errors: list[str],
) -> None:
    if not isinstance(verification, dict):
        errors.append("verification sidecar must be a JSON object")
        return
    if verification.get("tenant_id") != manifest.get("tenantId"):
        errors.append("verification tenant_id does not match manifest tenantId")
    if verification.get("active_ontology_version") != manifest.get("ontologyVersion"):
        errors.append("verification active_ontology_version does not match manifest ontologyVersion")
    if isinstance(proposal, dict):
        if verification.get("proposal_id") != proposal.get("proposal_id"):
            errors.append("verification proposal_id does not match the frozen proposal")
        if verification.get("risk") != proposal.get("risk"):
            errors.append("verification risk does not match the frozen proposal")
        if verification.get("confidence") != proposal.get("confidence"):
            errors.append("verification confidence vector does not match the frozen proposal")
        proposal_evidence = [item.get("evidence_id") for item in proposal.get("evidence", [])]
        verification_evidence = [item.get("evidence_id") for item in verification.get("evidence", [])]
        if verification_evidence != proposal_evidence:
            errors.append("verification evidence set does not match the frozen proposal")
    actual_proposal_hash = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
    if verification.get("frozen_proposal_sha256") != actual_proposal_hash:
        errors.append("verification frozen_proposal_sha256 does not match the proposal bytes")

    repository_root = manifest_dir.parents[1]
    evidence_index = repository_root / "profiles/crm/evidence-index.json"
    try:
        actual_evidence_hash = hashlib.sha256(evidence_index.read_bytes()).hexdigest()
    except OSError as exc:
        errors.append(f"cannot read frozen CRM evidence index: {exc}")
    else:
        if verification.get("frozen_evidence_index_sha256") != actual_evidence_hash:
            errors.append("verification frozen_evidence_index_sha256 does not match the evidence index")

    checks = verification.get("checks")
    if not isinstance(checks, dict):
        errors.append("verification checks must be an object")
    else:
        for name in ("provenance_complete", "schema_valid", "shacl_valid", "sql_valid"):
            if not isinstance(checks.get(name), bool):
                errors.append(f"verification checks.{name} must be boolean")
        total = checks.get("competency_questions_total")
        passed = checks.get("competency_questions_passed")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            errors.append("verification competency_questions_total must be a non-negative integer")
        if not isinstance(passed, int) or isinstance(passed, bool) or passed < 0:
            errors.append("verification competency_questions_passed must be a non-negative integer")
        if isinstance(total, int) and isinstance(passed, int) and passed > total:
            errors.append("verification competency question pass count cannot exceed total")

    models = verification.get("models")
    if not isinstance(models, dict) or models.get("mode") not in {"mock", "live"}:
        errors.append("verification models.mode must be mock or live")
    elif models["mode"] == "mock":
        if models.get("independent_agreement") is not None:
            errors.append("mock verification must keep independent_agreement null")
        if verification.get("status") not in {"HUMAN_REVIEW", "ABSTAINED"}:
            errors.append("mock verification must route to HUMAN_REVIEW or ABSTAINED")
    if verification.get("status") == "PUBLISHED":
        errors.append("a verification sidecar cannot assign PUBLISHED; only Publisher may do so")
    gate_result = verification.get("gate_result")
    if not isinstance(gate_result, dict) or gate_result.get("status") != verification.get("status"):
        errors.append("verification gate_result.status must match status")
    elif not isinstance(gate_result.get("reason_codes"), list) or not gate_result["reason_codes"]:
        errors.append("verification gate_result.reason_codes must be a non-empty array")


def _validate_publication(
    publication: Any,
    manifest: dict[str, Any],
    supporting_by_role: dict[str, Path],
    manifest_dir: Path | None,
    errors: list[str],
) -> None:
    if not isinstance(publication, dict):
        errors.append("publication must be an object")
        return
    state = publication.get("state")
    expected = {
        "CANDIDATE": ("DEMO_ONLY", False),
        "PUBLISHABLE": ("PUBLISHER_ONLY", False),
        "PUBLISHED": ("ACTIVE", True),
    }
    if state not in expected:
        errors.append("publication.state must be CANDIDATE, PUBLISHABLE, or PUBLISHED")
    else:
        serving_mode, is_published = expected[state]
        if publication.get("servingMode") != serving_mode:
            errors.append(
                f"publication.servingMode must be {serving_mode} when state is {state}"
            )
        if publication.get("isPublished") is not is_published:
            errors.append(
                f"publication.isPublished must be {str(is_published).lower()} when state is {state}"
            )

    ledger_path = supporting_by_role.get("publication-review")
    if ledger_path is not None and publication.get("reviewLedgerPath") != str(ledger_path):
        errors.append("publication.reviewLedgerPath must match the publication-review artifact")
    review_records = [
        record
        for record in manifest.get("supportingArtifacts", [])
        if isinstance(record, dict) and record.get("role") == "publication-review"
    ]
    if len(review_records) == 1:
        review_digest = review_records[0].get("sha256")
        if publication.get("reviewLedgerSha256") != review_digest:
            errors.append(
                "publication.reviewLedgerSha256 must match the publication-review artifact"
            )
    else:
        review_digest = None

    if manifest_dir is not None and ledger_path is not None:
        ledger = _load_json(manifest_dir / ledger_path, "publication review", errors)
        if isinstance(ledger, dict):
            if ledger.get("$schema") != "urn:ontology-appliance:schema:publication-review:1":
                errors.append("publication review uses an unsupported schema")
            for ledger_key, manifest_key in (
                ("bundleVersion", "version"),
                ("tenantId", "tenantId"),
                ("ontologyVersion", "ontologyVersion"),
            ):
                if ledger.get(ledger_key) != manifest.get(manifest_key):
                    errors.append(
                        f"publication review {ledger_key} does not match the manifest"
                    )
            expected_ledger_state = (
                "CANDIDATE" if state == "CANDIDATE" else "PUBLISHABLE"
            )
            if ledger.get("state") != expected_ledger_state:
                errors.append(
                    f"publication review state must be {expected_ledger_state}"
                )

    if state == "PUBLISHED":
        receipt_path = supporting_by_role.get("publication-receipt")
        if receipt_path is None:
            errors.append("published bundles require a publication-receipt artifact")
        elif publication.get("receiptPath") != str(receipt_path):
            errors.append("publication.receiptPath must match the publication-receipt artifact")
        if not isinstance(publication.get("publisherSubject"), str) or not publication.get(
            "publisherSubject", ""
        ).strip():
            errors.append("published bundles require publication.publisherSubject")
        for field in ("authorizedAt", "publishedAt"):
            value = publication.get(field)
            if not isinstance(value, str) or not ISO_UTC.fullmatch(value):
                errors.append(f"published bundles require UTC publication.{field}")
        if (
            isinstance(publication.get("authorizedAt"), str)
            and isinstance(publication.get("publishedAt"), str)
            and publication["authorizedAt"] > publication["publishedAt"]
        ):
            errors.append("publication.authorizedAt cannot be later than publishedAt")
        if not isinstance(publication.get("releaseId"), str) or not VERSION.fullmatch(
            publication.get("releaseId", "")
        ):
            errors.append("published bundles require a safe publication.releaseId")


def _validate_stats(
    stats: Any,
    manifest_dir: Path | None,
    errors: list[str],
) -> dict[str, Any]:
    if not isinstance(stats, dict):
        errors.append("stats must be an object")
        return {}
    for field in (
        "concepts",
        "relations",
        "mappings",
        "structuredSources",
        "documentRepositories",
        "competencyQuestions",
        "passedCompetencyQuestions",
    ):
        value = stats.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"stats.{field} must be a non-negative integer")
    if manifest_dir is None:
        return stats
    try:
        ontology = (manifest_dir / "ontology.ttl").read_text(encoding="utf-8")
        mappings = (manifest_dir / "mappings.ttl").read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot calculate package stats: {exc}")
        return stats
    source_systems = set(re.findall(r'oa:sourceSystem\s+"([^"]+)"', mappings))
    document_sources = {source for source in source_systems if "DOCUMENT" in source}
    actual = {
        "concepts": len(re.findall(r"\ba\s+(?:owl:Class|skos:Concept)\b", ontology)),
        "relations": len(re.findall(r"\ba\s+owl:ObjectProperty\b", ontology)),
        "mappings": len(re.findall(r"\ba\s+oa:MappingProposal\b", mappings)),
        "structuredSources": len(source_systems - document_sources),
        "documentRepositories": len(document_sources),
    }
    for field, value in actual.items():
        if stats.get(field) != value:
            errors.append(f"stats.{field} must equal the materialized count {value}")
    return stats


def validate(data: Any, pilot: bool = False, manifest_dir: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["manifest must be a JSON object"]

    required = (
        "$schema",
        "version",
        "tenantId",
        "ontologyVersion",
        "namespace",
        "createdAt",
        "materializeOwlRl",
        "publication",
        "artifacts",
        "supportingArtifacts",
        "stats",
    )
    for key in required:
        if key not in data:
            errors.append(f"missing required field: {key}")
    if data.get("$schema") != "urn:ontology-appliance:schema:artifact-manifest:1":
        errors.append("$schema must identify artifact-manifest:1")
    for key in ("version", "ontologyVersion"):
        value = data.get(key)
        if not isinstance(value, str) or not VERSION.fullmatch(value):
            errors.append(f"{key} has an invalid version format")
    if not isinstance(data.get("tenantId"), str) or not data.get("tenantId", "").strip():
        errors.append("tenantId must be a non-empty string")
    namespace = data.get("namespace")
    if not isinstance(namespace, str) or not (
        namespace.startswith("urn:ontology-appliance:") or namespace.startswith("https://")
    ):
        errors.append("namespace must be a governed HTTPS or urn:ontology-appliance IRI")
    if not isinstance(data.get("createdAt"), str) or not ISO_UTC.fullmatch(data.get("createdAt", "")):
        errors.append("createdAt must be a UTC date-time with second precision")
    if not isinstance(data.get("materializeOwlRl"), bool):
        errors.append("materializeOwlRl must be boolean")

    runtime_paths: set[str] = set()
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be an array")
    else:
        for index, artifact in enumerate(artifacts):
            label = f"artifacts[{index}]"
            if not isinstance(artifact, dict):
                errors.append(f"{label} must be an object")
                continue
            path = _safe_relative_path(artifact.get("path"), f"{label}.path", errors)
            path_text = str(path) if path is not None else ""
            if path_text in runtime_paths:
                errors.append(f"duplicate runtime artifact path: {path_text}")
            runtime_paths.add(path_text)
            expected = RUNTIME_ARTIFACTS.get(path_text)
            if expected is None:
                errors.append(f"unsupported runtime artifact: {path_text}")
            elif (artifact.get("format"), artifact.get("kind")) != expected:
                errors.append(
                    f"{label} must use format={expected[0]} and kind={expected[1]} for {path_text}"
                )
            digest = artifact.get("sha256")
            _validate_hash(digest, f"{label}.sha256", errors)
            _verify_file(manifest_dir, path, digest, label, errors)
        missing = set(RUNTIME_ARTIFACTS) - runtime_paths
        if missing:
            errors.append(f"missing runtime artifacts: {sorted(missing)}")

    supporting_by_role: dict[str, Path] = {}
    supporting = data.get("supportingArtifacts")
    if not isinstance(supporting, list):
        errors.append("supportingArtifacts must be an array")
    else:
        for index, artifact in enumerate(supporting):
            label = f"supportingArtifacts[{index}]"
            if not isinstance(artifact, dict):
                errors.append(f"{label} must be an object")
                continue
            role = artifact.get("role")
            if role not in SUPPORTING_ROLES:
                errors.append(f"{label}.role must be one of {sorted(SUPPORTING_ROLES)}")
            elif role in supporting_by_role:
                errors.append(f"duplicate supporting artifact role: {role}")
            path = _safe_relative_path(artifact.get("path"), f"{label}.path", errors)
            if isinstance(role, str) and path is not None:
                supporting_by_role[role] = path
            if artifact.get("mediaType") != "application/json":
                errors.append(f"{label}.mediaType must be application/json")
            digest = artifact.get("sha256")
            _validate_hash(digest, f"{label}.sha256", errors)
            _verify_file(manifest_dir, path, digest, label, errors)
        missing_roles = REQUIRED_SUPPORTING_ROLES - set(supporting_by_role)
        if missing_roles:
            errors.append(f"missing supporting artifact roles: {sorted(missing_roles)}")

    _validate_publication(
        data.get("publication"),
        data,
        supporting_by_role,
        manifest_dir,
        errors,
    )

    stats = _validate_stats(data.get("stats"), manifest_dir, errors)
    if pilot and isinstance(stats, dict):
        if not 30 <= stats.get("concepts", -1) <= 50:
            errors.append("pilot requires 30 to 50 materialized concepts")
        if not 15 <= stats.get("relations", -1) <= 25:
            errors.append("pilot requires 15 to 25 materialized relations")
        if not 100 <= stats.get("mappings", -1) <= 200:
            errors.append("pilot requires 100 to 200 materialized mappings")
        if not 3 <= stats.get("structuredSources", -1) <= 5:
            errors.append("pilot requires three to five materialized structured sources")
        if stats.get("documentRepositories", 0) < 1:
            errors.append("pilot requires at least one materialized document repository")
        if stats.get("competencyQuestions", 0) < 5:
            errors.append("pilot requires at least five competency questions")
        if stats.get("passedCompetencyQuestions", 0) < 4:
            errors.append("pilot requires at least four passing competency questions")

    if manifest_dir is not None:
        questions_path = supporting_by_role.get("questions")
        if questions_path is not None:
            questions = _load_json(manifest_dir / questions_path, "competency questions", errors)
            if questions is not None:
                _validate_questions(questions, stats, pilot, errors)
        proposal_path = supporting_by_role.get("proposal")
        proposal: Any | None = None
        if proposal_path is not None:
            proposal = _load_json(manifest_dir / proposal_path, "proposal", errors)
            if proposal is not None:
                _validate_proposal(proposal, data, manifest_dir, errors)
        verification_path = supporting_by_role.get("verification")
        if verification_path is not None and proposal_path is not None:
            verification = _load_json(manifest_dir / verification_path, "verification", errors)
            if verification is not None:
                _validate_verification(
                    verification,
                    proposal,
                    manifest_dir / proposal_path,
                    data,
                    manifest_dir,
                    errors,
                )
    return errors


def valid_example() -> dict[str, Any]:
    return {
        "$schema": "urn:ontology-appliance:schema:artifact-manifest:1",
        "version": "2026.07.1-demo-bank",
        "tenantId": "demo-bank",
        "ontologyVersion": "2026.07.1",
        "namespace": "urn:ontology-appliance:demo-bank:",
        "createdAt": "2026-07-22T13:51:12Z",
        "materializeOwlRl": True,
        "publication": {
            "state": "CANDIDATE",
            "servingMode": "DEMO_ONLY",
            "isPublished": False,
            "reviewLedgerPath": "publication-review.json",
            "reviewLedgerSha256": "e" * 64,
        },
        "artifacts": [
            {"path": path, "sha256": "a" * 64, "format": fmt, "kind": kind}
            for path, (fmt, kind) in RUNTIME_ARTIFACTS.items()
        ],
        "supportingArtifacts": [
            {
                "role": "questions",
                "path": "competency-questions.json",
                "sha256": "b" * 64,
                "mediaType": "application/json",
            },
            {
                "role": "proposal",
                "path": "proposals/mapping-crm-cif.json",
                "sha256": "c" * 64,
                "mediaType": "application/json",
            },
            {
                "role": "verification",
                "path": "verification/mapping-crm-cif.mock.json",
                "sha256": "d" * 64,
                "mediaType": "application/json",
            },
            {
                "role": "publication-review",
                "path": "publication-review.json",
                "sha256": "e" * 64,
                "mediaType": "application/json",
            },
        ],
        "stats": {
            "concepts": 40,
            "relations": 20,
            "mappings": 120,
            "structuredSources": 5,
            "documentRepositories": 1,
            "competencyQuestions": 5,
            "passedCompetencyQuestions": 5,
        },
    }


def self_test() -> int:
    assert validate(valid_example(), pilot=True) == []
    broken = valid_example()
    broken["artifacts"] = broken["artifacts"][:-1]
    broken["namespace"] = "relative"
    broken["stats"]["passedCompetencyQuestions"] = 3
    errors = validate(broken, pilot=True)
    assert any("missing runtime artifacts" in error for error in errors)
    assert any("namespace" in error for error in errors)
    assert any("four passing" in error for error in errors)
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--pilot", action="store_true", help="enforce pilot acceptance gates")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.manifest is None:
        parser.error("manifest is required unless --self-test is used")
    manifest = args.manifest.resolve()
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 2
    errors = validate(data, pilot=args.pilot, manifest_dir=manifest.parent)
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
