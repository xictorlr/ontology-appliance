import { describe, expect, it } from "vitest";
import {
  emptyMetricsPayload,
  parseMetricsPayload,
  type MetricsPayload,
} from "./metrics-contract";

function validPayload(): MetricsPayload {
  return {
    mode: "firebase",
    proposals: {
      total: 3,
      pendingReview: 2,
      byStatus: { PENDING_VERIFICATION: 0, HUMAN_REVIEW: 2, ABSTAINED: 1, APPROVED: 0 },
      byKind: {
        concept: 0,
        relation: 0,
        alias: 0,
        mapping: 2,
        duplicate: 0,
        constraint: 0,
        assertion: 1,
        drift: 0,
      },
    },
    verification: { runCount: 3, latestMode: "mock", latestDecidedAt: "2026-07-28T09:00:00Z" },
    sources: { profiledCount: 6, changedCount: 1 },
    drift: { latestDay: "2026-07-28", latestStatus: "NO_DRIFT_DETECTED" },
    gates: { sampledProposals: 3, statusCounts: { PASSED: 6, REVIEW_REQUIRED: 3 } },
    recentRuns: [
      {
        runId: "ver-abc123",
        proposalId: "ing-def456",
        status: "HUMAN_REVIEW",
        mode: "mock",
        decidedAt: "2026-07-28T09:00:00Z",
      },
    ],
  };
}

describe("metrics contract", () => {
  it("accepts a bounded live payload and the empty demo payload", () => {
    expect(parseMetricsPayload(validPayload())).toEqual(validPayload());
    expect(parseMetricsPayload(emptyMetricsPayload("demo"))?.mode).toBe("demo");
  });

  it("rejects unknown fields, negative counts, and invalid modes", () => {
    expect(parseMetricsPayload({ ...validPayload(), extra: true })).toBeNull();
    const negative = validPayload();
    negative.proposals.total = -1;
    expect(parseMetricsPayload(negative)).toBeNull();
    const badMode = validPayload();
    // @ts-expect-error deliberately invalid verification mode
    badMode.verification.latestMode = "autonomous";
    expect(parseMetricsPayload(badMode)).toBeNull();
    expect(parseMetricsPayload(null)).toBeNull();
    expect(parseMetricsPayload("metrics")).toBeNull();
  });

  it("bounds the recent run list to ten entries", () => {
    const overflow = validPayload();
    overflow.recentRuns = Array.from({ length: 11 }, (_, index) => ({
      runId: `ver-${index}`,
      proposalId: null,
      status: null,
      mode: null,
      decidedAt: null,
    }));
    expect(parseMetricsPayload(overflow)).toBeNull();
  });
});
