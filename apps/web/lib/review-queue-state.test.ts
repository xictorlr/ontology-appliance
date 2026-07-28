import { describe, expect, it } from "vitest";
import { initialProposals } from "./demo-data";
import { resolveReviewQueue } from "./review-queue-state";

describe("resolveReviewQueue", () => {
  it("keeps a clearly labelled preview visible when a live workspace is empty", () => {
    const state = resolveReviewQueue(
      {
        mode: "firebase",
        proposals: [],
        pendingCount: 0,
        abstainedCount: 0,
        receiptCount: 0,
        canRecordReview: true,
      },
      initialProposals,
    );

    expect(state.mode).toBe("preview");
    expect(state.proposals).toEqual(initialProposals);
    expect(state.selectedId).toBe(initialProposals[0]?.id);
    expect(state.canRecordReview).toBe(false);
    expect(state.message).toContain("synthetic preview");
  });

  it("keeps live proposals visible but read-only for an auditor", () => {
    const liveProposal = { ...initialProposals[0]!, id: "live-proposal" };
    const state = resolveReviewQueue(
      {
        mode: "firebase",
        proposals: [liveProposal],
        pendingCount: 1,
        canRecordReview: false,
      },
      initialProposals,
    );

    expect(state.mode).toBe("firebase");
    expect(state.proposals).toEqual([liveProposal]);
    expect(state.canRecordReview).toBe(false);
    expect(state.message).toContain("steward");
  });

  it("enables decisions only when the verified session authorizes them", () => {
    const liveProposal = { ...initialProposals[0]!, id: "live-proposal" };
    const state = resolveReviewQueue(
      {
        mode: "firebase",
        proposals: [liveProposal],
        pendingCount: 1,
        canRecordReview: true,
      },
      initialProposals,
    );

    expect(state.canRecordReview).toBe(true);
    expect(state.message).toBe("");
  });
});
