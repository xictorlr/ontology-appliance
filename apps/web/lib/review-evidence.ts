import { createHash } from "node:crypto";

const sha256 = /^[a-f0-9]{64}$/u;
const expectedGates = [
  "CONTRACT",
  "SEMANTIC",
  "SOURCE_EVIDENCE",
  "INDEPENDENT_QUESTIONS",
  "MODEL_CONSISTENCY",
  "DATA_TESTS",
  "GLOBAL_CONSISTENCY",
  "HUMAN_ADJUDICATION",
] as const;
const gateStatuses = new Set(["PASSED", "FAILED", "SKIPPED", "REVIEW_REQUIRED"]);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function canonicalJson(value: unknown, ancestors = new Set<object>()): string {
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Cannot hash a non-finite number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    if (ancestors.has(value)) throw new Error("Cannot hash a cyclic value");
    const next = new Set(ancestors).add(value);
    return `[${value.map((item) => canonicalJson(item, next)).join(",")}]`;
  }
  if (record(value)) {
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

export type BoundGate = {
  name: (typeof expectedGates)[number];
  status: "PASSED" | "FAILED" | "SKIPPED" | "REVIEW_REQUIRED";
};

export type ReviewEvidenceBinding = {
  frozenEvidenceIndexSha256: string;
  frozenProposal: Record<string, unknown>;
  frozenProposalSha256: string;
  gates: BoundGate[];
  verificationRunSha256: string;
};

export type ApprovalPolicyDecision = {
  eligible: boolean;
  reasonCodes: string[];
};

const approvalPolicyVersion = "semantic-verification-policy-v1";
const providerAliases: Record<string, string> = {
  anthropic: "anthropic",
  "anthropic-ai": "anthropic",
  claude: "anthropic",
  "open-ai": "openai",
  openai: "openai",
  gemini: "google-vertex-ai",
  google: "google-vertex-ai",
  "google-cloud-vertex-ai": "google-vertex-ai",
  "google-genai": "google-vertex-ai",
  "google-generative-ai": "google-vertex-ai",
  "google-vertex": "google-vertex-ai",
  "google-vertex-ai": "google-vertex-ai",
  vertex: "google-vertex-ai",
  "vertex-ai": "google-vertex-ai",
};

function normalizedIdentifier(value: string): string {
  return value
    .normalize("NFKC")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, "-")
    .replace(/^-+|-+$/gu, "");
}

function normalizedProvider(value: string): string {
  const normalized = normalizedIdentifier(value);
  return providerAliases[normalized] ?? normalized;
}

function normalizedModel(value: string): string {
  const leaf = value.trim().replace(/\/+$/gu, "").split("/").at(-1) ?? "";
  let normalized = normalizedIdentifier(leaf).replace(
    /^(?:google-vertex-ai|vertex-ai|anthropic|openai|google|models?)-+/u,
    "",
  );
  let previous: string | undefined;
  while (normalized && previous !== normalized) {
    previous = normalized;
    normalized = normalized
      .replace(/-(?:vertex|preview|snapshot)-20\d{6}$/u, "")
      .replace(/-20\d{2}-\d{2}-\d{2}$/u, "")
      .replace(/-20\d{6}$/u, "")
      .replace(/-(?:latest|stable)$/u, "");
  }
  return normalized;
}

/**
 * Recompute every content address used by a steward decision. Firestore field
 * copies and syntactically valid digests are not evidence on their own.
 */
export function bindReviewEvidence(
  proposal: Record<string, unknown>,
  run: Record<string, unknown>,
): ReviewEvidenceBinding | null {
  try {
    const verificationRunSha256 = run.verification_run_sha256;
    const frozenProposalSha256 = run.frozen_proposal_sha256;
    const frozenEvidenceIndexSha256 = run.frozen_evidence_index_sha256;
    if (
      typeof verificationRunSha256 !== "string" || !sha256.test(verificationRunSha256) ||
      typeof frozenProposalSha256 !== "string" || !sha256.test(frozenProposalSha256) ||
      typeof frozenEvidenceIndexSha256 !== "string" || !sha256.test(frozenEvidenceIndexSha256) ||
      !record(run.frozen_proposal) ||
      !Array.isArray(run.evidence) ||
      !Array.isArray(run.counterevidence) ||
      !Array.isArray(run.gate_results) ||
      !Array.isArray(run.gate_result_ids)
    ) return null;

    const runPayload = Object.fromEntries(
      Object.entries(run).filter(([key]) => key !== "verification_run_sha256"),
    );
    if (canonicalSha256(runPayload) !== verificationRunSha256) return null;
    if (canonicalSha256(run.frozen_proposal) !== frozenProposalSha256) return null;
    if (
      canonicalSha256({ evidence: run.evidence, counterevidence: run.counterevidence }) !==
      frozenEvidenceIndexSha256
    ) return null;

    const gateResults = run.gate_results;
    const gateResultIds = run.gate_result_ids;
    if (
      gateResults.length !== expectedGates.length ||
      gateResultIds.length !== expectedGates.length ||
      new Set(gateResultIds).size !== expectedGates.length
    ) return null;
    const gates = gateResults.flatMap((value, index): BoundGate[] => {
      if (!record(value)) return [];
      const expectedName = expectedGates[index];
      if (
        expectedName === undefined ||
        value.gate !== expectedName ||
        value.order !== index + 1 ||
        typeof value.gateResultId !== "string" ||
        !value.gateResultId.trim() ||
        gateResultIds[index] !== value.gateResultId ||
        typeof value.status !== "string" ||
        !gateStatuses.has(value.status)
      ) return [];
      return [{ name: expectedName, status: value.status as BoundGate["status"] }];
    });
    if (gates.length !== expectedGates.length) return null;

    if (
      proposal.verificationRunSha256 !== verificationRunSha256 ||
      proposal.frozenProposalSha256 !== frozenProposalSha256 ||
      proposal.frozenEvidenceIndexSha256 !== frozenEvidenceIndexSha256
    ) return null;

    return {
      frozenEvidenceIndexSha256,
      frozenProposal: run.frozen_proposal,
      frozenProposalSha256,
      gates,
      verificationRunSha256,
    };
  } catch {
    return null;
  }
}

/**
 * A steward approval is deliberately narrower than the ability to record a
 * review. The complete run must first be content-bound, low-risk, produced by
 * the current policy, and backed by a live independent verifier agreement.
 */
export function evaluateApprovalPolicy(
  proposal: Record<string, unknown>,
  run: Record<string, unknown>,
): ApprovalPolicyDecision {
  const binding = bindReviewEvidence(proposal, run);
  if (binding === null) {
    return { eligible: false, reasonCodes: ["VERIFICATION_RUN_NOT_HASH_BOUND"] };
  }

  const reasons: string[] = [];
  if (run.policy_version !== approvalPolicyVersion) reasons.push("POLICY_VERSION_NOT_APPROVABLE");
  if (
    !["low", "medium", "high"].includes(String(run.risk)) ||
    run.risk !== binding.frozenProposal.risk
  ) {
    reasons.push("RISK_POLICY_MISMATCH");
  }
  if (run.status !== "HUMAN_REVIEW") reasons.push("RUN_NOT_AWAITING_HUMAN_ADJUDICATION");

  const models = record(run.models) ? run.models : {};
  const generator = record(models.generator) ? models.generator : {};
  const verifier = record(models.verifier) ? models.verifier : {};
  const frozenGenerator = record(binding.frozenProposal.generator)
    ? binding.frozenProposal.generator
    : {};
  if (models.mode !== "live") reasons.push("LIVE_VERIFIER_REQUIRED");
  if (verifier.independent_model !== true) reasons.push("INDEPENDENT_MODEL_REQUIRED");
  if (models.independent_agreement !== true) reasons.push("INDEPENDENT_AGREEMENT_REQUIRED");
  if (canonicalSha256(generator) !== canonicalSha256(frozenGenerator)) {
    reasons.push("GENERATOR_TRACE_NOT_FROZEN");
  }
  const generatorProvider = typeof generator.provider === "string"
    ? normalizedProvider(generator.provider)
    : "";
  const generatorModel = typeof generator.model === "string"
    ? normalizedModel(generator.model)
    : "";
  const verifierProvider = typeof verifier.provider === "string"
    ? normalizedProvider(verifier.provider)
    : "";
  const verifierModel = typeof verifier.model === "string"
    ? normalizedModel(verifier.model)
    : "";
  if (
    !generatorProvider ||
    !generatorModel ||
    !verifierProvider ||
    !verifierModel ||
    generatorProvider === verifierProvider ||
    generatorModel === verifierModel
  ) {
    reasons.push("GENERATOR_VERIFIER_SEPARATION_REQUIRED");
  }

  for (const gate of binding.gates) {
    const allowed = gate.name === "HUMAN_ADJUDICATION"
      ? gate.status === "PASSED" || gate.status === "REVIEW_REQUIRED"
      : gate.status === "PASSED";
    if (!allowed) reasons.push(`GATE_${gate.name}_${gate.status}`);
  }

  return { eligible: reasons.length === 0, reasonCodes: reasons };
}
