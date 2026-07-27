import { describe, expect, it } from "vitest";
import {
  canManageSources,
  inspectSourceUpload,
  SourceInputError,
  validateSourceIdentity,
} from "./source-contract";

const bytes = (value: string) => new TextEncoder().encode(value);

describe("source onboarding contract", () => {
  it("allows only explicit source managers", () => {
    expect(canManageSources(["admin"])).toBe(true);
    expect(canManageSources(["steward"])).toBe(true);
    expect(canManageSources(["auditor"])).toBe(false);
  });

  it("validates source identity without accepting a tenant", () => {
    expect(validateSourceIdentity("customer-master", " Customer master ")).toEqual({
      sourceId: "customer-master",
      displayName: "Customer master",
    });
    expect(() => validateSourceIdentity("../tenant", "Customer master")).toThrow(SourceInputError);
  });

  it("profiles bounded CSV and JSONL uploads before storage", () => {
    expect(inspectSourceUpload("csv", bytes('id,"legal,name"\n1,"Acme, Ltd"\n'))).toMatchObject({
      canonicalMediaType: "text/csv",
      fieldCount: 2,
      observedRecordCount: 1,
    });
    expect(inspectSourceUpload("jsonl", bytes('{"id":1,"amount":10}\n{"id":2}\n'))).toMatchObject({
      canonicalMediaType: "application/x-ndjson",
      fieldCount: 2,
      observedRecordCount: 2,
    });
  });

  it("accepts only OpenAPI 3 JSON contracts", () => {
    expect(inspectSourceUpload("openapi", bytes('{"openapi":"3.1.0","paths":{"/records":{}}}'))).toMatchObject({
      fieldCount: 1,
      observedRecordCount: 1,
    });
    expect(() => inspectSourceUpload("openapi", bytes('{"swagger":"2.0","paths":{}}'))).toThrow(
      "Only OpenAPI 3.x schemas are supported.",
    );
  });

  it("checks PDF content instead of trusting its filename", () => {
    expect(inspectSourceUpload("pdf", bytes("%PDF-1.7\n"))).toMatchObject({
      canonicalMediaType: "application/pdf",
    });
    expect(() => inspectSourceUpload("pdf", bytes("not a pdf"))).toThrow(
      "The selected file is not a valid PDF document.",
    );
  });
});
