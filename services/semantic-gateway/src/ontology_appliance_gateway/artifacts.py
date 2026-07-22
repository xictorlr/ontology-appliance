"""Verified RDF artifact loading with in-memory and on-disk fallback."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from owlrl import DeductiveClosure, OWLRL_Semantics
from pyshacl import validate as shacl_validate
from rdflib import Dataset, Graph, Namespace, RDF, URIRef

from .config import Settings
from .models import EvidenceReference

DATA_GRAPH = URIRef("urn:ontology-appliance:cache:data")
SHAPES_GRAPH = URIRef("urn:ontology-appliance:cache:shapes")
OA = Namespace("urn:ontology-appliance:vocab:")


class ArtifactLoadError(RuntimeError):
    """A candidate artifact set could not be trusted or parsed."""


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    name: str
    sha256: str
    rdf_format: str
    kind: str


@dataclass(frozen=True, slots=True)
class EvidenceCoordinate:
    """Immutable source coordinate used to prove a golden-query answer."""

    evidence_iri: str
    source_id: str
    snapshot_id: str
    locator: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    graph: Graph
    shapes: Graph
    version: str
    records: tuple[ArtifactRecord, ...]
    loaded_at: datetime
    publication_state: str
    serving_mode: str
    is_published: bool
    status: str = "READY"
    diagnostic: str | None = None

    def evidence(self, *, locator: str | None = None) -> list[EvidenceReference]:
        return [
            EvidenceReference(
                artifact=record.name,
                sha256=record.sha256,
                locator=locator,
            )
            for record in self.records
        ]

    def evidence_coordinates(
        self, evidence_iris: tuple[str, ...] | list[str]
    ) -> list[EvidenceCoordinate]:
        """Resolve exact source provenance for a governed result, preserving order."""

        if len(set(evidence_iris)) != len(evidence_iris):
            raise ArtifactLoadError("Evidence coordinates must not contain duplicate IRIs.")
        coordinates: list[EvidenceCoordinate] = []
        fields = {
            "source_id": OA.sourceId,
            "snapshot_id": OA.snapshotId,
            "locator": OA.locator,
            "content_sha256": OA.contentSha256,
        }
        for evidence_iri in evidence_iris:
            evidence = URIRef(evidence_iri)
            if (evidence, RDF.type, OA.EvidenceArtifact) not in self.graph:
                raise ArtifactLoadError(
                    f"Golden-query evidence is not an oa:EvidenceArtifact: {evidence_iri}"
                )
            values: dict[str, str] = {}
            for name, predicate in fields.items():
                objects = {str(value) for value in self.graph.objects(evidence, predicate)}
                if len(objects) != 1:
                    raise ArtifactLoadError(
                        f"Golden-query evidence {evidence_iri} requires exactly one oa:{predicate.split(':')[-1]}."
                    )
                values[name] = next(iter(objects))
            if not re.fullmatch(r"[0-9a-f]{64}", values["content_sha256"]):
                raise ArtifactLoadError(
                    f"Golden-query evidence {evidence_iri} has an invalid content SHA-256."
                )
            coordinates.append(
                EvidenceCoordinate(
                    evidence_iri=evidence_iri,
                    source_id=values["source_id"],
                    snapshot_id=values["snapshot_id"],
                    locator=values["locator"],
                    content_sha256=values["content_sha256"],
                )
            )
        return coordinates


def clone_graph(source: Graph) -> Graph:
    target = Graph()
    for prefix, namespace in source.namespaces():
        target.bind(prefix, namespace)
    for triple in source:
        target.add(triple)
    return target


class ArtifactStore:
    """Atomically swaps the active graph only after hash and SHACL checks."""

    def __init__(self, settings: Settings, *, storage_client: Any | None = None) -> None:
        self.settings = settings
        self._storage_client_override = storage_client
        self._lock = threading.RLock()
        self._active: ArtifactSnapshot | None = None

    @property
    def snapshot(self) -> ArtifactSnapshot:
        with self._lock:
            if self._active is None:
                raise ArtifactLoadError("No valid ontology snapshot is active.")
            return self._active

    def initialize(self) -> ArtifactSnapshot:
        try:
            return self.reload()
        except ArtifactLoadError as candidate_error:
            try:
                cached = self._restore_cache()
            except ArtifactLoadError as cache_error:
                raise ArtifactLoadError(
                    f"Candidate load failed ({candidate_error}); no last-valid snapshot is available ({cache_error})."
                ) from candidate_error
            cached = replace(
                cached,
                status="DEGRADED_LAST_VALID",
                diagnostic=str(candidate_error),
            )
            with self._lock:
                self._active = cached
            return cached

    def reload(self) -> ArtifactSnapshot:
        """Load a candidate; retain the previous snapshot if verification fails."""

        try:
            candidate = (
                self._load_remote_candidate()
                if self.settings.artifact_bucket
                else self._load_candidate()
            )
        except Exception as exc:
            error = exc if isinstance(exc, ArtifactLoadError) else ArtifactLoadError(str(exc))
            with self._lock:
                if self._active is not None:
                    self._active = replace(
                        self._active,
                        status="DEGRADED_LAST_VALID",
                        diagnostic=str(error),
                    )
                    return self._active
            if self.settings.artifact_bucket:
                try:
                    candidate = replace(
                        self._restore_cache(),
                        status="DEGRADED_LAST_VALID",
                        diagnostic=str(error),
                    )
                except ArtifactLoadError:
                    candidate = None
                if candidate is not None:
                    with self._lock:
                        self._active = candidate
                    return candidate
                if not self.settings.is_development:
                    raise ArtifactLoadError(
                        f"Remote published artifact load failed ({error}); no verified published "
                        "last-valid snapshot is available. Bundled demo candidates are disabled "
                        "in production."
                    ) from error
                try:
                    candidate = replace(
                        self._load_candidate(),
                        status="DEGRADED_BUNDLED_FALLBACK",
                        diagnostic=str(error),
                    )
                except Exception as bundled_exc:
                    raise ArtifactLoadError(
                        f"Remote artifact load failed ({error}); bundled artifact load also failed "
                        f"({bundled_exc})."
                    ) from error
            else:
                raise error

        with self._lock:
            self._active = candidate
        self._persist_cache(candidate)
        return candidate

    def _load_candidate(self, artifact_dir: Path | None = None) -> ArtifactSnapshot:
        artifact_root = (artifact_dir or self.settings.artifact_dir).resolve()
        manifest_path = artifact_root / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactLoadError(f"Cannot read artifact manifest: {exc}") from exc

        version = str(manifest.get("version", "")).strip()
        manifest_tenant = str(manifest.get("tenantId", "")).strip()
        entries = manifest.get("artifacts")
        if not version or not manifest_tenant or not isinstance(entries, list) or not entries:
            raise ArtifactLoadError(
                "Manifest requires a version, tenantId, and a non-empty artifacts array."
            )
        if manifest_tenant != self.settings.dev_tenant_id:
            raise ArtifactLoadError(
                f"Manifest tenant '{manifest_tenant}' does not match configured tenant "
                f"'{self.settings.dev_tenant_id}'."
            )
        publication_state, serving_mode, is_published = self._parse_publication(manifest)
        if (
            not self.settings.is_development
            and not is_published
            and not (
                self.settings.allow_demo_candidate
                and self.settings.artifact_bucket is None
                and serving_mode == "DEMO_ONLY"
            )
        ):
            raise ArtifactLoadError(
                "Production refuses non-published bundled or remote candidate artifacts."
            )

        graph = Graph()
        shapes = Graph()
        records: list[ArtifactRecord] = []
        for raw in entries:
            record = self._parse_record(raw)
            artifact_path = (artifact_root / record.name).resolve()
            if not artifact_path.is_relative_to(artifact_root):
                raise ArtifactLoadError(f"Artifact path escapes its root: {record.name}")
            try:
                content = artifact_path.read_bytes()
            except OSError as exc:
                raise ArtifactLoadError(f"Cannot read artifact {record.name}: {exc}") from exc
            actual_hash = hashlib.sha256(content).hexdigest()
            if actual_hash != record.sha256:
                raise ArtifactLoadError(
                    f"SHA-256 mismatch for {record.name}: expected {record.sha256}, got {actual_hash}."
                )
            target = shapes if record.kind == "shapes" else graph
            try:
                self._parse_rdf(content, record.rdf_format, target)
            except Exception as exc:
                raise ArtifactLoadError(f"Invalid RDF in {record.name}: {exc}") from exc
            records.append(record)

        if not graph:
            raise ArtifactLoadError("The candidate data graph is empty.")
        if not shapes:
            raise ArtifactLoadError("The candidate SHACL graph is empty.")

        if bool(manifest.get("materializeOwlRl", True)):
            DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False).expand(graph)

        conforms, _report_graph, report_text = shacl_validate(
            data_graph=graph,
            shacl_graph=shapes,
            inference="rdfs",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
        )
        if not conforms:
            compact_report = " ".join(str(report_text).split())[:1_000]
            raise ArtifactLoadError(f"SHACL validation rejected candidate: {compact_report}")

        return ArtifactSnapshot(
            graph=graph,
            shapes=shapes,
            version=version,
            records=tuple(records),
            loaded_at=datetime.now(UTC),
            publication_state=publication_state,
            serving_mode=serving_mode,
            is_published=is_published,
        )

    def _load_remote_candidate(self) -> ArtifactSnapshot:
        bucket_name = (self.settings.artifact_bucket or "").strip()
        if not bucket_name:
            raise ArtifactLoadError("Remote artifact bucket name is empty.")
        try:
            pointer_name = self.settings.artifact_pointer.format(
                tenant_id=self.settings.dev_tenant_id
            ).strip("/")
        except (KeyError, ValueError) as exc:
            raise ArtifactLoadError(f"Invalid active pointer template: {exc}") from exc
        expected_pointer = f"tenants/{self.settings.dev_tenant_id}/ontology/active.json"
        if pointer_name != expected_pointer:
            raise ArtifactLoadError(
                f"Active pointer must be the stable tenant path '{expected_pointer}'."
            )
        if not self.settings.is_development and self.settings.active_pointer_generation is None:
            raise ArtifactLoadError(
                "Production remote artifacts require OA_ACTIVE_POINTER_GENERATION so cold "
                "starts remain pinned to a Publisher-approved pointer generation."
            )

        client = self._storage_client_override or self._google_storage_client()
        try:
            bucket = client.bucket(bucket_name)
            pointer_blob = bucket.blob(
                pointer_name,
                generation=self.settings.active_pointer_generation,
            )
            pointer_bytes = self._download_blob(pointer_blob, maximum_size=100_000)
            pointer = json.loads(pointer_bytes)
            manifest_object = self._pointer_manifest_object(
                pointer,
                tenant_id=self.settings.dev_tenant_id,
            )
            manifest_blob = bucket.blob(manifest_object)
            manifest_bytes = self._download_blob(manifest_blob, maximum_size=1_000_000)
            manifest = json.loads(manifest_bytes)
            self._verify_active_pointer(pointer, manifest, manifest_bytes)
            if pointer.get("operation") == "ROLLBACK":
                audit_object = pointer["rollbackAuditObject"]
                audit_bytes = self._download_blob(bucket.blob(audit_object), maximum_size=100_000)
                self._verify_rollback_audit(pointer, json.loads(audit_bytes), audit_bytes)
            raw_entries = manifest.get("artifacts")
            if not isinstance(raw_entries, list) or not raw_entries:
                raise ArtifactLoadError("Remote manifest has no artifacts array.")
            records = [self._parse_record(item) for item in raw_entries]
            release_prefix = manifest_object.rsplit("/", 1)[0]
            receipt_path, receipt_digest = self._publication_receipt_record(manifest)
            receipt_blob = bucket.blob(f"{release_prefix}/{receipt_path}")
            receipt_bytes = self._download_blob(receipt_blob, maximum_size=100_000)
            if hashlib.sha256(receipt_bytes).hexdigest() != receipt_digest:
                raise ArtifactLoadError(
                    "Publication receipt SHA-256 does not match the published manifest."
                )
            self._verify_publication_receipt(json.loads(receipt_bytes), manifest)

            self.settings.last_valid_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="oa-remote-artifacts-",
                dir=self.settings.last_valid_path.parent,
            ) as temporary_dir:
                target_root = Path(temporary_dir).resolve()
                (target_root / "manifest.json").write_bytes(manifest_bytes)
                for record in records:
                    target_path = (target_root / record.name).resolve()
                    if not target_path.is_relative_to(target_root):
                        raise ArtifactLoadError(
                            f"Remote artifact path escapes snapshot root: {record.name}"
                        )
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    blob = bucket.blob(f"{release_prefix}/{record.name}")
                    target_path.write_bytes(self._download_blob(blob, maximum_size=25_000_000))
                candidate = self._load_candidate(target_root)
                if not candidate.is_published:
                    raise ArtifactLoadError(
                        "The active pointer resolved to a non-published semantic bundle."
                    )
        except ArtifactLoadError:
            raise
        except Exception as exc:
            raise ArtifactLoadError(
                f"Cannot resolve gs://{bucket_name}/{pointer_name}: {exc}"
            ) from exc
        return replace(
            candidate,
            diagnostic=(
                f"Resolved gs://{bucket_name}/{pointer_name} to "
                f"gs://{bucket_name}/{manifest_object}"
                + (
                    f" from pinned pointer generation {self.settings.active_pointer_generation}"
                    if self.settings.active_pointer_generation is not None
                    else ""
                )
            ),
        )

    @staticmethod
    def _pointer_manifest_object(pointer: Any, *, tenant_id: str) -> str:
        if not isinstance(pointer, dict):
            raise ArtifactLoadError("Active pointer must be a JSON object.")
        if pointer.get("$schema") != "urn:ontology-appliance:schema:active-pointer:1":
            raise ArtifactLoadError("Active pointer uses an unsupported schema.")
        if pointer.get("tenantId") != tenant_id:
            raise ArtifactLoadError("Active pointer tenant does not match the configured tenant.")
        manifest_object = pointer.get("manifestObject")
        if not isinstance(manifest_object, str):
            raise ArtifactLoadError("Active pointer requires manifestObject.")
        expected_prefix = f"tenants/{tenant_id}/ontology/releases/"
        if (
            not manifest_object.startswith(expected_prefix)
            or not manifest_object.endswith("/manifest.json")
            or any(part in {"", ".", ".."} for part in manifest_object.split("/"))
        ):
            raise ArtifactLoadError(
                "Active pointer manifestObject must name an immutable tenant release manifest."
            )
        return manifest_object

    @staticmethod
    def _verify_active_pointer(
        pointer: dict[str, Any],
        manifest: Any,
        manifest_bytes: bytes,
    ) -> None:
        if not isinstance(manifest, dict):
            raise ArtifactLoadError("Published manifest must be a JSON object.")
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        if pointer.get("manifestSha256") != manifest_digest:
            raise ArtifactLoadError("Active pointer manifestSha256 does not match manifest bytes.")
        publication = manifest.get("publication")
        if not isinstance(publication, dict):
            raise ArtifactLoadError("Published manifest lacks publication metadata.")
        checks = {
            "bundleVersion": manifest.get("version"),
            "ontologyVersion": manifest.get("ontologyVersion"),
            "publisherSubject": publication.get("publisherSubject"),
            "releaseSha": publication.get("releaseSha"),
            "releaseId": publication.get("releaseId"),
            "publicationReceiptSha256": publication.get("receiptSha256"),
        }
        for field, expected in checks.items():
            if pointer.get(field) != expected:
                raise ArtifactLoadError(
                    f"Active pointer {field} does not match the published manifest."
                )
        operation = pointer.get("operation")
        if operation not in {"PUBLISH", "ROLLBACK"}:
            raise ArtifactLoadError("Active pointer operation must be PUBLISH or ROLLBACK.")
        for field in ("authorizedAt", "activatedAt"):
            value = pointer.get(field)
            if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
            ):
                raise ArtifactLoadError(f"Active pointer requires UTC {field}.")
        if pointer["authorizedAt"] > pointer["activatedAt"]:
            raise ArtifactLoadError("Active pointer authorization cannot follow activation.")
        if operation == "PUBLISH" and pointer["authorizedAt"] != publication.get("authorizedAt"):
            raise ArtifactLoadError(
                "Published pointer authorization does not match the publication receipt."
            )
        if operation == "ROLLBACK":
            for field in (
                "replacesGeneration",
                "previousManifestObject",
                "previousManifestSha256",
                "rollbackAuthorizedBy",
                "rollbackAuditObject",
                "rollbackAuditSha256",
            ):
                if not isinstance(pointer.get(field), str) or not pointer[field].strip():
                    raise ArtifactLoadError(f"Rollback pointer requires {field}.")
            if not pointer["replacesGeneration"].isdigit():
                raise ArtifactLoadError("Rollback replacesGeneration must be numeric.")
            if pointer["rollbackAuthorizedBy"] != pointer.get("publisherSubject"):
                raise ArtifactLoadError("Rollback must be authorized by the configured Publisher.")
            if not re.fullmatch(r"[0-9a-f]{64}", pointer["previousManifestSha256"]):
                raise ArtifactLoadError("Rollback previousManifestSha256 is invalid.")
            if not re.fullmatch(r"[0-9a-f]{64}", pointer["rollbackAuditSha256"]):
                raise ArtifactLoadError("Rollback rollbackAuditSha256 is invalid.")
            expected_audit_prefix = f"tenants/{pointer['tenantId']}/ontology/rollbacks/"
            audit_object = pointer["rollbackAuditObject"]
            if (
                not audit_object.startswith(expected_audit_prefix)
                or not audit_object.endswith("/rollback-audit.json")
                or any(part in {"", ".", ".."} for part in audit_object.split("/"))
            ):
                raise ArtifactLoadError("Rollback audit object path is unsafe.")

    @staticmethod
    def _verify_rollback_audit(pointer: dict[str, Any], audit: Any, audit_bytes: bytes) -> None:
        if hashlib.sha256(audit_bytes).hexdigest() != pointer["rollbackAuditSha256"]:
            raise ArtifactLoadError("Rollback audit SHA-256 does not match pointer metadata.")
        if (
            not isinstance(audit, dict)
            or audit.get("$schema") != "urn:ontology-appliance:schema:rollback-audit:1"
        ):
            raise ArtifactLoadError("Rollback audit uses an unsupported schema.")
        if audit.get("operation") != "ROLLBACK":
            raise ArtifactLoadError("Rollback audit operation is invalid.")
        target = audit.get("to")
        source = audit.get("from")
        cas = audit.get("generationCas")
        checks = {
            "tenantId": pointer.get("tenantId"),
            "publisherSubject": pointer.get("rollbackAuthorizedBy"),
            "authorizedAt": pointer.get("authorizedAt"),
            "activatedAt": pointer.get("activatedAt"),
        }
        for field, expected in checks.items():
            if audit.get(field) != expected:
                raise ArtifactLoadError(
                    f"Rollback audit {field} does not match the active pointer."
                )
        if not isinstance(target, dict) or (
            target.get("manifestObject") != pointer.get("manifestObject")
            or target.get("manifestSha256") != pointer.get("manifestSha256")
            or target.get("publicationReceiptSha256") != pointer.get("publicationReceiptSha256")
        ):
            raise ArtifactLoadError("Rollback audit target does not match the active pointer.")
        if not isinstance(source, dict) or (
            source.get("manifestObject") != pointer.get("previousManifestObject")
            or source.get("manifestSha256") != pointer.get("previousManifestSha256")
            or source.get("pointerGeneration") != pointer.get("replacesGeneration")
        ):
            raise ArtifactLoadError("Rollback audit source does not match the active pointer.")
        if not isinstance(cas, dict) or (
            cas.get("expected") != pointer.get("replacesGeneration")
            or cas.get("observed") != pointer.get("replacesGeneration")
        ):
            raise ArtifactLoadError("Rollback audit generation CAS does not match the pointer.")

    @staticmethod
    def _publication_receipt_record(manifest: dict[str, Any]) -> tuple[str, str]:
        records = manifest.get("supportingArtifacts")
        matches = [
            record
            for record in records or []
            if isinstance(record, dict) and record.get("role") == "publication-receipt"
        ]
        if len(matches) != 1:
            raise ArtifactLoadError(
                "Published manifest requires exactly one publication-receipt artifact."
            )
        path = matches[0].get("path")
        digest = matches[0].get("sha256")
        publication = manifest.get("publication", {})
        if (
            not isinstance(path, str)
            or path != publication.get("receiptPath")
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ArtifactLoadError("Published manifest has an unsafe receipt path.")
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or digest != publication.get("receiptSha256")
        ):
            raise ArtifactLoadError("Published manifest has inconsistent receipt hashes.")
        return path, digest

    @staticmethod
    def _verify_publication_receipt(receipt: Any, manifest: dict[str, Any]) -> None:
        if (
            not isinstance(receipt, dict)
            or receipt.get("$schema") != "urn:ontology-appliance:schema:publication-receipt:1"
        ):
            raise ArtifactLoadError("Publication receipt uses an unsupported schema.")
        publication = manifest["publication"]
        checks = {
            "bundleVersion": manifest.get("version"),
            "tenantId": manifest.get("tenantId"),
            "ontologyVersion": manifest.get("ontologyVersion"),
            "publisherSubject": publication.get("publisherSubject"),
            "authorizedAt": publication.get("authorizedAt"),
            "publishedAt": publication.get("publishedAt"),
            "releaseSha": publication.get("releaseSha"),
            "releaseId": publication.get("releaseId"),
            "sourceManifestSha256": publication.get("sourceManifestSha256"),
            "reviewLedgerSha256": publication.get("reviewLedgerSha256"),
        }
        for field, expected in checks.items():
            if receipt.get(field) != expected:
                raise ArtifactLoadError(
                    f"Publication receipt {field} does not match the published manifest."
                )

    @staticmethod
    def _parse_publication(manifest: dict[str, Any]) -> tuple[str, str, bool]:
        publication = manifest.get("publication")
        if not isinstance(publication, dict):
            raise ArtifactLoadError("Manifest requires explicit publication metadata.")
        state = str(publication.get("state", "")).strip().upper()
        serving_mode = str(publication.get("servingMode", "")).strip().upper()
        is_published = publication.get("isPublished")
        allowed = {
            "CANDIDATE": ("DEMO_ONLY", False),
            "PUBLISHED": ("ACTIVE", True),
        }
        if state == "PUBLISHABLE":
            raise ArtifactLoadError(
                "A PUBLISHABLE bundle is Publisher input and cannot be served before promotion."
            )
        expected = allowed.get(state)
        if expected is None:
            raise ArtifactLoadError("Manifest publication state must be CANDIDATE or PUBLISHED.")
        if (serving_mode, is_published) != expected:
            raise ArtifactLoadError(
                f"Publication metadata is inconsistent for {state}: expected "
                f"servingMode={expected[0]} and isPublished={str(expected[1]).lower()}."
            )
        if state == "PUBLISHED":
            for field in ("reviewLedgerSha256", "sourceManifestSha256", "receiptSha256"):
                value = publication.get(field)
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    raise ArtifactLoadError(
                        f"Published manifest requires publication.{field} as a SHA-256 digest."
                    )
            for field in (
                "publisherSubject",
                "authorizedAt",
                "publishedAt",
                "releaseSha",
                "releaseId",
                "receiptPath",
            ):
                value = publication.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ArtifactLoadError(
                        f"Published manifest requires non-empty publication.{field}."
                    )
            for field in ("authorizedAt", "publishedAt"):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", publication[field]):
                    raise ArtifactLoadError(f"Published manifest requires UTC publication.{field}.")
            if publication["authorizedAt"] > publication["publishedAt"]:
                raise ArtifactLoadError("Publication authorization cannot follow publication time.")
        return state, serving_mode, bool(is_published)

    @staticmethod
    def _download_blob(blob: Any, *, maximum_size: int) -> bytes:
        size = getattr(blob, "size", None)
        if isinstance(size, int) and size > maximum_size:
            raise ArtifactLoadError(
                f"Remote artifact exceeds the {maximum_size}-byte safety limit."
            )
        content = blob.download_as_bytes(checksum="auto", timeout=30)
        if not isinstance(content, bytes):
            raise ArtifactLoadError("Cloud Storage returned a non-bytes artifact.")
        if len(content) > maximum_size:
            raise ArtifactLoadError(
                f"Remote artifact exceeds the {maximum_size}-byte safety limit."
            )
        return content

    @staticmethod
    def _google_storage_client() -> Any:
        try:
            from google.cloud import storage
        except ImportError as exc:  # pragma: no cover - production packaging guard
            raise ArtifactLoadError(
                "Cloud artifact loading requires the firebase optional dependencies."
            ) from exc
        return storage.Client()

    @staticmethod
    def _parse_record(raw: Any) -> ArtifactRecord:
        if not isinstance(raw, dict):
            raise ArtifactLoadError("Each manifest artifact must be an object.")
        name = str(raw.get("path", "")).strip()
        sha256 = str(raw.get("sha256", "")).strip().lower()
        rdf_format = str(raw.get("format", "")).strip().lower()
        kind = str(raw.get("kind", "graph")).strip().lower()
        if not name or len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise ArtifactLoadError(f"Invalid artifact record: {raw}")
        if kind not in {"graph", "shapes", "provenance"}:
            raise ArtifactLoadError(f"Unsupported artifact kind '{kind}'.")
        if rdf_format not in {"turtle", "nquads", "trig", "json-ld", "xml"}:
            raise ArtifactLoadError(f"Unsupported RDF format '{rdf_format}'.")
        return ArtifactRecord(name=name, sha256=sha256, rdf_format=rdf_format, kind=kind)

    @staticmethod
    def _parse_rdf(content: bytes, rdf_format: str, target: Graph) -> None:
        if rdf_format in {"nquads", "trig"}:
            dataset = Dataset()
            dataset.parse(data=content, format=rdf_format)
            for subject, predicate, obj, _context in dataset.quads((None, None, None, None)):
                target.add((subject, predicate, obj))
            return
        target.parse(data=content, format=rdf_format)

    def _persist_cache(self, snapshot: ArtifactSnapshot) -> None:
        try:
            self.settings.last_valid_path.parent.mkdir(parents=True, exist_ok=True)
            dataset = Dataset()
            data_context = dataset.graph(DATA_GRAPH)
            shapes_context = dataset.graph(SHAPES_GRAPH)
            for triple in snapshot.graph:
                data_context.add(triple)
            for triple in snapshot.shapes:
                shapes_context.add(triple)
            temporary = self.settings.last_valid_path.with_suffix(".tmp")
            dataset.serialize(destination=temporary, format="trig")
            cache_sha256 = hashlib.sha256(temporary.read_bytes()).hexdigest()
            temporary.replace(self.settings.last_valid_path)
            meta_path = self.settings.last_valid_path.with_suffix(
                self.settings.last_valid_path.suffix + ".json"
            )
            meta_temp = meta_path.with_suffix(meta_path.suffix + ".tmp")
            meta_temp.write_text(
                json.dumps(
                    {
                        "version": snapshot.version,
                        "loadedAt": snapshot.loaded_at.isoformat(),
                        "cacheSha256": cache_sha256,
                        "publicationState": snapshot.publication_state,
                        "servingMode": snapshot.serving_mode,
                        "isPublished": snapshot.is_published,
                        "artifacts": [asdict(record) for record in snapshot.records],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            meta_temp.replace(meta_path)
        except (OSError, TypeError):
            # Cache persistence must never make an already verified graph unavailable.
            return

    def _restore_cache(self) -> ArtifactSnapshot:
        cache_path = self.settings.last_valid_path
        meta_path = cache_path.with_suffix(cache_path.suffix + ".json")
        try:
            cache_content = cache_path.read_bytes()
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            actual_cache_hash = hashlib.sha256(cache_content).hexdigest()
            if actual_cache_hash != metadata["cacheSha256"]:
                raise ArtifactLoadError("Last-valid cache SHA-256 does not match its metadata.")
            dataset = Dataset()
            dataset.parse(data=cache_content, format="trig")
            graph = clone_graph(dataset.graph(DATA_GRAPH))
            shapes = clone_graph(dataset.graph(SHAPES_GRAPH))
            records = tuple(ArtifactRecord(**item) for item in metadata["artifacts"])
            loaded_at = datetime.fromisoformat(metadata["loadedAt"])
            publication_state = str(metadata["publicationState"])
            serving_mode = str(metadata["servingMode"])
            is_published = metadata["isPublished"]
        except ArtifactLoadError:
            raise
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ArtifactLoadError(f"Cannot restore last-valid cache: {exc}") from exc
        if not graph or not shapes:
            raise ArtifactLoadError("Last-valid cache is incomplete.")
        if (publication_state, serving_mode, is_published) not in {
            ("CANDIDATE", "DEMO_ONLY", False),
            ("PUBLISHED", "ACTIVE", True),
        }:
            raise ArtifactLoadError("Last-valid cache has inconsistent publication metadata.")
        if (
            not self.settings.is_development
            and not is_published
            and not (
                self.settings.allow_demo_candidate
                and self.settings.artifact_bucket is None
                and serving_mode == "DEMO_ONLY"
            )
        ):
            raise ArtifactLoadError(
                "Production refuses a non-published last-valid candidate cache."
            )
        conforms, _report_graph, report_text = shacl_validate(
            data_graph=graph,
            shacl_graph=shapes,
            inference="rdfs",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
        )
        if not conforms:
            compact_report = " ".join(str(report_text).split())[:1_000]
            raise ArtifactLoadError(
                f"Last-valid cache no longer conforms to SHACL: {compact_report}"
            )
        return ArtifactSnapshot(
            graph=graph,
            shapes=shapes,
            version=str(metadata["version"]),
            records=records,
            loaded_at=loaded_at,
            publication_state=publication_state,
            serving_mode=serving_mode,
            is_published=is_published,
        )
