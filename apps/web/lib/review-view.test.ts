import { describe, expect, it } from "vitest";
import { canonicalSha256 } from "./review-evidence";
import { buildReviewProposalView } from "./review-view";

function fixture() {
  const frozenProposal = {
    proposal_id: "proposal-1",
    tenant_id: "demo-bank",
    kind: "mapping",
    risk: "low",
    source_locator: "frozen.csv#field=customer_id",
    target_iri: "urn:test:CustomerIdentifier",
    evidence: [{ evidence_id: "evidence-1" }],
    counterevidence: [],
    confidence: {
      lexical: 0.9,
      structural: 0.8,
      instance: 0.7,
      external: 0,
      model: 1,
      evidence_coverage: 1,
    },
    generator: { provider: "rules", model: "generator-v1" },
    reason_codes: ["FROZEN_REASON"],
  };
  const evidence = [{ evidence_id: "evidence-1" }];
  const counterevidence: unknown[] = [];
  const names = [
    "CONTRACT",
    "SEMANTIC",
    "SOURCE_EVIDENCE",
    "INDEPENDENT_QUESTIONS",
    "MODEL_CONSISTENCY",
    "DATA_TESTS",
    "GLOBAL_CONSISTENCY",
    "HUMAN_ADJUDICATION",
  ];
  const gates = names.map((gate, index) => ({
    gate,
    gateResultId: `gate-${index + 1}`,
    order: index + 1,
    status: index === 7 ? "REVIEW_REQUIRED" : "PASSED",
  }));
  const runPayload = {
    verification_run_id: "run-1",
    proposal_id: "proposal-1",
    tenant_id: "demo-bank",
    policy_version: "semantic-verification-policy-v1",
    risk: "low",
    status: "HUMAN_REVIEW",
    frozen_proposal: frozenProposal,
    frozen_proposal_sha256: canonicalSha256(frozenProposal),
    evidence,
    counterevidence,
    frozen_evidence_index_sha256: canonicalSha256({ evidence, counterevidence }),
    gate_results: gates,
    gate_result_ids: gates.map((gate) => gate.gateResultId),
    models: {
      mode: "live",
      generator: { provider: "rules", model: "generator-v1" },
      verifier: {
        provider: "anthropic",
        model: "claude-sonnet-5",
        independent_model: true,
      },
      independent_agreement: true,
    },
  };
  const run = { ...runPayload, verification_run_sha256: canonicalSha256(runPayload) };
  const state = {
    status: "HUMAN_REVIEW",
    source_locator: "tampered.csv#field=attacker",
    target_iri: "urn:tampered",
    confidence: { evidence_coverage: 0 },
    kind: "constraint",
    risk: "high",
    reason_codes: ["MUTABLE_REASON"],
    verificationRunSha256: run.verification_run_sha256,
    frozenProposalSha256: run.frozen_proposal_sha256,
    frozenEvidenceIndexSha256: run.frozen_evidence_index_sha256,
  };
  return { run, state };
}

describe("review projection", () => {
  it("shows only hash-bound frozen review content", () => {
    const { run, state } = fixture();
    const view = buildReviewProposalView("proposal-1", "demo-bank", state, run);
    expect(view).toMatchObject({
      kind: "Mapping",
      detail: "frozen.csv#field=customer_id",
      targetIri: "urn:test:CustomerIdentifier",
      confidence: 100,
      risk: "Low",
      reasonCodes: ["FROZEN_REASON"],
      approvalEligible: true,
    });
  });

  it("allows only status and receipt state to come from the mutable document", () => {
    const { run, state } = fixture();
    state.status = "ABSTAINED";
    Object.assign(state, {
      humanDecision: "ABSTAINED",
      lastReviewReceiptId: "receipt-1",
    });
    expect(buildReviewProposalView("proposal-1", "demo-bank", state, run)).toMatchObject({
      status: "Abstained",
      reviewed: true,
      reviewDecision: "ABSTAINED",
    });
  });

  it("fails closed when the frozen identity does not match the path", () => {
    const { run, state } = fixture();
    expect(buildReviewProposalView("other-proposal", "demo-bank", state, run)).toBeNull();
  });
});
