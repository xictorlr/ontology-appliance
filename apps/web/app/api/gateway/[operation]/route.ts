import { GoogleAuth } from "google-auth-library";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { isSameOriginRequest } from "@/lib/request-security";
import { getSession } from "@/lib/server-auth";

const allowedOperations = new Set(["resolve", "context", "query", "explain", "validate", "sparql"]);

export async function POST(request: Request, { params }: { params: Promise<{ operation: string }> }) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json(
      { type: "about:blank", title: "Forbidden", status: 403, detail: "Cross-origin gateway requests are not allowed." },
      { status: 403 },
    );
  }
  const session = await getSession();
  if (!session) {
    return NextResponse.json(
      { type: "about:blank", title: "Unauthorized", status: 401, detail: "Sign in before using the semantic gateway." },
      { status: 401 },
    );
  }

  const { operation } = await params;
  if (!allowedOperations.has(operation)) {
    return NextResponse.json(
      { type: "about:blank", title: "Not found", status: 404, detail: "Unknown gateway operation." },
      { status: 404 },
    );
  }

  const gatewayUrl = process.env.SEMANTIC_GATEWAY_URL ?? "http://127.0.0.1:8081";
  const endpoint = `${gatewayUrl.replace(/\/$/, "")}/v1/${operation}`;

  try {
    const mediaType = request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
    if (mediaType !== "application/json") {
      return NextResponse.json(
        { type: "about:blank", title: "Unsupported Media Type", status: 415, detail: "Gateway requests must use application/json." },
        { status: 415 },
      );
    }
    const rawBody = await request.text();
    if (new TextEncoder().encode(rawBody).byteLength > 1_100_000) {
      return NextResponse.json(
        { type: "about:blank", title: "Payload Too Large", status: 413, detail: "The gateway request is too large." },
        { status: 413 },
      );
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(rawBody);
    } catch {
      return NextResponse.json(
        { type: "about:blank", title: "Bad Request", status: 400, detail: "The gateway request is not valid JSON." },
        { status: 400 },
      );
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return NextResponse.json(
        { type: "about:blank", title: "Bad Request", status: 400, detail: "The gateway request must be a JSON object." },
        { status: 400 },
      );
    }
    const body = parsed as Record<string, unknown>;
    const headers = new Headers({
      "content-type": "application/json",
      "x-tenant-id": session.tenantId,
      "x-user-id": session.uid,
      "x-user-roles": session.roles.join(","),
    });

    if (!session.demo || !gatewayUrl.includes("127.0.0.1")) {
      const sessionCookie = (await cookies()).get("oa_session")?.value;
      if (!sessionCookie || sessionCookie === "demo") {
        throw new Error("A Firebase session is required for the cloud gateway.");
      }
      headers.set("authorization", `Bearer ${sessionCookie}`);
      const audience = process.env.SEMANTIC_GATEWAY_AUDIENCE ?? gatewayUrl;
      const idTokenClient = await new GoogleAuth().getIdTokenClient(audience);
      const authHeaders = await idTokenClient.getRequestHeaders(endpoint);
      const serviceAuthorization = authHeaders.get("authorization");
      if (!serviceAuthorization) throw new Error("Could not mint the Cloud Run service identity token.");
      headers.set("x-serverless-authorization", serviceAuthorization);
    }

    const response = await fetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
      cache: "no-store",
    });
    const payload = await response.text();
    return new Response(payload, {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
    });
  } catch (error) {
    console.error("Semantic gateway request failed", error instanceof Error ? error.name : "unknown-error");
    return NextResponse.json(
      {
        type: "urn:ontology-appliance:problem:gateway-unavailable",
        title: "Semantic gateway unavailable",
        status: 503,
        detail: "The semantic gateway could not complete the request.",
      },
      { status: 503 },
    );
  }
}
