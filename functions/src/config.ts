import { defineString } from "firebase-functions/params";

export const REGION = "europe-west4";

export const sourceBucket = defineString("SOURCE_BUCKET", {
  description: "Firebase-enabled input bucket provisioned by Terraform.",
  default: "demo-ontology-appliance-oa-input",
});

export const functionsServiceAccount = defineString(
  "FUNCTIONS_SERVICE_ACCOUNT",
  {
    description: "Terraform-managed least-privilege Functions runtime identity.",
  },
);

export const ontologyBaseVersion = defineString("ONTOLOGY_BASE_VERSION", {
  description: "Pinned ontology version used when building deterministic proposals.",
  default: "2026.07.1-candidate",
});

export const defaultTenantId = defineString("DEFAULT_TENANT_ID", {
  description: "Pilot tenant used only when seeding local emulator data.",
  default: "demo-bank",
});

export const taskRetryConfig = {
  maxAttempts: 5,
  minBackoffSeconds: 30,
  maxBackoffSeconds: 3_600,
  maxDoublings: 5,
} as const;

export const taskRateLimits = {
  maxConcurrentDispatches: 5,
  maxDispatchesPerSecond: 2,
} as const;
