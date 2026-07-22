import { describe, expect, it } from "vitest";

import {
  assertSafeSegment,
  assertUtcDay,
  assertUtcTimestamp,
  deterministicId,
  isSupportedContentType,
  parseSourceObjectName,
  utcDay,
} from "../src/lib/identifiers";

describe("tenant object identifiers", () => {
  it("parses the narrow immutable upload contract", () => {
    expect(
      parseSourceObjectName("tenants/demo-bank/uploads/crm/parties.csv"),
    ).toEqual({
      tenantId: "demo-bank",
      sourceId: "crm",
      fileName: "parties.csv",
    });
  });

  it.each([
    "tenants/demo-bank/sources/crm/parties.csv",
    "tenants/demo-bank/uploads/crm/folder/parties.csv",
    "other/demo-bank/uploads/crm/parties.csv",
  ])("ignores objects outside the upload contract: %s", (objectName) => {
    expect(parseSourceObjectName(objectName)).toBeNull();
  });

  it("rejects traversal and unsafe document segments", () => {
    expect(() => assertSafeSegment("..", "tenantId")).toThrow("Invalid tenantId");
    expect(() =>
      parseSourceObjectName("tenants/demo bank/uploads/crm/parties.csv"),
    ).toThrow("Invalid tenantId");
  });

  it("accepts only the connector MIME allowlist", () => {
    expect(isSupportedContentType("text/csv; charset=utf-8")).toBe(true);
    expect(isSupportedContentType("application/pdf")).toBe(true);
    expect(isSupportedContentType("application/octet-stream")).toBe(false);
    expect(isSupportedContentType("text/html")).toBe(false);
  });
});

describe("deterministic orchestration values", () => {
  it("builds stable collision-resistant ids", () => {
    const first = deterministicId("verification", "demo-bank", "p-1", 1);
    const second = deterministicId("verification", "demo-bank", "p-1", 1);
    const changed = deterministicId("verification", "demo-bank", "p-2", 1);
    expect(first).toHaveLength(64);
    expect(first).toBe(second);
    expect(first).not.toBe(changed);
  });

  it("normalizes unicode before hashing", () => {
    expect(deterministicId("caf\u00e9")).toBe(deterministicId("cafe\u0301"));
  });

  it("uses an explicit UTC day for drift idempotency", () => {
    expect(utcDay(new Date("2026-07-22T23:59:59.000Z"))).toBe("2026-07-22");
    expect(assertUtcDay("2026-07-22")).toBe("2026-07-22");
    expect(() => assertUtcDay("2026-02-30")).toThrow("Invalid scheduledDay");
    expect(() => assertUtcDay("../../secrets")).toThrow("Invalid scheduledDay");
  });

  it("accepts only explicit UTC instants", () => {
    expect(assertUtcTimestamp("2026-07-22T13:51:12Z")).toBe(
      "2026-07-22T13:51:12Z",
    );
    expect(assertUtcTimestamp("2026-07-22T13:51:12.123456Z")).toBe(
      "2026-07-22T13:51:12.123456Z",
    );
    expect(() => assertUtcTimestamp("2026-07-22T15:51:12+02:00")).toThrow(
      "Invalid UTC timestamp",
    );
    expect(() => assertUtcTimestamp("2026-02-30T13:51:12Z")).toThrow(
      "Invalid UTC timestamp",
    );
  });
});
