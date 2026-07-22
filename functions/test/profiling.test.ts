import { describe, expect, it } from "vitest";

import { profileSource } from "../src/lib/profiling";

describe("metadata-first evidence profiling", () => {
  it("counts CSV data records without persisting values", () => {
    const profile = profileSource(
      Buffer.from('id,name\n1,"Acme, S.A."\n2,Example\n'),
      "text/csv; charset=utf-8",
    );
    expect(profile.recordCount).toBe(2);
    expect(profile.sha256).toMatch(/^[a-f0-9]{64}$/u);
    expect(profile).not.toHaveProperty("sample");
  });

  it("validates and counts JSONL records", () => {
    expect(
      profileSource(Buffer.from('{"id":1}\n{"id":2}\n'), "application/x-ndjson")
        .recordCount,
    ).toBe(2);
    expect(() =>
      profileSource(Buffer.from('{"id":1}\nnot-json\n'), "application/x-ndjson"),
    ).toThrow();
  });

  it("hashes PDF evidence without attempting to extract sensitive text", () => {
    const profile = profileSource(Buffer.from("%PDF-1.7 synthetic"), "application/pdf");
    expect(profile.recordCount).toBeNull();
    expect(profile.byteSize).toBeGreaterThan(0);
  });
});
