import { describe, expect, it } from "vitest";
import {
  hasExplicitMembershipClaims,
  selfEnrollmentAssignment,
} from "../lib/self-enrollment";

const enabled = {
  OA_SELF_ENROLLMENT_ENABLED: "true",
  OA_SELF_ENROLLMENT_TENANT_ID: "demo-bank",
};

describe("selfEnrollmentAssignment", () => {
  it("assigns a verified, unassigned identity to the configured tenant as auditor", () => {
    expect(selfEnrollmentAssignment({ email_verified: true }, enabled)).toEqual({
      tenantId: "demo-bank",
      roles: ["auditor"],
    });
  });

  it("fails closed when disabled, unverified, preassigned, or misconfigured", () => {
    expect(selfEnrollmentAssignment({ email_verified: true }, {})).toBeNull();
    expect(selfEnrollmentAssignment({ email_verified: false }, enabled)).toBeNull();
    expect(
      selfEnrollmentAssignment(
        { email_verified: true, tenant_id: "other-bank" },
        enabled,
      ),
    ).toBeNull();
    expect(
      selfEnrollmentAssignment(
        { email_verified: true },
        { ...enabled, OA_SELF_ENROLLMENT_TENANT_ID: "../other" },
      ),
    ).toBeNull();
  });

  it("detects partial membership claims instead of overwriting them", () => {
    expect(hasExplicitMembershipClaims({ roles: [] })).toBe(true);
    expect(hasExplicitMembershipClaims({ tenant_id: "" })).toBe(true);
    expect(hasExplicitMembershipClaims({ email_verified: true })).toBe(false);
  });
});
