import { createHash } from "node:crypto";

export const PROFILE_EXTRACTOR_VERSION = "firebase-evidence-profiler/1.0.0";

export interface SourceProfile {
  sha256: string;
  byteSize: number;
  recordCount: number | null;
  mediaType: string;
  extractorVersion: string;
}

function countCsvRecords(text: string): number {
  let inQuotes = false;
  let records = 0;
  let recordHasContent = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]!;
    if (character === '"') {
      if (inQuotes && text[index + 1] === '"') {
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if ((character === "\n" || character === "\r") && !inQuotes) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      if (recordHasContent) records += 1;
      recordHasContent = false;
    } else if (!/\s/.test(character)) {
      recordHasContent = true;
    }
  }
  if (recordHasContent) records += 1;
  return Math.max(0, records - 1); // The first record is the schema/header.
}

function countJsonRecords(text: string): number {
  const parsed: unknown = JSON.parse(text);
  if (Array.isArray(parsed)) return parsed.length;
  return parsed && typeof parsed === "object" ? 1 : 0;
}

function countNdjsonRecords(text: string): number {
  let count = 0;
  for (const line of text.split(/\r?\n/u)) {
    if (!line.trim()) continue;
    JSON.parse(line);
    count += 1;
  }
  return count;
}

export function profileSource(content: Buffer, contentType: string): SourceProfile {
  const mediaType = contentType.toLowerCase().split(";", 1)[0] ?? "";
  const text = mediaType === "application/pdf" ? "" : content.toString("utf8");
  let recordCount: number | null;
  if (mediaType === "text/csv") {
    recordCount = countCsvRecords(text);
  } else if (mediaType === "application/json") {
    recordCount = countJsonRecords(text);
  } else if (mediaType === "application/x-ndjson") {
    recordCount = countNdjsonRecords(text);
  } else if (mediaType === "text/plain") {
    recordCount = text.split(/\r?\n/u).filter((line) => line.trim()).length;
  } else if (mediaType === "application/pdf") {
    recordCount = null;
  } else {
    throw new Error("Unsupported content type for profiling");
  }
  return {
    sha256: createHash("sha256").update(content).digest("hex"),
    byteSize: content.byteLength,
    recordCount,
    mediaType,
    extractorVersion: PROFILE_EXTRACTOR_VERSION,
  };
}
