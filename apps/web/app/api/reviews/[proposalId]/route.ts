import { applicationDefault, getApps, initializeApp } from "firebase-admin/app";
import { FieldValue, getFirestore } from "firebase-admin/firestore";
import { NextResponse } from "next/server";
import { isSameOriginRequest } from "@/lib/request-security";
import {
  canRecordReview,
  isSafeProposalId,
  parseReviewCommand,
  rationaleSha256,
  reviewReceiptId,
} from "@/lib/review-contract";
import { bindReviewEvidence, evaluateApprovalPolicy } from "@/lib/review-evidence";
import { getSession } from "@/lib/server-auth";

const maxReviewRequestBytes = 4 * 1024;
class ReviewError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function database() {
  if (!getApps().length) initializeApp({ credential: applicationDefault() });
  return getFirestore();
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ proposalId: string }> },
) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json({ title: "Forbidden", status: 403 }, { status: 403 });
  }
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ title: "Unauthorized", status: 401 }, { status: 401 });
  }
  if (!canRecordReview(session.roles)) {
    return NextResponse.json(
      { title: "Forbidden", status: 403, detail: "An explicit steward role is required." },
      { status: 403 },
    );
  }
  if (session.demo) {
    return NextResponse.json(
      { title: "Demo is read-only", status: 409, detail: "Sign in with a governed Firebase identity to create a content-bound reviewer receipt." },
      { status: 409 },
    );
  }
  const mediaType = request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (mediaType !== "application/json") {
    return NextResponse.json({ title: "Unsupported Media Type", status: 415 }, { status: 415 });
  }
  const rawBody = await request.text();
  if (new TextEncoder().encode(rawBody).byteLength > maxReviewRequestBytes) {
    return NextResponse.json({ title: "Payload Too Large", status: 413 }, { status: 413 });
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ title: "Bad Request", status: 400 }, { status: 400 });
  }
  const command = parseReviewCommand(parsed);
  const { proposalId } = await params;
  if (!command || !isSafeProposalId(proposalId)) {
    return NextResponse.json(
      { title: "Invalid review decision", status: 400, detail: "Decision, rationale, request id, or proposal id is invalid." },
      { status: 400 },
    );
  }

  try {
    const result = await database().runTransaction(async (transaction) => {
      const proposalRef = database().doc(`tenants/${session.tenantId}/proposals/${proposalId}`);
      const receiptId = reviewReceiptId(session.tenantId, proposalId);
      const receiptRef = database().doc(`tenants/${session.tenantId}/reviewReceipts/${receiptId}`);
      const auditRef = database().doc(`tenants/${session.tenantId}/auditEvents/${receiptId}`);
      const rationaleHash = rationaleSha256(command.rationale);
      const receiptSnapshot = await transaction.get(receiptRef);
      const proposalSnapshot = await transaction.get(proposalRef);

      if (receiptSnapshot.exists) {
        const receipt = receiptSnapshot.data() ?? {};
        const proposal = proposalSnapshot.data() ?? {};
        if (
          !proposalSnapshot.exists ||
          receipt.tenantId !== session.tenantId ||
          receipt.proposalId !== proposalId ||
          receipt.reviewerUid !== session.uid ||
          receipt.decision !== command.decision ||
          receipt.rationaleSha256 !== rationaleHash ||
          proposal.lastReviewReceiptId !== receiptId ||
          proposal.status !== receipt.resultingStatus ||
          proposal.verificationRunId !== receipt.verificationRunId ||
          proposal.verificationRunSha256 !== receipt.verificationRunSha256 ||
          proposal.frozenProposalSha256 !== receipt.frozenProposalSha256 ||
          proposal.frozenEvidenceIndexSha256 !== receipt.frozenEvidenceIndexSha256
        ) {
          throw new ReviewError(409, "This proposal already has a different content-bound adjudication.");
        }
        return { receiptId, idempotent: true, status: receipt.resultingStatus };
      }
      if (!proposalSnapshot.exists) throw new ReviewError(404, "The proposal does not exist.");
      const proposal = proposalSnapshot.data() ?? {};
      if (proposal.tenant_id !== session.tenantId || proposal.proposal_id !== proposalId) {
        throw new ReviewError(409, "The proposal is not bound to this tenant and document path.");
      }
      const priorStatus = proposal.status;
      if (priorStatus !== "HUMAN_REVIEW") {
        throw new ReviewError(409, "Only a proposal in HUMAN_REVIEW can receive this decision.");
      }
      const verificationRunId = proposal.verificationRunId;
      if (typeof verificationRunId !== "string" || !isSafeProposalId(verificationRunId)) {
        throw new ReviewError(409, "The proposal has no valid immutable verification run.");
      }
      const runRef = database().doc(`tenants/${session.tenantId}/verificationRuns/${verificationRunId}`);
      const runSnapshot = await transaction.get(runRef);
      if (!runSnapshot.exists) throw new ReviewError(409, "The verification run does not exist.");
      const run = runSnapshot.data() ?? {};
      const binding = bindReviewEvidence(proposal, run);
      if (
        run.tenant_id !== session.tenantId ||
        run.proposal_id !== proposalId ||
        run.verification_run_id !== verificationRunId ||
        run.status !== "HUMAN_REVIEW" ||
        binding === null
      ) {
        throw new ReviewError(409, "The proposal and verification evidence are not hash-bound.");
      }
      const {
        frozenProposalSha256,
        frozenEvidenceIndexSha256,
        verificationRunSha256,
      } = binding;
      const policyVersion = run.policy_version;
      const activeOntologyVersion = run.active_ontology_version;
      if (typeof policyVersion !== "string" || typeof activeOntologyVersion !== "string") {
        throw new ReviewError(409, "The verification policy or ontology version is missing.");
      }
      const approval = evaluateApprovalPolicy(proposal, run);
      if (command.decision === "APPROVED" && !approval.eligible) {
        throw new ReviewError(
          409,
          `Approval is not permitted by the bound verification policy: ${approval.reasonCodes.join(", ")}.`,
        );
      }
      const resultingStatus = command.decision === "APPROVED"
        ? "APPROVED"
        : command.decision === "ABSTAINED"
          ? "ABSTAINED"
          : "HUMAN_REVIEW";

      const receipt = {
        receiptId,
        requestId: command.requestId,
        proposalId,
        tenantId: session.tenantId,
        reviewerUid: session.uid,
        reviewerEmail: session.email,
        reviewerRoles: session.roles,
        priorStatus,
        decision: command.decision,
        resultingStatus,
        rationale: command.rationale,
        rationaleSha256: rationaleHash,
        verificationRunId,
        verificationRunSha256,
        frozenProposalSha256,
        frozenEvidenceIndexSha256,
        policyVersion,
        activeOntologyVersion,
        createdAt: FieldValue.serverTimestamp(),
      };
      transaction.create(receiptRef, receipt);
      transaction.create(auditRef, {
        eventType: "REVIEW_DECISION_RECORDED",
        actorUid: session.uid,
        proposalId,
        receiptId,
        decision: command.decision,
        resultingStatus,
        verificationRunId,
        verificationRunSha256,
        frozenProposalSha256,
        frozenEvidenceIndexSha256,
        rationaleSha256: rationaleHash,
        createdAt: FieldValue.serverTimestamp(),
      });
      transaction.update(proposalRef, {
        status: resultingStatus,
        humanDecision: command.decision,
        lastReviewReceiptId: receiptId,
        reviewedAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
      return { receiptId, idempotent: false, status: resultingStatus };
    });
    return NextResponse.json(result, { status: result.idempotent ? 200 : 201 });
  } catch (error) {
    if (error instanceof ReviewError) {
      return NextResponse.json({ title: "Review rejected", status: error.status, detail: error.message }, { status: error.status });
    }
    console.error("Review decision failed", error instanceof Error ? error.name : "unknown-error");
    return NextResponse.json(
      { title: "Review unavailable", status: 503, detail: "The content-bound reviewer receipt could not be recorded." },
      { status: 503 },
    );
  }
}
