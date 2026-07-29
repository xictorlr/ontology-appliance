import { z } from "zod";

/**
 * Typed contract for the tenant semantic observability endpoint.
 *
 * Every value is an aggregate over bounded Firestore reads for the tenant that
 * the verified session resolves to. The payload never carries proposal or
 * evidence content, only counts and identifiers.
 */

export const proposalKinds = [
  "concept",
  "relation",
  "alias",
  "mapping",
  "duplicate",
  "constraint",
  "assertion",
  "drift",
] as const;

export const proposalStatuses = [
  "PENDING_VERIFICATION",
  "HUMAN_REVIEW",
  "ABSTAINED",
  "APPROVED",
] as const;

export const verificationModes = ["disabled", "mock", "live"] as const;

export type VerificationMode = (typeof verificationModes)[number];

const count = z.number().int().min(0).max(1_000_000_000);
const boundedString = z.string().min(1).max(128);

export const recentRunSchema = z
  .object({
    runId: boundedString,
    proposalId: boundedString.nullable(),
    status: boundedString.nullable(),
    mode: boundedString.nullable(),
    decidedAt: z.string().min(1).max(64).nullable(),
  })
  .strict();

export const metricsPayloadSchema = z
  .object({
    mode: z.enum(["demo", "firebase"]),
    proposals: z
      .object({
        total: count,
        pendingReview: count,
        byStatus: z.record(z.enum(proposalStatuses), count),
        byKind: z.record(z.enum(proposalKinds), count),
      })
      .strict(),
    verification: z
      .object({
        runCount: count,
        latestMode: z.enum(verificationModes).nullable(),
        latestDecidedAt: z.string().min(1).max(64).nullable(),
      })
      .strict(),
    sources: z
      .object({
        profiledCount: count,
        changedCount: count,
      })
      .strict(),
    drift: z
      .object({
        latestDay: z.string().min(1).max(32).nullable(),
        latestStatus: z.string().min(1).max(64).nullable(),
      })
      .strict(),
    gates: z
      .object({
        sampledProposals: count,
        statusCounts: z.record(z.string().min(1).max(64), count),
      })
      .strict(),
    recentRuns: z.array(recentRunSchema).max(10),
  })
  .strict();

export type MetricsPayload = z.infer<typeof metricsPayloadSchema>;
export type RecentRun = z.infer<typeof recentRunSchema>;

export function parseMetricsPayload(value: unknown): MetricsPayload | null {
  const result = metricsPayloadSchema.safeParse(value);
  return result.success ? result.data : null;
}

export function emptyMetricsPayload(mode: MetricsPayload["mode"]): MetricsPayload {
  return {
    mode,
    proposals: {
      total: 0,
      pendingReview: 0,
      byStatus: Object.fromEntries(
        proposalStatuses.map((status) => [status, 0]),
      ) as MetricsPayload["proposals"]["byStatus"],
      byKind: Object.fromEntries(
        proposalKinds.map((kind) => [kind, 0]),
      ) as MetricsPayload["proposals"]["byKind"],
    },
    verification: { runCount: 0, latestMode: null, latestDecidedAt: null },
    sources: { profiledCount: 0, changedCount: 0 },
    drift: { latestDay: null, latestStatus: null },
    gates: { sampledProposals: 0, statusCounts: {} },
    recentRuns: [],
  };
}
