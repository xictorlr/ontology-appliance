import { describe, expect, it } from "vitest";
import { pilotMembership } from "../lib/claims";

describe("pilotMembership", () => {
  it("accepts explicit custom tenant claims and only approved roles", () => {
    expect(
      pilotMembership({ tenant_id: "bank-a", roles: ["steward", "unknown", "steward"] }),
    ).toEqual({ tenantId: "bank-a", roles: ["steward"] });
  });

  it("requires the same explicit tenant_id custom claim as Firebase rules", () => {
    expect(
      pilotMembership({ firebase: { tenant: "bank-b" }, roles: ["auditor"] } as never),
    ).toBeNull();
  });

  it("never falls back to the demo tenant for an incomplete cloud identity", () => {
    expect(pilotMembership({ roles: ["admin"] })).toBeNull();
    expect(pilotMembership({ tenant_id: "bank-a", roles: [] })).toBeNull();
  });
});
