import { applicationDefault, getApps, initializeApp } from "firebase-admin/app";
import { FieldPath, getFirestore, type Firestore } from "firebase-admin/firestore";
import { NextResponse } from "next/server";
import {
  emptyMetricsPayload,
  proposalKinds,
  proposalStatuses,
  verificationModes,
  type MetricsPayload,
  type RecentRun,
  type VerificationMode,
} from "@/lib/metrics-contract";
import { isSameOriginRequest } from "@/lib/request-security";
import { getSession } from "@/lib/server-auth";

const recentRunLimit = 10;
const gateSampleLimit = 25;

function database() {
  if (!getApps().length) initializeApp({ credential: applicationDefault() });
  return getFirestore();
}

function boundedId(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= 128 ? value : null;
}

function boundedTimestamp(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= 64 ? value : null;
}

function verificationMode(value: unknown): VerificationMode | null {
  return typeof value === "string" && (verificationModes as readonly string[]).includes(value)
    ? (value as VerificationMode)
    : null;
}

async function readTenantMetrics(db: Firestore, tenantId: string): Promise<MetricsPayload> {
  const proposals = db.collection(`tenants/${tenantId}/proposals`);
  const runs = db.collection(`tenants/${tenantId}/verificationRuns`);
  const profiles = db.collection(`tenants/${tenantId}/sourceProfiles`);
  const driftChecks = db.collection(`tenants/${tenantId}/driftChecks`);

  const [
    statusCounts,
    kindCounts,
    runCountSnapshot,
    profiledCountSnapshot,
    changedCountSnapshot,
    latestDriftSnapshot,
    gateSampleSnapshot,
    recentRunSnapshot,
  ] = await Promise.all([
    Promise.all(
      proposalStatuses.map((status) => proposals.where("status", "==", status).count().get()),
    ),
    Promise.all(
      proposalKinds.map((kind) => proposals.where("kind", "==", kind).count().get()),
    ),
    runs.count().get(),
    profiles.count().get(),
    profiles.where("contentChanged", "==", true).count().get(),
    driftChecks.orderBy(FieldPath.documentId(), "desc").limit(1).get(),
    proposals
      .orderBy("verifiedAt", "desc")
      .limit(gateSampleLimit)
      .select("gateSummary")
      .get(),
    runs
      .orderBy("decided_at", "desc")
      .limit(recentRunLimit)
      .select("proposal_id", "status", "models.mode", "decided_at")
      .get(),
  ]);

  const byStatus = Object.fromEntries(
    proposalStatuses.map((status, index) => [status, statusCounts[index]?.data().count ?? 0]),
  ) as MetricsPayload["proposals"]["byStatus"];
  const byKind = Object.fromEntries(
    proposalKinds.map((kind, index) => [kind, kindCounts[index]?.data().count ?? 0]),
  ) as MetricsPayload["proposals"]["byKind"];
  const total = Object.values(byStatus).reduce((sum, value) => sum + value, 0);

  const gateStatusCounts: Record<string, number> = {};
  for (const document of gateSampleSnapshot.docs) {
    const summary = document.get("gateSummary");
    if (!Array.isArray(summary)) continue;
    for (const entry of summary.slice(0, 16)) {
      const status = entry && typeof entry === "object" ? (entry as Record<string, unknown>).status : null;
      if (typeof status !== "string" || status.length === 0 || status.length > 64) continue;
      gateStatusCounts[status] = (gateStatusCounts[status] ?? 0) + 1;
    }
  }

  const recentRuns: RecentRun[] = recentRunSnapshot.docs.map((document) => ({
    runId: document.id,
    proposalId: boundedId(document.get("proposal_id")),
    status: boundedId(document.get("status")),
    mode: boundedId(document.get("models.mode")),
    decidedAt: boundedTimestamp(document.get("decided_at")),
  }));
  const latestRun = recentRuns[0] ?? null;
  const latestDrift = latestDriftSnapshot.docs[0] ?? null;

  return {
    mode: "firebase",
    proposals: { total, pendingReview: byStatus.HUMAN_REVIEW, byStatus, byKind },
    verification: {
      runCount: runCountSnapshot.data().count,
      latestMode: latestRun ? verificationMode(latestRun.mode) : null,
      latestDecidedAt: latestRun?.decidedAt ?? null,
    },
    sources: {
      profiledCount: profiledCountSnapshot.data().count,
      changedCount: changedCountSnapshot.data().count,
    },
    drift: {
      latestDay: latestDrift ? latestDrift.id.slice(0, 32) : null,
      latestStatus: latestDrift ? boundedId(latestDrift.get("status")) : null,
    },
    gates: {
      sampledProposals: gateSampleSnapshot.size,
      statusCounts: gateStatusCounts,
    },
    recentRuns,
  };
}

export async function GET(request: Request) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json({ title: "Forbidden", status: 403 }, { status: 403 });
  }
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ title: "Unauthorized", status: 401 }, { status: 401 });
  }
  if (session.demo) {
    return NextResponse.json(emptyMetricsPayload("demo"));
  }

  try {
    const payload = await readTenantMetrics(database(), session.tenantId);
    return NextResponse.json(payload);
  } catch (error) {
    console.error("Semantic metrics read failed", error instanceof Error ? error.name : "unknown-error");
    return NextResponse.json(
      { title: "Metrics unavailable", status: 503, detail: "Tenant semantic metrics could not be aggregated." },
      { status: 503 },
    );
  }
}
