import { applicationDefault, getApps, initializeApp } from "firebase-admin/app";
import { FieldValue, Timestamp, getFirestore } from "firebase-admin/firestore";
import { NextResponse } from "next/server";
import {
  businessAreas,
  canManageCompetencyQuestions,
  competencyQuestionId,
  competencyQuestionSchemaVersion,
  parseCompetencyQuestionCommand,
  type BusinessArea,
  type CompetencyQuestionView,
} from "@/lib/competency-contract";
import { isSameOriginRequest } from "@/lib/request-security";
import { getSession } from "@/lib/server-auth";

const maxQuestionRequestBytes = 4 * 1024;
const questionListLimit = 50;

class CompetencyError extends Error {
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

function createdAtIso(value: unknown): string | null {
  if (value instanceof Timestamp) return value.toDate().toISOString();
  if (typeof value === "string" && value.length > 0 && value.length <= 64) return value;
  return null;
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
    return NextResponse.json({ mode: "demo", canManageQuestions: false, questions: [] });
  }

  try {
    const snapshot = await database()
      .collection(`tenants/${session.tenantId}/competencyQuestions`)
      .orderBy("createdAt", "desc")
      .limit(questionListLimit)
      .select("questionId", "text", "businessArea", "status", "createdAt")
      .get();
    const questions: CompetencyQuestionView[] = snapshot.docs.flatMap((document) => {
      const data = document.data();
      if (
        typeof data.text !== "string" ||
        data.text.length < 10 ||
        data.text.length > 500 ||
        typeof data.businessArea !== "string" ||
        !(businessAreas as readonly string[]).includes(data.businessArea) ||
        data.status !== "PROPOSED" ||
        data.questionId !== document.id
      ) {
        return [];
      }
      return [{
        questionId: document.id,
        text: data.text,
        businessArea: data.businessArea as BusinessArea,
        status: "PROPOSED" as const,
        createdAt: createdAtIso(data.createdAt),
      }];
    });
    return NextResponse.json({
      mode: "firebase",
      canManageQuestions: canManageCompetencyQuestions(session.roles),
      questions,
    });
  } catch (error) {
    console.error("Competency question read failed", error instanceof Error ? error.name : "unknown-error");
    return NextResponse.json(
      { title: "Competency questions unavailable", status: 503, detail: "The tenant competency questions could not be loaded." },
      { status: 503 },
    );
  }
}

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json({ title: "Forbidden", status: 403 }, { status: 403 });
  }
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ title: "Unauthorized", status: 401 }, { status: 401 });
  }
  if (!canManageCompetencyQuestions(session.roles)) {
    return NextResponse.json(
      { title: "Forbidden", status: 403, detail: "An administrator or steward role is required to record competency questions." },
      { status: 403 },
    );
  }
  if (session.demo) {
    return NextResponse.json(
      { title: "Demo is read-only", status: 409, detail: "Sign in with a governed Firebase identity to record a competency question." },
      { status: 409 },
    );
  }
  const mediaType = request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (mediaType !== "application/json") {
    return NextResponse.json({ title: "Unsupported Media Type", status: 415 }, { status: 415 });
  }
  const rawBody = await request.text();
  if (new TextEncoder().encode(rawBody).byteLength > maxQuestionRequestBytes) {
    return NextResponse.json({ title: "Payload Too Large", status: 413 }, { status: 413 });
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ title: "Bad Request", status: 400 }, { status: 400 });
  }
  const command = parseCompetencyQuestionCommand(parsed);
  if (!command) {
    return NextResponse.json(
      { title: "Invalid competency question", status: 400, detail: "Provide a question between 10 and 500 characters and a valid business area." },
      { status: 400 },
    );
  }
  const questionId = competencyQuestionId(command.text);

  try {
    await database().runTransaction(async (transaction) => {
      const questionRef = database().doc(`tenants/${session.tenantId}/competencyQuestions/${questionId}`);
      const auditRef = database().doc(`tenants/${session.tenantId}/auditEvents/cq-${questionId}`);
      const existing = await transaction.get(questionRef);
      if (existing.exists) {
        throw new CompetencyError(409, `An equivalent question already exists as ${questionId}.`);
      }
      transaction.create(questionRef, {
        questionId,
        text: command.text,
        businessArea: command.businessArea,
        status: "PROPOSED",
        tenantId: session.tenantId,
        createdBy: session.uid,
        createdAt: FieldValue.serverTimestamp(),
        schemaVersion: competencyQuestionSchemaVersion,
      });
      transaction.create(auditRef, {
        eventType: "COMPETENCY_QUESTION_PROPOSED",
        actorUid: session.uid,
        questionId,
        businessArea: command.businessArea,
        createdAt: FieldValue.serverTimestamp(),
      });
    });
    return NextResponse.json({ questionId, status: "PROPOSED" }, { status: 201 });
  } catch (error) {
    if (error instanceof CompetencyError) {
      return NextResponse.json(
        { title: "Competency question rejected", status: error.status, detail: error.message },
        { status: error.status },
      );
    }
    console.error("Competency question write failed", error instanceof Error ? error.name : "unknown-error");
    return NextResponse.json(
      { title: "Competency questions unavailable", status: 503, detail: "The competency question could not be recorded." },
      { status: 503 },
    );
  }
}
