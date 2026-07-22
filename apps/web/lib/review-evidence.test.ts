import { describe, expect, it } from "vitest";
import {
  bindReviewEvidence,
  canonicalSha256,
  evaluateApprovalPolicy,
} from "./review-evidence";

const gateNames = [
  "CONTRACT",
  "SEMANTIC",
  "SOURCE_EVIDENCE",
  "INDEPENDENT_QUESTIONS",
  "MODEL_CONSISTENCY",
  "DATA_TESTS",
  "GLOBAL_CONSISTENCY",
  "HUMAN_ADJUDICATION",
];

function fixture() {
  const frozenProposal = {
    proposal_id: "proposal-1",
    tenant_id: "demo-bank",
    risk: "low",
    status: "PENDING_VERIFICATION",
    generator: { provider: "rules", model: "generator-v1" },
  };
  const evidence = [{ evidence_id: "evidence-1", content_sha256: "a".repeat(64) }];
  const counterevidence: unknown[] = [];
  const gates = gateNames.map((gate, index) => ({
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
      generator: frozenProposal.generator,
      verifier: {
        provider: "anthropic",
        model: "claude-sonnet-5",
        independent_model: true,
      },
      independent_agreement: true,
    },
  };
  const run = { ...runPayload, verification_run_sha256: canonicalSha256(runPayload) };
  const proposal = {
    verificationRunSha256: run.verification_run_sha256,
    frozenProposalSha256: run.frozen_proposal_sha256,
    frozenEvidenceIndexSha256: run.frozen_evidence_index_sha256,
  };
  return { proposal, run };
}

function rehash(value: ReturnType<typeof fixture>) {
  value.run.frozen_proposal_sha256 = canonicalSha256(value.run.frozen_proposal);
  value.proposal.frozenProposalSha256 = value.run.frozen_proposal_sha256;
  const payload = Object.fromEntries(
    Object.entries(value.run).filter(([key]) => key !== "verification_run_sha256"),
  );
  value.run.verification_run_sha256 = canonicalSha256(payload);
  value.proposal.verificationRunSha256 = value.run.verification_run_sha256;
}

describe("review evidence binding", () => {
  it("accepts a fully content-addressed run", () => {
    const { proposal, run } = fixture();
    expect(bindReviewEvidence(proposal, run)?.gates).toHaveLength(8);
  });

  it.each(["frozen proposal", "evidence index", "gate result"])(
    "rejects tampering with the %s even when stored digests are unchanged",
    (target) => {
      const { proposal, run } = fixture();
      if (target === "frozen proposal") run.frozen_proposal.status = "PUBLISHED";
      if (target === "evidence index") run.evidence[0]!.content_sha256 = "b".repeat(64);
      if (target === "gate result") run.gate_results[0]!.status = "FAILED";
      expect(bindReviewEvidence(proposal, run)).toBeNull();
    },
  );

  it("rejects a copied proposal digest that does not match the run", () => {
    const { proposal, run } = fixture();
    proposal.verificationRunSha256 = "f".repeat(64);
    expect(bindReviewEvidence(proposal, run)).toBeNull();
  });

  it("permits a steward approval for an independent live run", () => {
    const { proposal, run } = fixture();
    expect(evaluateApprovalPolicy(proposal, run)).toEqual({
      eligible: true,
      reasonCodes: [],
    });
  });

  it.each(["medium", "high"])(
    "permits steward adjudication for a fully passed %s-risk run",
    (risk) => {
      const value = fixture();
      value.run.risk = risk;
      value.run.frozen_proposal.risk = risk;
      rehash(value);
      expect(evaluateApprovalPolicy(value.proposal, value.run).eligible).toBe(true);
    },
  );

  it("rejects provider aliases that refer to the same provider", () => {
    const value = fixture();
    value.run.frozen_proposal.generator.provider = "Claude";
    value.run.models.verifier.provider = "anthropic-ai";
    rehash(value);
    expect(evaluateApprovalPolicy(value.proposal, value.run).reasonCodes).toContain(
      "GENERATOR_VERIFIER_SEPARATION_REQUIRED",
    );
  });

  it("rejects dated/latest aliases of the same model family across providers", () => {
    const value = fixture();
    value.run.frozen_proposal.generator.model = "models/claude-sonnet-5-20260722";
    value.run.models.verifier.model = "anthropic/claude-sonnet-5-latest";
    rehash(value);
    expect(evaluateApprovalPolicy(value.proposal, value.run).reasonCodes).toContain(
      "GENERATOR_VERIFIER_SEPARATION_REQUIRED",
    );
  });

  it.each([
    ["mock verifier", (run: ReturnType<typeof fixture>["run"]) => { run.models.mode = "mock"; }],
    ["no independent agreement", (run: ReturnType<typeof fixture>["run"]) => { run.models.independent_agreement = null as unknown as boolean; }],
    ["mismatched risk", (run: ReturnType<typeof fixture>["run"]) => { run.risk = "medium"; }],
    ["skipped automated gate", (run: ReturnType<typeof fixture>["run"]) => { run.gate_results[1]!.status = "SKIPPED"; }],
  ])("denies approval for %s", (_label, mutate) => {
    const { proposal, run } = fixture();
    mutate(run);
    rehash({ proposal, run });
    expect(evaluateApprovalPolicy(proposal, run).eligible).toBe(false);
  });
});
