import { applicationDefault, getApps, initializeApp } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { cookies } from "next/headers";
import { pilotMembership, type PilotRole } from "@/lib/claims";

export type SessionIdentity = {
  uid: string;
  email: string;
  tenantId: string;
  roles: PilotRole[];
  demo: boolean;
};

const demoIdentity: SessionIdentity = {
  uid: "demo-steward",
  email: "steward@demo-bank.test",
  tenantId: process.env.DEMO_TENANT_ID ?? "demo-bank",
  roles: ["admin", "steward", "auditor"],
  demo: true,
};

function adminAuth() {
  if (!getApps().length) {
    initializeApp({ credential: applicationDefault() });
  }
  return getAuth();
}

export async function getSession(): Promise<SessionIdentity | null> {
  const cookieStore = await cookies();
  const value = cookieStore.get("oa_session")?.value;
  if (!value) return null;

  const demoModeEnabled =
    process.env.NEXT_PUBLIC_DEMO_MODE === "true" ||
    (process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_DEMO_MODE !== "false");
  if (value === "demo" && demoModeEnabled) {
    return demoIdentity;
  }

  try {
    const decoded = await adminAuth().verifySessionCookie(value, true);
    const membership = pilotMembership(decoded);
    if (!membership) return null;

    return {
      uid: decoded.uid,
      email: decoded.email ?? "unknown",
      tenantId: membership.tenantId,
      roles: membership.roles,
      demo: false,
    };
  } catch {
    return null;
  }
}
