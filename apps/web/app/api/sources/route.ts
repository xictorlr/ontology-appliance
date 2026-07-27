import { randomUUID } from "node:crypto";
import { applicationDefault, getApp, getApps, initializeApp } from "firebase-admin/app";
import { FieldValue, getFirestore, type DocumentData } from "firebase-admin/firestore";
import { getStorage } from "firebase-admin/storage";
import { NextResponse } from "next/server";
import { sources as fixtureSources } from "@/lib/demo-data";
import { isSameOriginRequest } from "@/lib/request-security";
import { getSession } from "@/lib/server-auth";
import {
  canManageSources,
  inspectSourceUpload,
  maximumSourceBytes,
  parseSourceType,
  SourceInputError,
  validateSourceIdentity,
} from "@/lib/source-contract";

const maximumMultipartBytes = maximumSourceBytes + 128 * 1024;
const maximumTenantSources = 100;

function adminApp() {
  if (!getApps().length) initializeApp({ credential: applicationDefault() });
  return getApp();
}

function database() {
  return getFirestore(adminApp());
}

function storage() {
  return getStorage(adminApp());
}

function timestamp(value: unknown): string | null {
  if (
    typeof value === "object" &&
    value !== null &&
    "toDate" in value &&
    typeof value.toDate === "function"
  ) {
    return value.toDate().toISOString();
  }
  return typeof value === "string" ? value : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function liveSource(
  sourceId: string,
  connection: DocumentData,
  profile: DocumentData,
) {
  const sha256 = stringValue(profile.sha256);
  const sourceType = stringValue(connection.sourceType);
  const profileRecordCount = numberValue(profile.recordCount);
  return {
    id: sourceId,
    name: stringValue(connection.displayName) ?? sourceId,
    kind: sourceType?.toUpperCase() ?? stringValue(profile.mediaType) ?? "FILE",
    sourceType: sourceType ?? "file",
    accessMode: "read_only",
    status: sha256
      ? "READY"
      : stringValue(connection.status) ?? "PROFILING",
    fields: numberValue(connection.fieldCount),
    records: profileRecordCount ?? numberValue(connection.observedRecordCount),
    bytes: numberValue(profile.byteSize) ?? numberValue(connection.sizeBytes),
    snapshotId: stringValue(profile.snapshotId),
    sha256,
    mediaType: stringValue(profile.mediaType) ?? stringValue(connection.mediaType),
    updatedAt:
      timestamp(profile.updatedAt) ??
      timestamp(profile.observedAt) ??
      timestamp(connection.updatedAt) ??
      timestamp(connection.createdAt),
    origin: "firebase",
  };
}

function problem(status: number, title: string, detail: string) {
  return NextResponse.json(
    { type: "about:blank", title, status, detail },
    { status },
  );
}

export async function GET(request: Request) {
  if (!isSameOriginRequest(request)) {
    return problem(403, "Forbidden", "Cross-origin source reads are not allowed.");
  }
  const session = await getSession();
  if (!session) return problem(401, "Unauthorized", "A verified session is required.");

  if (session.demo) {
    return NextResponse.json({
      mode: "demo",
      canManageSources: false,
      sources: fixtureSources.map((source) => ({
        id: source.id,
        name: source.name,
        kind: source.kind,
        sourceType: source.kind.toLowerCase(),
        accessMode: "read_only",
        status: "READY",
        fields: source.fields,
        records: source.records,
        bytes: source.bytes,
        snapshotId: null,
        sha256: null,
        mediaType: null,
        updatedAt: null,
        origin: "fixture",
      })),
    });
  }

  try {
    const [connections, profiles] = await Promise.all([
      database().collection(`tenants/${session.tenantId}/sourceConnections`).limit(maximumTenantSources + 1).get(),
      database().collection(`tenants/${session.tenantId}/sourceProfiles`).limit(maximumTenantSources + 1).get(),
    ]);
    const connectionsById = new Map(
      connections.docs.map((document) => [document.id, document.data()]),
    );
    const profilesById = new Map(
      profiles.docs.map((document) => [document.id, document.data()]),
    );
    const allSourceIds = [...new Set([
      ...connectionsById.keys(),
      ...profilesById.keys(),
    ])].sort();
    const sourceIds = allSourceIds.slice(0, maximumTenantSources);
    return NextResponse.json({
      mode: "firebase",
      canManageSources: canManageSources(session.roles),
      truncated: allSourceIds.length > maximumTenantSources,
      sources: sourceIds.map((sourceId) =>
        liveSource(
          sourceId,
          connectionsById.get(sourceId) ?? {},
          profilesById.get(sourceId) ?? {},
        ),
      ),
    });
  } catch (error) {
    console.error("Source inventory read failed", error instanceof Error ? error.name : "unknown-error");
    return problem(503, "Source inventory unavailable", "The source inventory could not be loaded.");
  }
}

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) {
    return problem(403, "Forbidden", "Cross-origin source changes are not allowed.");
  }
  const session = await getSession();
  if (!session) return problem(401, "Unauthorized", "A verified session is required.");
  if (session.demo) {
    return problem(409, "Demo is read-only", "Sign in with a governed Firebase identity to connect a source.");
  }
  if (!canManageSources(session.roles)) {
    return problem(403, "Forbidden", "An administrator or steward role is required to connect sources.");
  }

  const mediaType = request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (mediaType !== "multipart/form-data") {
    return problem(415, "Unsupported Media Type", "Source uploads must use multipart/form-data.");
  }
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (
    !Number.isFinite(declaredLength) ||
    declaredLength < 1 ||
    declaredLength > maximumMultipartBytes
  ) {
    return problem(413, "Payload Too Large", "The multipart source upload exceeds the 20 MiB file limit.");
  }

  try {
    const form = await request.formData();
    const sourceType = parseSourceType(form.get("sourceType"));
    if (!sourceType) throw new SourceInputError(400, "Select a supported source type.");
    const identity = validateSourceIdentity(form.get("sourceId"), form.get("displayName"));
    const upload = form.get("file");
    if (!(upload instanceof File)) {
      throw new SourceInputError(400, "Select a source file.");
    }
    const content = new Uint8Array(await upload.arrayBuffer());
    const inspection = inspectSourceUpload(sourceType, content);
    const objectName =
      `tenants/${session.tenantId}/uploads/${identity.sourceId}/` +
      `${Date.now()}-${randomUUID()}.${inspection.extension}`;
    const bucketName = process.env.SOURCE_BUCKET?.trim();
    if (!bucketName) {
      return problem(503, "Source ingestion unavailable", "The governed input bucket is not configured.");
    }

    const connectionRef = database().doc(
      `tenants/${session.tenantId}/sourceConnections/${identity.sourceId}`,
    );
    const auditRef = database().doc(
      `tenants/${session.tenantId}/auditEvents/source-connected-${randomUUID()}`,
    );
    await database().runTransaction(async (transaction) => {
      const prior = await transaction.get(connectionRef);
      if (prior.exists) {
        throw new SourceInputError(
          409,
          "This source ID already exists. Choose a different ID for a new connection.",
        );
      }
      transaction.create(connectionRef, {
        sourceId: identity.sourceId,
        tenantId: session.tenantId,
        displayName: identity.displayName,
        sourceType,
        connectorMode: sourceType === "openapi" ? "SCHEMA_UPLOAD" : "FILE_UPLOAD",
        accessMode: "READ_ONLY",
        capabilities: ["schema", "sample", "profile", "snapshot"],
        status: "UPLOAD_PENDING",
        fieldCount: inspection.fieldCount,
        observedRecordCount: inspection.observedRecordCount,
        sizeBytes: content.byteLength,
        mediaType: inspection.canonicalMediaType,
        createdByUid: session.uid,
        createdByEmail: session.email,
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
      transaction.create(auditRef, {
        eventType: "SOURCE_CONNECTION_REGISTERED",
        tenantId: session.tenantId,
        sourceId: identity.sourceId,
        sourceType,
        accessMode: "READ_ONLY",
        actorUid: session.uid,
        actorEmail: session.email,
        actorRoles: session.roles,
        createdAt: FieldValue.serverTimestamp(),
      });
    });

    let objectCreated = false;
    try {
      await storage().bucket(bucketName).file(objectName).save(Buffer.from(content), {
        resumable: false,
        preconditionOpts: { ifGenerationMatch: 0 },
        metadata: {
          contentType: inspection.canonicalMediaType,
          cacheControl: "no-store",
          metadata: {
            tenantId: session.tenantId,
            uploadedBy: session.uid,
            sourceId: identity.sourceId,
            sourceType,
          },
        },
      });
      objectCreated = true;
    } catch (error) {
      await connectionRef.update({
        status: "UPLOAD_FAILED",
        failureCode: "OBJECT_CREATE_FAILED",
        updatedAt: FieldValue.serverTimestamp(),
      });
      throw error;
    }
    if (objectCreated) {
      try {
        await connectionRef.update({
          status: "INGESTION_QUEUED",
          objectName,
          sourceLocator: `gs://${bucketName}/${objectName}`,
          updatedAt: FieldValue.serverTimestamp(),
        });
      } catch (error) {
        // The immutable object event is authoritative and will still create the
        // profile. Do not tell the operator to retry an upload that succeeded.
        console.warn("Source connection status update deferred", error instanceof Error ? error.name : "unknown-error");
      }
    }

    return NextResponse.json(
      {
        source: {
          id: identity.sourceId,
          name: identity.displayName,
          kind: sourceType.toUpperCase(),
          sourceType,
          accessMode: "read_only",
          status: "INGESTION_QUEUED",
          fields: inspection.fieldCount,
          records: inspection.observedRecordCount,
          bytes: content.byteLength,
          snapshotId: null,
          sha256: null,
          mediaType: inspection.canonicalMediaType,
          updatedAt: new Date().toISOString(),
          origin: "firebase",
        },
      },
      { status: 202 },
    );
  } catch (error) {
    if (error instanceof SourceInputError) {
      return problem(error.status, "Invalid source", error.message);
    }
    console.error("Source registration failed", error instanceof Error ? error.name : "unknown-error");
    return problem(503, "Source registration failed", "The source could not be registered or uploaded.");
  }
}
