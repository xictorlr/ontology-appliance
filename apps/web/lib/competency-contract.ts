import { createHash } from "node:crypto";

import { z } from "zod";

import type { PilotRole } from "@/lib/claims";

/**
 * Contract for tenant competency-question onboarding (Paso 1).
 *
 * Stored questions scope future discovery runs; they never modify the bundled
 * golden questions that the semantic gateway serves, and they are written only
 * through the BFF with the tenant taken from the verified session.
 */

export const competencyQuestionSchemaVersion = 1;

export const businessAreas = ["kyc-aml", "payments", "risk", "customer", "other"] as const;

export type BusinessArea = (typeof businessAreas)[number];

export const competencyQuestionCommandSchema = z
  .object({
    text: z
      .string()
      .transform((value) => value.replace(/\s+/gu, " ").trim())
      .pipe(z.string().min(10).max(500)),
    businessArea: z.enum(businessAreas),
  })
  .strict();

export type CompetencyQuestionCommand = z.infer<typeof competencyQuestionCommandSchema>;

export const competencyQuestionViewSchema = z
  .object({
    questionId: z.string().regex(/^CQT-[a-f0-9]{12}$/u),
    text: z.string().min(10).max(500),
    businessArea: z.enum(businessAreas),
    status: z.literal("PROPOSED"),
    createdAt: z.string().min(1).max(64).nullable(),
  })
  .strict();

export type CompetencyQuestionView = z.infer<typeof competencyQuestionViewSchema>;

export const competencyQuestionListSchema = z
  .object({
    mode: z.enum(["demo", "firebase"]),
    canManageQuestions: z.boolean(),
    questions: z.array(competencyQuestionViewSchema).max(50),
  })
  .strict();

export type CompetencyQuestionList = z.infer<typeof competencyQuestionListSchema>;

export function parseCompetencyQuestionCommand(value: unknown): CompetencyQuestionCommand | null {
  const result = competencyQuestionCommandSchema.safeParse(value);
  return result.success ? result.data : null;
}

export function parseCompetencyQuestionList(value: unknown): CompetencyQuestionList | null {
  const result = competencyQuestionListSchema.safeParse(value);
  return result.success ? result.data : null;
}

export function canManageCompetencyQuestions(roles: readonly PilotRole[]): boolean {
  return roles.includes("admin") || roles.includes("steward");
}

export function normalizedQuestionText(text: string): string {
  return text.normalize("NFKC").replace(/\s+/gu, " ").trim().toLowerCase();
}

/**
 * Deterministic, race-free identifier: a zero-padded sequence would race under
 * concurrent creates, so the id commits to the normalized question text.
 */
export function competencyQuestionId(text: string): string {
  const digest = createHash("sha256").update(normalizedQuestionText(text)).digest("hex");
  return `CQT-${digest.slice(0, 12)}`;
}
