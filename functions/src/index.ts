import { initializeApp } from "firebase-admin/app";
import { FieldValue, getFirestore, Timestamp } from "firebase-admin/firestore";
import { getFunctions } from "firebase-admin/functions";
import { getStorage } from "firebase-admin/storage";
import { logger } from "firebase-functions";
import { setGlobalOptions } from "firebase-functions/v2/options";
import { onDocumentCreated } from "firebase-functions/v2/firestore";
import { onSchedule } from "firebase-functions/v2/scheduler";
import { onObjectFinalized } from "firebase-functions/v2/storage";
import { onTaskDispatched } from "firebase-functions/v2/tasks";

import {
  REGION,
  functionsServiceAccount,
  ontologyBaseVersion,
  sourceBucket,
  taskRateLimits,
  taskRetryConfig,
} from "./config";
import { enqueueDriftForTenants, listActiveTenantIds } from "./lib/drift";
import { claimExecution, failExecution } from "./lib/idempotency";
import {
  assertSafeSegment,
  assertUtcDay,
  assertUtcTimestamp,
  deterministicId,
  isSupportedContentType,
  parseSourceObjectName,
  utcDay,
} from "./lib/identifiers";
import { profileSource } from "./lib/profiling";
import {
  buildDriftProposal,
  buildIngestionProposal,
  buildVerificationDecision,
  type DriftSource,
} from "./lib/workflows";
import type {
  DriftTaskPayload,
  IngestionTaskPayload,
  VerificationTaskPayload,
} from "./types";

const app = initializeApp();
const db = getFirestore(app);
const taskQueues = getFunctions(app);
const storage = getStorage(app);

function requireRetryForRunningExecution(
  claim: Awaited<ReturnType<typeof claimExecution>>,
  tenantId: string,
  executionId: string,
): boolean {
  if (claim.claimed) return false;
  if (claim.priorStatus === "COMPLETED") {
    logger.info("Skipping completed task delivery", { tenantId, executionId });
    return true;
  }
  throw new Error(
    `Execution ${executionId} is already running; Cloud Tasks must retry instead of acknowledging it`,
  );
}

function evidenceObservedAt(value: unknown): string {
  if (typeof value === "string") return assertUtcTimestamp(value);
  if (value instanceof Timestamp) return value.toDate().toISOString();
  throw new Error("Changed source profile has no reproducible observation timestamp");
}

setGlobalOptions({
  region: REGION,
  cpu: 1,
  memory: "256MiB",
  minInstances: 0,
  maxInstances: 10,
  concurrency: 20,
  timeoutSeconds: 60,
  serviceAccount: functionsServiceAccount,
});

const taskOptions = {
  region: REGION,
  retryConfig: taskRetryConfig,
  rateLimits: taskRateLimits,
  memory: "512MiB" as const,
  timeoutSeconds: 300,
  minInstances: 0,
  maxInstances: 5,
};

async function enqueue<T extends { executionId: string }>(
  queueName: string,
  data: T,
): Promise<void> {
  const functionName = `locations/${REGION}/functions/${queueName}`;
  try {
    await taskQueues.taskQueue<T>(functionName).enqueue(data, {
      id: data.executionId,
      scheduleDelaySeconds: 0,
    });
  } catch (error) {
    const code =
      typeof error === "object" && error !== null && "code" in error
        ? String(error.code)
        : "";
    if (code === "functions/task-already-exists") {
      logger.info("Task already exists; treating enqueue as idempotent", {
        queueName,
        executionId: data.executionId,
      });
      return;
    }
    throw error;
  }
}

export const sourceObjectFinalized = onObjectFinalized(
  {
    region: REGION,
    bucket: sourceBucket,
    maxInstances: 4,
  },
  async (event) => {
    const objectName = event.data.name;
    const identity = parseSourceObjectName(objectName);
    if (identity === null) {
      logger.info("Ignoring object outside tenant upload contract", { objectName });
      return;
    }

    const generation = String(event.data.generation ?? "unknown");
    const sizeBytes = Number(event.data.size ?? 0);
    const contentType = event.data.contentType ?? "application/octet-stream";
    const executionId = deterministicId(
      "ingestion",
      event.data.bucket,
      objectName,
      generation,
    );
    const jobRef = db.doc(
      `tenants/${identity.tenantId}/jobs/ingestion-${executionId}`,
    );

    if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 1 || sizeBytes > 20 * 1024 * 1024) {
      await jobRef.set({
        type: "INGESTION",
        sourceId: identity.sourceId,
        objectName,
        status: "QUARANTINED",
        reason: "INVALID_OBJECT_SIZE",
        sizeBytes,
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
      return;
    }

    if (
      !isSupportedContentType(contentType) ||
      event.data.metadata?.tenantId !== identity.tenantId
    ) {
      await jobRef.set({
        type: "INGESTION",
        sourceId: identity.sourceId,
        objectName,
        status: "QUARANTINED",
        reason: !isSupportedContentType(contentType)
          ? "UNSUPPORTED_CONTENT_TYPE"
          : "TENANT_METADATA_MISMATCH",
        contentType,
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
      return;
    }

    const payload: IngestionTaskPayload = {
      tenantId: identity.tenantId,
      sourceId: identity.sourceId,
      objectName,
      bucket: event.data.bucket,
      generation,
      contentType,
      sizeBytes,
      observedAt: assertUtcTimestamp(event.time),
      executionId,
    };
    await jobRef.set(
      {
        type: "INGESTION",
        sourceId: identity.sourceId,
        objectName,
        bucket: event.data.bucket,
        generation,
        status: "QUEUED",
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      },
      { merge: true },
    );
    await enqueue("processIngestionTask", payload);
  },
);

export const proposalCreated = onDocumentCreated(
  {
    region: REGION,
    document: "tenants/{tenantId}/proposals/{proposalId}",
    maxInstances: 5,
  },
  async (event) => {
    const tenantId = assertSafeSegment(event.params.tenantId, "tenantId");
    const proposalId = assertSafeSegment(event.params.proposalId, "proposalId");
    const proposal = event.data?.data();
    if (proposal?.status !== "PENDING_VERIFICATION") {
      logger.info("Proposal does not require verification", {
        tenantId,
        proposalId,
        status: proposal?.status,
      });
      return;
    }

    const executionId = deterministicId(
      "verification",
      tenantId,
      proposalId,
      String(event.data?.createTime.toMillis() ?? 0),
    );
    await enqueue<VerificationTaskPayload>("processVerificationTask", {
      tenantId,
      proposalId,
      requestedAt: assertUtcTimestamp(event.time),
      executionId,
    });
  },
);

export const processIngestionTask = onTaskDispatched<IngestionTaskPayload>(
  taskOptions,
  async (request) => {
    const tenantId = assertSafeSegment(request.data.tenantId, "tenantId");
    const executionId = assertSafeSegment(request.data.executionId, "executionId");
    const sourceId = assertSafeSegment(request.data.sourceId, "sourceId");
    const identity = parseSourceObjectName(request.data.objectName);
    if (
      identity === null ||
      identity.tenantId !== tenantId ||
      identity.sourceId !== sourceId ||
      request.data.bucket !== sourceBucket.value()
    ) {
      throw new Error("Ingestion task does not match the immutable source object identity");
    }
    const claim = await claimExecution(db, tenantId, executionId, "INGESTION");
    if (requireRetryForRunningExecution(claim, tenantId, executionId)) return;

    const jobRef = db.doc(`tenants/${tenantId}/jobs/ingestion-${executionId}`);
    try {
      await jobRef.set(
        { status: "RUNNING", updatedAt: FieldValue.serverTimestamp() },
        { merge: true },
      );
      const object = storage
        .bucket(request.data.bucket)
        .file(request.data.objectName, { generation: request.data.generation });
      const [content] = await object.download({ validation: "crc32c" });
      if (content.byteLength !== request.data.sizeBytes) {
        throw new Error("Downloaded object size does not match the finalized generation");
      }
      const profile = profileSource(content, request.data.contentType);
      const snapshotId = `${sourceId}@sha256:${profile.sha256}`;
      const proposal = buildIngestionProposal({
        tenantId,
        sourceId,
        bucket: request.data.bucket,
        objectName: request.data.objectName,
        generation: request.data.generation,
        contentType: request.data.contentType,
        sizeBytes: request.data.sizeBytes,
        observedAt: assertUtcTimestamp(request.data.observedAt),
        activeOntologyVersion: ontologyBaseVersion.value(),
        profile,
      });
      const profileRef = db.doc(`tenants/${tenantId}/sourceProfiles/${sourceId}`);
      const snapshotRef = profileRef.collection("snapshots").doc(profile.sha256);
      const proposalRef = db.doc(
        `tenants/${tenantId}/proposals/${proposal.proposal_id}`,
      );
      const executionRef = db.doc(
        `tenants/${tenantId}/taskExecutions/${executionId}`,
      );
      await db.runTransaction(async (transaction) => {
        const [priorProfileSnapshot, priorSnapshot, priorProposal] = await Promise.all([
          transaction.get(profileRef),
          transaction.get(snapshotRef),
          transaction.get(proposalRef),
        ]);
        const priorProfile = priorProfileSnapshot.data();
        if (
          priorSnapshot.exists &&
          (priorSnapshot.data()?.sha256 !== profile.sha256 ||
            priorSnapshot.data()?.snapshotId !== snapshotId ||
            priorSnapshot.data()?.objectGeneration !== request.data.generation)
        ) {
          throw new Error("Immutable source snapshot conflicts with this task");
        }
        if (
          priorProposal.exists &&
          priorProposal.data()?.deterministic_input_hash !==
            proposal.deterministic_input_hash
        ) {
          throw new Error("Immutable ingestion proposal conflicts with this task");
        }
        if (!priorSnapshot.exists) {
          transaction.set(snapshotRef, {
            ...profile,
            snapshotId,
            sourceId,
            objectName: request.data.objectName,
            objectGeneration: request.data.generation,
            observedAt: request.data.observedAt,
            evidenceLocator: `gs://${request.data.bucket}/${request.data.objectName}#generation=${request.data.generation}`,
            createdAt: request.data.observedAt,
          });
        }
        if (!priorProposal.exists) {
          transaction.set(proposalRef, {
            ...proposal,
            createdAt: request.data.observedAt,
          });
        }
        const priorObservedAt = priorProfileSnapshot.exists
          ? evidenceObservedAt(
              priorProfile?.evidenceObservedAt ?? priorProfile?.observedAt,
            )
          : null;
        const isNewerOrSame =
          priorObservedAt === null ||
          new Date(priorObservedAt).getTime() <=
            new Date(request.data.observedAt).getTime();
        if (
          priorProfile?.workflowExecutionId !== executionId &&
          isNewerOrSame
        ) {
          transaction.set(
            profileRef,
            {
              ...profile,
              snapshotId,
              sourceId,
              objectName: request.data.objectName,
              objectGeneration: request.data.generation,
              previousSha256:
                typeof priorProfile?.sha256 === "string" ? priorProfile.sha256 : null,
              contentChanged:
                typeof priorProfile?.sha256 === "string" &&
                priorProfile.sha256 !== profile.sha256,
              evidenceLocator: `gs://${request.data.bucket}/${request.data.objectName}#generation=${request.data.generation}`,
              evidenceObservedAt: request.data.observedAt,
              workflowExecutionId: executionId,
              observedAt: request.data.observedAt,
              updatedAt: FieldValue.serverTimestamp(),
            },
            { merge: true },
          );
        }
        const status = "PROPOSAL_CREATED";
        transaction.set(
          jobRef,
          {
            status,
            snapshotId,
            proposalId: proposal.proposal_id,
            profile,
            updatedAt: FieldValue.serverTimestamp(),
          },
          { merge: true },
        );
        transaction.set(
          executionRef,
          {
            status: "COMPLETED",
            outcome: {
              status,
              snapshotId,
              proposalId: proposal.proposal_id,
            },
            completedAt: FieldValue.serverTimestamp(),
            updatedAt: FieldValue.serverTimestamp(),
          },
          { merge: true },
        );
      });
    } catch (error) {
      await Promise.all([
        failExecution(db, tenantId, executionId, error),
        jobRef.set(
          {
            status: "FAILED",
            error: error instanceof Error ? error.message.slice(0, 1_000) : "Unknown error",
            updatedAt: FieldValue.serverTimestamp(),
          },
          { merge: true },
        ),
      ]);
      throw error;
    }
  },
);

export const processVerificationTask = onTaskDispatched<VerificationTaskPayload>(
  taskOptions,
  async (request) => {
    const tenantId = assertSafeSegment(request.data.tenantId, "tenantId");
    const proposalId = assertSafeSegment(request.data.proposalId, "proposalId");
    const executionId = assertSafeSegment(request.data.executionId, "executionId");
    const claim = await claimExecution(db, tenantId, executionId, "VERIFICATION");
    if (requireRetryForRunningExecution(claim, tenantId, executionId)) return;

    const proposalRef = db.doc(`tenants/${tenantId}/proposals/${proposalId}`);
    const runRef = db.doc(`tenants/${tenantId}/verificationRuns/${executionId}`);
    const executionRef = db.doc(
      `tenants/${tenantId}/taskExecutions/${executionId}`,
    );
    try {
      await db.runTransaction(async (transaction) => {
        const [proposalSnapshot, priorRun] = await Promise.all([
          transaction.get(proposalRef),
          transaction.get(runRef),
        ]);
        if (!proposalSnapshot.exists) {
          throw new Error("Proposal no longer exists");
        }
        const proposal = proposalSnapshot.data() ?? {};
        if (proposal.status !== "PENDING_VERIFICATION") {
          throw new Error(
            "Verification refuses to overwrite a proposal that is no longer pending",
          );
        }
        const decision = buildVerificationDecision(
          tenantId,
          proposalId,
          executionId,
          assertUtcTimestamp(request.data.requestedAt),
          proposal,
        );
        if (priorRun.exists) {
          throw new Error("Verification refuses to overwrite an existing immutable run");
        }
        transaction.set(runRef, decision.run);
        for (const gateResult of decision.gates) {
          transaction.set(
            runRef.collection("gateResults").doc(gateResult.gateResultId),
            gateResult,
          );
        }
        transaction.set(
          proposalRef,
          {
            ...decision.proposalUpdate,
            updatedAt: FieldValue.serverTimestamp(),
          },
          { merge: true },
        );
        transaction.set(
          executionRef,
          {
            status: "COMPLETED",
            outcome: {
              status: decision.status,
              proposalId,
              verificationRunId: executionId,
              gateResultCount: decision.gates.length,
            },
            completedAt: FieldValue.serverTimestamp(),
            updatedAt: FieldValue.serverTimestamp(),
          },
          { merge: true },
        );
      });
    } catch (error) {
      await failExecution(db, tenantId, executionId, error);
      throw error;
    }
  },
);

export const enqueueDailyDriftChecks = onSchedule(
  {
    region: REGION,
    schedule: "0 2 * * *",
    timeZone: "Europe/Madrid",
    retryCount: 2,
    maxRetrySeconds: 3_600,
    timeoutSeconds: 300,
    maxInstances: 1,
  },
  async () => {
    const evaluatedAt = new Date().toISOString();
    const scheduledDay = utcDay(new Date(evaluatedAt));
    const tenantIds = await listActiveTenantIds(db);
    await enqueueDriftForTenants(
      tenantIds,
      scheduledDay,
      evaluatedAt,
      async (payload) => enqueue<DriftTaskPayload>("processDriftTask", payload),
    );
    logger.info("Daily drift checks enqueued", {
      scheduledDay,
      tenantCount: tenantIds.length,
    });
  },
);

export const processDriftTask = onTaskDispatched<DriftTaskPayload>(
  taskOptions,
  async (request) => {
    const tenantId = assertSafeSegment(request.data.tenantId, "tenantId");
    const scheduledDay = assertUtcDay(request.data.scheduledDay);
    const executionId = assertSafeSegment(request.data.executionId, "executionId");
    const claim = await claimExecution(db, tenantId, executionId, "DRIFT");
    if (requireRetryForRunningExecution(claim, tenantId, executionId)) return;

    const checkRef = db.doc(`tenants/${tenantId}/driftChecks/${scheduledDay}`);
    const executionRef = db.doc(
      `tenants/${tenantId}/taskExecutions/${executionId}`,
    );
    try {
      const sourceProfiles = await db
        .collection(`tenants/${tenantId}/sourceProfiles`)
        .limit(101)
        .get();
      if (sourceProfiles.size > 100) {
        throw new Error(
          "Drift profile bound exceeded; refusing to produce an incomplete proposal",
        );
      }
      const changedSourceEvidence: DriftSource[] = sourceProfiles.docs
        .filter((profile) => profile.data().contentChanged === true)
        .map((profile) => {
          const data = profile.data();
          const locator =
            typeof data.evidenceLocator === "string"
              ? data.evidenceLocator
              : typeof data.objectName === "string" &&
                  typeof data.objectGeneration === "string"
                ? `gs://${sourceBucket.value()}/${data.objectName}#generation=${data.objectGeneration}`
                : "";
          return {
            sourceId: profile.id,
            snapshotId: typeof data.snapshotId === "string" ? data.snapshotId : "",
            sha256: typeof data.sha256 === "string" ? data.sha256 : "",
            previousSha256:
              typeof data.previousSha256 === "string" ? data.previousSha256 : "",
            evidenceLocator: locator,
            observedAt: evidenceObservedAt(
              data.evidenceObservedAt ?? data.observedAt,
            ),
            extractorVersion:
              typeof data.extractorVersion === "string" ? data.extractorVersion : "",
          };
        });
      const proposal = buildDriftProposal({
        tenantId,
        scheduledDay,
        evaluatedAt: assertUtcTimestamp(request.data.evaluatedAt),
        activeOntologyVersion: ontologyBaseVersion.value(),
        changedSources: changedSourceEvidence,
      });
      const proposalRef = proposal
        ? db.doc(`tenants/${tenantId}/proposals/${proposal.proposal_id}`)
        : null;
      await db.runTransaction(async (transaction) => {
        const changedProfileRefs = changedSourceEvidence.map((source) =>
          db.doc(`tenants/${tenantId}/sourceProfiles/${source.sourceId}`),
        );
        const [priorProposal, ...currentProfiles] = await Promise.all([
          proposalRef ? transaction.get(proposalRef) : Promise.resolve(null),
          ...changedProfileRefs.map((reference) => transaction.get(reference)),
        ]);
        if (
          proposal &&
          priorProposal?.exists &&
          priorProposal.data()?.deterministic_input_hash !==
            proposal.deterministic_input_hash
        ) {
          throw new Error("Immutable drift proposal conflicts with this task");
        }
        if (proposal && proposalRef && !priorProposal?.exists) {
          transaction.set(proposalRef, {
            ...proposal,
            createdAt: request.data.evaluatedAt,
          });
        }
        for (const [index, profileSnapshot] of currentProfiles.entries()) {
          const evaluatedSource = changedSourceEvidence[index];
          const changedProfileRef = changedProfileRefs[index];
          const current = profileSnapshot.data();
          // Never acknowledge a newer upload that raced this drift task.
          if (
            evaluatedSource &&
            changedProfileRef &&
            profileSnapshot.exists &&
            current?.contentChanged === true &&
            current.sha256 === evaluatedSource.sha256 &&
            current.snapshotId === evaluatedSource.snapshotId
          ) {
            transaction.update(changedProfileRef, {
              contentChanged: false,
              driftBaselineSha256: evaluatedSource.sha256,
              driftBaselineSnapshotId: evaluatedSource.snapshotId,
              lastDriftProposalId: proposal?.proposal_id ?? null,
              lastDriftEvaluatedAt: request.data.evaluatedAt,
              updatedAt: FieldValue.serverTimestamp(),
            });
          }
        }
        const changedSources = changedSourceEvidence
          .map((source) => source.sourceId)
          .sort();
        const status = proposal
          ? "CHANGES_REQUIRE_REVIEW"
          : "NO_DRIFT_DETECTED";
        transaction.set(
          checkRef,
          {
            status,
            executionId,
            profiledSourceCount: sourceProfiles.size,
            changedSources,
            proposalId: proposal?.proposal_id ?? null,
            scheduledDay,
            evaluatedAt: request.data.evaluatedAt,
            createdAt: FieldValue.serverTimestamp(),
            updatedAt: FieldValue.serverTimestamp(),
          },
          { merge: true },
        );
        transaction.set(
          executionRef,
          {
            status: "COMPLETED",
            outcome: {
              status,
              proposalId: proposal?.proposal_id ?? null,
              changedSources,
            },
            completedAt: FieldValue.serverTimestamp(),
            updatedAt: FieldValue.serverTimestamp(),
          },
          { merge: true },
        );
      });
    } catch (error) {
      await failExecution(db, tenantId, executionId, error);
      throw error;
    }
  },
);
