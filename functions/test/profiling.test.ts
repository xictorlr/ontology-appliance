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
    expect(profile.columnNames).toEqual(["id", "name"]);
    expect(JSON.stringify(profile)).not.toContain("Acme");
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
    expect(profile.columnNames).toEqual([]);
  });
});

describe("bounded column name extraction", () => {
  it("parses only the first CSV line, honoring quotes and a BOM", () => {
    const profile = profileSource(
      Buffer.from('\uFEFF id ,"full, name","she said ""hi""",amount\n1,"Acme, S.A.",x,5\n'),
      "text/csv",
    );
    expect(profile.columnNames).toEqual([
      "id",
      "full, name",
      'she said "hi"',
      "amount",
    ]);
    expect(JSON.stringify(profile.columnNames)).not.toContain("Acme");
  });

  it("keeps a quoted header cell that spans an embedded newline", () => {
    const profile = profileSource(
      Buffer.from('"first\nheader",second\n1,2\n'),
      "text/csv",
    );
    expect(profile.columnNames).toEqual(["first\nheader", "second"]);
  });

  it("records a numeric-looking header row without heuristics", () => {
    const profile = profileSource(Buffer.from("1,2.5,+3\n4,5,6\n"), "text/csv");
    expect(profile.columnNames).toEqual(["1", "2.5", "+3"]);
  });

  it("drops empty names, drops oversized names, and bounds the list", () => {
    const oversized = "x".repeat(201);
    const names = Array.from({ length: 120 }, (_, index) => `c${index}`);
    const profile = profileSource(
      Buffer.from([`,${oversized}`, ...names].join(",") + "\n"),
      "text/csv",
    );
    expect(profile.columnNames).toHaveLength(100);
    expect(profile.columnNames[0]).toBe("c0");
    expect(profile.columnNames).not.toContain(oversized);
    expect(profile.columnNames).not.toContain("");
  });

  it("takes the sorted top-level keys of only the first NDJSON record", () => {
    const profile = profileSource(
      Buffer.from('{"beta":1,"alpha":{"nested":2}}\n{"gamma":3}\n'),
      "application/x-ndjson",
    );
    expect(profile.columnNames).toEqual(["alpha", "beta"]);
  });

  it("takes the sorted top-level keys of the first record of a JSON array", () => {
    const profile = profileSource(
      Buffer.from('[{"zulu":1,"alpha":2},{"other":3}]'),
      "application/json",
    );
    expect(profile.columnNames).toEqual(["alpha", "zulu"]);
  });

  it("records no column names for non-tabular JSON shapes", () => {
    expect(
      profileSource(Buffer.from('{"top":1}'), "application/json").columnNames,
    ).toEqual([]);
    expect(
      profileSource(Buffer.from("[1,2,3]"), "application/json").columnNames,
    ).toEqual([]);
    expect(
      profileSource(Buffer.from("line one\nline two\n"), "text/plain").columnNames,
    ).toEqual([]);
  });
});
