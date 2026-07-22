#!/usr/bin/env node

const { createHash } = require("node:crypto");
const { initializeApp } = require("firebase-admin/app");
const { getFunctions } = require("firebase-admin/functions");

const [projectId, region, tenantId, scheduledDay, smokeId] = process.argv.slice(2);
if (![projectId, region, tenantId, scheduledDay, smokeId].every(Boolean)) {
  throw new Error(
    "Usage: enqueue-drift-smoke.cjs PROJECT REGION TENANT YYYY-MM-DD SMOKE_ID",
  );
}
if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(tenantId)) {
  throw new Error("Unsafe tenant ID");
}
if (!/^\d{4}-\d{2}-\d{2}$/u.test(scheduledDay)) {
  throw new Error("Invalid UTC day");
}

const executionId = createHash("sha256")
  .update(["drift-smoke", tenantId, scheduledDay, smokeId].join("\u001f"))
  .digest("hex");
const app = initializeApp({ projectId });
const functionName = `locations/${region}/functions/processDriftTask`;
const evaluatedAt = new Date().toISOString();

getFunctions(app)
  .taskQueue(functionName)
  .enqueue(
    { tenantId, scheduledDay, evaluatedAt, executionId },
    { id: executionId, scheduleDelaySeconds: 0 },
  )
  .then(() => process.stdout.write(`${executionId}\n`))
  .catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
