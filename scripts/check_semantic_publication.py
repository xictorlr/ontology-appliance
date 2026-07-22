#!/usr/bin/env python3
"""Validate candidate/published graph separation and the Publisher release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF


OA = Namespace("urn:ontology-appliance:vocab:")
ROOT = Path(__file__).resolve().parents[1]
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UTC_SECOND = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RELEASE_SHA = re.compile(r"^[0-9a-f]{40,64}$")
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
MODE_METADATA = {
    "candidate": ("CANDIDATE", "DEMO_ONLY", False),
    "publish": ("PUBLISHABLE", "PUBLISHER_ONLY", False),
    "published": ("PUBLISHED", "ACTIVE", True),
}
PUBLISHABLE_MAPPING_STATES = {"APPROVED", "PUBLISHED"}
AUTHORIZED_HUMAN_ROLES = {"steward", "compliance-reviewer"}
AUTHORIZED_MODEL_ROLES = {"independent-verifier"}
GOLDEN_SCHEMA = "urn:ontology-appliance:schema:competency-question-golden:1"
MANIFEST_SCHEMA = "urn:ontology-appliance:schema:artifact-manifest:1"
EVIDENCE_INDEX_SCHEMA = "urn:ontology-appliance:schema:evidence-index:1"
REVIEW_EXPORT_SCHEMA = (
    "urn:ontology-appliance:schema:firestore-review-receipts-export:1"
)
REVIEW_EXPORT_NORMALIZATION = "firestore-review-export-normalization/1.0.0"
REVIEW_EXPORT_TRUST_BOUNDARY = (
    "UNSIGNED_OPERATOR_EXPORT_REQUIRES_PROTECTED_PR_REVIEW"
)
REVIEW_ARTIFACT_FIELDS = {
    "proposalSha256": "proposal",
    "verificationSha256": "verification",
    "evidenceIndexSha256": "evidence-index",
}
GOLDEN_EVIDENCE_FIELDS = {
    "sourceId": OA.sourceId,
    "snapshotId": OA.snapshotId,
    "locator": OA.locator,
    "contentSha256": OA.contentSha256,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verification_run_sha256(
    verification: dict[str, Any], label: str, errors: list[str]
) -> str | None:
    recorded = verification.get("verification_run_sha256")
    if not isinstance(recorded, str) or not SHA256.fullmatch(recorded):
        errors.append(f"{label} verification_run_sha256 must be a SHA-256 digest")
        return None
    payload = {
        key: value
        for key, value in verification.items()
        if key != "verification_run_sha256"
    }
    actual = _canonical_sha256(payload)
    if recorded != actual:
        errors.append(
            f"{label} verification_run_sha256 does not match canonical run content"
        )
        return None
    return actual


def _safe_path(root: Path, value: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{label} must be a non-empty relative path")
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{label} must stay inside the bundle")
        return None
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        errors.append(f"{label} escapes the bundle")
        return None
    return target


def _load_json(path: Path, label: str, errors: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read {label}: {exc}")
        return None


def _verify_digest(
    path: Path | None, digest: Any, label: str, errors: list[str]
) -> None:
    if path is None:
        return
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        errors.append(f"{label} must be a lowercase SHA-256 digest")
        return
    try:
        actual = _sha256(path)
    except OSError as exc:
        errors.append(f"cannot hash {label}: {exc}")
        return
    if actual != digest:
        errors.append(f"{label} hash mismatch: expected {digest}, got {actual}")


def _supporting_record(manifest: dict[str, Any], role: str) -> dict[str, Any] | None:
    matches = _supporting_records(manifest, role)
    return matches[0] if len(matches) == 1 else None


def _supporting_records(
    manifest: dict[str, Any], role: str
) -> list[dict[str, Any]]:
    records = manifest.get("supportingArtifacts")
    if not isinstance(records, list):
        return []
    return [
        record
        for record in records
        if isinstance(record, dict) and record.get("role") == role
    ]


def _proposal_supporting_record(
    manifest: dict[str, Any], role: str, proposal_id: str
) -> dict[str, Any] | None:
    records = manifest.get("supportingArtifacts")
    if not isinstance(records, list):
        return None
    matches = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("role") == role
        and record.get("proposalId") == proposal_id
    ]
    return matches[0] if len(matches) == 1 else None


def _first_value(document: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in document:
            return document[key]
    return None


def _mapping_record(manifest: dict[str, Any]) -> dict[str, Any] | None:
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        return None
    matches = [
        record
        for record in records
        if isinstance(record, dict) and record.get("path") == "mappings.ttl"
    ]
    return matches[0] if len(matches) == 1 else None


def _mapping_states(path: Path, errors: list[str]) -> dict[str, str]:
    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:
        errors.append(f"cannot parse mappings.ttl: {exc}")
        return {}

    mappings: dict[str, str] = {}
    for subject in set(graph.subjects(RDF.type, OA.MappingProposal)):
        identifiers = {str(value) for value in graph.objects(subject, OA.mappingId)}
        statuses = {
            str(value).upper() for value in graph.objects(subject, OA.proposalStatus)
        }
        if len(identifiers) != 1:
            errors.append(f"mapping {subject} must have exactly one oa:mappingId")
            continue
        mapping_id = next(iter(identifiers))
        if mapping_id in mappings:
            errors.append(f"duplicate mapping id: {mapping_id}")
            continue
        if len(statuses) != 1:
            errors.append(
                f"mapping {mapping_id} must have exactly one oa:proposalStatus"
            )
            continue
        mappings[mapping_id] = next(iter(statuses))
    if not mappings:
        errors.append("mappings.ttl contains no oa:MappingProposal resources")
    return mappings


def _load_runtime_graph(
    root: Path, manifest: dict[str, Any], errors: list[str]
) -> Graph | None:
    raw_records = manifest.get("artifacts")
    if not isinstance(raw_records, list):
        errors.append("manifest artifacts must be an array for golden-query execution")
        return None
    graph = Graph()
    loaded = 0
    for index, record in enumerate(raw_records):
        if not isinstance(record, dict) or record.get("kind") not in {
            "graph",
            "provenance",
        }:
            continue
        label = f"golden runtime artifact[{index}]"
        path = _safe_path(root, record.get("path"), f"{label} path", errors)
        _verify_digest(path, record.get("sha256"), label, errors)
        if path is None:
            continue
        rdf_format = record.get("format")
        if rdf_format not in {"turtle", "nquads", "trig", "json-ld", "xml"}:
            errors.append(f"{label} has unsupported RDF format {rdf_format!r}")
            continue
        try:
            if rdf_format in {"nquads", "trig"}:
                dataset = Dataset()
                dataset.parse(path, format=rdf_format)
                for subject, predicate, obj, _context in dataset.quads(
                    (None, None, None, None)
                ):
                    graph.add((subject, predicate, obj))
            else:
                graph.parse(path, format=rdf_format)
        except Exception as exc:
            errors.append(f"cannot parse {label}: {exc}")
            continue
        loaded += 1
    if loaded == 0 or not graph:
        errors.append("golden-query execution requires a non-empty runtime RDF graph")
        return None
    if manifest.get("materializeOwlRl", True) is True:
        try:
            DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False).expand(graph)
        except Exception as exc:
            errors.append(f"cannot materialize OWL-RL for golden queries: {exc}")
            return None
    return graph


def _normalized_select_rows(graph: Graph, query: str) -> list[dict[str, Any]]:
    result = graph.query(query)
    variables = [str(variable) for variable in result.vars]
    rows: list[dict[str, Any]] = []
    for row in result:
        normalized: dict[str, Any] = {}
        for variable in variables:
            value = row.get(variable)
            if value is None:
                normalized[variable] = None
            elif isinstance(value, (Literal, URIRef)):
                normalized[variable] = str(value)
            else:
                normalized[variable] = str(value)
        rows.append(normalized)
    return rows


def _golden_evidence(
    graph: Graph, evidence_iris: Any, label: str
) -> tuple[list[dict[str, str]], list[str]]:
    problems: list[str] = []
    if not isinstance(evidence_iris, list) or not evidence_iris:
        return [], [f"{label}.evidenceIris must be a non-empty array"]
    if len(evidence_iris) != len(set(evidence_iris)):
        problems.append(f"{label}.evidenceIris must not contain duplicates")
    coordinates: list[dict[str, str]] = []
    for index, evidence_iri in enumerate(evidence_iris):
        evidence_label = f"{label}.evidenceIris[{index}]"
        if not isinstance(evidence_iri, str) or not evidence_iri:
            problems.append(f"{evidence_label} must be a non-empty IRI")
            continue
        evidence = URIRef(evidence_iri)
        if (evidence, RDF.type, OA.EvidenceArtifact) not in graph:
            problems.append(f"{evidence_label} is not an oa:EvidenceArtifact")
            continue
        coordinate = {"evidenceIri": evidence_iri}
        complete = True
        for field, predicate in GOLDEN_EVIDENCE_FIELDS.items():
            values = {str(value) for value in graph.objects(evidence, predicate)}
            if len(values) != 1:
                problems.append(
                    f"{evidence_label} requires exactly one oa:{str(predicate).rsplit(':', 1)[-1]}"
                )
                complete = False
                continue
            coordinate[field] = next(iter(values))
        if complete and not SHA256.fullmatch(coordinate["contentSha256"]):
            problems.append(f"{evidence_label}.contentSha256 is not a SHA-256 digest")
            complete = False
        if complete:
            coordinates.append(coordinate)
    return coordinates, problems


def _validate_golden_questions(
    golden: Any,
    manifest: dict[str, Any],
    graph: Graph,
    errors: list[str],
) -> dict[str, int]:
    counts = {"total": 0, "passed": 0}
    if not isinstance(golden, dict):
        errors.append("competency-question golden fixture must be a JSON object")
        return counts
    if golden.get("$schema") != GOLDEN_SCHEMA:
        errors.append("competency-question golden fixture uses an unsupported schema")
    for golden_key, manifest_key in (
        ("bundleVersion", "version"),
        ("ontologyVersion", "ontologyVersion"),
        ("tenantId", "tenantId"),
    ):
        if golden.get(golden_key) != manifest.get(manifest_key):
            errors.append(f"golden {golden_key} does not match the manifest")
    normalization = golden.get("normalization")
    if not isinstance(normalization, dict) or "Deep JSON equality" not in str(
        normalization.get("comparison", "")
    ):
        errors.append("golden normalization must require deep JSON equality")

    questions = golden.get("questions")
    if not isinstance(questions, list):
        errors.append("golden questions must be an array")
        return counts
    counts["total"] = len(questions)
    required_ids = {f"CQ-{number:03d}" for number in range(1, 6)}
    observed_ids: set[str] = set()
    for index, question in enumerate(questions):
        label = f"golden questions[{index}]"
        if not isinstance(question, dict):
            errors.append(f"{label} must be an object")
            continue
        question_id = question.get("id")
        if not isinstance(question_id, str) or question_id in observed_ids:
            errors.append(f"{label}.id must be a unique competency-question ID")
            continue
        observed_ids.add(question_id)
        case_problems: list[str] = []
        if question.get("queryVersion") != "1.0.0":
            case_problems.append(f"{label}.queryVersion must be 1.0.0")
        query = question.get("sparql")
        actual_rows: list[dict[str, Any]] = []
        if not isinstance(query, str) or not query.strip():
            case_problems.append(f"{label}.sparql must be a non-empty SELECT query")
        elif not re.search(r"\bSELECT\b", query, re.IGNORECASE) or not re.search(
            r"\bORDER\s+BY\b", query, re.IGNORECASE
        ):
            case_problems.append(f"{label}.sparql must be an ordered SELECT query")
        elif re.search(
            r"\b(INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|COPY|MOVE|ADD|SERVICE)\b",
            query,
            re.IGNORECASE,
        ):
            case_problems.append(f"{label}.sparql is not local and read-only")
        else:
            try:
                actual_rows = _normalized_select_rows(graph, query)
            except Exception as exc:
                case_problems.append(f"{label}.sparql execution failed: {exc}")

        expected = question.get("expectedOutcome")
        if not isinstance(expected, dict):
            case_problems.append(f"{label}.expectedOutcome must be an object")
            expected = {}
        if actual_rows != expected.get("rows"):
            case_problems.append(
                f"{label} rows differ from the exact normalized golden result"
            )
        actual_evidence, evidence_problems = _golden_evidence(
            graph, question.get("evidenceIris"), label
        )
        case_problems.extend(evidence_problems)
        if actual_evidence != expected.get("evidence"):
            case_problems.append(
                f"{label} evidence coordinates differ from the exact golden provenance"
            )
        if expected.get("bundleVersion") != manifest.get("version"):
            case_problems.append(f"{label} expected bundleVersion is stale")
        if expected.get("ontologyVersion") != manifest.get("ontologyVersion"):
            case_problems.append(f"{label} expected ontologyVersion is stale")
        expected_trace = (
            f"golden-{question_id.lower()}-"
            f"{str(manifest.get('ontologyVersion', '')).replace('.', '-')}"
        )
        if expected.get("traceId") != expected_trace:
            case_problems.append(
                f"{label} traceId must be the reproducible trace {expected_trace}"
            )

        derived_status = "PASS" if not case_problems else "FAIL"
        if question.get("status") != derived_status:
            errors.append(
                f"{label}.status is {question.get('status')!r}, but exact execution derives {derived_status}"
            )
        if derived_status == "PASS":
            counts["passed"] += 1
        elif question.get("status") == "PASS":
            errors.extend(case_problems)

    missing = required_ids - observed_ids
    if missing or len(questions) != len(required_ids):
        errors.append(
            f"golden suite must contain exactly CQ-001 through CQ-005; missing={sorted(missing)}"
        )
    if golden.get("summary") != counts:
        errors.append(
            f"golden summary must be derived from exact execution: expected {counts}"
        )
    stats = manifest.get("stats")
    if not isinstance(stats, dict):
        errors.append("manifest stats are required for golden-query acceptance")
    else:
        if stats.get("competencyQuestions") != counts["total"]:
            errors.append(
                "stats.competencyQuestions does not equal the executed golden total"
            )
        if stats.get("passedCompetencyQuestions") != counts["passed"]:
            errors.append(
                "stats.passedCompetencyQuestions does not equal exact golden passes"
            )
    return counts


def _load_linked_review_artifacts(
    decision: dict[str, Any],
    mapping_id: str,
    manifest: dict[str, Any],
    root: Path,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    evidence = decision.get("reviewEvidence")
    if not isinstance(evidence, dict):
        errors.append(f"{mapping_id}: reviewEvidence is required")
        return {}

    documents: dict[str, dict[str, Any]] = {}
    for evidence_field, role in REVIEW_ARTIFACT_FIELDS.items():
        review_digest = evidence.get(evidence_field)
        if not isinstance(review_digest, str) or not SHA256.fullmatch(review_digest):
            errors.append(
                f"{mapping_id}: reviewEvidence.{evidence_field} must be a SHA-256 digest"
            )
        record = _proposal_supporting_record(manifest, role, mapping_id)
        if record is None:
            errors.append(
                f"{mapping_id}: manifest must contain exactly one {role} artifact "
                "with the same proposalId"
            )
            continue
        manifest_digest = record.get("sha256")
        if review_digest != manifest_digest:
            errors.append(
                f"{mapping_id}: reviewEvidence.{evidence_field} does not match "
                f"the manifest {role} digest"
            )
        path = _safe_path(
            root,
            record.get("path"),
            f"{mapping_id} {role} artifact path",
            errors,
        )
        _verify_digest(path, manifest_digest, f"{mapping_id} {role} artifact", errors)
        document = (
            _load_json(path, f"{mapping_id} {role} artifact", errors)
            if path is not None
            else None
        )
        if not isinstance(document, dict):
            errors.append(f"{mapping_id}: {role} artifact must be a JSON object")
            continue
        documents[role] = document

    proposal = documents.get("proposal")
    verification = documents.get("verification")
    evidence_index = documents.get("evidence-index")
    tenant_id = manifest.get("tenantId")
    if proposal is not None:
        if _first_value(proposal, "proposal_id", "proposalId") != mapping_id:
            errors.append(f"{mapping_id}: proposal artifact identifies another proposal")
        if _first_value(proposal, "tenant_id", "tenantId") != tenant_id:
            errors.append(f"{mapping_id}: proposal artifact identifies another tenant")
    if verification is not None:
        if _first_value(verification, "proposal_id", "proposalId") != mapping_id:
            errors.append(
                f"{mapping_id}: verification artifact identifies another proposal"
            )
        if _first_value(verification, "tenant_id", "tenantId") != tenant_id:
            errors.append(f"{mapping_id}: verification artifact identifies another tenant")
        if verification.get("verification_run_id") != decision.get("verificationRunId"):
            errors.append(
                f"{mapping_id}: verificationRunId does not identify the linked "
                "verification artifact"
            )
        canonical_run_sha = _verification_run_sha256(
            verification, f"{mapping_id}: verification artifact", errors
        )
        if decision.get("verificationRunSha256") != canonical_run_sha:
            errors.append(
                f"{mapping_id}: verificationRunSha256 does not match the canonical "
                "verification run"
            )
        if isinstance(evidence, dict):
            if verification.get("frozen_proposal_sha256") != evidence.get(
                "proposalSha256"
            ):
                errors.append(
                    f"{mapping_id}: verification artifact does not freeze the linked proposal"
                )
    if evidence_index is not None:
        if evidence_index.get("$schema") != EVIDENCE_INDEX_SCHEMA:
            errors.append(f"{mapping_id}: evidence-index schema is unsupported")
        if _first_value(evidence_index, "proposal_id", "proposalId") != mapping_id:
            errors.append(
                f"{mapping_id}: evidence-index artifact identifies another proposal"
            )
        if _first_value(evidence_index, "tenant_id", "tenantId") != tenant_id:
            errors.append(
                f"{mapping_id}: evidence-index artifact identifies another tenant"
            )
        frozen_evidence_sha = evidence_index.get(
            "sourceEvidenceIndexSha256",
            evidence.get("evidenceIndexSha256") if isinstance(evidence, dict) else None,
        )
        if not isinstance(frozen_evidence_sha, str) or not SHA256.fullmatch(
            frozen_evidence_sha
        ):
            errors.append(
                f"{mapping_id}: evidence-index frozen source digest is invalid"
            )
        elif (
            verification is not None
            and verification.get("frozen_evidence_index_sha256")
            != frozen_evidence_sha
        ):
            errors.append(
                f"{mapping_id}: verification artifact does not freeze the source "
                "represented by the linked evidence index"
            )

    if proposal is not None and evidence_index is not None:
        for field in ("evidence", "counterevidence"):
            if proposal.get(field) != evidence_index.get(field):
                errors.append(
                    f"{mapping_id}: evidence-index {field} does not match the frozen proposal"
                )
    if verification is not None and evidence_index is not None:
        for field in ("evidence", "counterevidence"):
            if verification.get(field) != evidence_index.get(field):
                errors.append(
                    f"{mapping_id}: evidence-index {field} does not match the "
                    "verification artifact"
                )
    return documents


def _validate_reviewer(
    decision: dict[str, Any],
    mapping_id: str,
    manifest: dict[str, Any],
    root: Path,
    errors: list[str],
) -> None:
    reviewer = decision.get("reviewer")
    if not isinstance(reviewer, dict):
        errors.append(
            f"{mapping_id}: an immutable independent reviewer record is required"
        )
        return
    subject = reviewer.get("subject")
    kind = reviewer.get("kind")
    role = reviewer.get("role")
    reviewed_at = reviewer.get("reviewedAt")
    generator = decision.get("generatorSubject")
    verifier = decision.get("verifierSubject")

    if not isinstance(subject, str) or not subject.strip():
        errors.append(f"{mapping_id}: reviewer.subject is required")
    if not isinstance(generator, str) or not generator.strip():
        errors.append(f"{mapping_id}: generatorSubject is required")
    if not isinstance(verifier, str) or not verifier.strip():
        errors.append(f"{mapping_id}: verifierSubject is required")
    if isinstance(subject, str) and isinstance(generator, str) and subject == generator:
        errors.append(f"{mapping_id}: reviewer must be independent from the generator")
    if (
        isinstance(generator, str)
        and isinstance(verifier, str)
        and generator == verifier
    ):
        errors.append(f"{mapping_id}: verifier must be independent from the generator")

    if kind == "HUMAN":
        if role not in AUTHORIZED_HUMAN_ROLES:
            errors.append(f"{mapping_id}: human reviewer role is not authorized")
        if (
            isinstance(subject, str)
            and isinstance(verifier, str)
            and subject == verifier
        ):
            errors.append(
                f"{mapping_id}: human reviewer must be separate from the verifier"
            )
    elif kind == "INDEPENDENT_MODEL":
        if role not in AUTHORIZED_MODEL_ROLES:
            errors.append(f"{mapping_id}: model reviewer role is not authorized")
        if (
            isinstance(subject, str)
            and isinstance(verifier, str)
            and subject != verifier
        ):
            errors.append(
                f"{mapping_id}: model reviewer must identify the recorded verifier"
            )
    else:
        errors.append(f"{mapping_id}: reviewer.kind must be HUMAN or INDEPENDENT_MODEL")

    if not isinstance(reviewed_at, str) or not UTC_SECOND.fullmatch(reviewed_at):
        errors.append(f"{mapping_id}: reviewer.reviewedAt must be a UTC timestamp")

    _load_linked_review_artifacts(decision, mapping_id, manifest, root, errors)
    source_receipt_sha = decision.get("sourceReceiptSha256")
    if not isinstance(source_receipt_sha, str) or not SHA256.fullmatch(
        source_receipt_sha
    ):
        errors.append(f"{mapping_id}: sourceReceiptSha256 is required")
    if (
        not isinstance(decision.get("decisionId"), str)
        or not decision.get("decisionId", "").strip()
    ):
        errors.append(f"{mapping_id}: decisionId is required")


def _validate_export_provenance(
    ledger: dict[str, Any], manifest: dict[str, Any], errors: list[str]
) -> None:
    provenance = ledger.get("exportProvenance")
    if not isinstance(provenance, dict):
        errors.append("publication review exportProvenance is required")
        return
    required = {
        "sourceSchema",
        "normalizationVersion",
        "sourceExportSha256",
        "digestAlgorithm",
        "collectionPath",
        "exportedAt",
        "trustBoundary",
    }
    if set(provenance) != required:
        errors.append(
            "publication review exportProvenance must contain exactly the versioned "
            "normalized-export contract"
        )
    tenant_id = manifest.get("tenantId")
    expected_collection = f"tenants/{tenant_id}/reviewReceipts"
    expected = {
        "sourceSchema": REVIEW_EXPORT_SCHEMA,
        "normalizationVersion": REVIEW_EXPORT_NORMALIZATION,
        "digestAlgorithm": "SHA-256",
        "collectionPath": expected_collection,
        "trustBoundary": REVIEW_EXPORT_TRUST_BOUNDARY,
    }
    for key, value in expected.items():
        if provenance.get(key) != value:
            errors.append(f"publication review exportProvenance.{key} is invalid")
    if not isinstance(provenance.get("sourceExportSha256"), str) or not SHA256.fullmatch(
        provenance["sourceExportSha256"]
    ):
        errors.append(
            "publication review exportProvenance.sourceExportSha256 must be a SHA-256 digest"
        )
    if not isinstance(provenance.get("exportedAt"), str) or not UTC_SECOND.fullmatch(
        provenance["exportedAt"]
    ):
        errors.append(
            "publication review exportProvenance.exportedAt must be a UTC timestamp"
        )


def _validate_ledger(
    ledger: Any,
    manifest: dict[str, Any],
    mappings: dict[str, str],
    mode: str,
    root: Path,
    errors: list[str],
) -> None:
    if not isinstance(ledger, dict):
        errors.append("publication review ledger must be a JSON object")
        return
    if ledger.get("$schema") != "urn:ontology-appliance:schema:publication-review:1":
        errors.append("publication review ledger uses an unsupported schema")
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
        "PUBLISHABLE" if mode in {"publish", "published"} else "CANDIDATE"
    )
    if ledger.get("state") != expected_ledger_state:
        errors.append(
            f"publication review state must be {expected_ledger_state} for {mode} mode"
        )

    counts = Counter(mappings.values())
    population = ledger.get("mappingPopulation")
    expected_population = {
        "total": len(mappings),
        "approved": counts["APPROVED"],
        "published": counts["PUBLISHED"],
        "humanReview": counts["HUMAN_REVIEW"],
    }
    if population != expected_population:
        errors.append(
            "publication review mappingPopulation does not match mappings.ttl: "
            f"expected {expected_population}"
        )

    raw_decisions = ledger.get("decisions")
    if not isinstance(raw_decisions, list):
        errors.append("publication review decisions must be an array")
        return
    decisions: dict[str, dict[str, Any]] = {}
    has_publishable_decision = False
    for index, decision in enumerate(raw_decisions):
        if not isinstance(decision, dict):
            errors.append(f"publication review decisions[{index}] must be an object")
            continue
        mapping_id = decision.get("mappingId")
        if not isinstance(mapping_id, str) or not mapping_id:
            errors.append(
                f"publication review decisions[{index}].mappingId is required"
            )
            continue
        if mapping_id in decisions:
            errors.append(f"duplicate publication decision for {mapping_id}")
            continue
        if mapping_id not in mappings:
            errors.append(
                f"publication decision references unknown mapping {mapping_id}"
            )
            continue
        decisions[mapping_id] = decision
        decision_status = str(decision.get("status", "")).upper()
        if decision_status != mappings[mapping_id]:
            errors.append(
                f"{mapping_id}: ledger status {decision_status or '<missing>'} does not match "
                f"RDF status {mappings[mapping_id]}"
            )
        if decision_status in PUBLISHABLE_MAPPING_STATES:
            has_publishable_decision = True
            _validate_reviewer(decision, mapping_id, manifest, root, errors)

    if has_publishable_decision or mode in {"publish", "published"}:
        _validate_export_provenance(ledger, manifest, errors)

    if mode in {"publish", "published"}:
        unresolved = [
            f"{mapping_id}={status}"
            for mapping_id, status in mappings.items()
            if status not in PUBLISHABLE_MAPPING_STATES
        ]
        if unresolved:
            sample = ", ".join(sorted(unresolved)[:8])
            suffix = " ..." if len(unresolved) > 8 else ""
            errors.append(
                f"{len(unresolved)} mapping(s) are not APPROVED/PUBLISHED: {sample}{suffix}"
            )
        missing = sorted(set(mappings) - set(decisions))
        if missing:
            sample = ", ".join(missing[:8])
            suffix = " ..." if len(missing) > 8 else ""
            errors.append(
                f"{len(missing)} mapping(s) lack an immutable review decision: {sample}{suffix}"
            )
        if ledger.get("coverage") != "FULL":
            errors.append("publication review coverage must be FULL")


def validate(manifest_path: Path, mode: str) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    manifest_path = manifest_path.resolve()
    manifest = _load_json(manifest_path, "manifest", errors)
    if not isinstance(manifest, dict):
        return errors, {}
    root = manifest_path.parent

    publication = manifest.get("publication")
    if not isinstance(publication, dict):
        errors.append("manifest publication metadata is required")
        publication = {}
    expected_state, expected_serving, expected_published = MODE_METADATA[mode]
    if publication.get("state") != expected_state:
        errors.append(f"publication.state must be {expected_state} for {mode} mode")
    if publication.get("servingMode") != expected_serving:
        errors.append(
            f"publication.servingMode must be {expected_serving} for {mode} mode"
        )
    if publication.get("isPublished") is not expected_published:
        errors.append(
            f"publication.isPublished must be {str(expected_published).lower()}"
        )

    mapping_record = _mapping_record(manifest)
    if mapping_record is None:
        errors.append("manifest must contain exactly one mappings.ttl runtime artifact")
        mappings: dict[str, str] = {}
    else:
        mapping_path = _safe_path(
            root, mapping_record.get("path"), "mappings path", errors
        )
        _verify_digest(
            mapping_path, mapping_record.get("sha256"), "mappings.ttl", errors
        )
        mappings = (
            _mapping_states(mapping_path, errors) if mapping_path is not None else {}
        )

    review_record = _supporting_record(manifest, "publication-review")
    if review_record is None:
        errors.append(
            "manifest must contain exactly one publication-review supporting artifact"
        )
        ledger = None
    else:
        review_path = _safe_path(
            root, review_record.get("path"), "publication review path", errors
        )
        _verify_digest(
            review_path, review_record.get("sha256"), "publication review", errors
        )
        if publication.get("reviewLedgerPath") != review_record.get("path"):
            errors.append(
                "publication.reviewLedgerPath must match the publication-review artifact"
            )
        if publication.get("reviewLedgerSha256") != review_record.get("sha256"):
            errors.append(
                "publication.reviewLedgerSha256 must match the publication-review artifact"
            )
        ledger = (
            _load_json(review_path, "publication review", errors)
            if review_path is not None
            else None
        )
    _validate_ledger(ledger, manifest, mappings, mode, root, errors)

    golden_counts = {"total": 0, "passed": 0}
    questions_record = _supporting_record(manifest, "questions")
    if questions_record is None:
        if manifest.get("$schema") == MANIFEST_SCHEMA:
            errors.append(
                "manifest must contain exactly one hash-verified questions golden fixture"
            )
    else:
        questions_path = _safe_path(
            root, questions_record.get("path"), "questions golden path", errors
        )
        _verify_digest(
            questions_path,
            questions_record.get("sha256"),
            "questions golden fixture",
            errors,
        )
        golden = (
            _load_json(questions_path, "questions golden fixture", errors)
            if questions_path is not None
            else None
        )
        runtime_graph = _load_runtime_graph(root, manifest, errors)
        if runtime_graph is not None:
            golden_counts = _validate_golden_questions(
                golden, manifest, runtime_graph, errors
            )

    verification_records = _supporting_records(manifest, "verification")
    if not verification_records:
        if manifest.get("$schema") == MANIFEST_SCHEMA:
            errors.append(
                "manifest must contain at least one hash-verified verification record"
            )
    for verification_index, verification_record in enumerate(verification_records):
        verification_label = f"verification record[{verification_index}]"
        verification_path = _safe_path(
            root,
            verification_record.get("path"),
            f"{verification_label} path",
            errors,
        )
        _verify_digest(
            verification_path,
            verification_record.get("sha256"),
            verification_label,
            errors,
        )
        verification = (
            _load_json(verification_path, verification_label, errors)
            if verification_path is not None
            else None
        )
        if isinstance(verification, dict):
            _verification_run_sha256(verification, verification_label, errors)
        checks = verification.get("checks") if isinstance(verification, dict) else None
        if not isinstance(checks, dict):
            errors.append(f"{verification_label} checks must be an object")
        else:
            if checks.get("competency_questions_total") != golden_counts["total"]:
                errors.append(
                    f"{verification_label} competency_questions_total does not equal "
                    "exact golden execution"
                )
            if checks.get("competency_questions_passed") != golden_counts["passed"]:
                errors.append(
                    f"{verification_label} competency_questions_passed does not equal "
                    "exact golden execution"
                )

    if mode == "published":
        receipt_record = _supporting_record(manifest, "publication-receipt")
        if receipt_record is None:
            errors.append(
                "a published manifest requires one publication-receipt artifact"
            )
        else:
            receipt_path = _safe_path(
                root, receipt_record.get("path"), "publication receipt path", errors
            )
            _verify_digest(
                receipt_path,
                receipt_record.get("sha256"),
                "publication receipt",
                errors,
            )
            if publication.get("receiptPath") != receipt_record.get("path"):
                errors.append("publication.receiptPath must match the receipt artifact")
            if publication.get("receiptSha256") != receipt_record.get("sha256"):
                errors.append(
                    "publication.receiptSha256 must match the receipt artifact"
                )
            receipt = (
                _load_json(receipt_path, "publication receipt", errors)
                if receipt_path is not None
                else None
            )
            if isinstance(receipt, dict):
                if (
                    receipt.get("$schema")
                    != "urn:ontology-appliance:schema:publication-receipt:1"
                ):
                    errors.append("publication receipt uses an unsupported schema")
                for receipt_key, manifest_key in (
                    ("bundleVersion", "version"),
                    ("tenantId", "tenantId"),
                    ("ontologyVersion", "ontologyVersion"),
                ):
                    if receipt.get(receipt_key) != manifest.get(manifest_key):
                        errors.append(
                            f"publication receipt {receipt_key} does not match the manifest"
                        )
                for receipt_key, publication_key in (
                    ("publisherSubject", "publisherSubject"),
                    ("authorizedAt", "authorizedAt"),
                    ("publishedAt", "publishedAt"),
                    ("releaseSha", "releaseSha"),
                    ("releaseId", "releaseId"),
                    ("sourceManifestSha256", "sourceManifestSha256"),
                    ("reviewLedgerSha256", "reviewLedgerSha256"),
                ):
                    if receipt.get(receipt_key) != publication.get(publication_key):
                        errors.append(
                            f"publication receipt {receipt_key} does not match the manifest"
                        )
        if (
            not isinstance(publication.get("publisherSubject"), str)
            or not publication.get("publisherSubject", "").strip()
        ):
            errors.append("published manifest requires publication.publisherSubject")
        if not isinstance(
            publication.get("publishedAt"), str
        ) or not UTC_SECOND.fullmatch(publication.get("publishedAt", "")):
            errors.append("published manifest requires a UTC publication.publishedAt")
        if not isinstance(
            publication.get("authorizedAt"), str
        ) or not UTC_SECOND.fullmatch(publication.get("authorizedAt", "")):
            errors.append("published manifest requires a UTC publication.authorizedAt")
        elif (
            isinstance(publication.get("publishedAt"), str)
            and UTC_SECOND.fullmatch(publication.get("publishedAt", ""))
            and publication["authorizedAt"] > publication["publishedAt"]
        ):
            errors.append("publication.authorizedAt cannot be later than publishedAt")
        if not isinstance(
            publication.get("releaseSha"), str
        ) or not RELEASE_SHA.fullmatch(publication.get("releaseSha", "")):
            errors.append("published manifest requires a 40-64 character releaseSha")
        if not isinstance(
            publication.get("sourceManifestSha256"), str
        ) or not SHA256.fullmatch(publication.get("sourceManifestSha256", "")):
            errors.append("published manifest requires sourceManifestSha256")
        if not isinstance(
            publication.get("releaseId"), str
        ) or not RELEASE_ID.fullmatch(publication.get("releaseId", "")):
            errors.append("published manifest requires a safe publication.releaseId")

    summary = {
        "bundleVersion": manifest.get("version"),
        "publicationState": publication.get("state"),
        "servingMode": publication.get("servingMode"),
        "isPublished": publication.get("isPublished"),
        "mappingCount": len(mappings),
        "mappingStates": dict(sorted(Counter(mappings.values()).items())),
        "competencyQuestions": golden_counts["total"],
        "passedCompetencyQuestions": golden_counts["passed"],
    }
    return errors, summary


def promote(
    manifest_path: Path,
    output_dir: Path,
    publisher_subject: str,
    release_sha: str,
    release_id: str,
    authorized_at: str,
    published_at: str,
    manifest_object: str,
) -> Path:
    errors, _summary = validate(manifest_path, "publish")
    if errors:
        raise ValueError("publication eligibility failed: " + "; ".join(errors))
    if not publisher_subject.strip():
        raise ValueError("publisher subject is required")
    if not RELEASE_SHA.fullmatch(release_sha):
        raise ValueError(
            "release SHA must contain 40-64 lowercase hexadecimal characters"
        )
    if not RELEASE_ID.fullmatch(release_id):
        raise ValueError("release ID must be a safe 1-160 character identifier")
    if not UTC_SECOND.fullmatch(authorized_at):
        raise ValueError("authorized-at must be a UTC timestamp with second precision")
    if not UTC_SECOND.fullmatch(published_at):
        raise ValueError("published-at must be a UTC timestamp with second precision")
    if authorized_at > published_at:
        raise ValueError("authorized-at cannot be later than published-at")
    if output_dir.exists():
        raise ValueError(f"promotion output already exists: {output_dir}")

    source_root = manifest_path.resolve().parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_manifest_object = (
        f"tenants/{manifest['tenantId']}/ontology/releases/"
        f"{manifest['version']}-{release_id}/manifest.json"
    )
    if manifest_object != expected_manifest_object:
        raise ValueError(
            f"manifest object must be the immutable tenant release path {expected_manifest_object}"
        )
    referenced: set[str] = set()
    for collection in ("artifacts", "supportingArtifacts"):
        for record in manifest.get(collection, []):
            if isinstance(record, dict) and isinstance(record.get("path"), str):
                referenced.add(record["path"])

    temporary_root = Path(
        tempfile.mkdtemp(prefix="oa-publication-", dir=output_dir.parent)
    )
    try:
        for relative_text in sorted(referenced):
            source = _safe_path(source_root, relative_text, "promotion source", [])
            if source is None or not source.is_file():
                raise ValueError(f"promotion source is missing: {relative_text}")
            target = temporary_root / relative_text
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        source_manifest_sha256 = _sha256(manifest_path)
        review_sha256 = manifest["publication"]["reviewLedgerSha256"]
        receipt = {
            "$schema": "urn:ontology-appliance:schema:publication-receipt:1",
            "bundleVersion": manifest["version"],
            "tenantId": manifest["tenantId"],
            "ontologyVersion": manifest["ontologyVersion"],
            "publisherSubject": publisher_subject,
            "authorizedAt": authorized_at,
            "publishedAt": published_at,
            "releaseSha": release_sha,
            "releaseId": release_id,
            "sourceManifestSha256": source_manifest_sha256,
            "reviewLedgerSha256": review_sha256,
        }
        receipt_path = temporary_root / "publication-receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        receipt_sha256 = _sha256(receipt_path)
        manifest["supportingArtifacts"].append(
            {
                "role": "publication-receipt",
                "path": "publication-receipt.json",
                "sha256": receipt_sha256,
                "mediaType": "application/json",
            }
        )
        manifest["publication"].update(
            {
                "state": "PUBLISHED",
                "servingMode": "ACTIVE",
                "isPublished": True,
                "publisherSubject": publisher_subject,
                "authorizedAt": authorized_at,
                "publishedAt": published_at,
                "releaseSha": release_sha,
                "releaseId": release_id,
                "sourceManifestSha256": source_manifest_sha256,
                "receiptPath": "publication-receipt.json",
                "receiptSha256": receipt_sha256,
            }
        )
        promoted_manifest = temporary_root / "manifest.json"
        promoted_manifest.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        published_errors, _published_summary = validate(promoted_manifest, "published")
        if published_errors:
            raise ValueError(
                "promoted bundle is invalid: " + "; ".join(published_errors)
            )
        temporary_root.replace(output_dir)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    return output_dir / "manifest.json"


def create_active_pointer(
    manifest_path: Path,
    output_path: Path,
    manifest_object: str,
    activated_at: str,
) -> Path:
    errors, _summary = validate(manifest_path, "published")
    if errors:
        raise ValueError("published bundle validation failed: " + "; ".join(errors))
    if not UTC_SECOND.fullmatch(activated_at):
        raise ValueError("activated-at must be a UTC timestamp with second precision")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    publication = manifest["publication"]
    expected_manifest_object = (
        f"tenants/{manifest['tenantId']}/ontology/releases/"
        f"{manifest['version']}-{publication['releaseId']}/manifest.json"
    )
    if manifest_object != expected_manifest_object:
        raise ValueError(
            f"manifest object must be the immutable tenant release path {expected_manifest_object}"
        )
    if activated_at < publication["authorizedAt"]:
        raise ValueError("activated-at cannot be earlier than authorized-at")
    if output_path.exists():
        raise ValueError(f"active pointer output already exists: {output_path}")
    pointer = {
        "$schema": "urn:ontology-appliance:schema:active-pointer:1",
        "operation": "PUBLISH",
        "tenantId": manifest["tenantId"],
        "bundleVersion": manifest["version"],
        "ontologyVersion": manifest["ontologyVersion"],
        "manifestObject": manifest_object,
        "manifestSha256": _sha256(manifest_path),
        "publicationReceiptSha256": publication["receiptSha256"],
        "publisherSubject": publication["publisherSubject"],
        "authorizedAt": publication["authorizedAt"],
        "activatedAt": activated_at,
        "releaseSha": publication["releaseSha"],
        "releaseId": publication["releaseId"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    return output_path


def _write_fixture(root: Path, *, publishable: bool) -> Path:
    mapping_status = "APPROVED" if publishable else "HUMAN_REVIEW"
    mappings = (
        "@prefix oa: <urn:ontology-appliance:vocab:> .\n"
        "@prefix ex: <urn:test:> .\n"
        f'ex:m1 a oa:MappingProposal ; oa:mappingId "m1" ; '
        f'oa:proposalStatus "{mapping_status}" .\n'
    )
    mapping_path = root / "mappings.ttl"
    mapping_path.write_text(mappings, encoding="utf-8")
    proposal_path = root / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "proposal_id": "m1",
                "tenant_id": "demo-bank",
                "evidence": [],
                "counterevidence": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence_index_path = root / "evidence-index.json"
    evidence_index_path.write_text(
        json.dumps(
            {
                "$schema": "urn:ontology-appliance:schema:evidence-index:1",
                "proposalId": "m1",
                "tenantId": "demo-bank",
                "evidence": [],
                "counterevidence": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    verification_path = root / "verification.json"
    verification = {
        "verification_run_id": "verification-m1-1",
        "proposal_id": "m1",
        "tenant_id": "demo-bank",
        "frozen_proposal_sha256": _sha256(proposal_path),
        "frozen_evidence_index_sha256": _sha256(evidence_index_path),
        "evidence": [],
        "counterevidence": [],
        "checks": {
            "competency_questions_total": 0,
            "competency_questions_passed": 0,
        },
    }
    verification["verification_run_sha256"] = _canonical_sha256(verification)
    verification_path.write_text(
        json.dumps(verification, indent=2) + "\n", encoding="utf-8"
    )
    decision: dict[str, Any] = {"mappingId": "m1", "status": mapping_status}
    if publishable:
        decision.update(
            {
                "decisionId": "decision-m1-1",
                "verificationRunId": "verification-m1-1",
                "verificationRunSha256": verification[
                    "verification_run_sha256"
                ],
                "sourceReceiptSha256": "b" * 64,
                "generatorSubject": "service:generator",
                "verifierSubject": "service:verifier",
                "reviewer": {
                    "subject": "user:steward-1",
                    "kind": "HUMAN",
                    "role": "steward",
                    "reviewedAt": "2026-07-22T14:00:00Z",
                },
                "reviewEvidence": {
                    "proposalSha256": _sha256(proposal_path),
                    "verificationSha256": _sha256(verification_path),
                    "evidenceIndexSha256": _sha256(evidence_index_path),
                },
            }
        )
    ledger = {
        "$schema": "urn:ontology-appliance:schema:publication-review:1",
        "bundleVersion": "fixture-1",
        "tenantId": "demo-bank",
        "ontologyVersion": "fixture",
        "state": "PUBLISHABLE" if publishable else "CANDIDATE",
        "coverage": "FULL" if publishable else "PARTIAL",
        "mappingPopulation": {
            "total": 1,
            "approved": int(publishable),
            "published": 0,
            "humanReview": int(not publishable),
        },
        "decisions": [decision],
    }
    if publishable:
        ledger["exportProvenance"] = {
            "sourceSchema": REVIEW_EXPORT_SCHEMA,
            "normalizationVersion": REVIEW_EXPORT_NORMALIZATION,
            "sourceExportSha256": "a" * 64,
            "digestAlgorithm": "SHA-256",
            "collectionPath": "tenants/demo-bank/reviewReceipts",
            "exportedAt": "2026-07-22T13:59:00Z",
            "trustBoundary": REVIEW_EXPORT_TRUST_BOUNDARY,
        }
    ledger_path = root / "publication-review.json"
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "version": "fixture-1",
        "tenantId": "demo-bank",
        "ontologyVersion": "fixture",
        "publication": {
            "state": "PUBLISHABLE" if publishable else "CANDIDATE",
            "servingMode": "PUBLISHER_ONLY" if publishable else "DEMO_ONLY",
            "isPublished": False,
            "reviewLedgerPath": "publication-review.json",
            "reviewLedgerSha256": _sha256(ledger_path),
        },
        "artifacts": [
            {
                "path": "mappings.ttl",
                "sha256": _sha256(mapping_path),
                "format": "turtle",
                "kind": "graph",
            }
        ],
        "supportingArtifacts": [
            {
                "role": "publication-review",
                "path": "publication-review.json",
                "sha256": _sha256(ledger_path),
                "mediaType": "application/json",
            },
            {
                "role": "proposal",
                "proposalId": "m1",
                "path": "proposal.json",
                "sha256": _sha256(proposal_path),
                "mediaType": "application/json",
            },
            {
                "role": "verification",
                "proposalId": "m1",
                "path": "verification.json",
                "sha256": _sha256(verification_path),
                "mediaType": "application/json",
            },
            {
                "role": "evidence-index",
                "proposalId": "m1",
                "path": "evidence-index.json",
                "sha256": _sha256(evidence_index_path),
                "mediaType": "application/json",
            },
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="oa-publication-self-test-") as temporary:
        root = Path(temporary)
        candidate_root = root / "candidate"
        candidate_root.mkdir()
        candidate = _write_fixture(candidate_root, publishable=False)
        candidate_errors, _ = validate(candidate, "candidate")
        assert not candidate_errors, candidate_errors
        publish_errors, _ = validate(candidate, "publish")
        assert any("not APPROVED/PUBLISHED" in error for error in publish_errors)

        eligible_root = root / "eligible"
        eligible_root.mkdir()
        eligible = _write_fixture(eligible_root, publishable=True)
        eligible_errors, _ = validate(eligible, "publish")
        assert not eligible_errors, eligible_errors

        broken_ledger_path = eligible_root / "publication-review.json"
        original_ledger = json.loads(broken_ledger_path.read_text(encoding="utf-8"))
        original_manifest = json.loads(eligible.read_text(encoding="utf-8"))
        invented_hash_ledger = json.loads(json.dumps(original_ledger))
        invented_hash_ledger["decisions"][0]["reviewEvidence"][
            "proposalSha256"
        ] = "a" * 64
        broken_ledger_path.write_text(
            json.dumps(invented_hash_ledger, indent=2) + "\n", encoding="utf-8"
        )
        invented_hash_manifest = json.loads(json.dumps(original_manifest))
        invented_ledger_hash = _sha256(broken_ledger_path)
        invented_hash_manifest["publication"][
            "reviewLedgerSha256"
        ] = invented_ledger_hash
        invented_hash_manifest["supportingArtifacts"][0][
            "sha256"
        ] = invented_ledger_hash
        eligible.write_text(
            json.dumps(invented_hash_manifest, indent=2) + "\n", encoding="utf-8"
        )
        invented_hash_errors, _ = validate(eligible, "publish")
        assert any(
            "does not match the manifest proposal digest" in error
            for error in invented_hash_errors
        )

        broken_ledger_path.write_text(
            json.dumps(original_ledger, indent=2) + "\n", encoding="utf-8"
        )
        eligible.write_text(
            json.dumps(original_manifest, indent=2) + "\n", encoding="utf-8"
        )
        broken_ledger = json.loads(broken_ledger_path.read_text(encoding="utf-8"))
        broken_ledger["decisions"][0]["reviewer"]["subject"] = "service:generator"
        broken_ledger_path.write_text(
            json.dumps(broken_ledger, indent=2) + "\n", encoding="utf-8"
        )
        broken_manifest = json.loads(eligible.read_text(encoding="utf-8"))
        broken_hash = _sha256(broken_ledger_path)
        broken_manifest["publication"]["reviewLedgerSha256"] = broken_hash
        broken_manifest["supportingArtifacts"][0]["sha256"] = broken_hash
        eligible.write_text(
            json.dumps(broken_manifest, indent=2) + "\n", encoding="utf-8"
        )
        independence_errors, _ = validate(eligible, "publish")
        assert any(
            "independent from the generator" in error for error in independence_errors
        )

        receipt_root = root / "missing-receipt-digest"
        receipt_root.mkdir()
        receipt_manifest_path = _write_fixture(receipt_root, publishable=True)
        receipt_ledger_path = receipt_root / "publication-review.json"
        receipt_ledger = json.loads(receipt_ledger_path.read_text(encoding="utf-8"))
        del receipt_ledger["decisions"][0]["sourceReceiptSha256"]
        receipt_ledger_path.write_text(
            json.dumps(receipt_ledger, indent=2) + "\n", encoding="utf-8"
        )
        receipt_manifest = json.loads(
            receipt_manifest_path.read_text(encoding="utf-8")
        )
        receipt_ledger_sha = _sha256(receipt_ledger_path)
        receipt_manifest["publication"]["reviewLedgerSha256"] = receipt_ledger_sha
        receipt_manifest["supportingArtifacts"][0]["sha256"] = receipt_ledger_sha
        receipt_manifest_path.write_text(
            json.dumps(receipt_manifest, indent=2) + "\n", encoding="utf-8"
        )
        receipt_errors, _ = validate(receipt_manifest_path, "publish")
        assert any("sourceReceiptSha256 is required" in error for error in receipt_errors)

        provenance_root = root / "bad-export-provenance"
        provenance_root.mkdir()
        provenance_manifest_path = _write_fixture(provenance_root, publishable=True)
        provenance_ledger_path = provenance_root / "publication-review.json"
        provenance_ledger = json.loads(
            provenance_ledger_path.read_text(encoding="utf-8")
        )
        provenance_ledger["exportProvenance"]["trustBoundary"] = "AUTHENTICATED"
        provenance_ledger_path.write_text(
            json.dumps(provenance_ledger, indent=2) + "\n", encoding="utf-8"
        )
        provenance_manifest = json.loads(
            provenance_manifest_path.read_text(encoding="utf-8")
        )
        provenance_ledger_sha = _sha256(provenance_ledger_path)
        provenance_manifest["publication"]["reviewLedgerSha256"] = (
            provenance_ledger_sha
        )
        provenance_manifest["supportingArtifacts"][0]["sha256"] = (
            provenance_ledger_sha
        )
        provenance_manifest_path.write_text(
            json.dumps(provenance_manifest, indent=2) + "\n", encoding="utf-8"
        )
        provenance_errors, _ = validate(provenance_manifest_path, "publish")
        assert any("trustBoundary is invalid" in error for error in provenance_errors)

        run_root = root / "tampered-run"
        run_root.mkdir()
        run_manifest_path = _write_fixture(run_root, publishable=True)
        run_verification_path = run_root / "verification.json"
        run_verification = json.loads(
            run_verification_path.read_text(encoding="utf-8")
        )
        run_verification["tampered"] = True
        run_verification_path.write_text(
            json.dumps(run_verification, indent=2) + "\n", encoding="utf-8"
        )
        run_ledger_path = run_root / "publication-review.json"
        run_ledger = json.loads(run_ledger_path.read_text(encoding="utf-8"))
        run_ledger["decisions"][0]["reviewEvidence"]["verificationSha256"] = (
            _sha256(run_verification_path)
        )
        run_ledger_path.write_text(
            json.dumps(run_ledger, indent=2) + "\n", encoding="utf-8"
        )
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        run_manifest["supportingArtifacts"][2]["sha256"] = _sha256(
            run_verification_path
        )
        run_ledger_sha = _sha256(run_ledger_path)
        run_manifest["publication"]["reviewLedgerSha256"] = run_ledger_sha
        run_manifest["supportingArtifacts"][0]["sha256"] = run_ledger_sha
        run_manifest_path.write_text(
            json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8"
        )
        run_errors, _ = validate(run_manifest_path, "publish")
        assert any(
            "does not match canonical run content" in error for error in run_errors
        )

        promotable_root = root / "promotable"
        promotable_root.mkdir()
        promotable = _write_fixture(promotable_root, publishable=True)
        promoted = root / "published"
        promoted_manifest = promote(
            promotable,
            promoted,
            "serviceAccount:publisher@example.invalid",
            "d" * 40,
            "d" * 40 + "-123-1",
            "2026-07-22T14:04:00Z",
            "2026-07-22T14:05:00Z",
            "tenants/demo-bank/ontology/releases/fixture-1-"
            + "d" * 40
            + "-123-1"
            + "/manifest.json",
        )
        promoted_errors, _ = validate(promoted_manifest, "published")
        assert not promoted_errors, promoted_errors
        pointer_path = create_active_pointer(
            promoted_manifest,
            promoted / "active.json",
            "tenants/demo-bank/ontology/releases/fixture-1-"
            + "d" * 40
            + "-123-1/manifest.json",
            "2026-07-22T14:06:00Z",
        )
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        assert pointer["manifestSha256"] == _sha256(promoted_manifest)
        assert pointer["publisherSubject"] == "serviceAccount:publisher@example.invalid"
        assert pointer["operation"] == "PUBLISH"
        assert pointer["activatedAt"] != pointer["authorizedAt"]

        golden_graph = Graph()
        golden_subject = URIRef("urn:test:subject")
        golden_predicate = URIRef("urn:test:value")
        golden_evidence = URIRef("urn:test:evidence")
        golden_graph.add((golden_subject, golden_predicate, Literal("expected")))
        golden_graph.add((golden_evidence, RDF.type, OA.EvidenceArtifact))
        golden_graph.add((golden_evidence, OA.sourceId, Literal("source")))
        golden_graph.add(
            (golden_evidence, OA.snapshotId, Literal(f"source@sha256:{'a' * 64}"))
        )
        golden_graph.add((golden_evidence, OA.locator, Literal("fixture#record=1")))
        golden_graph.add((golden_evidence, OA.contentSha256, Literal("a" * 64)))
        golden_query = (
            "SELECT ?value WHERE { <urn:test:subject> <urn:test:value> ?value } "
            "ORDER BY ?value"
        )
        golden_coordinate = {
            "evidenceIri": str(golden_evidence),
            "sourceId": "source",
            "snapshotId": f"source@sha256:{'a' * 64}",
            "locator": "fixture#record=1",
            "contentSha256": "a" * 64,
        }
        golden_manifest = {
            "version": "fixture-1",
            "ontologyVersion": "fixture",
            "tenantId": "demo-bank",
            "stats": {"competencyQuestions": 5, "passedCompetencyQuestions": 5},
        }
        golden_fixture = {
            "$schema": GOLDEN_SCHEMA,
            "bundleVersion": "fixture-1",
            "ontologyVersion": "fixture",
            "tenantId": "demo-bank",
            "normalization": {"comparison": "Deep JSON equality"},
            "questions": [
                {
                    "id": f"CQ-{number:03d}",
                    "queryVersion": "1.0.0",
                    "sparql": golden_query,
                    "evidenceIris": [str(golden_evidence)],
                    "expectedOutcome": {
                        "rows": [{"value": "expected"}],
                        "evidence": [golden_coordinate],
                        "bundleVersion": "fixture-1",
                        "ontologyVersion": "fixture",
                        "traceId": f"golden-cq-{number:03d}-fixture",
                    },
                    "status": "PASS",
                }
                for number in range(1, 6)
            ],
            "summary": {"total": 5, "passed": 5},
        }
        golden_errors: list[str] = []
        _validate_golden_questions(
            golden_fixture, golden_manifest, golden_graph, golden_errors
        )
        assert not golden_errors, golden_errors
        tampered_golden = json.loads(json.dumps(golden_fixture))
        tampered_golden["questions"][0]["expectedOutcome"]["rows"] = [
            {"value": "tampered"}
        ]
        tamper_errors: list[str] = []
        _validate_golden_questions(
            tampered_golden, golden_manifest, golden_graph, tamper_errors
        )
        assert any("exact normalized golden result" in error for error in tamper_errors)
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=ROOT / "semantic/artifacts/manifest.json",
    )
    parser.add_argument("--mode", choices=tuple(MODE_METADATA), default="candidate")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--promote-output", type=Path)
    parser.add_argument("--publisher-subject")
    parser.add_argument("--release-sha")
    parser.add_argument("--release-id")
    parser.add_argument("--authorized-at")
    parser.add_argument("--published-at")
    parser.add_argument("--manifest-object")
    parser.add_argument("--create-pointer-output", type=Path)
    parser.add_argument("--activated-at")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    if args.promote_output is not None:
        if args.mode != "publish":
            parser.error("--promote-output requires --mode publish")
        if args.create_pointer_output is not None:
            parser.error(
                "--promote-output and --create-pointer-output are separate operations"
            )
        try:
            promoted_manifest = promote(
                args.manifest,
                args.promote_output.resolve(),
                args.publisher_subject or "",
                args.release_sha or "",
                args.release_id or "",
                args.authorized_at or "",
                args.published_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                args.manifest_object or "",
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(
                json.dumps(
                    {
                        "valid": False,
                        "publicationEligible": False,
                        "errors": [str(exc)],
                    },
                    indent=2,
                )
            )
            return 1
        print(
            json.dumps(
                {
                    "valid": True,
                    "publicationEligible": True,
                    "promotedManifest": str(promoted_manifest),
                },
                indent=2,
            )
        )
        return 0

    if args.create_pointer_output is not None:
        if args.mode != "published":
            parser.error("--create-pointer-output requires --mode published")
        try:
            pointer_path = create_active_pointer(
                args.manifest,
                args.create_pointer_output.resolve(),
                args.manifest_object or "",
                args.activated_at or "",
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
            return 1
        print(json.dumps({"valid": True, "activePointer": str(pointer_path)}, indent=2))
        return 0

    errors, summary = validate(args.manifest, args.mode)
    result = {
        "valid": not errors,
        "publicationEligible": not errors and args.mode in {"publish", "published"},
        "mode": args.mode,
        **summary,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
