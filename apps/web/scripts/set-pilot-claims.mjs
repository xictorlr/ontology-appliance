import { applicationDefault, initializeApp } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";

function option(name) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const email = option("email");
const uid = option("uid");
const projectId = option("project");
const confirmedProject = option("confirm-project");
const tenantId = option("tenant") ?? "demo-bank";
const roles = (option("roles") ?? "steward,auditor")
  .split(",")
  .map((role) => role.trim())
  .filter(Boolean);
const allowedRoles = new Set(["admin", "steward", "auditor"]);

if ((!email && !uid) || !projectId || confirmedProject !== projectId) {
  console.error("Usage: pnpm claims:set -- --project PROJECT_ID --confirm-project PROJECT_ID --email user@example.com --roles steward,auditor");
  process.exit(2);
}
if (roles.length === 0 || roles.some((role) => !allowedRoles.has(role))) {
  console.error("Roles must be a comma-separated subset of admin,steward,auditor.");
  process.exit(2);
}
if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(tenantId)) {
  console.error("Tenant must be a safe 1-64 character document identifier.");
  process.exit(2);
}
const environmentProject = process.env.GOOGLE_CLOUD_PROJECT ?? process.env.GCLOUD_PROJECT;
if (environmentProject && environmentProject !== projectId) {
  console.error(`Refusing project mismatch: environment=${environmentProject}, argument=${projectId}.`);
  process.exit(2);
}

console.log(`Confirmed mutation target: project=${projectId}, principal=${uid ?? email}, tenant=${tenantId}, roles=${roles.join(",")}.`);
initializeApp({ credential: applicationDefault(), projectId });
const auth = getAuth();
const user = uid ? await auth.getUser(uid) : await auth.getUserByEmail(email);
const current = user.customClaims ?? {};
await auth.setCustomUserClaims(user.uid, { ...current, tenant_id: tenantId, roles });
await auth.revokeRefreshTokens(user.uid);
console.log(`Assigned tenant ${tenantId} and roles ${roles.join(",")} to uid ${user.uid}.`);
console.log("Existing sessions were revoked; the user must sign in again.");
