import { createHash } from "node:crypto";

import { assertUtcDay, assertUtcTimestamp } from "./identifiers";
import type { SourceProfile } from "./profiling";

export const DISCOVERY_ALGORITHM_VERSION = "firebase-source-profile-discovery/1.0.0";
export const DRIFT_ALGORITHM_VERSION = "firebase-source-profile-drift/1.0.0";
export const VERIFICATION_POLICY_VERSION = "semantic-verification-policy-v1";

const SHA256 = /^[a-f0-9]{64}$/u;
const PROPOSAL_KINDS = new Set([
  "concept",
  "relation",
  "alias",
  "mapping",
  "duplicate",
  "constraint",
  "assertion",
  "drift",
]);
const RISKS = new Set(["low", "medium", "high"]);
const PROPOSAL_CONTRACT_FIELDS = [
  "schema_version",
  "proposal_id",
  "tenant_id",
  "kind",
  "risk",
  "source_snapshot_ids",
  "active_ontology_version",
  "source_locator",
  "target_iri",
  "transformation",
  "evidence",
  "counterevidence",
  "confidence",
  "generator",
  "algorithm_version",
  "deterministic_input",
  "deterministic_input_hash",
  "status",
  "reason_codes",
] as const;

type ProposalStatus = "PENDING_VERIFICATION" | "HUMAN_REVIEW" | "ABSTAINED";
type Risk = "low" | "medium" | "high";

export interface EvidenceDocument {
  evidence_id: string;
  tenant_id: string;
  source_id: string;
  snapshot_id: string;
  locator: string;
  observed_at: string;
  extractor_version: string;
  content_sha256: string;
  claim: string;
}

export interface ConfidenceVector {
  lexical: number;
  structural: number;
  instance: number;
  external: number;
  model: number;
  evidence_coverage: number;
}

export interface ProposalDocument {
  schema_version: "1.0";
  proposal_id: string;
  tenant_id: string;
  kind: "assertion" | "drift";
  risk: Risk;
  source_snapshot_ids: string[];
  active_ontology_version: string;
  source_locator: string;
  target_iri: string;
  transformation: string;
  evidence: EvidenceDocument[];
  counterevidence: EvidenceDocument[];
  confidence: ConfidenceVector;
  generator: {
    mode: "deterministic";
    model_participated: false;
    provider: "ontology-appliance";
    model: string;
    provider_returned_model_id: null;
    prompt_version: "not-applicable";
    parameters: Record<string, unknown>;
    token_usage: null;
    latency_ms: 0;
    response_status: "not_invoked";
  };
  algorithm_version: string;
  deterministic_input: Record<string, unknown>;
  deterministic_input_hash: string;
  status: "PENDING_VERIFICATION";
  reason_codes: string[];
}

export interface IngestionProposalInput {
  tenantId: string;
  sourceId: string;
  bucket: string;
  objectName: string;
  generation: string;
  contentType: string;
  sizeBytes: number;
  observedAt: string;
  activeOntologyVersion: string;
  profile: SourceProfile;
}

export interface DriftSource {
  sourceId: string;
  snapshotId: string;
  sha256: string;
  previousSha256: string;
  evidenceLocator: string;
  observedAt: string;
  extractorVersion: string;
}

export interface DriftProposalInput {
  tenantId: string;
  scheduledDay: string;
  evaluatedAt: string;
  activeOntologyVersion: string;
  changedSources: DriftSource[];
}

type GateName =
  | "CONTRACT"
  | "SEMANTIC"
  | "SOURCE_EVIDENCE"
  | "INDEPENDENT_QUESTIONS"
  | "MODEL_CONSISTENCY"
  | "DATA_TESTS"
  | "GLOBAL_CONSISTENCY"
  | "HUMAN_ADJUDICATION";

type GateStatus = "PASSED" | "FAILED" | "SKIPPED" | "REVIEW_REQUIRED";

export interface GateResultDocument {
  gateResultId: string;
  verificationRunId: string;
  proposalId: string;
  order: number;
  gate: GateName;
  status: GateStatus;
  details: string;
  evidenceIds: string[];
  evaluatedAt: string;
  policyVersion: string;
}

export interface VerificationDecision {
  status: Exclude<ProposalStatus, "PENDING_VERIFICATION">;
  reasonCodes: string[];
  frozenProposalSha256: string;
  run: Record<string, unknown>;
  gates: GateResultDocument[];
  proposalUpdate: Record<string, unknown>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function canonicalJson(value: unknown, ancestors = new Set<object>()): string {
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Cannot hash a non-finite number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    if (ancestors.has(value)) throw new Error("Cannot hash a cyclic value");
    const next = new Set(ancestors).add(value);
    return `[${value.map((item) => canonicalJson(item, next)).join(",")}]`;
  }
  if (isRecord(value)) {
    if (ancestors.has(value)) throw new Error("Cannot hash a cyclic value");
    const next = new Set(ancestors).add(value);
    const pairs = Object.keys(value)
      .filter((key) => value[key] !== undefined)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key], next)}`);
    return `{${pairs.join(",")}}`;
  }
  throw new Error("Cannot hash an unsupported value");
}

export function canonicalSha256(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function proposalContractPayload(proposal: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    PROPOSAL_CONTRACT_FIELDS.filter(
      (field) => proposal[field] !== undefined,
    ).map((field) => [field, proposal[field]]),
  );
}

function deterministicGenerator(model: string): ProposalDocument["generator"] {
  return {
    mode: "deterministic",
    model_participated: false,
    provider: "ontology-appliance",
    model,
    provider_returned_model_id: null,
    prompt_version: "not-applicable",
    parameters: {},
    token_usage: null,
    latency_ms: 0,
    response_status: "not_invoked",
  };
}

export interface SnapshotIdentity {
  sha256: string;
  snapshotId: string;
}

/**
 * A stored snapshot is content-addressed: its document key and identity are
 * the content hash, and its object coordinates record the first observation.
 * Re-observing byte-identical content under a new object or generation is a
 * legitimate event, not an immutability violation; only a stored snapshot
 * whose identity fields no longer match its content-derived key conflicts.
 */
export function immutableSnapshotConflict(
  stored: Record<string, unknown> | undefined,
  expected: SnapshotIdentity,
): boolean {
  if (stored === undefined) return true;
  return stored.sha256 !== expected.sha256 || stored.snapshotId !== expected.snapshotId;
}

export function buildIngestionProposal(
  input: IngestionProposalInput,
): ProposalDocument {
  assertUtcTimestamp(input.observedAt);
  if (!SHA256.test(input.profile.sha256)) throw new Error("Invalid source SHA-256");
  if (!Number.isSafeInteger(input.sizeBytes) || input.sizeBytes < 1) {
    throw new Error("Invalid source size");
  }
  const snapshotId = `${input.sourceId}@sha256:${input.profile.sha256}`;
  const locator = `gs://${input.bucket}/${input.objectName}#generation=${input.generation}`;
  const deterministicInput: Record<string, unknown> = {
    tenantId: input.tenantId,
    sourceId: input.sourceId,
    sourceSnapshotIds: [snapshotId],
    ontologyVersion: input.activeOntologyVersion,
    sourceObject: {
      bucket: input.bucket,
      name: input.objectName,
      generation: input.generation,
      contentType: input.contentType,
      sizeBytes: input.sizeBytes,
    },
    profile: {
      contentSha256: input.profile.sha256,
      byteSize: input.profile.byteSize,
      recordCount: input.profile.recordCount,
      mediaType: input.profile.mediaType,
      extractorVersion: input.profile.extractorVersion,
    },
    algorithmVersion: DISCOVERY_ALGORITHM_VERSION,
  };
  const deterministicInputHash = canonicalSha256(deterministicInput);
  const proposalId = `ingestion-${deterministicInputHash}`;
  const evidenceId = `evidence-${canonicalSha256({
    snapshotId,
    locator,
    extractorVersion: input.profile.extractorVersion,
  })}`;
  return {
    schema_version: "1.0",
    proposal_id: proposalId,
    tenant_id: input.tenantId,
    kind: "assertion",
    risk: "low",
    source_snapshot_ids: [snapshotId],
    active_ontology_version: input.activeOntologyVersion,
    source_locator: locator,
    target_iri: `urn:ontology-appliance:${input.tenantId}:source:${input.sourceId}:snapshot:${input.profile.sha256}`,
    transformation:
      "register immutable metadata profile as a discovery candidate; do_not_publish",
    evidence: [
      {
        evidence_id: evidenceId,
        tenant_id: input.tenantId,
        source_id: input.sourceId,
        snapshot_id: snapshotId,
        locator,
        observed_at: input.observedAt,
        extractor_version: input.profile.extractorVersion,
        content_sha256: input.profile.sha256,
        claim:
          "The immutable object generation produced this bounded metadata-only source profile.",
      },
    ],
    counterevidence: [],
    confidence: {
      lexical: 0,
      structural: 1,
      instance: input.profile.recordCount === null ? 0 : 1,
      external: 0,
      model: 0,
      evidence_coverage: 1,
    },
    generator: deterministicGenerator("firebase-metadata-profiler-v1"),
    algorithm_version: DISCOVERY_ALGORITHM_VERSION,
    deterministic_input: deterministicInput,
    deterministic_input_hash: deterministicInputHash,
    status: "PENDING_VERIFICATION",
    reason_codes: ["IMMUTABLE_SOURCE_PROFILE_READY_FOR_VERIFICATION"],
  };
}

export function buildDriftProposal(
  input: DriftProposalInput,
): ProposalDocument | null {
  assertUtcDay(input.scheduledDay);
  assertUtcTimestamp(input.evaluatedAt);
  if (input.changedSources.length === 0) return null;

  const changedSources = [...input.changedSources].sort((left, right) =>
    left.sourceId.localeCompare(right.sourceId),
  );
  for (const source of changedSources) {
    assertUtcTimestamp(source.observedAt);
    if (!SHA256.test(source.sha256) || !SHA256.test(source.previousSha256)) {
      throw new Error("Invalid drift source SHA-256");
    }
    if (!source.snapshotId || !source.evidenceLocator || !source.extractorVersion) {
      throw new Error("Incomplete drift source evidence");
    }
  }

  const sourceSnapshotIds = changedSources.map((source) => source.snapshotId);
  const deterministicInput: Record<string, unknown> = {
    tenantId: input.tenantId,
    ontologyVersion: input.activeOntologyVersion,
    changedSources: changedSources.map((source) => ({
      sourceId: source.sourceId,
      snapshotId: source.snapshotId,
      contentSha256: source.sha256,
      previousContentSha256: source.previousSha256,
      evidenceLocator: source.evidenceLocator,
      extractorVersion: source.extractorVersion,
    })),
    algorithmVersion: DRIFT_ALGORITHM_VERSION,
  };
  const deterministicInputHash = canonicalSha256(deterministicInput);
  // A source change is one semantic fact even if the scheduler observes it on
  // multiple days. The daily check remains separately timestamped in Firestore.
  const proposalId = `drift-${deterministicInputHash}`;
  const evidence = changedSources.map((source) => ({
    evidence_id: `evidence-${canonicalSha256({
      sourceId: source.sourceId,
      snapshotId: source.snapshotId,
      current: source.sha256,
      previous: source.previousSha256,
    })}`,
    tenant_id: input.tenantId,
    source_id: source.sourceId,
    snapshot_id: source.snapshotId,
    locator: source.evidenceLocator,
    observed_at: source.observedAt,
    extractor_version: source.extractorVersion,
    content_sha256: source.sha256,
    claim: `The current immutable source profile differs from previous SHA-256 ${source.previousSha256}.`,
  }));
  return {
    schema_version: "1.0",
    proposal_id: proposalId,
    tenant_id: input.tenantId,
    kind: "drift",
    risk: "medium",
    source_snapshot_ids: sourceSnapshotIds,
    active_ontology_version: input.activeOntologyVersion,
    source_locator: `firestore://tenants/${input.tenantId}/sourceProfiles#change=${deterministicInputHash}`,
    target_iri: `urn:ontology-appliance:${input.tenantId}:source-drift:${deterministicInputHash}`,
    transformation:
      "compare immutable source profile hashes; route semantic impact to independent verification",
    evidence,
    counterevidence: [],
    confidence: {
      lexical: 0,
      structural: 1,
      instance: 0,
      external: 0,
      model: 0,
      evidence_coverage: 1,
    },
    generator: deterministicGenerator("firebase-profile-drift-v1"),
    algorithm_version: DRIFT_ALGORITHM_VERSION,
    deterministic_input: deterministicInput,
    deterministic_input_hash: deterministicInputHash,
    status: "PENDING_VERIFICATION",
    reason_codes: ["SOURCE_CONTENT_HASH_CHANGED"],
  };
}

function validateEvidence(
  value: unknown,
  tenantId: string,
  snapshotIds: Set<string>,
  label: string,
): { errors: string[]; evidenceIds: string[] } {
  if (!Array.isArray(value)) {
    return { errors: [`${label} must be an array`], evidenceIds: [] };
  }
  const errors: string[] = [];
  const evidenceIds: string[] = [];
  for (const [index, item] of value.entries()) {
    if (!isRecord(item)) {
      errors.push(`${label}[${index}] is not an object`);
      continue;
    }
    const allowedFields = new Set([
      "evidence_id",
      "tenant_id",
      "source_id",
      "snapshot_id",
      "locator",
      "observed_at",
      "extractor_version",
      "content_sha256",
      "claim",
    ]);
    const unexpectedFields = Object.keys(item).filter(
      (field) => !allowedFields.has(field),
    );
    if (unexpectedFields.length > 0) {
      errors.push(`${label}[${index}] has unexpected fields`);
    }
    const evidenceId = item.evidence_id;
    if (typeof evidenceId !== "string" || evidenceId.length === 0) {
      errors.push(`${label}[${index}] has no evidence_id`);
    } else {
      evidenceIds.push(evidenceId);
    }
    if (item.tenant_id !== tenantId) errors.push(`${label}[${index}] tenant mismatch`);
    if (typeof item.source_id !== "string" || item.source_id.length === 0) {
      errors.push(`${label}[${index}] has no source_id`);
    }
    if (typeof item.snapshot_id !== "string" || !snapshotIds.has(item.snapshot_id)) {
      errors.push(`${label}[${index}] references an unpinned snapshot`);
    }
    if (typeof item.locator !== "string" || item.locator.length === 0) {
      errors.push(`${label}[${index}] has no locator`);
    }
    if (typeof item.observed_at !== "string") {
      errors.push(`${label}[${index}] has no observed_at`);
    } else {
      try {
        assertUtcTimestamp(item.observed_at);
      } catch {
        errors.push(`${label}[${index}] observed_at is not UTC`);
      }
    }
    if (
      typeof item.extractor_version !== "string" ||
      item.extractor_version.length === 0
    ) {
      errors.push(`${label}[${index}] has no extractor_version`);
    }
    if (typeof item.content_sha256 !== "string" || !SHA256.test(item.content_sha256)) {
      errors.push(`${label}[${index}] has invalid content_sha256`);
    }
    if (
      item.claim !== undefined &&
      (typeof item.claim !== "string" || item.claim.length > 2_000)
    ) {
      errors.push(`${label}[${index}] has invalid claim`);
    }
  }
  if (new Set(evidenceIds).size !== evidenceIds.length) {
    errors.push(`${label} contains duplicate evidence_id values`);
  }
  return { errors, evidenceIds };
}

function validateConfidence(value: unknown): string[] {
  if (!isRecord(value)) return ["confidence must be an object"];
  const errors: string[] = [];
  const names = [
    "lexical",
    "structural",
    "instance",
    "external",
    "model",
    "evidence_coverage",
  ];
  if (Object.keys(value).some((name) => !names.includes(name))) {
    errors.push("confidence contains an unexplained dimension or scalar");
  }
  for (const name of names) {
    const score = value[name];
    if (typeof score !== "number" || !Number.isFinite(score) || score < 0 || score > 1) {
      errors.push(`confidence.${name} must be between zero and one`);
    }
  }
  return errors;
}

function validateGenerator(value: unknown): string[] {
  if (!isRecord(value)) return ["generator must be an object"];
  const errors: string[] = [];
  const fields = new Set([
    "mode",
    "model_participated",
    "provider",
    "model",
    "provider_returned_model_id",
    "prompt_version",
    "parameters",
    "token_usage",
    "latency_ms",
    "response_status",
  ]);
  if (Object.keys(value).some((field) => !fields.has(field))) {
    errors.push("generator contains unexpected fields");
  }
  if (value.mode !== "deterministic" && value.mode !== "live") {
    errors.push("generator.mode is invalid");
  }
  if (typeof value.model_participated !== "boolean") {
    errors.push("generator.model_participated is invalid");
  }
  for (const field of ["provider", "model", "prompt_version", "response_status"]) {
    if (typeof value[field] !== "string" || value[field].length === 0) {
      errors.push(`generator.${field} is required`);
    }
  }
  if (!isRecord(value.parameters)) errors.push("generator.parameters is invalid");
  if (
    value.provider_returned_model_id !== null &&
    typeof value.provider_returned_model_id !== "string"
  ) {
    errors.push("generator.provider_returned_model_id is invalid");
  }
  if (value.token_usage !== null && !isRecord(value.token_usage)) {
    errors.push("generator.token_usage is invalid");
  }
  if (
    typeof value.latency_ms !== "number" ||
    !Number.isInteger(value.latency_ms) ||
    value.latency_ms < 0
  ) {
    errors.push("generator.latency_ms is invalid");
  }
  return errors;
}

function validateProposal(
  proposal: Record<string, unknown>,
  tenantId: string,
  proposalId: string,
): { errors: string[]; evidenceIds: string[] } {
  const errors: string[] = [];
  if (proposal.schema_version !== "1.0") errors.push("schema_version is unsupported");
  if (proposal.proposal_id !== proposalId) errors.push("proposal_id does not match path");
  if (proposal.tenant_id !== tenantId) errors.push("tenant_id does not match task identity");
  if (typeof proposal.kind !== "string" || !PROPOSAL_KINDS.has(proposal.kind)) {
    errors.push("kind is invalid");
  }
  if (typeof proposal.risk !== "string" || !RISKS.has(proposal.risk)) {
    errors.push("risk is invalid");
  }
  const snapshotIds = Array.isArray(proposal.source_snapshot_ids)
    ? proposal.source_snapshot_ids.filter(
        (snapshot): snapshot is string => typeof snapshot === "string" && snapshot.length > 0,
      )
    : [];
  if (
    !Array.isArray(proposal.source_snapshot_ids) ||
    snapshotIds.length === 0 ||
    snapshotIds.length !== proposal.source_snapshot_ids.length
  ) {
    errors.push("source_snapshot_ids must contain pinned identifiers");
  }
  if (new Set(snapshotIds).size !== snapshotIds.length) {
    errors.push("source_snapshot_ids must be unique");
  }
  for (const field of [
    "active_ontology_version",
    "source_locator",
    "target_iri",
    "transformation",
    "algorithm_version",
  ]) {
    if (typeof proposal[field] !== "string" || proposal[field].length === 0) {
      errors.push(`${field} is required`);
    }
  }
  if (proposal.status !== "PENDING_VERIFICATION") {
    errors.push("proposal is not pending verification");
  }
  if (
    !Array.isArray(proposal.reason_codes) ||
    proposal.reason_codes.length === 0 ||
    proposal.reason_codes.some((code) => typeof code !== "string" || code.length === 0)
  ) {
    errors.push("reason_codes are invalid");
  }
  if (!isRecord(proposal.deterministic_input)) {
    errors.push("deterministic_input must be an object");
  } else {
    try {
      if (
        typeof proposal.deterministic_input_hash !== "string" ||
        !SHA256.test(proposal.deterministic_input_hash) ||
        canonicalSha256(proposal.deterministic_input) !==
          proposal.deterministic_input_hash
      ) {
        errors.push("deterministic_input_hash does not match deterministic_input");
      }
    } catch {
      errors.push("deterministic_input contains unsupported values");
    }
  }
  errors.push(...validateConfidence(proposal.confidence));
  errors.push(...validateGenerator(proposal.generator));

  const evidence = validateEvidence(
    proposal.evidence,
    tenantId,
    new Set(snapshotIds),
    "evidence",
  );
  const counterevidence = validateEvidence(
    proposal.counterevidence,
    tenantId,
    new Set(snapshotIds),
    "counterevidence",
  );
  errors.push(...evidence.errors, ...counterevidence.errors);
  if (!Array.isArray(proposal.evidence) || proposal.evidence.length === 0) {
    errors.push("at least one evidence item is required");
  }
  return {
    errors,
    evidenceIds: [...evidence.evidenceIds, ...counterevidence.evidenceIds],
  };
}

function gate(
  order: number,
  name: GateName,
  status: GateStatus,
  details: string,
  evidenceIds: string[],
  runId: string,
  proposalId: string,
  evaluatedAt: string,
): GateResultDocument {
  return {
    gateResultId: `${String(order).padStart(2, "0")}-${name.toLowerCase().replaceAll("_", "-")}`,
    verificationRunId: runId,
    proposalId,
    order,
    gate: name,
    status,
    details,
    evidenceIds,
    evaluatedAt,
    policyVersion: VERIFICATION_POLICY_VERSION,
  };
}

export function buildVerificationDecision(
  tenantId: string,
  proposalId: string,
  runId: string,
  evaluatedAt: string,
  value: unknown,
): VerificationDecision {
  assertUtcTimestamp(evaluatedAt);
  const proposal = isRecord(value) ? value : {};
  const frozenPayload = proposalContractPayload(proposal);
  const validation = validateProposal(proposal, tenantId, proposalId);
  const valid = validation.errors.length === 0;
  const status = valid ? "HUMAN_REVIEW" : "ABSTAINED";
  const reasonCodes = valid
    ? ["INDEPENDENT_VERIFIER_NOT_CONFIGURED", "STEWARD_REVIEW_REQUIRED"]
    : ["CONTRACT_OR_EVIDENCE_INCOMPLETE", "VERIFIER_ABSTAINED"];
  const frozenProposalSha256 = canonicalSha256(frozenPayload);
  const evidence = Array.isArray(proposal.evidence) ? proposal.evidence : [];
  const counterevidence = Array.isArray(proposal.counterevidence)
    ? proposal.counterevidence
    : [];
  const frozenEvidenceIndexSha256 = canonicalSha256({ evidence, counterevidence });
  const contractDetail = valid
    ? "The frozen proposal matches the required tenant-bound contract."
    : `Verification abstained because ${validation.errors.slice(0, 5).join("; ")}.`;
  const gates = [
    gate(
      1,
      "CONTRACT",
      valid ? "PASSED" : "FAILED",
      contractDetail,
      [],
      runId,
      proposalId,
      evaluatedAt,
    ),
    gate(
      2,
      "SEMANTIC",
      "SKIPPED",
      "RDF, SHACL, and namespace evaluation is not implemented in the Functions control plane.",
      [],
      runId,
      proposalId,
      evaluatedAt,
    ),
    gate(
      3,
      "SOURCE_EVIDENCE",
      valid ? "PASSED" : "FAILED",
      valid
        ? "Every evidence item is tenant-bound, content-addressed, and tied to a pinned snapshot."
        : "Source evidence is incomplete or does not match the frozen proposal.",
      validation.evidenceIds,
      runId,
      proposalId,
      evaluatedAt,
    ),
    gate(
      4,
      "INDEPENDENT_QUESTIONS",
      "SKIPPED",
      "No independent question-answering verifier is configured.",
      validation.evidenceIds,
      runId,
      proposalId,
      evaluatedAt,
    ),
    gate(
      5,
      "MODEL_CONSISTENCY",
      "SKIPPED",
      "No independent model result exists; agreement remains null.",
      [],
      runId,
      proposalId,
      evaluatedAt,
    ),
    gate(
      6,
      "DATA_TESTS",
      valid ? "REVIEW_REQUIRED" : "SKIPPED",
      valid
        ? "The metadata profile is reproducible, but semantic data assertions require steward review."
        : "Data tests cannot run against an invalid or incomplete proposal.",
      validation.evidenceIds,
      runId,
      proposalId,
      evaluatedAt,
    ),
    gate(
      7,
      "GLOBAL_CONSISTENCY",
      "SKIPPED",
      "Global graph impact is not established by the metadata-only Functions workflow.",
      [],
      runId,
      proposalId,
      evaluatedAt,
    ),
    gate(
      8,
      "HUMAN_ADJUDICATION",
      valid ? "REVIEW_REQUIRED" : "SKIPPED",
      valid
        ? "An authorized steward must adjudicate this proposal before any Publisher workflow can consume it."
        : "The verifier abstained; repair the proposal or its evidence before adjudication.",
      validation.evidenceIds,
      runId,
      proposalId,
      evaluatedAt,
    ),
  ];
  const risk = RISKS.has(String(proposal.risk)) ? proposal.risk : "unknown";
  const sourceSnapshotIds = Array.isArray(proposal.source_snapshot_ids)
    ? proposal.source_snapshot_ids.filter((item): item is string => typeof item === "string")
    : [];
  const activeOntologyVersion =
    typeof proposal.active_ontology_version === "string"
      ? proposal.active_ontology_version
      : "unknown";
  const runPayload: Record<string, unknown> = {
    schema_version: "1.0",
    verification_run_id: runId,
    policy_version: VERIFICATION_POLICY_VERSION,
    proposal_id: proposalId,
    tenant_id: tenantId,
    risk,
    frozen_proposal_sha256: frozenProposalSha256,
    frozen_proposal: frozenPayload,
    frozen_evidence_index_sha256: frozenEvidenceIndexSha256,
    source_snapshot_ids: sourceSnapshotIds,
    active_ontology_version: activeOntologyVersion,
    evidence,
    counterevidence,
    confidence: isRecord(proposal.confidence) ? proposal.confidence : null,
    checks: {
      contract_valid: valid,
      provenance_complete: valid,
      semantic_valid: null,
      data_assertions_valid: null,
      global_consistency_valid: null,
    },
    models: {
      mode: "disabled",
      generator: isRecord(proposal.generator) ? proposal.generator : null,
      verifier: {
        provider: "not-configured",
        model: "not-invoked",
        prompt_version: "not-applicable",
        store: false,
        independent_model: false,
        response_status: "abstained",
      },
      independent_agreement: null,
    },
    gate_result: { status, reason_codes: reasonCodes },
    // The run digest must commit to the complete, ordered gate evidence rather
    // than only to document identifiers stored in the gateResults subcollection.
    gate_results: gates,
    gate_result_ids: gates.map((result) => result.gateResultId),
    status,
    review_requirement:
      status === "HUMAN_REVIEW"
        ? "An authorized steward must review the proposal; Functions cannot publish it."
        : "The verifier abstained because contract or evidence requirements were not met.",
    decided_at: evaluatedAt,
  };
  const verificationRunSha256 = canonicalSha256(runPayload);
  const run: Record<string, unknown> = {
    ...runPayload,
    verification_run_sha256: verificationRunSha256,
  };
  return {
    status,
    reasonCodes,
    frozenProposalSha256,
    run,
    gates,
    proposalUpdate: {
      status,
      reason_codes: reasonCodes,
      verificationRunId: runId,
      verificationRunSha256,
      frozenProposalSha256,
      frozenEvidenceIndexSha256,
      verificationPolicyVersion: VERIFICATION_POLICY_VERSION,
      gateSummary: gates.map((result) => ({
        gate: result.gate,
        status: result.status,
      })),
      verifiedAt: evaluatedAt,
    },
  };
}
