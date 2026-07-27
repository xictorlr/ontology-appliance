import { sourceTypes, type SourceType } from "./source-contract";

export const connectorCategories = [
  "file",
  "api",
  "database",
  "object-storage",
  "lakehouse",
] as const;

export type ConnectorCategory = (typeof connectorCategories)[number];
export type ConnectorAvailability = "active" | "planned";
export type EnterpriseConnectorId =
  | SourceType
  | "postgresql"
  | "mysql"
  | "sql-server"
  | "oracle"
  | "amazon-s3"
  | "azure-blob"
  | "google-cloud-storage"
  | "databricks"
  | "bigquery"
  | "snowflake";

export type ConnectorDefinition = {
  id: EnterpriseConnectorId;
  label: string;
  category: ConnectorCategory;
  detail: string;
  availability: ConnectorAvailability;
  accept: string;
  credentialBoundary: "none" | "secret-manager" | "workload-identity";
  activationRequirements: readonly string[];
};

const fileActivationRequirements = [
  "bounded-upload-validation",
  "immutable-storage-generation",
  "sha256-evidence",
] as const;

export const connectorCatalog: readonly ConnectorDefinition[] = [
  {
    id: "csv",
    label: "CSV / delimited",
    category: "file",
    detail: "Header discovery, bounded profiling, and an immutable evidence snapshot.",
    availability: "active",
    accept: ".csv,text/csv",
    credentialBoundary: "none",
    activationRequirements: fileActivationRequirements,
  },
  {
    id: "jsonl",
    label: "JSON Lines",
    category: "file",
    detail: "Object records, schema evidence, and deterministic line locators.",
    availability: "active",
    accept: ".jsonl,.ndjson,application/x-ndjson",
    credentialBoundary: "none",
    activationRequirements: fileActivationRequirements,
  },
  {
    id: "pdf",
    label: "PDF evidence",
    category: "file",
    detail: "Document snapshot and content hash without changing the source.",
    availability: "active",
    accept: ".pdf,application/pdf",
    credentialBoundary: "none",
    activationRequirements: fileActivationRequirements,
  },
  {
    id: "openapi",
    label: "OpenAPI 3",
    category: "api",
    detail: "JSON contract inventory; remote API execution remains disabled.",
    availability: "active",
    accept: ".json,application/json",
    credentialBoundary: "none",
    activationRequirements: fileActivationRequirements,
  },
  {
    id: "postgresql",
    label: "PostgreSQL",
    category: "database",
    detail: "TLS read replica or read-only user, schema metadata, and bounded sampling.",
    availability: "planned",
    accept: "",
    credentialBoundary: "secret-manager",
    activationRequirements: ["read-only-adapter", "secret-reference", "network-policy", "ephemeral-environment", "integration-test"],
  },
  {
    id: "mysql",
    label: "MySQL",
    category: "database",
    detail: "Read-only schema discovery with an explicit table and row policy.",
    availability: "planned",
    accept: "",
    credentialBoundary: "secret-manager",
    activationRequirements: ["read-only-adapter", "secret-reference", "network-policy", "ephemeral-environment", "integration-test"],
  },
  {
    id: "sql-server",
    label: "SQL Server",
    category: "database",
    detail: "Read-only catalog access with encrypted transport and query timeouts.",
    availability: "planned",
    accept: "",
    credentialBoundary: "secret-manager",
    activationRequirements: ["read-only-adapter", "secret-reference", "network-policy", "ephemeral-environment", "integration-test"],
  },
  {
    id: "oracle",
    label: "Oracle Database",
    category: "database",
    detail: "Schema and synonym discovery through a least-privilege service identity.",
    availability: "planned",
    accept: "",
    credentialBoundary: "secret-manager",
    activationRequirements: ["read-only-adapter", "secret-reference", "network-policy", "ephemeral-environment", "integration-test"],
  },
  {
    id: "amazon-s3",
    label: "Amazon S3",
    category: "object-storage",
    detail: "Bucket/prefix inventory using an assumed read-only role and external ID.",
    availability: "planned",
    accept: "",
    credentialBoundary: "workload-identity",
    activationRequirements: ["federated-read-role", "prefix-allowlist", "object-versioning", "integration-test"],
  },
  {
    id: "azure-blob",
    label: "Azure Blob Storage",
    category: "object-storage",
    detail: "Container/prefix inventory through workload identity or a vault-backed SAS.",
    availability: "planned",
    accept: "",
    credentialBoundary: "workload-identity",
    activationRequirements: ["federated-read-role", "prefix-allowlist", "version-or-etag-snapshot", "integration-test"],
  },
  {
    id: "google-cloud-storage",
    label: "Google Cloud Storage",
    category: "object-storage",
    detail: "Cross-bucket object inventory with generation-pinned read-only access.",
    availability: "planned",
    accept: "",
    credentialBoundary: "workload-identity",
    activationRequirements: ["bucket-reader-role", "prefix-allowlist", "generation-pinned-snapshot", "integration-test"],
  },
  {
    id: "databricks",
    label: "Databricks",
    category: "lakehouse",
    detail: "Unity Catalog and SQL Warehouse metadata with bounded statement execution.",
    availability: "planned",
    accept: "",
    credentialBoundary: "secret-manager",
    activationRequirements: ["sql-warehouse-adapter", "oauth-or-secret-reference", "catalog-allowlist", "integration-test"],
  },
  {
    id: "bigquery",
    label: "BigQuery",
    category: "lakehouse",
    detail: "Dataset metadata and dry-run guarded samples with maximum-bytes-billed.",
    availability: "planned",
    accept: "",
    credentialBoundary: "workload-identity",
    activationRequirements: ["metadata-viewer-role", "dataset-allowlist", "maximum-bytes-billed", "integration-test"],
  },
  {
    id: "snowflake",
    label: "Snowflake",
    category: "lakehouse",
    detail: "Database/schema inventory through a read-only role and warehouse limits.",
    availability: "planned",
    accept: "",
    credentialBoundary: "secret-manager",
    activationRequirements: ["read-only-adapter", "key-pair-secret-reference", "warehouse-policy", "integration-test"],
  },
] as const;

export function isActiveFileConnector(
  connector: ConnectorDefinition,
): connector is ConnectorDefinition & { id: SourceType; availability: "active" } {
  return connector.availability === "active" &&
    sourceTypes.includes(connector.id as SourceType);
}
