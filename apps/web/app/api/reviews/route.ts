import { applicationDefault, getApps, initializeApp } from "firebase-admin/app";
import { FieldPath, getFirestore, type Query } from "firebase-admin/firestore";
import { NextResponse } from "next/server";
import { isSameOriginRequest } from "@/lib/request-security";
import { canRecordReview, isSafeProposalId } from "@/lib/review-contract";
import { buildReviewProposalView } from "@/lib/review-view";
import { getSession } from "@/lib/server-auth";

function database() {
  if (!getApps().length) initializeApp({ credential: applicationDefault() });
  return getFirestore();
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
    return NextResponse.json({ mode: "demo", proposals: [], pendingCount: 100, abstainedCount: 1, receiptCount: 0 });
  }

  try {
    const url = new URL(request.url);
    const requestedLimit = Number(url.searchParams.get("limit") ?? "25");
    const pageSize = Number.isSafeInteger(requestedLimit)
      ? Math.max(1, Math.min(50, requestedLimit))
      : 25;
    const cursor = url.searchParams.get("after");
    if (cursor !== null && !isSafeProposalId(cursor)) {
      return NextResponse.json({ title: "Invalid cursor", status: 400 }, { status: 400 });
    }

    const collection = database().collection(`tenants/${session.tenantId}/proposals`);
    let query: Query = collection
      .where("status", "in", ["HUMAN_REVIEW", "ABSTAINED"])
      .orderBy(FieldPath.documentId())
      .select(
        "status",
        "verificationRunId",
        "verificationRunSha256",
        "frozenProposalSha256",
        "frozenEvidenceIndexSha256",
        "lastReviewReceiptId",
        "humanDecision",
      );
    if (cursor) query = query.startAfter(cursor);
    query = query.limit(pageSize + 1);

    const [proposalSnapshot, pendingCountSnapshot, abstainedCountSnapshot, receiptCountSnapshot] = await Promise.all([
      query.get(),
      collection.where("status", "==", "HUMAN_REVIEW").count().get(),
      collection.where("status", "==", "ABSTAINED").count().get(),
      database().collection(`tenants/${session.tenantId}/reviewReceipts`).count().get(),
    ]);
    const hasNextPage = proposalSnapshot.size > pageSize;
    const visibleDocuments = proposalSnapshot.docs.slice(0, pageSize);
    const runIds = visibleDocuments.map((document) => {
      const value = document.data().verificationRunId;
      return typeof value === "string" && isSafeProposalId(value) ? value : null;
    });
    const runRefs = runIds.flatMap((runId) =>
      runId ? [database().doc(`tenants/${session.tenantId}/verificationRuns/${runId}`)] : [],
    );
    const runSnapshots = runRefs.length > 0 ? await database().getAll(...runRefs) : [];
    const runsById = new Map(
      runSnapshots.flatMap((snapshot) => snapshot.exists ? [[snapshot.id, snapshot.data() ?? {}] as const] : []),
    );
    const proposals = visibleDocuments.flatMap((document) => {
      const data = document.data();
      const runId = typeof data.verificationRunId === "string" ? data.verificationRunId : "";
      const view = buildReviewProposalView(
        document.id,
        session.tenantId,
        data,
        runsById.get(runId) ?? {},
      );
      return view === null
        ? []
        : [{
            ...view,
            approvalEligible:
              view.approvalEligible === true && canRecordReview(session.roles),
          }];
    });
    return NextResponse.json({
      mode: "firebase",
      proposals,
      pendingCount: pendingCountSnapshot.data().count,
      abstainedCount: abstainedCountSnapshot.data().count,
      receiptCount: receiptCountSnapshot.data().count,
      nextCursor: hasNextPage ? visibleDocuments.at(-1)?.id ?? null : null,
    });
  } catch (error) {
    console.error("Review queue read failed", error instanceof Error ? error.name : "unknown-error");
    return NextResponse.json(
      { title: "Review queue unavailable", status: 503, detail: "The governed review queue could not be loaded." },
      { status: 503 },
    );
  }
}
