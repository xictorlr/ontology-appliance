import { createHash } from "node:crypto";

export interface SourceObjectIdentity {
  tenantId: string;
  sourceId: string;
  fileName: string;
}

const SEGMENT = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/;
const SUPPORTED_CONTENT_TYPES = new Set([
  "application/json",
  "application/pdf",
  "application/x-ndjson",
  "text/csv",
  "text/plain",
]);

export function assertSafeSegment(value: string, field: string): string {
  if (!SEGMENT.test(value) || value === "." || value === "..") {
    throw new Error(`Invalid ${field}`);
  }
  return value;
}

export function parseSourceObjectName(
  objectName: string,
): SourceObjectIdentity | null {
  const segments = objectName.split("/");
  if (
    segments.length !== 5 ||
    segments[0] !== "tenants" ||
    segments[2] !== "uploads"
  ) {
    return null;
  }

  const tenantId = assertSafeSegment(segments[1] ?? "", "tenantId");
  const sourceId = assertSafeSegment(segments[3] ?? "", "sourceId");
  const fileName = assertSafeSegment(segments[4] ?? "", "fileName");
  return { tenantId, sourceId, fileName };
}

export function deterministicId(...parts: Array<string | number>): string {
  const normalized = parts.map((part) => String(part).normalize("NFKC"));
  return createHash("sha256").update(normalized.join("\u001f")).digest("hex");
}

export function isSupportedContentType(contentType: string): boolean {
  return SUPPORTED_CONTENT_TYPES.has(contentType.toLowerCase().split(";", 1)[0] ?? "");
}

export function utcDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function assertUtcDay(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error("Invalid scheduledDay");
  }
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime()) || utcDay(parsed) !== value) {
    throw new Error("Invalid scheduledDay");
  }
  return value;
}

export function assertUtcTimestamp(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/u.test(value)) {
    throw new Error("Invalid UTC timestamp");
  }
  const parsed = new Date(value);
  if (
    Number.isNaN(parsed.getTime()) ||
    parsed.toISOString().slice(0, 19) !== value.slice(0, 19)
  ) {
    throw new Error("Invalid UTC timestamp");
  }
  return value;
}
