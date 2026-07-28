import type { ProposalView } from "./demo-data";

export type ReviewQueueMode = "loading" | "demo" | "firebase" | "preview" | "unavailable";

export type ReviewQueuePayload = {
  mode?: string;
  proposals?: ProposalView[];
  pendingCount?: number;
  abstainedCount?: number;
  receiptCount?: number;
  canRecordReview?: boolean;
};

export type ReviewQueueState = {
  mode: Exclude<ReviewQueueMode, "loading" | "unavailable">;
  proposals: ProposalView[];
  selectedId: string;
  pendingCount: number;
  abstainedCount: number;
  receiptCount: number;
  canRecordReview: boolean;
  message: string;
};

function safeCount(value: number | undefined): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

export function resolveReviewQueue(
  payload: ReviewQueuePayload,
  representativeProposals: ProposalView[],
): ReviewQueueState {
  if (payload.mode === "firebase") {
    const liveProposals = Array.isArray(payload.proposals) ? payload.proposals : [];
    const canRecord = payload.canRecordReview === true;
    const common = {
      pendingCount: safeCount(payload.pendingCount),
      abstainedCount: safeCount(payload.abstainedCount),
      receiptCount: safeCount(payload.receiptCount),
    };
    if (liveProposals.length > 0) {
      return {
        ...common,
        mode: "firebase",
        proposals: liveProposals,
        selectedId: liveProposals[0]?.id ?? "",
        canRecordReview: canRecord,
        message: canRecord
          ? ""
          : "Read-only access: a steward role is required to record review decisions.",
      };
    }
    return {
      ...common,
      mode: "preview",
      proposals: representativeProposals,
      selectedId: representativeProposals[0]?.id ?? "",
      canRecordReview: false,
      message:
        "No live proposals are queued for this workspace. Showing a read-only synthetic preview.",
    };
  }

  return {
    mode: "demo",
    proposals: representativeProposals,
    selectedId: representativeProposals[0]?.id ?? "",
    pendingCount: safeCount(payload.pendingCount),
    abstainedCount: safeCount(payload.abstainedCount),
    receiptCount: safeCount(payload.receiptCount),
    canRecordReview: false,
    message: "Local demo is read-only; governed decisions require a Firebase identity.",
  };
}
