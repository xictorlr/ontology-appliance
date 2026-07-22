import {
  FieldValue,
  Firestore,
  Timestamp,
} from "firebase-admin/firestore";

// A task may execute for at most five minutes. The six-minute lease prevents a
// concurrent delivery from taking over a live handler while still allowing the
// final bounded Cloud Tasks retry (30/60/120/240-second backoff) to recover a
// process that was terminated before it could record FAILED or COMPLETED.
const STALE_EXECUTION_MS = 6 * 60 * 1_000;

export interface ExecutionClaim {
  claimed: boolean;
  priorStatus?: string;
}

export async function claimExecution(
  db: Firestore,
  tenantId: string,
  executionId: string,
  kind: string,
): Promise<ExecutionClaim> {
  const ref = db.doc(
    `tenants/${tenantId}/taskExecutions/${executionId}`,
  );

  return db.runTransaction(async (transaction) => {
    const snapshot = await transaction.get(ref);
    const prior = snapshot.data();
    const priorStatus = typeof prior?.status === "string" ? prior.status : undefined;

    if (priorStatus === "COMPLETED") {
      return { claimed: false, priorStatus };
    }

    if (priorStatus === "RUNNING") {
      const startedAt = prior?.startedAt;
      const startedAtMs =
        startedAt instanceof Timestamp ? startedAt.toMillis() : Date.now();
      if (Date.now() - startedAtMs < STALE_EXECUTION_MS) {
        return { claimed: false, priorStatus };
      }
    }

    const attempts = typeof prior?.attempts === "number" ? prior.attempts + 1 : 1;
    transaction.set(
      ref,
      {
        kind,
        status: "RUNNING",
        attempts,
        startedAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      },
      { merge: true },
    );
    return priorStatus === undefined
      ? { claimed: true }
      : { claimed: true, priorStatus };
  });
}

export async function failExecution(
  db: Firestore,
  tenantId: string,
  executionId: string,
  error: unknown,
): Promise<void> {
  const message = error instanceof Error ? error.message : "Unknown task error";
  await db.doc(`tenants/${tenantId}/taskExecutions/${executionId}`).set(
    {
      status: "FAILED",
      error: message.slice(0, 1_000),
      failedAt: FieldValue.serverTimestamp(),
      updatedAt: FieldValue.serverTimestamp(),
    },
    { merge: true },
  );
}
