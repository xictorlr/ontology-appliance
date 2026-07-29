import { createHash } from "node:crypto";

export const PROFILE_EXTRACTOR_VERSION = "firebase-evidence-profiler/1.0.0";

const MAX_COLUMN_NAMES = 100;
const MAX_COLUMN_NAME_LENGTH = 200;

export interface SourceProfile {
  sha256: string;
  byteSize: number;
  recordCount: number | null;
  mediaType: string;
  extractorVersion: string;
  /** Header/key names only; cell values never leave the profiler. */
  columnNames: string[];
}

function boundColumnNames(names: string[]): string[] {
  return names
    .map((name) => name.trim())
    .filter((name) => name.length > 0 && name.length <= MAX_COLUMN_NAME_LENGTH)
    .slice(0, MAX_COLUMN_NAMES);
}

function csvHeaderColumns(text: string): string[] {
  const header = text.startsWith("\uFEFF") ? text.slice(1) : text;
  const names: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let index = 0; index < header.length; index += 1) {
    const character = header[index]!;
    if (character === '"') {
      if (inQuotes && header[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (character === "," && !inQuotes) {
      names.push(field);
      field = "";
    } else if ((character === "\n" || character === "\r") && !inQuotes) {
      break;
    } else {
      field += character;
    }
  }
  names.push(field);
  return boundColumnNames(names);
}

function firstRecordColumns(record: unknown): string[] {
  if (typeof record !== "object" || record === null || Array.isArray(record)) {
    return [];
  }
  return boundColumnNames(Object.keys(record).sort());
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
  let columnNames: string[] = [];
  if (mediaType === "text/csv") {
    recordCount = countCsvRecords(text);
    columnNames = csvHeaderColumns(text);
  } else if (mediaType === "application/json") {
    recordCount = countJsonRecords(text);
    const parsed: unknown = JSON.parse(text);
    columnNames = Array.isArray(parsed) ? firstRecordColumns(parsed[0]) : [];
  } else if (mediaType === "application/x-ndjson") {
    recordCount = countNdjsonRecords(text);
    const firstLine = text.split(/\r?\n/u).find((line) => line.trim());
    columnNames = firstLine === undefined ? [] : firstRecordColumns(JSON.parse(firstLine));
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
    columnNames,
  };
}
