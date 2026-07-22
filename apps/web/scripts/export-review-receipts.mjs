#!/usr/bin/env node

import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const exportSchema = "urn:ontology-appliance:schema:firestore-review-receipts-export:1";
const safeIdentifier = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;

function utcSecond(value, label) {
  const date = value && typeof value.toDate === "function" ? value.toDate() : null;
  if (!(date instanceof Date) || Number.isNaN(date.valueOf())) {
    throw new Error(`${label} must be a Firestore Timestamp`);
  }
  return date.toISOString().replace(/\.\d{3}Z$/u, "Z");
}

function requiredText(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

export function normalizeReceipt(documentId, data, tenantId) {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`${documentId} must contain an object`);
  }
  if (data.tenantId !== tenantId) {
    throw new Error(`${documentId} is not bound to tenant ${tenantId}`);
  }
  if (!Array.isArray(data.reviewerRoles) || data.reviewerRoles.some((role) => typeof role !== "string")) {
    throw new Error(`${documentId}.reviewerRoles must be a string array`);
  }
  const normalized = {
    receiptId: requiredText(data.receiptId, `${documentId}.receiptId`),
    proposalId: requiredText(data.proposalId, `${documentId}.proposalId`),
    tenantId,
    reviewerUid: requiredText(data.reviewerUid, `${documentId}.reviewerUid`),
    reviewerRoles: [...new Set(data.reviewerRoles)].sort(),
    decision: requiredText(data.decision, `${documentId}.decision`),
    resultingStatus: requiredText(data.resultingStatus, `${documentId}.resultingStatus`),
    rationaleSha256: requiredText(data.rationaleSha256, `${documentId}.rationaleSha256`),
    verificationRunId: requiredText(data.verificationRunId, `${documentId}.verificationRunId`),
    verificationRunSha256: requiredText(
      data.verificationRunSha256,
      `${documentId}.verificationRunSha256`,
    ),
    frozenProposalSha256: requiredText(
      data.frozenProposalSha256,
      `${documentId}.frozenProposalSha256`,
    ),
    frozenEvidenceIndexSha256: requiredText(
      data.frozenEvidenceIndexSha256,
      `${documentId}.frozenEvidenceIndexSha256`,
    ),
    policyVersion: requiredText(data.policyVersion, `${documentId}.policyVersion`),
    activeOntologyVersion: requiredText(
      data.activeOntologyVersion,
      `${documentId}.activeOntologyVersion`,
    ),
    createdAt: utcSecond(data.createdAt, `${documentId}.createdAt`),
  };
  if (normalized.receiptId !== documentId) {
    throw new Error(`${documentId} does not match its receiptId`);
  }
  return normalized;
}

function parseArgs(argv) {
  const options = { confirmCloudRead: false, selfTest: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--confirm-cloud-read") options.confirmCloudRead = true;
    else if (argument === "--self-test") options.selfTest = true;
    else if (["--project", "--tenant", "--output"].includes(argument)) {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`${argument} requires a value`);
      options[argument.slice(2)] = value;
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${argument}`);
    }
  }
  return options;
}

function selfTest() {
  const normalized = normalizeReceipt(
    "review-1",
    {
      receiptId: "review-1",
      proposalId: "mapping-1",
      tenantId: "demo-bank",
      reviewerUid: "steward-1",
      reviewerEmail: "must-not-be-exported@example.invalid",
      reviewerRoles: ["steward", "steward"],
      decision: "REVIEW_REQUIRED",
      resultingStatus: "HUMAN_REVIEW",
      rationale: "must not leave Firestore",
      rationaleSha256: "a".repeat(64),
      verificationRunId: "run-1",
      verificationRunSha256: "b".repeat(64),
      frozenProposalSha256: "c".repeat(64),
      frozenEvidenceIndexSha256: "d".repeat(64),
      policyVersion: "policy-v1",
      activeOntologyVersion: "ontology-v1",
      createdAt: { toDate: () => new Date("2026-07-22T15:04:05.678Z") },
    },
    "demo-bank",
  );
  assert.equal(normalized.createdAt, "2026-07-22T15:04:05Z");
  assert.deepEqual(normalized.reviewerRoles, ["steward"]);
  assert.equal("reviewerEmail" in normalized, false);
  assert.equal("rationale" in normalized, false);
  console.log("self-test: ok");
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.selfTest) {
    selfTest();
    return;
  }
  if (!options.confirmCloudRead) {
    throw new Error("Refusing Firestore access without --confirm-cloud-read");
  }
  const projectId = requiredText(options.project, "--project");
  const tenantId = requiredText(options.tenant, "--tenant");
  const output = requiredText(options.output, "--output");
  if (!safeIdentifier.test(projectId) || !safeIdentifier.test(tenantId)) {
    throw new Error("--project and --tenant must be explicit safe identifiers");
  }

  const [{ applicationDefault, initializeApp }, { getFirestore }] = await Promise.all([
    import("firebase-admin/app"),
    import("firebase-admin/firestore"),
  ]);
  const app = initializeApp({ credential: applicationDefault(), projectId });
  const database = getFirestore(app);
  const collectionPath = `tenants/${tenantId}/reviewReceipts`;
  const snapshot = await database.collection(collectionPath).orderBy("proposalId").get();
  const receipts = snapshot.docs.map((document) =>
    normalizeReceipt(document.id, document.data(), tenantId),
  );
  receipts.sort((left, right) =>
    left.proposalId.localeCompare(right.proposalId) || left.receiptId.localeCompare(right.receiptId),
  );
  const payload = {
    $schema: exportSchema,
    tenantId,
    collectionPath,
    exportedAt: new Date().toISOString().replace(/\.\d{3}Z$/u, "Z"),
    receipts,
  };
  const outputPath = resolve(output);
  await writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  await database.terminate();
  console.log(JSON.stringify({ exported: true, receiptCount: receipts.length, path: outputPath }));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : "Review receipt export failed");
  process.exitCode = 1;
});
