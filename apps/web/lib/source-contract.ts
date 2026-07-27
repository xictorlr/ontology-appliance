export const sourceTypes = ["csv", "jsonl", "pdf", "openapi"] as const;

export type SourceType = (typeof sourceTypes)[number];

export const maximumSourceBytes = 20 * 1024 * 1024;
export const maximumJsonlRecords = 100_000;
export const maximumCsvRecords = 100_000;

export type SourceInspection = {
  canonicalMediaType: string;
  extension: string;
  fieldCount: number | null;
  observedRecordCount: number | null;
};

export class SourceInputError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const safeSourceId = /^[a-z][a-z0-9-]{2,63}$/;

export function canManageSources(roles: readonly string[]): boolean {
  return roles.includes("admin") || roles.includes("steward");
}

export function parseSourceType(value: unknown): SourceType | null {
  return typeof value === "string" && sourceTypes.includes(value as SourceType)
    ? value as SourceType
    : null;
}

export function validateSourceIdentity(sourceId: unknown, displayName: unknown): {
  sourceId: string;
  displayName: string;
} {
  if (typeof sourceId !== "string" || !safeSourceId.test(sourceId)) {
    throw new SourceInputError(
      400,
      "Source ID must use 3–64 lowercase letters, numbers, and hyphens.",
    );
  }
  if (typeof displayName !== "string") {
    throw new SourceInputError(400, "A source name is required.");
  }
  const normalizedName = displayName.trim();
  if (normalizedName.length < 3 || normalizedName.length > 80) {
    throw new SourceInputError(400, "Source name must contain 3–80 characters.");
  }
  return { sourceId, displayName: normalizedName };
}

function decodeUtf8(content: Uint8Array): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(content);
  } catch {
    throw new SourceInputError(400, "Text sources must be valid UTF-8.");
  }
}

function parseCsvHeader(text: string): string[] {
  const fields: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]!;
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      fields.push(field.trim());
      field = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      fields.push(field.trim());
      break;
    } else {
      field += character;
    }
    if (index > 64 * 1024) {
      throw new SourceInputError(400, "CSV header exceeds the 64 KiB limit.");
    }
  }
  if (fields.length === 0 && field.trim()) fields.push(field.trim());
  if (quoted) throw new SourceInputError(400, "CSV header contains an unclosed quote.");
  if (
    fields.length === 0 ||
    fields.length > 256 ||
    fields.some((value) => value.length === 0 || value.length > 256)
  ) {
    throw new SourceInputError(400, "CSV must contain 1–256 named header fields.");
  }
  if (new Set(fields).size !== fields.length) {
    throw new SourceInputError(400, "CSV header field names must be unique.");
  }
  return fields;
}

function countCsvRecords(text: string): number {
  let quoted = false;
  let records = 0;
  let hasContent = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]!;
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      if (hasContent) records += 1;
      hasContent = false;
    } else if (!/\s/u.test(character)) {
      hasContent = true;
    }
  }
  if (hasContent) records += 1;
  return Math.max(0, records - 1);
}

function inspectCsv(content: Uint8Array): SourceInspection {
  const text = decodeUtf8(content);
  const fields = parseCsvHeader(text);
  const recordCount = countCsvRecords(text);
  if (recordCount > maximumCsvRecords) {
    throw new SourceInputError(
      400,
      `CSV exceeds the ${maximumCsvRecords.toLocaleString("en-US")} record limit.`,
    );
  }
  return {
    canonicalMediaType: "text/csv",
    extension: "csv",
    fieldCount: fields.length,
    observedRecordCount: recordCount,
  };
}

function inspectJsonl(content: Uint8Array): SourceInspection {
  const lines = decodeUtf8(content).split(/\r?\n/u).filter((line) => line.trim());
  if (lines.length === 0 || lines.length > maximumJsonlRecords) {
    throw new SourceInputError(
      400,
      `JSONL must contain 1–${maximumJsonlRecords.toLocaleString("en-US")} records.`,
    );
  }
  let firstRecord: unknown;
  for (let index = 0; index < lines.length; index += 1) {
    let record: unknown;
    try {
      record = JSON.parse(lines[index]!);
    } catch {
      throw new SourceInputError(400, `JSONL record ${index + 1} is not valid JSON.`);
    }
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      throw new SourceInputError(400, `JSONL record ${index + 1} must be an object.`);
    }
    firstRecord ??= record;
  }
  return {
    canonicalMediaType: "application/x-ndjson",
    extension: "jsonl",
    fieldCount: Object.keys(firstRecord as Record<string, unknown>).length,
    observedRecordCount: lines.length,
  };
}

function inspectPdf(content: Uint8Array): SourceInspection {
  const signature = new TextDecoder("ascii").decode(content.slice(0, 5));
  if (signature !== "%PDF-") {
    throw new SourceInputError(400, "The selected file is not a valid PDF document.");
  }
  return {
    canonicalMediaType: "application/pdf",
    extension: "pdf",
    fieldCount: null,
    observedRecordCount: null,
  };
}

function inspectOpenApi(content: Uint8Array): SourceInspection {
  let document: unknown;
  try {
    document = JSON.parse(decodeUtf8(content));
  } catch {
    throw new SourceInputError(400, "OpenAPI schemas must be uploaded as valid JSON.");
  }
  if (!document || typeof document !== "object" || Array.isArray(document)) {
    throw new SourceInputError(400, "OpenAPI schema must be a JSON object.");
  }
  const values = document as Record<string, unknown>;
  if (typeof values.openapi !== "string" || !values.openapi.startsWith("3.")) {
    throw new SourceInputError(400, "Only OpenAPI 3.x schemas are supported.");
  }
  if (!values.paths || typeof values.paths !== "object" || Array.isArray(values.paths)) {
    throw new SourceInputError(400, "OpenAPI schema must contain a paths object.");
  }
  const pathCount = Object.keys(values.paths).length;
  if (pathCount > 5_000) {
    throw new SourceInputError(400, "OpenAPI schema exceeds the 5,000 path limit.");
  }
  return {
    canonicalMediaType: "application/json",
    extension: "openapi.json",
    fieldCount: pathCount,
    observedRecordCount: 1,
  };
}

export function inspectSourceUpload(
  sourceType: SourceType,
  content: Uint8Array,
): SourceInspection {
  if (content.byteLength < 1 || content.byteLength > maximumSourceBytes) {
    throw new SourceInputError(
      413,
      `Source files must contain 1 byte–${maximumSourceBytes / 1024 / 1024} MiB.`,
    );
  }
  switch (sourceType) {
    case "csv":
      return inspectCsv(content);
    case "jsonl":
      return inspectJsonl(content);
    case "pdf":
      return inspectPdf(content);
    case "openapi":
      return inspectOpenApi(content);
  }
}
