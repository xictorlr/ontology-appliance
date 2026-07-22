import type { PilotRole } from "@/lib/claims";

import { createHash } from "node:crypto";

export const reviewDecisions = ["APPROVED", "REVIEW_REQUIRED", "ABSTAINED"] as const;

export type ReviewDecision = (typeof reviewDecisions)[number];

export type ReviewCommand = {
  decision: ReviewDecision;
  rationale: string;
  requestId: string;
};

const safeDocumentId = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isSafeProposalId(value: string): boolean {
  return safeDocumentId.test(value);
}

export function canRecordReview(roles: PilotRole[]): boolean {
  return roles.includes("steward");
}

export function reviewReceiptId(tenantId: string, proposalId: string): string {
  return `review-${createHash("sha256").update(`${tenantId}\u0000${proposalId}`).digest("hex")}`;
}

export function rationaleSha256(rationale: string): string {
  return createHash("sha256").update(rationale).digest("hex");
}

export function parseReviewCommand(value: unknown): ReviewCommand | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const body = value as Record<string, unknown>;
  if (Object.keys(body).some((key) => !["decision", "rationale", "requestId"].includes(key))) {
    return null;
  }
  if (
    typeof body.decision !== "string" ||
    !reviewDecisions.includes(body.decision as ReviewDecision) ||
    typeof body.rationale !== "string" ||
    typeof body.requestId !== "string"
  ) {
    return null;
  }
  const rationale = body.rationale.trim();
  if (rationale.length < 10 || rationale.length > 1_000 || !uuid.test(body.requestId)) {
    return null;
  }
  return {
    decision: body.decision as ReviewDecision,
    rationale,
    requestId: body.requestId.toLowerCase(),
  };
}
