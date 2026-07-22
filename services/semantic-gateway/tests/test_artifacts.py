from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from ontology_appliance_gateway.artifacts import ArtifactLoadError, ArtifactStore
from ontology_appliance_gateway.config import Settings


def _copy_artifacts(source: Path, target: Path) -> Path:
    artifact_dir = target / "artifacts"
    shutil.copytree(source, artifact_dir)
    return artifact_dir


def test_failed_reload_retains_in_memory_last_valid(settings: Settings, tmp_path: Path) -> None:
    artifact_dir = _copy_artifacts(settings.artifact_dir, tmp_path / "copy")
    isolated = replace(settings, artifact_dir=artifact_dir)
    store = ArtifactStore(isolated)
    valid = store.initialize()
    valid_count = len(valid.graph)

    (artifact_dir / "ontology.ttl").write_text("corrupted", encoding="utf-8")
    fallback = store.reload()

    assert fallback.status == "DEGRADED_LAST_VALID"
    assert fallback.version == valid.version
    assert len(fallback.graph) == valid_count
    assert "SHA-256 mismatch" in (fallback.diagnostic or "")


def test_new_process_restores_persisted_last_valid(settings: Settings, tmp_path: Path) -> None:
    artifact_dir = _copy_artifacts(settings.artifact_dir, tmp_path / "persisted")
    isolated = replace(settings, artifact_dir=artifact_dir)
    first_store = ArtifactStore(isolated)
    valid = first_store.initialize()
    assert isolated.last_valid_path.exists()

    (artifact_dir / "mappings.ttl").write_text("invalid", encoding="utf-8")
    restored = ArtifactStore(isolated).initialize()
    assert restored.status == "DEGRADED_LAST_VALID"
    assert restored.version == valid.version
    assert len(restored.graph) == len(valid.graph)


def test_initial_hash_failure_without_cache_is_fatal(settings: Settings, tmp_path: Path) -> None:
    artifact_dir = _copy_artifacts(settings.artifact_dir, tmp_path / "broken")
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    isolated = replace(
        settings,
        artifact_dir=artifact_dir,
        last_valid_path=tmp_path / "does-not-exist" / "last-valid.trig",
    )

    with pytest.raises(ArtifactLoadError, match="no last-valid snapshot"):
        ArtifactStore(isolated).initialize()


def test_publishable_bundle_cannot_be_served_before_publisher_promotion(
    settings: Settings, tmp_path: Path
) -> None:
    artifact_dir = _copy_artifacts(settings.artifact_dir, tmp_path / "publishable")
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publication"].update(
        {"state": "PUBLISHABLE", "servingMode": "PUBLISHER_ONLY", "isPublished": False}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    isolated = replace(
        settings,
        artifact_dir=artifact_dir,
        last_valid_path=tmp_path / "publishable-cache" / "last-valid.trig",
    )

    with pytest.raises(ArtifactLoadError, match="cannot be served before promotion"):
        ArtifactStore(isolated).initialize()


def test_publisher_promoted_bundle_is_labeled_published(settings: Settings, tmp_path: Path) -> None:
    artifact_dir = _copy_artifacts(settings.artifact_dir, tmp_path / "published")
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publication"].update(
        {
            "state": "PUBLISHED",
            "servingMode": "ACTIVE",
            "isPublished": True,
            "publisherSubject": "serviceAccount:publisher@example.invalid",
            "authorizedAt": "2026-07-22T14:04:00Z",
            "publishedAt": "2026-07-22T14:05:00Z",
            "releaseSha": "d" * 40,
            "releaseId": "d" * 40 + "-123-1",
            "sourceManifestSha256": "e" * 64,
            "receiptPath": "publication-receipt.json",
            "receiptSha256": "f" * 64,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    isolated = replace(
        settings,
        artifact_dir=artifact_dir,
        last_valid_path=tmp_path / "published-cache" / "last-valid.trig",
    )

    snapshot = ArtifactStore(isolated).initialize()

    assert snapshot.publication_state == "PUBLISHED"
    assert snapshot.serving_mode == "ACTIVE"
    assert snapshot.is_published is True


class _FakeBlob:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.size = len(content)

    def download_as_bytes(self, *, checksum: str, timeout: int) -> bytes:
        assert checksum == "auto"
        assert timeout == 30
        return self.content


class _FakeBucket:
    def __init__(
        self,
        objects: dict[str, bytes],
        *,
        versioned_objects: dict[tuple[str, int], bytes] | None = None,
    ) -> None:
        self.objects = objects
        self.versioned_objects = versioned_objects or {}
        self.requested: list[str] = []
        self.requested_generations: list[tuple[str, int | None]] = []

    def blob(self, name: str, *, generation: int | None = None) -> _FakeBlob:
        self.requested.append(name)
        self.requested_generations.append((name, generation))
        if generation is not None:
            versioned_key = (name, generation)
            if versioned_key not in self.versioned_objects:
                raise FileNotFoundError(f"{name}#{generation}")
            return _FakeBlob(self.versioned_objects[versioned_key])
        if name not in self.objects:
            raise FileNotFoundError(name)
        return _FakeBlob(self.objects[name])


class _FakeStorageClient:
    def __init__(self, bucket: _FakeBucket) -> None:
        self.fake_bucket = bucket
        self.requested_bucket: str | None = None

    def bucket(self, name: str) -> _FakeBucket:
        self.requested_bucket = name
        return self.fake_bucket


def _remote_objects(
    artifact_dir: Path, pointer_name: str, *, version: str
) -> tuple[dict[str, bytes], str]:
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    release_sha = "d" * 40
    publisher = "serviceAccount:publisher@example.invalid"
    published_at = "2026-07-22T14:05:00Z"
    authorized_at = "2026-07-22T14:04:00Z"
    release_id = release_sha + "-123-1"
    source_manifest_sha = "e" * 64
    receipt = {
        "$schema": "urn:ontology-appliance:schema:publication-receipt:1",
        "bundleVersion": version,
        "tenantId": manifest["tenantId"],
        "ontologyVersion": manifest["ontologyVersion"],
        "publisherSubject": publisher,
        "authorizedAt": authorized_at,
        "publishedAt": published_at,
        "releaseSha": release_sha,
        "releaseId": release_id,
        "sourceManifestSha256": source_manifest_sha,
        "reviewLedgerSha256": manifest["publication"]["reviewLedgerSha256"],
    }
    receipt_bytes = json.dumps(receipt).encode()
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    manifest["publication"].update(
        {
            "state": "PUBLISHED",
            "servingMode": "ACTIVE",
            "isPublished": True,
            "publisherSubject": publisher,
            "authorizedAt": authorized_at,
            "publishedAt": published_at,
            "releaseSha": release_sha,
            "releaseId": release_id,
            "sourceManifestSha256": source_manifest_sha,
            "receiptPath": "publication-receipt.json",
            "receiptSha256": receipt_sha,
        }
    )
    manifest["supportingArtifacts"].append(
        {
            "role": "publication-receipt",
            "path": "publication-receipt.json",
            "sha256": receipt_sha,
            "mediaType": "application/json",
        }
    )
    release_prefix = f"tenants/demo-bank/ontology/releases/{version}-{release_id}"
    manifest_object = f"{release_prefix}/manifest.json"
    manifest_bytes = json.dumps(manifest).encode()
    pointer = {
        "$schema": "urn:ontology-appliance:schema:active-pointer:1",
        "operation": "PUBLISH",
        "tenantId": "demo-bank",
        "bundleVersion": version,
        "ontologyVersion": manifest["ontologyVersion"],
        "manifestObject": manifest_object,
        "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "publicationReceiptSha256": receipt_sha,
        "publisherSubject": publisher,
        "authorizedAt": authorized_at,
        "activatedAt": "2026-07-22T14:05:00Z",
        "releaseSha": release_sha,
        "releaseId": release_id,
    }
    objects = {
        pointer_name: json.dumps(pointer).encode(),
        manifest_object: manifest_bytes,
        f"{release_prefix}/publication-receipt.json": receipt_bytes,
    }
    for item in manifest["artifacts"]:
        objects[f"{release_prefix}/{item['path']}"] = (artifact_dir / item["path"]).read_bytes()
    return objects, release_prefix


def test_remote_snapshot_is_downloaded_and_verified(settings: Settings, tmp_path: Path) -> None:
    pointer_name = "tenants/demo-bank/ontology/active.json"
    objects, _release_prefix = _remote_objects(
        settings.artifact_dir, pointer_name, version="remote-2026.07.2"
    )
    bucket = _FakeBucket(objects)
    client = _FakeStorageClient(bucket)
    remote_settings = replace(
        settings,
        artifact_bucket="oa-artifacts-test",
        artifact_pointer="tenants/{tenant_id}/ontology/active.json",
        last_valid_path=tmp_path / "remote-cache.trig",
    )

    snapshot = ArtifactStore(remote_settings, storage_client=client).initialize()

    assert snapshot.version == "remote-2026.07.2"
    assert snapshot.status == "READY"
    assert snapshot.publication_state == "PUBLISHED"
    assert snapshot.serving_mode == "ACTIVE"
    assert snapshot.is_published is True
    assert snapshot.diagnostic == (
        "Resolved gs://oa-artifacts-test/tenants/demo-bank/ontology/active.json to "
        "gs://oa-artifacts-test/tenants/demo-bank/ontology/releases/"
        f"remote-2026.07.2-{'d' * 40}-123-1/manifest.json"
    )
    assert client.requested_bucket == "oa-artifacts-test"
    assert len(bucket.requested) == 8


def test_production_cold_start_uses_pinned_pointer_generation(
    settings: Settings, tmp_path: Path
) -> None:
    pointer_name = "tenants/demo-bank/ontology/active.json"
    objects, _release_prefix = _remote_objects(
        settings.artifact_dir,
        pointer_name,
        version="pinned-cold-start",
    )
    approved_pointer = objects[pointer_name]
    objects[pointer_name] = b'{"tampered":"latest"}'
    production = replace(
        settings,
        environment="production",
        artifact_bucket="oa-artifacts-test",
        active_pointer_generation=42,
        last_valid_path=tmp_path / "new-instance" / "last-valid.trig",
    )
    bucket = _FakeBucket(
        objects,
        versioned_objects={(pointer_name, 42): approved_pointer},
    )

    snapshot = ArtifactStore(
        production,
        storage_client=_FakeStorageClient(bucket),
    ).initialize()

    assert snapshot.version == "pinned-cold-start"
    assert snapshot.status == "READY"
    assert (pointer_name, 42) in bucket.requested_generations
    assert "pinned pointer generation 42" in (snapshot.diagnostic or "")


def test_production_remote_pointer_must_be_generation_pinned(
    settings: Settings, tmp_path: Path
) -> None:
    pointer_name = "tenants/demo-bank/ontology/active.json"
    objects, _release_prefix = _remote_objects(
        settings.artifact_dir,
        pointer_name,
        version="unpinned-production",
    )
    production = replace(
        settings,
        environment="production",
        artifact_bucket="oa-artifacts-test",
        active_pointer_generation=None,
        last_valid_path=tmp_path / "unpinned" / "last-valid.trig",
    )

    with pytest.raises(ArtifactLoadError, match="OA_ACTIVE_POINTER_GENERATION"):
        ArtifactStore(
            production,
            storage_client=_FakeStorageClient(_FakeBucket(objects)),
        ).initialize()


def _convert_to_rollback(objects: dict[str, bytes], pointer_name: str) -> str:
    pointer = json.loads(objects[pointer_name])
    pointer.update(
        {
            "operation": "ROLLBACK",
            "authorizedAt": "2026-07-22T15:00:00Z",
            "activatedAt": "2026-07-22T15:01:00Z",
            "replacesGeneration": "42",
            "previousManifestObject": (
                "tenants/demo-bank/ontology/releases/newer-current/manifest.json"
            ),
            "previousManifestSha256": "a" * 64,
            "rollbackAuthorizedBy": pointer["publisherSubject"],
        }
    )
    audit_object = "tenants/demo-bank/ontology/rollbacks/123-1/rollback-audit.json"
    audit = {
        "$schema": "urn:ontology-appliance:schema:rollback-audit:1",
        "operation": "ROLLBACK",
        "tenantId": "demo-bank",
        "publisherSubject": pointer["publisherSubject"],
        "authorizedAt": pointer["authorizedAt"],
        "activatedAt": pointer["activatedAt"],
        "generationCas": {"expected": "42", "observed": "42"},
        "from": {
            "manifestObject": pointer["previousManifestObject"],
            "manifestSha256": pointer["previousManifestSha256"],
            "pointerGeneration": "42",
        },
        "to": {
            "manifestObject": pointer["manifestObject"],
            "manifestSha256": pointer["manifestSha256"],
            "publicationReceiptSha256": pointer["publicationReceiptSha256"],
        },
    }
    audit_bytes = json.dumps(audit).encode()
    pointer["rollbackAuditObject"] = audit_object
    pointer["rollbackAuditSha256"] = hashlib.sha256(audit_bytes).hexdigest()
    objects[audit_object] = audit_bytes
    objects[pointer_name] = json.dumps(pointer).encode()
    return audit_object


def test_remote_rollback_requires_hashed_audit_evidence(settings: Settings, tmp_path: Path) -> None:
    pointer_name = "tenants/demo-bank/ontology/active.json"
    objects, _release_prefix = _remote_objects(
        settings.artifact_dir, pointer_name, version="rolled-back"
    )
    audit_object = _convert_to_rollback(objects, pointer_name)
    bucket = _FakeBucket(objects)
    remote_settings = replace(
        settings,
        artifact_bucket="oa-artifacts-test",
        last_valid_path=tmp_path / "rollback-cache.trig",
    )

    snapshot = ArtifactStore(
        remote_settings, storage_client=_FakeStorageClient(bucket)
    ).initialize()

    assert snapshot.version == "rolled-back"
    assert audit_object in bucket.requested


def test_tampered_rollback_audit_fails_closed(settings: Settings, tmp_path: Path) -> None:
    pointer_name = "tenants/demo-bank/ontology/active.json"
    objects, _release_prefix = _remote_objects(
        settings.artifact_dir, pointer_name, version="rollback-tampered"
    )
    audit_object = _convert_to_rollback(objects, pointer_name)
    objects[audit_object] = b'{"tampered":true}'
    production = replace(
        settings,
        environment="production",
        artifact_bucket="oa-artifacts-test",
        active_pointer_generation=42,
        last_valid_path=tmp_path / "no-cache" / "last-valid.trig",
    )
    versioned_objects = {(pointer_name, 42): objects[pointer_name]}

    with pytest.raises(ArtifactLoadError, match="Rollback audit SHA-256"):
        ArtifactStore(
            production,
            storage_client=_FakeStorageClient(
                _FakeBucket(objects, versioned_objects=versioned_objects)
            ),
        ).initialize()


def test_remote_failure_uses_verified_bundled_snapshot(settings: Settings, tmp_path: Path) -> None:
    pointer_name = "tenants/demo-bank/ontology/active.json"
    objects, release_prefix = _remote_objects(
        settings.artifact_dir, pointer_name, version="bad-remote"
    )
    objects[f"{release_prefix}/ontology.ttl"] = b"tampered"
    remote_settings = replace(
        settings,
        artifact_bucket="oa-artifacts-test",
        last_valid_path=tmp_path / "bundled-cache.trig",
    )

    snapshot = ArtifactStore(
        remote_settings,
        storage_client=_FakeStorageClient(_FakeBucket(objects)),
    ).initialize()

    assert snapshot.version == "2026.07.1-demo-bank"
    assert snapshot.status == "DEGRADED_BUNDLED_FALLBACK"
    assert "SHA-256 mismatch" in (snapshot.diagnostic or "")


def test_remote_outage_prefers_persisted_snapshot_over_bundle(
    settings: Settings, tmp_path: Path
) -> None:
    pointer_name = "tenants/demo-bank/ontology/active.json"
    remote_settings = replace(
        settings,
        artifact_bucket="oa-artifacts-test",
        last_valid_path=tmp_path / "remote-last-valid.trig",
    )
    healthy_objects, _release_prefix = _remote_objects(
        settings.artifact_dir,
        pointer_name,
        version="remote-newer-than-bundle",
    )
    published = ArtifactStore(
        remote_settings,
        storage_client=_FakeStorageClient(_FakeBucket(healthy_objects)),
    ).initialize()
    assert published.version == "remote-newer-than-bundle"

    recovered = ArtifactStore(
        remote_settings,
        storage_client=_FakeStorageClient(_FakeBucket({})),
    ).initialize()

    assert recovered.version == "remote-newer-than-bundle"
    assert recovered.status == "DEGRADED_LAST_VALID"


def test_production_never_falls_back_to_bundled_candidate(
    settings: Settings, tmp_path: Path
) -> None:
    production = replace(
        settings,
        environment="production",
        artifact_bucket="oa-artifacts-test",
        active_pointer_generation=42,
        last_valid_path=tmp_path / "production-empty-cache" / "last-valid.trig",
    )

    with pytest.raises(ArtifactLoadError, match="Bundled demo candidates are disabled"):
        ArtifactStore(
            production,
            storage_client=_FakeStorageClient(_FakeBucket({})),
        ).initialize()


def test_cloud_demo_candidate_requires_explicit_opt_in(settings: Settings, tmp_path: Path) -> None:
    demo = replace(
        settings,
        environment="production",
        allow_demo_candidate=True,
        last_valid_path=tmp_path / "demo-cache.trig",
    )

    snapshot = ArtifactStore(demo).initialize()

    assert snapshot.publication_state == "CANDIDATE"
    assert snapshot.serving_mode == "DEMO_ONLY"
    assert snapshot.is_published is False
