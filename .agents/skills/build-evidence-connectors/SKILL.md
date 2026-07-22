---
name: build-evidence-connectors
description: Build and validate read-only, provenance-first evidence bundles for the implemented CSV, JSONL, PDF, and OpenAPI synthetic sources. Use when defining connector manifests and source snapshots, profiling metadata, handling credential references, emitting evidence coordinates, or testing the pilot adapters without granting write access. PostgreSQL remains roadmap work.
---

# Build Evidence Connectors

Connect sources once and emit reproducible evidence without changing upstream systems.

## Workflow

1. Read `references/connector-contract.md` before creating or changing an adapter.
2. Define a versioned connector manifest. Keep credentials in Secret Manager references, never in manifests, logs, fixtures, or source control.
3. Implement discovery in this order: connectivity, schema/metadata, bounded sample, profile, immutable snapshot reference. Keep every operation read-only.
4. Normalize metadata types without erasing original names, values, encodings, or source coordinates.
5. Emit an evidence record for every profile statistic, sample, document span, and extracted claim.
6. Make retries idempotent using tenant, connector, snapshot, extractor version, and content hash.
7. Validate the manifest:

   `python3 .agents/skills/build-evidence-connectors/scripts/validate_connector_manifest.py data/contracts/crm-parties.connector.json`

8. Materialize or drift-check the committed synthetic evidence bundles:

   `python3 .agents/skills/build-evidence-connectors/scripts/materialize_synthetic_bundles.py --check`

9. Validate snapshot hashes, profile bounds, evidence envelopes, and contract-report artifact hashes:

   `python3 .agents/skills/build-evidence-connectors/scripts/validate_evidence_bundle.py`

10. Test the implemented adapters with committed synthetic fixtures. Treat the PostgreSQL example as a roadmap contract only: there is no PostgreSQL adapter, Testcontainer suite, or Cloud SQL resource in the MVP.

## Guardrails

- Derive tenant identity from the authenticated execution context, not from an untrusted request field.
- Default to metadata-first sampling and enforce row, byte, page, and time limits.
- Redact sensitive values in logs and traces while retaining non-secret evidence hashes.
- Reject embedded credentials, writable access modes, ambiguous snapshots, and evidence without stable locators.
- Separate raw input storage from immutable semantic artifacts and operational Firestore projections.

## Required outputs

For each implemented synthetic source, produce a connector manifest, normalized schema, bounded profile, snapshot descriptor, evidence index, and a contract-test report. Record source ID, snapshot ID, locator, observed timestamp, extractor version, and content SHA-256 on every evidence item. A real database connector and credential-backed connectivity test are roadmap outputs, not current acceptance evidence.
