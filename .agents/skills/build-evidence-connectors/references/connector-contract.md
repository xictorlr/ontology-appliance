# Evidence connector contract

## Supported pilot sources

The implemented MVP covers CRM CSV, accounts CSV, payments JSONL, AML CSV, a sanctions OpenAPI mock, and one KYC PDF fixture. The PostgreSQL file is a non-executable roadmap example; the repository does not yet contain a PostgreSQL adapter or Testcontainer coverage. All production credentials remain external to fixtures.

## Manifest shape

Use this logical structure:

```json
{
  "schema_version": "1.0",
  "connector_id": "crm-parties",
  "tenant_id": "demo-bank",
  "source_type": "csv",
  "access_mode": "read_only",
  "source": {
    "uri": "gs://bucket/inputs/crm.csv",
    "snapshot_strategy": "immutable"
  },
  "credential_ref": "projects/example/secrets/crm-reader/versions/latest",
  "capabilities": ["schema", "sample", "profile"],
  "fields": [
    {"source_path": "cif_no", "logical_type": "string", "nullable": false}
  ],
  "evidence": {
    "locator_template": "row:{row}:field:{field}",
    "hash_algorithm": "sha256"
  }
}
```

Omit `credential_ref` for public or local synthetic sources. Never place a secret value in any field.

## Adapter interface

Expose equivalent operations across adapters:

- `check_connection()`: verify read-only access without returning secrets.
- `inspect_schema()`: return original and normalized field metadata.
- `sample(limit, byte_limit)`: return a deterministic bounded sample or document spans.
- `profile(snapshot)`: compute null, uniqueness, cardinality, pattern, and relationship evidence.
- `snapshot()`: return an immutable identifier, observed time, content hash, and source locator.

Use cursors or watermarks only as discovery aids. The snapshot identifier and evidence hash determine reproducibility.

## Evidence envelope

Each evidence item contains:

- `evidence_id`, `tenant_id`, `source_id`, and `snapshot_id`
- source-native locator plus normalized field or document coordinates
- observation time and extractor name/version
- content SHA-256 and optional redacted preview
- classification and policy tags
- the claim or statistic supported by the evidence

Do not store raw secret values, authentication headers, full sensitive documents in logs, or unbounded row samples.

## Failure behavior

Classify failures as authentication, authorization, unavailable, schema drift, content invalid, policy blocked, or limit exceeded. Emit retryability and a stable error code. Retries must not duplicate evidence records. Quarantine changed content under an existing snapshot ID.

## Roadmap boundary

Add PostgreSQL only with a read-only adapter, bounded statements, credential references, and an ephemeral integration test. Do not claim database connectivity, provision Cloud SQL, or count the roadmap example as a passing pilot source before those controls exist.
