import { describe, expect, it } from "vitest";
import {
  canRecordReview,
  isSafeProposalId,
  parseReviewCommand,
  rationaleSha256,
  reviewReceiptId,
} from "./review-contract";

describe("review command contract", () => {
  it("accepts a bounded, idempotent human decision", () => {
    expect(
      parseReviewCommand({
        decision: "REVIEW_REQUIRED",
        rationale: "Insufficient independent evidence.",
        requestId: "123e4567-e89b-42d3-a456-426614174000",
      }),
    ).toEqual({
      decision: "REVIEW_REQUIRED",
      rationale: "Insufficient independent evidence.",
      requestId: "123e4567-e89b-42d3-a456-426614174000",
    });
    expect(
      parseReviewCommand({
        decision: "APPROVED",
        rationale: "All independent verification gates passed.",
        requestId: "123e4567-e89b-42d3-a456-426614174000",
      })?.decision,
    ).toBe("APPROVED");
  });

  it("rejects unknown decisions, extra fields, weak rationale, and malformed ids", () => {
    expect(parseReviewCommand({ decision: "PUBLISHED", rationale: "Long enough rationale", requestId: "bad" })).toBeNull();
    expect(parseReviewCommand({ decision: "REVIEW_REQUIRED", rationale: "short", requestId: "123e4567-e89b-42d3-a456-426614174000" })).toBeNull();
    expect(parseReviewCommand({ decision: "REVIEW_REQUIRED", rationale: "A valid rationale", requestId: "123e4567-e89b-42d3-a456-426614174000", tenantId: "other" })).toBeNull();
  });

  it("allows only safe proposal ids and explicit steward writes", () => {
    expect(isSafeProposalId("MAP-104")).toBe(true);
    expect(isSafeProposalId("../other-tenant")).toBe(false);
    expect(canRecordReview(["steward"])).toBe(true);
    expect(canRecordReview(["admin", "auditor"])).toBe(false);
    expect(canRecordReview(["auditor"])).toBe(false);
  });

  it("derives tenant-bound receipt and rationale hashes", () => {
    expect(reviewReceiptId("demo-bank", "MAP-104")).toMatch(/^review-[a-f0-9]{64}$/u);
    expect(reviewReceiptId("demo-bank", "MAP-104")).not.toBe(
      reviewReceiptId("other-bank", "MAP-104"),
    );
    expect(rationaleSha256("Evidence is incomplete.")).toMatch(/^[a-f0-9]{64}$/u);
  });
});
