import type { PilotRole } from "@/lib/claims";

const safeTenantId = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

type SelfEnrollmentEnvironment = {
  [key: string]: string | undefined;
  OA_SELF_ENROLLMENT_ENABLED?: string;
  OA_SELF_ENROLLMENT_TENANT_ID?: string;
};

export type SelfEnrollmentAssignment = {
  tenantId: string;
  roles: readonly [Extract<PilotRole, "auditor">];
};

export function hasExplicitMembershipClaims(claims: unknown): boolean {
  if (typeof claims !== "object" || claims === null || Array.isArray(claims)) return false;
  return (
    Object.prototype.hasOwnProperty.call(claims, "tenant_id") ||
    Object.prototype.hasOwnProperty.call(claims, "roles")
  );
}

export function selfEnrollmentAssignment(
  claims: unknown,
  environment: SelfEnrollmentEnvironment = process.env,
): SelfEnrollmentAssignment | null {
  if (environment.OA_SELF_ENROLLMENT_ENABLED !== "true") return null;
  if (typeof claims !== "object" || claims === null || Array.isArray(claims)) return null;

  const values = claims as Record<string, unknown>;
  if (values.email_verified !== true || hasExplicitMembershipClaims(values)) return null;

  const tenantId = environment.OA_SELF_ENROLLMENT_TENANT_ID;
  if (typeof tenantId !== "string" || !safeTenantId.test(tenantId)) return null;

  return { tenantId, roles: ["auditor"] };
}
