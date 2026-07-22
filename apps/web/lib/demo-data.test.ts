import { describe, expect, it } from "vitest";
import { competencyQuestions, initialProposals, sources } from "./demo-data";

describe("synthetic pilot presentation", () => {
  it("contains the six planned evidence sources", () => {
    expect(sources).toHaveLength(6);
    expect(new Set(sources.map((source) => source.id)).size).toBe(6);
    expect(sources.reduce((total, source) => total + source.assets, 0)).toBe(7);
    expect(sources.reduce((total, source) => total + source.fields, 0)).toBe(37);
    expect(sources.reduce((total, source) => total + source.records, 0)).toBe(16);
    expect(sources.reduce((total, source) => total + source.bytes, 0)).toBe(4_139);
    expect(sources.reduce((total, source) => total + source.evidence, 0)).toBe(79);
    expect(sources.reduce((total, source) => total + source.records * source.fields * source.completeness / 100, 0)).toBeCloseTo(99, 4);
  });

  it("defines exactly five competency questions", () => {
    expect(competencyQuestions.map((question) => question.id)).toEqual([
      "CQ-001",
      "CQ-002",
      "CQ-003",
      "CQ-004",
      "CQ-005",
    ]);
  });

  it("never presents the high-risk relation as auto-approved", () => {
    const highRisk = initialProposals.filter((proposal) => proposal.risk === "High");
    expect(highRisk.length).toBeGreaterThan(0);
    expect(highRisk.every((proposal) => proposal.status !== "Auto-approved")).toBe(true);
  });

  it("does not invent a published or auto-approved mapping in mock mode", () => {
    expect(initialProposals.every((proposal) => proposal.status !== "Auto-approved")).toBe(true);
  });
});
