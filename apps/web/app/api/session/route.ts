import { applicationDefault, getApps, initializeApp } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { pilotMembership } from "@/lib/claims";
import { isSameOriginRequest } from "@/lib/request-security";
import {
  hasExplicitMembershipClaims,
  selfEnrollmentAssignment,
} from "@/lib/self-enrollment";

const fiveDays = 5 * 24 * 60 * 60 * 1000;
const maxSessionRequestBytes = 16 * 1024;

function auth() {
  if (!getApps().length) initializeApp({ credential: applicationDefault() });
  return getAuth();
}

function membershipRequired() {
  return NextResponse.json(
    {
      type: "urn:ontology-appliance:problem:membership-required",
      title: "Pilot membership required",
      status: 403,
      detail: "Your identity is valid but is not eligible for automatic pilot enrollment. Ask an administrator to grant a workspace role.",
    },
    { status: 403 },
  );
}

function membershipTokenRefreshRequired() {
  return NextResponse.json(
    {
      type: "urn:ontology-appliance:problem:membership-token-refresh-required",
      title: "Pilot membership assigned",
      status: 409,
      detail: "Your pilot membership was assigned. Refresh the identity token to continue.",
    },
    { status: 409 },
  );
}

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json(
      { type: "about:blank", title: "Forbidden", status: 403, detail: "Cross-origin session changes are not allowed." },
      { status: 403 },
    );
  }
  const mediaType = request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (mediaType !== "application/json") {
    return NextResponse.json(
      { type: "about:blank", title: "Unsupported Media Type", status: 415, detail: "Session requests must use application/json." },
      { status: 415 },
    );
  }
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > maxSessionRequestBytes) {
    return NextResponse.json(
      { type: "about:blank", title: "Payload Too Large", status: 413, detail: "The session request is too large." },
      { status: 413 },
    );
  }
  const rawBody = await request.text();
  if (new TextEncoder().encode(rawBody).byteLength > maxSessionRequestBytes) {
    return NextResponse.json(
      { type: "about:blank", title: "Payload Too Large", status: 413, detail: "The session request is too large." },
      { status: 413 },
    );
  }
  let body: { idToken?: string; demo?: boolean };
  try {
    const parsed: unknown = JSON.parse(rawBody);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("object required");
    body = parsed as { idToken?: string; demo?: boolean };
  } catch {
    return NextResponse.json(
      { type: "about:blank", title: "Bad Request", status: 400, detail: "The request body is not valid JSON." },
      { status: 400 },
    );
  }
  const cookieStore = await cookies();

  const demoModeEnabled =
    process.env.NEXT_PUBLIC_DEMO_MODE === "true" ||
    (process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_DEMO_MODE !== "false");
  if (body.demo && demoModeEnabled) {
    cookieStore.set("oa_session", "demo", {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: fiveDays / 1000,
    });
    return NextResponse.json({ ok: true, mode: "demo" });
  }

  if (!body.idToken) {
    return NextResponse.json(
      { type: "about:blank", title: "Unauthorized", status: 401, detail: "An ID token is required." },
      { status: 401 },
    );
  }

  let decoded;
  try {
    decoded = await auth().verifyIdToken(body.idToken);
  } catch {
    return NextResponse.json(
      { type: "about:blank", title: "Unauthorized", status: 401, detail: "The ID token is invalid." },
      { status: 401 },
    );
  }
  if (Date.now() / 1000 - decoded.auth_time > 5 * 60) {
    return NextResponse.json(
      { type: "about:blank", title: "Recent sign-in required", status: 401, detail: "Sign in again to create a session." },
      { status: 401 },
    );
  }

  const membership = pilotMembership(decoded);
  if (!membership) {
    const assignment = selfEnrollmentAssignment(decoded);
    if (!assignment) return membershipRequired();

    try {
      const user = await auth().getUser(decoded.uid);
      const storedMembership = pilotMembership(user.customClaims);
      if (storedMembership) return membershipTokenRefreshRequired();
      if (hasExplicitMembershipClaims(user.customClaims)) return membershipRequired();

      await auth().setCustomUserClaims(decoded.uid, {
        ...(user.customClaims ?? {}),
        tenant_id: assignment.tenantId,
        roles: assignment.roles,
      });
      return membershipTokenRefreshRequired();
    } catch {
      return NextResponse.json(
        {
          type: "urn:ontology-appliance:problem:membership-provisioning-unavailable",
          title: "Pilot enrollment unavailable",
          status: 503,
          detail: "Your identity is valid, but pilot enrollment could not be completed. Try again shortly.",
        },
        { status: 503 },
      );
    }
  }

  try {
    const sessionCookie = await auth().createSessionCookie(body.idToken, { expiresIn: fiveDays });
    cookieStore.set("oa_session", sessionCookie, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: fiveDays / 1000,
    });
    return NextResponse.json({ ok: true, mode: "firebase" });
  } catch {
    return NextResponse.json(
      { type: "about:blank", title: "Unauthorized", status: 401, detail: "The ID token is invalid." },
      { status: 401 },
    );
  }
}

export async function DELETE(request: Request) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json(
      { type: "about:blank", title: "Forbidden", status: 403, detail: "Cross-origin session changes are not allowed." },
      { status: 403 },
    );
  }
  const cookieStore = await cookies();
  cookieStore.delete("oa_session");
  return NextResponse.json({ ok: true });
}
