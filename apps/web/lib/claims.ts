export const pilotRoles = ["admin", "steward", "auditor"] as const;

export type PilotRole = (typeof pilotRoles)[number];

export function pilotMembership(claims: unknown): {
  tenantId: string;
  roles: PilotRole[];
} | null {
  if (typeof claims !== "object" || claims === null || Array.isArray(claims)) return null;
  const values = claims as Record<string, unknown>;
  const tenantClaim = values.tenant_id;
  if (
    typeof tenantClaim !== "string" ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(tenantClaim)
  ) return null;

  const roles = Array.isArray(values.roles)
    ? values.roles.filter(
        (role): role is PilotRole =>
          typeof role === "string" && pilotRoles.includes(role as PilotRole),
      )
    : [];
  if (roles.length === 0) return null;

  return { tenantId: tenantClaim, roles: [...new Set(roles)] };
}
