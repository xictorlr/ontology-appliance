# Enterprise connector activation contract

The control plane presents the target connector portfolio without implying that
every adapter is already implemented. This release activates only bounded CSV,
JSONL, PDF, and OpenAPI 3 JSON file onboarding. Every source remains read-only,
metadata-first, tenant-bound, and provenance-bearing.

## Portfolio

| Family | Connectors | Release state | Credential boundary |
|---|---|---|---|
| Files and contracts | CSV, JSONL, PDF, OpenAPI 3 JSON | Active | No external credential |
| Databases | PostgreSQL, MySQL, SQL Server, Oracle | Planned | Secret Manager reference |
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
