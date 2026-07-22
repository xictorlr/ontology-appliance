import type { ProposalView } from "./demo-data";
import { bindReviewEvidence, evaluateApprovalPolicy } from "./review-evidence";

const proposalKinds = {
  alias: "Alias",
  assertion: "Assertion",
  concept: "Concept",
  constraint: "Constraint",
  drift: "Drift",
  duplicate: "Duplicate",
  mapping: "Mapping",
  relation: "Relation",
} as const;

const proposalRisks = {
  high: "High",
  low: "Low",
  medium: "Medium",
} as const;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function confidence(value: unknown): Array<{ label: string; value: number }> {
  if (!record(value)) return [];
  return ([
    ["Lexical", "lexical"],
    ["Structural", "structural"],
    ["Instance", "instance"],
    ["External", "external"],
    ["Model", "model"],
    ["Evidence coverage", "evidence_coverage"],
  ] as const).flatMap(([label, key]) => {
    const score = value[key];
    return typeof score === "number" && Number.isFinite(score) && score >= 0 && score <= 1
      ? [{ label, value: Math.round(score * 100) }]
      : [];
  });
}

/**
 * Build the reviewer projection exclusively from the validated frozen proposal
 * and hash-bound verification run. The mutable proposal document contributes
 * only workflow state and the receipt pointer/decision.
 */
export function buildReviewProposalView(
  proposalId: string,
  tenantId: string,
  proposalState: Record<string, unknown>,
  run: Record<string, unknown>,
): ProposalView | null {
  const binding = bindReviewEvidence(proposalState, run);
  if (binding === null) return null;
  const frozen = binding.frozenProposal;
  if (
    run.proposal_id !== proposalId ||
    run.tenant_id !== tenantId ||
    frozen.proposal_id !== proposalId ||
    frozen.tenant_id !== tenantId
  ) return null;

  const rawKind = text(frozen.kind, "assertion").toLowerCase();
  const kind = proposalKinds[rawKind as keyof typeof proposalKinds] ?? "Assertion";
  const rawRisk = text(frozen.risk, "medium").toLowerCase();
  const risk = proposalRisks[rawRisk as keyof typeof proposalRisks] ?? "Medium";
  const vector = confidence(frozen.confidence);
  const evidenceCoverage = vector.find(
    (dimension) => dimension.label === "Evidence coverage",
  )?.value ?? 0;
  const evidence = Array.isArray(frozen.evidence) ? frozen.evidence.length : 0;
  const counterevidence = Array.isArray(frozen.counterevidence)
    ? frozen.counterevidence.length
    : 0;
  const status = proposalState.status === "ABSTAINED"
    ? "Abstained"
    : proposalState.status === "APPROVED"
      ? "Approved"
      : "Human review";
  const title = rawKind === "drift"
    ? "Source drift requires semantic review"
    : `Review ${kind.toLowerCase()} proposal`;
  const approval = evaluateApprovalPolicy(proposalState, run);
  const models = record(run.models) ? run.models : {};

  return {
    id: proposalId,
    kind,
    title,
    detail: text(frozen.source_locator, "No source locator recorded"),
    confidence: evidenceCoverage,
    confidenceVector: vector,
    risk,
    status,
    evidence: evidence + counterevidence,
    targetIri: text(frozen.target_iri, "No target IRI recorded"),
    gates: binding.gates,
    reasonCodes: Array.isArray(frozen.reason_codes)
      ? frozen.reason_codes.filter((item): item is string => typeof item === "string")
      : [],
    reviewed:
      typeof proposalState.lastReviewReceiptId === "string" &&
      proposalState.lastReviewReceiptId.length > 0,
    reviewDecision:
      proposalState.humanDecision === "APPROVED" ||
      proposalState.humanDecision === "ABSTAINED" ||
      proposalState.humanDecision === "REVIEW_REQUIRED"
        ? proposalState.humanDecision
        : undefined,
    approvalEligible: approval.eligible,
    approvalReasonCodes: approval.reasonCodes,
    verifierMode: typeof models.mode === "string" ? models.mode : "unknown",
  };
}
