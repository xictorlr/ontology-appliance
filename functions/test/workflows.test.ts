import { describe, expect, it } from "vitest";

import {
  gateResultSchema,
  proposalSchema,
} from "../../packages/contracts/src/index";
import type { SourceProfile } from "../src/lib/profiling";
import {
  buildDriftProposal,
  buildIngestionProposal,
  buildVerificationDecision,
  canonicalSha256,
  VERIFICATION_POLICY_VERSION,
} from "../src/lib/workflows";

const profile: SourceProfile = {
  sha256: "a".repeat(64),
  byteSize: 42,
  recordCount: 2,
  mediaType: "text/csv",
  extractorVersion: "firebase-evidence-profiler/1.0.0",
};

function ingestionProposal() {
  return buildIngestionProposal({
    tenantId: "demo-bank",
    sourceId: "crm",
    bucket: "demo-input",
    objectName: "tenants/demo-bank/uploads/crm/parties.csv",
    generation: "1721640000000000",
    contentType: "text/csv",
    sizeBytes: 42,
    observedAt: "2026-07-22T13:51:12.123Z",
    activeOntologyVersion: "2026.07.1-candidate",
    profile,
  });
}

describe("durable ingestion discovery", () => {
  it("creates a deterministic pending proposal with content-addressed evidence", () => {
    const first = ingestionProposal();
    const second = ingestionProposal();

    expect(proposalSchema.parse(first)).toEqual(first);
    expect(first).toEqual(second);
    expect(first.proposal_id).toMatch(/^ingestion-[a-f0-9]{64}$/u);
    expect(first.status).toBe("PENDING_VERIFICATION");
    expect(first.kind).toBe("assertion");
    expect(first.evidence).toHaveLength(1);
    expect(first.evidence[0]).toMatchObject({
      tenant_id: "demo-bank",
      source_id: "crm",
      snapshot_id: `crm@sha256:${profile.sha256}`,
      content_sha256: profile.sha256,
      observed_at: "2026-07-22T13:51:12.123Z",
    });
    expect(first.confidence).toEqual({
      lexical: 0,
      structural: 1,
      instance: 1,
      external: 0,
      model: 0,
      evidence_coverage: 1,
    });
    expect(first).not.toHaveProperty("confidenceScore");
    expect(JSON.stringify(first)).not.toContain("Alice");
  });

  it("binds identity-changing inputs into the proposal ID", () => {
    const first = ingestionProposal();
    const changed = buildIngestionProposal({
      tenantId: "demo-bank",
      sourceId: "crm",
      bucket: "demo-input",
      objectName: "tenants/demo-bank/uploads/crm/parties.csv",
      generation: "1721640000000001",
      contentType: "text/csv",
      sizeBytes: 42,
      observedAt: "2026-07-22T13:51:12.123Z",
      activeOntologyVersion: "2026.07.1-candidate",
      profile,
    });
    expect(changed.proposal_id).not.toBe(first.proposal_id);
  });
});

describe("fail-closed deterministic verification", () => {
  it("persists an ordered run and all gates, ending in human review", () => {
    const proposal = ingestionProposal();
    const decision = buildVerificationDecision(
      "demo-bank",
      proposal.proposal_id,
      "verify-run-001",
      "2026-07-22T13:52:00Z",
      proposal,
    );

    expect(decision.status).toBe("HUMAN_REVIEW");
    expect(decision.proposalUpdate).toMatchObject({
      status: "HUMAN_REVIEW",
      verificationRunId: "verify-run-001",
    });
    expect(decision.gates.map((gate) => gate.gate)).toEqual([
      "CONTRACT",
      "SEMANTIC",
      "SOURCE_EVIDENCE",
      "INDEPENDENT_QUESTIONS",
      "MODEL_CONSISTENCY",
      "DATA_TESTS",
      "GLOBAL_CONSISTENCY",
      "HUMAN_ADJUDICATION",
    ]);
    expect(decision.gates.map((gate) => gate.order)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8,
    ]);
    for (const result of decision.gates) {
      expect(
        gateResultSchema.parse({
          gate: result.gate,
          status: result.status,
          details: result.details,
          evidenceIds: result.evidenceIds,
        }),
      ).toBeDefined();
    }
    expect(decision.run).toMatchObject({
      policy_version: VERIFICATION_POLICY_VERSION,
      status: "HUMAN_REVIEW",
      frozen_proposal: proposal,
      models: {
        mode: "disabled",
        independent_agreement: null,
        verifier: {
          independent_model: false,
          response_status: "abstained",
          store: false,
        },
      },
    });
    expect(decision.run.verification_run_sha256).toMatch(/^[a-f0-9]{64}$/u);
    expect(decision.proposalUpdate).toMatchObject({
      verificationRunSha256: decision.run.verification_run_sha256,
      frozenEvidenceIndexSha256: decision.run.frozen_evidence_index_sha256,
      verificationPolicyVersion: VERIFICATION_POLICY_VERSION,
    });
    expect(decision.proposalUpdate.gateSummary).toEqual(
      decision.gates.map(({ gate, status }) => ({ gate, status })),
    );
    expect(JSON.stringify(decision)).not.toContain("AUTO_APPROVED");
    expect(JSON.stringify(decision)).not.toContain("PUBLISHED");
  });

  it("abstains with a complete decision trace when evidence is invalid", () => {
    const proposal = ingestionProposal();
    proposal.evidence = [];
    const decision = buildVerificationDecision(
      "demo-bank",
      proposal.proposal_id,
      "verify-run-002",
      "2026-07-22T13:52:00Z",
      proposal,
    );

    expect(decision.status).toBe("ABSTAINED");
    expect(decision.gates).toHaveLength(8);
    expect(decision.gates[0]).toMatchObject({
      gate: "CONTRACT",
      status: "FAILED",
    });
    expect(decision.gates[2]).toMatchObject({
      gate: "SOURCE_EVIDENCE",
      status: "FAILED",
    });
    expect(decision.reasonCodes).toContain("VERIFIER_ABSTAINED");
  });

  it("detects deterministic-input tampering", () => {
    const proposal = ingestionProposal();
    proposal.deterministic_input.sourceId = "tampered-source";
    const decision = buildVerificationDecision(
      "demo-bank",
      proposal.proposal_id,
      "verify-run-003",
      "2026-07-22T13:52:00Z",
      proposal,
    );

    expect(decision.status).toBe("ABSTAINED");
    expect(decision.gates[0]?.details).toContain(
      "deterministic_input_hash does not match deterministic_input",
    );
  });
});

describe("durable drift discovery", () => {
  it("creates one stable drift proposal regardless of source query order", () => {
    const changedSources = [
      {
        sourceId: "payments",
        snapshotId: `payments@sha256:${"b".repeat(64)}`,
        sha256: "b".repeat(64),
        previousSha256: "c".repeat(64),
        evidenceLocator: "gs://demo-input/payments.jsonl#generation=2",
        observedAt: "2026-07-22T13:50:00Z",
        extractorVersion: "firebase-evidence-profiler/1.0.0",
      },
      {
        sourceId: "crm",
        snapshotId: `crm@sha256:${"d".repeat(64)}`,
        sha256: "d".repeat(64),
        previousSha256: "e".repeat(64),
        evidenceLocator: "gs://demo-input/crm.csv#generation=3",
        observedAt: "2026-07-22T13:49:00Z",
        extractorVersion: "firebase-evidence-profiler/1.0.0",
      },
    ];
    const input = {
      tenantId: "demo-bank",
      scheduledDay: "2026-07-22",
      evaluatedAt: "2026-07-22T14:00:00Z",
      activeOntologyVersion: "2026.07.1-candidate",
      changedSources,
    };

    const first = buildDriftProposal(input);
    const reversed = buildDriftProposal({
      ...input,
      changedSources: [...changedSources].reverse(),
    });
    expect(first).toEqual(reversed);
    expect(first).toMatchObject({
      kind: "drift",
      risk: "medium",
      status: "PENDING_VERIFICATION",
      tenant_id: "demo-bank",
    });
    expect(first?.evidence).toHaveLength(2);
    expect(first?.source_snapshot_ids[0]).toMatch(/^crm@sha256:/u);
    expect(proposalSchema.parse(first)).toEqual(first);

    const nextDay = buildDriftProposal({
      ...input,
      scheduledDay: "2026-07-23",
      evaluatedAt: "2026-07-23T14:00:00Z",
    });
    expect(nextDay).toEqual(first);
    expect(nextDay?.proposal_id).toBe(first?.proposal_id);
  });

  it("does not manufacture a proposal when no source changed", () => {
    expect(
      buildDriftProposal({
        tenantId: "demo-bank",
        scheduledDay: "2026-07-22",
        evaluatedAt: "2026-07-22T14:00:00Z",
        activeOntologyVersion: "2026.07.1-candidate",
        changedSources: [],
      }),
    ).toBeNull();
  });
});

describe("canonical hashing", () => {
  it("is stable across object key order while preserving array order", () => {
    expect(canonicalSha256({ b: 2, a: 1 })).toBe(
      canonicalSha256({ a: 1, b: 2 }),
    );
    expect(canonicalSha256(["a", "b"])).not.toBe(
      canonicalSha256(["b", "a"]),
    );
  });
});
