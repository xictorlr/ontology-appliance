import { describe, expect, it } from "vitest";
import {
  canManageCompetencyQuestions,
  competencyQuestionId,
  normalizedQuestionText,
  parseCompetencyQuestionCommand,
  parseCompetencyQuestionList,
} from "./competency-contract";

describe("competency question command contract", () => {
  it("accepts a bounded question and normalizes whitespace", () => {
    expect(
      parseCompetencyQuestionCommand({
        text: "  Which customers are related   to a sanctioned company? ",
        businessArea: "kyc-aml",
      }),
    ).toEqual({
      text: "Which customers are related to a sanctioned company?",
      businessArea: "kyc-aml",
    });
  });

  it("rejects short text, long text, unknown areas, and extra fields", () => {
    expect(parseCompetencyQuestionCommand({ text: "Too short", businessArea: "risk" })).toBeNull();
    expect(parseCompetencyQuestionCommand({ text: "x".repeat(501), businessArea: "risk" })).toBeNull();
    expect(parseCompetencyQuestionCommand({ text: "Which payments come from sanctioned owners?", businessArea: "trading" })).toBeNull();
    expect(parseCompetencyQuestionCommand({ text: "Which payments come from sanctioned owners?", businessArea: "risk", tenantId: "other" })).toBeNull();
    expect(parseCompetencyQuestionCommand(null)).toBeNull();
  });

  it("restricts writes to admins and stewards", () => {
    expect(canManageCompetencyQuestions(["admin"])).toBe(true);
    expect(canManageCompetencyQuestions(["steward"])).toBe(true);
    expect(canManageCompetencyQuestions(["auditor"])).toBe(false);
    expect(canManageCompetencyQuestions([])).toBe(false);
  });
});

describe("deterministic question id", () => {
  it("derives the same CQT id for text that normalizes identically", () => {
    const id = competencyQuestionId("Which customers are related to a sanctioned company?");
    expect(id).toMatch(/^CQT-[a-f0-9]{12}$/u);
    expect(competencyQuestionId("  which CUSTOMERS are related\tto a sanctioned company?  ")).toBe(id);
    expect(competencyQuestionId("Which contracts depend on a specific supplier?")).not.toBe(id);
  });

  it("normalizes casing, unicode compatibility forms, and whitespace", () => {
    expect(normalizedQuestionText("  Which ACCOUNTS   move funds? ")).toBe("which accounts move funds?");
  });
});

describe("competency question list contract", () => {
  const question = {
    questionId: "CQT-0123456789ab",
    text: "Which customers are related to a sanctioned company?",
    businessArea: "kyc-aml",
    status: "PROPOSED",
    createdAt: "2026-07-28T09:00:00.000Z",
  };

  it("accepts a tenant-scoped listing", () => {
    expect(
      parseCompetencyQuestionList({ mode: "firebase", canManageQuestions: true, questions: [question] }),
    ).not.toBeNull();
  });

  it("rejects malformed ids and non-proposed statuses", () => {
    expect(
      parseCompetencyQuestionList({
        mode: "firebase",
        canManageQuestions: false,
        questions: [{ ...question, questionId: "CQT-1" }],
      }),
    ).toBeNull();
    expect(
      parseCompetencyQuestionList({
        mode: "firebase",
        canManageQuestions: false,
        questions: [{ ...question, status: "PUBLISHED" }],
      }),
    ).toBeNull();
  });
});
