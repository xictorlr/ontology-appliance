import { describe, expect, it, vi } from "vitest";

import {
  enqueueDriftForTenants,
  listActiveTenantIds,
  type ActiveTenantStore,
} from "../src/lib/drift";
import { deterministicId } from "../src/lib/identifiers";

describe("daily drift tenant enumeration", () => {
  it("queries only active tenants with the governed bound", async () => {
    const get = vi.fn().mockResolvedValue({
      docs: [{ id: "demo-bank" }, { id: "second-bank" }],
    });
    const limit = vi.fn().mockReturnValue({ get });
    const where = vi.fn().mockReturnValue({ limit });
    const collection = vi.fn().mockReturnValue({ where });

    const tenantIds = await listActiveTenantIds({
      collection,
    } as ActiveTenantStore);

    expect(collection).toHaveBeenCalledWith("tenants");
    expect(where).toHaveBeenCalledWith("status", "==", "ACTIVE");
    expect(limit).toHaveBeenCalledWith(101);
    expect(tenantIds).toEqual(["demo-bank", "second-bank"]);
  });

  it("enqueues one deterministic task per enumerated tenant", async () => {
    const enqueueTask = vi.fn().mockResolvedValue(undefined);

    await enqueueDriftForTenants(
      ["demo-bank", "second-bank"],
      "2026-07-22",
      "2026-07-22T00:00:00Z",
      enqueueTask,
    );

    expect(enqueueTask).toHaveBeenCalledTimes(2);
    expect(enqueueTask).toHaveBeenCalledWith({
      tenantId: "demo-bank",
      scheduledDay: "2026-07-22",
      evaluatedAt: "2026-07-22T00:00:00Z",
      executionId: deterministicId("drift", "demo-bank", "2026-07-22"),
    });
  });

  it("rejects an unsafe tenant returned by the database", async () => {
    const database = {
      collection: () => ({
        where: () => ({
          limit: () => ({ get: async () => ({ docs: [{ id: ".." }] }) }),
        }),
      }),
    } as ActiveTenantStore;

    await expect(listActiveTenantIds(database)).rejects.toThrow("Invalid tenantId");
  });

  it("fails closed instead of silently truncating active tenants", async () => {
    const database = {
      collection: () => ({
        where: () => ({
          limit: () => ({
            get: async () => ({
              docs: Array.from({ length: 101 }, (_, index) => ({
                id: `tenant-${index}`,
              })),
            }),
          }),
        }),
      }),
    } as ActiveTenantStore;

    await expect(listActiveTenantIds(database)).rejects.toThrow(
      "Active tenant bound exceeded",
    );
  });

  it("rejects ambiguous scheduler timestamps before dispatch", async () => {
    await expect(
      enqueueDriftForTenants(
        ["demo-bank"],
        "2026-07-22",
        "2026-07-22T02:00:00+02:00",
        vi.fn(),
      ),
    ).rejects.toThrow("Invalid UTC timestamp");
  });
});
