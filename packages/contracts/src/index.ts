import { z } from "zod";

/**
 * Runtime mirrors of the canonical JSON Schemas in contracts/schemas.
 *
 * The MVP deliberately keeps snake_case wire names compatible with committed
 * immutable artifacts. These schemas route and validate proposals; they do not
 * publish or manufacture an approval decision.
 */

export const connectorSourceTypes = ["csv", "jsonl", "pdf", "openapi", "postgres"] as const;
export const connectorCapabilities = ["schema", "sample", "profile", "snapshot"] as const;
export const connectorLogicalTypes = [
  "string",
  "integer",
  "number",
  "boolean",
  "date",
  "datetime",
  "object",
  "array",
  "binary",
] as const;

const connectorSourceSchema = z
  .object({
    uri: z.string().min(1),
    snapshot_strategy: z.enum(["immutable", "watermark", "content_hash"]),
    response_fixture: z.string().min(1).optional(),
    document_glob: z.string().min(1).optional(),
  })
  .strict();

const connectorFieldSchema = z
  .object({
    source_path: z.string().min(1),
    logical_type: z.enum(connectorLogicalTypes),
    nullable: z.boolean(),
    source_representation: z.string().min(1).optional(),
  })
  .strict();

const connectorEvidencePolicySchema = z
  .object({
    locator_template: z.string().min(1),
    hash_algorithm: z.literal("sha256"),
  })
  .strict();

const connectorLimitsSchema = z
  .object({
    maximum_bytes: z.number().int().positive().optional(),
    maximum_records: z.number().int().positive().optional(),
    maximum_pages: z.number().int().positive().optional(),
    maximum_schemas: z.number().int().positive().optional(),
    maximum_tables: z.number().int().positive().optional(),
    maximum_columns: z.number().int().positive().optional(),
    timeout_seconds: z.number().int().positive().optional(),
  })
  .strict();

export const connectorManifestSchema = z
  .object({
    schema_version: z.literal("1.0"),
    connector_id: z.string().regex(/^[a-z][a-z0-9-]{2,63}$/),
    tenant_id: z.string().min(1).max(128),
    source_type: z.enum(connectorSourceTypes),
    access_mode: z.literal("read_only"),
    source: connectorSourceSchema,
    credential_ref: z
      .string()
      .regex(/^projects\/[^/]+\/secrets\/[^/]+\/versions\/[^/]+$/)
      .optional(),
    capabilities: z
      .array(z.enum(connectorCapabilities))
      .min(1)
      .refine((items) => new Set(items).size === items.length, "capabilities must be unique"),
    fields: z.array(connectorFieldSchema),
    evidence: connectorEvidencePolicySchema,
    limits: connectorLimitsSchema.optional(),
  })
  .strict();

export const proposalStatuses = [
  "PENDING_VERIFICATION",
  "AUTO_APPROVED",
  "HUMAN_REVIEW",
  "REJECTED",
  "QUARANTINED",
  "ABSTAINED",
] as const;

export const proposalKinds = [
  "concept",
  "relation",
  "alias",
  "mapping",
  "duplicate",
  "constraint",
  "assertion",
  "drift",
] as const;

export const confidenceDimensionNames = [
  "lexical",
  "structural",
  "instance",
  "external",
  "model",
  "evidence_coverage",
] as const;

export const proposalStatusSchema = z.enum(proposalStatuses);
export const proposalKindSchema = z.enum(proposalKinds);

export const proposalEvidenceSchema = z
  .object({
    evidence_id: z.string().min(1),
    tenant_id: z.string().min(1),
    source_id: z.string().min(1),
    snapshot_id: z.string().min(1),
    locator: z.string().min(1),
    observed_at: z.string().datetime(),
    extractor_version: z.string().min(1),
    content_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    claim: z.string().max(2_000).optional(),
  })
  .strict();

export const confidenceVectorSchema = z
  .object({
    lexical: z.number().min(0).max(1),
    structural: z.number().min(0).max(1),
    instance: z.number().min(0).max(1),
    external: z.number().min(0).max(1),
    model: z.number().min(0).max(1),
    evidence_coverage: z.number().min(0).max(1),
  })
  .strict();

export const generatorTraceSchema = z
  .object({
    mode: z.enum(["deterministic", "live"]),
    model_participated: z.boolean(),
    provider: z.string().min(1),
    model: z.string().min(1),
    provider_returned_model_id: z.string().nullable(),
    prompt_version: z.string().min(1),
    parameters: z.record(z.string(), z.unknown()),
    token_usage: z.record(z.string(), z.unknown()).nullable(),
    latency_ms: z.number().int().min(0),
    response_status: z.string().min(1),
  })
  .strict();

export const proposalSchema = z
  .object({
    schema_version: z.literal("1.0"),
    proposal_id: z.string().min(1).max(256),
    tenant_id: z.string().min(1).max(128),
    kind: proposalKindSchema,
    risk: z.enum(["low", "medium", "high"]),
    source_snapshot_ids: z.array(z.string().min(1)).min(1),
    active_ontology_version: z.string().min(1),
    source_locator: z.string().min(1),
    target_iri: z.string().min(1),
    transformation: z.string().min(1),
    evidence: z.array(proposalEvidenceSchema).min(1),
    counterevidence: z.array(proposalEvidenceSchema),
    confidence: confidenceVectorSchema,
    generator: generatorTraceSchema,
    algorithm_version: z.string().min(1),
    deterministic_input: z.record(z.string(), z.unknown()),
    deterministic_input_hash: z.string().regex(/^[a-f0-9]{64}$/),
    status: proposalStatusSchema,
    reason_codes: z.array(z.string().min(1)).min(1),
  })
  .strict();

// API response metadata is a separate boundary from proposal/evidence records.
export const evidenceReferenceSchema = z
  .object({
    artifact: z.string().min(1),
    sha256: z.string().regex(/^[a-f0-9]{64}$/),
    locator: z.string().nullable().optional(),
    sourceSystem: z.string().nullable().optional(),
    sourceRecordId: z.string().nullable().optional(),
  })
  .strict();

export const gateResultSchema = z
  .object({
    gate: z.enum([
      "CONTRACT",
      "SEMANTIC",
      "SOURCE_EVIDENCE",
      "INDEPENDENT_QUESTIONS",
      "MODEL_CONSISTENCY",
      "DATA_TESTS",
      "GLOBAL_CONSISTENCY",
      "HUMAN_ADJUDICATION",
    ]),
    status: z.enum(["PASSED", "FAILED", "SKIPPED", "REVIEW_REQUIRED"]),
    details: z.string(),
    evidenceIds: z.array(z.string()),
  })
  .strict();

export const responseMetaFieldNames = [
  "ontologyVersion",
  "traceId",
  "tenantId",
  "publicationState",
  "servingMode",
  "isPublished",
  "evidence",
  "warnings",
  "status",
  "generatedAt",
] as const;

export const responseMetaSchema = z
  .object({
    ontologyVersion: z.string(),
    traceId: z.string(),
    tenantId: z.string().regex(/^[a-z][a-z0-9-]{2,63}$/),
    publicationState: z.enum(["CANDIDATE", "PUBLISHED"]),
    servingMode: z.enum(["DEMO_ONLY", "ACTIVE"]),
    isPublished: z.boolean(),
    evidence: z.array(evidenceReferenceSchema),
    warnings: z.array(z.string()),
    status: z.enum(["OK", "PARTIAL", "ABSTAINED"]),
    generatedAt: z.string().datetime(),
  })
  .strict();

export type ConnectorManifest = z.infer<typeof connectorManifestSchema>;
export type ProposalStatus = z.infer<typeof proposalStatusSchema>;
export type ProposalKind = z.infer<typeof proposalKindSchema>;
export type ProposalEvidence = z.infer<typeof proposalEvidenceSchema>;
export type EvidenceReference = z.infer<typeof evidenceReferenceSchema>;
export type ConfidenceVector = z.infer<typeof confidenceVectorSchema>;
export type GateResult = z.infer<typeof gateResultSchema>;
export type Proposal = z.infer<typeof proposalSchema>;
export type ResponseMeta = z.infer<typeof responseMetaSchema>;
