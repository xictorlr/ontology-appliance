import type { DriftTaskPayload } from "../types";
import {
  assertSafeSegment,
  assertUtcDay,
  assertUtcTimestamp,
  deterministicId,
} from "./identifiers";

interface TenantDocument {
  id: string;
}

interface ActiveTenantQuery {
  get(): Promise<{ docs: TenantDocument[] }>;
}

export interface ActiveTenantStore {
  collection(path: string): {
    where(field: string, operator: "==", value: string): {
      limit(count: number): ActiveTenantQuery;
    };
  };
}

export type DriftTaskEnqueuer = (payload: DriftTaskPayload) => Promise<void>;

export async function listActiveTenantIds(
  database: ActiveTenantStore,
): Promise<string[]> {
  const snapshot = await database
    .collection("tenants")
    .where("status", "==", "ACTIVE")
    .limit(101)
    .get();
  if (snapshot.docs.length > 100) {
    throw new Error(
      "Active tenant bound exceeded; refusing a partial drift schedule",
    );
  }
  return snapshot.docs.map((tenant) => assertSafeSegment(tenant.id, "tenantId"));
}

export async function enqueueDriftForTenants(
  tenantIds: readonly string[],
  scheduledDay: string,
  evaluatedAt: string,
  enqueueTask: DriftTaskEnqueuer,
): Promise<void> {
  const safeScheduledDay = assertUtcDay(scheduledDay);
  const safeEvaluatedAt = assertUtcTimestamp(evaluatedAt);
  await Promise.all(
    tenantIds.map(async (candidateTenantId) => {
      const tenantId = assertSafeSegment(candidateTenantId, "tenantId");
      const executionId = deterministicId("drift", tenantId, safeScheduledDay);
      await enqueueTask({
        tenantId,
        scheduledDay: safeScheduledDay,
        evaluatedAt: safeEvaluatedAt,
        executionId,
      });
    }),
  );
}
