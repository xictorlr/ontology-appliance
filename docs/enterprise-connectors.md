# Enterprise connector activation contract

The control plane presents the target connector portfolio without implying that
every adapter is already implemented. This release activates bounded CSV,
JSONL, PDF, and OpenAPI 3 JSON file onboarding plus metadata-snapshot
PostgreSQL intake. Every source remains read-only, metadata-first,
tenant-bound, and provenance-bearing.

## Portfolio

| Family | Connectors | Release state | Credential boundary |
|---|---|---|---|
| Files and contracts | CSV, JSONL, PDF, OpenAPI 3 JSON | Active | No external credential |
| Databases | PostgreSQL | Active (metadata snapshot) | Secret Manager reference |
| Databases | MySQL, SQL Server, Oracle | Planned | Secret Manager reference |
| Object storage | Amazon S3, Azure Blob Storage, Google Cloud Storage | Planned | Federated workload identity preferred |
| Warehouses and lakehouses | Databricks, BigQuery, Snowflake | Planned | Workload identity or Secret Manager reference |

## Mandatory gates

A planned connector can become active only after all of these gates pass:

1. The adapter uses a read-only identity and begins with schema, catalog, or
   object metadata.
2. The browser never receives or submits a database password, access key, SAS
   token, private key, or service-account key.
3. The verified server session supplies the tenant. Connector input cannot
   override it.
4. Database, catalog, bucket, container, and prefix allowlists are explicit.
5. Sampling is bounded by time, row, object, byte, and cost limits as
   appropriate.
6. Snapshots capture stable evidence coordinates such as object version,
   generation, ETag, table/column, row locator, or query fingerprint.
7. Credentials are stored as server-side secret references or exchanged through
   workload identity; they are never persisted in Firestore connector documents.
8. An ephemeral integration test proves read-only behavior, tenant isolation,
   timeout handling, credential revocation, and provenance output.
9. Security and data owners authorize activation. The model that proposes a
   mapping cannot approve the connector or publish semantics.

## PostgreSQL activation (metadata snapshot mode)

PostgreSQL is active in *metadata snapshot mode*: an operator (or a bounded
runner) executes the documented, parameter-free catalog SQL published in
`services/semantic-gateway/src/ontology_appliance_gateway/connectors/postgres.py`
(`CATALOG_SQL`) against `information_schema`/`pg_catalog` with a dedicated
read-only identity, and the deterministic normalizer
(`python -m ontology_appliance_gateway.connectors.postgres`) turns the JSON
catalog snapshot into the committed profile, evidence-index, and snapshot
artifacts (`profiles/postgres-demo/`). The appliance never opens a live
database connection in this release, and value sampling is disabled.

How each mandatory gate is satisfied:

1. **Read-only, metadata-first adapter.** The manifest
   (`data/contracts/postgres.connector.json`) pins `access_mode: read_only`,
   omits the `sample` capability, and the extraction SQL reads only
   `information_schema`/`pg_catalog`. Session options enforce
   `default_transaction_read_only=on` and `statement_timeout` (see
   `READ_ONLY_CONNECTION_OPTIONS` and the manifest `source.uri`).
2. **No secret ever reaches the browser.** The manifest carries a Secret
   Manager version *resource name* (`credential_ref`), never a value; the DSN
   template embeds no credential, and the web catalog keeps
   `credentialBoundary: "secret-manager"` with no upload/credential form.
3. **Tenant from the verified session.** Catalog snapshots normalize into
   tenant-bound artifacts (`tenant_id` fixed in the manifest); connector input
   cannot override the tenant, matching the file-connector onboarding path.
4. **Explicit allowlists.** The snapshot enumerates concrete schemas; the
   normalizer refuses tables or columns that reference unlisted schemas or
   tables, and the extraction SQL excludes `pg_catalog`, `information_schema`,
   and `pg_%` system schemas.
5. **Bounded intake.** `maximum_schemas`/`maximum_tables`/`maximum_columns`
   manifest limits mirror `CatalogLimits` (16/200/2000) and are enforced
   fail-closed; `timeout_seconds: 30` mirrors the 30000 ms statement timeout.
   Row **values** are never sampled at all in this mode.
6. **Stable evidence coordinates.** Snapshot IDs are content-hash pinned
   (`postgres-demo@sha256:<catalog sha256>`); every evidence entry carries a
   `postgres://database/schema/table#column=...` or profile-pointer locator and
   a SHA-256 content hash.
7. **Server-side secret references only.** `credential_ref` matches the
   `projects/*/secrets/*/versions/*` contract pattern; no credential is
   persisted in Firestore connector documents or fixtures.
8. **Deterministic proof of read-only behavior.**
   `services/semantic-gateway/tests/test_postgres_connector.py` proves the
   normalizer refuses value-bearing input (fail closed), enforces limits,
   verifies SQL constants are read-only and parameter-free, checks
   timeout/read-only session options, and regenerates the committed bundle
   byte-for-byte. A live ephemeral integration test remains a precondition for
   enabling *live connection mode*, which stays disabled in this release.
9. **Authorized activation.** Activation shipped as this code + policy + test
   change reviewed through the protected-branch process; the normalizer only
   produces `PENDING_VERIFICATION`-style evidence and proposals — it cannot
   approve mappings or publish semantics.

## Connector-specific boundaries

- **Amazon S3:** assume a read-only role with an external ID; restrict bucket and
  prefix; preserve version ID or ETag evidence.
- **Azure Blob Storage:** prefer workload identity; otherwise reference a
  vault-backed, read-only SAS; restrict account, container, and prefix.
- **Google Cloud Storage:** use a dedicated object-viewer identity and pin object
  generations.
- **Databricks:** restrict Unity Catalog and SQL Warehouse access; bound statement
  execution and retain query lineage.
- **BigQuery:** use metadata-viewer permissions where possible; enforce dataset
  allowlists, dry runs, and `maximumBytesBilled`.
- **Snowflake:** use a read-only role, key-pair or OAuth credential reference, and
  warehouse resource limits.
- **Relational databases:** require TLS, a dedicated read-only user or replica,
  schema/table allowlists, statement timeout, and bounded sampling.

Activation is a code, policy, test, and authorization change—not a UI toggle.
