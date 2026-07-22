import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
  type RulesTestContext,
  type RulesTestEnvironment,
} from "@firebase/rules-unit-testing";
import {
  collection,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  setDoc,
  updateDoc,
} from "firebase/firestore";
import {
  deleteObject,
  getBytes,
  getMetadata,
  ref,
  uploadBytes,
  type UploadMetadata,
} from "firebase/storage";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

const PROJECT_ID = "demo-ontology-appliance-rules";
const DEMO_TENANT = "demo-bank";
const USER_ID = "user-42";
const FIRESTORE_RULES = fileURLToPath(
  new URL("../../../firestore.rules", import.meta.url),
);
const STORAGE_RULES = fileURLToPath(
  new URL("../../../storage.rules", import.meta.url),
);

let testEnvironment: RulesTestEnvironment;

function authenticatedContext(
  roles: unknown,
  tenantId: unknown = DEMO_TENANT,
  uid = USER_ID,
): RulesTestContext {
  return testEnvironment.authenticatedContext(uid, {
    roles,
    tenant_id: tenantId,
  });
}

function uploadMetadata(
  tenantId = DEMO_TENANT,
  uploadedBy = USER_ID,
  contentType = "text/csv",
): UploadMetadata {
  return {
    contentType,
    customMetadata: {
      tenantId,
      uploadedBy,
    },
  };
}

async function seedFirestore(): Promise<void> {
  await testEnvironment.withSecurityRulesDisabled(async (context) => {
    const database = context.firestore();
    await Promise.all([
      setDoc(doc(database, "tenants", DEMO_TENANT), { name: "Demo Bank" }),
      setDoc(
        doc(database, "tenants", DEMO_TENANT, "ontologyVersions", "v1"),
        { status: "candidate" },
      ),
      setDoc(doc(database, "tenants", DEMO_TENANT, "concepts", "party"), {
        label: "Party",
      }),
      setDoc(
        doc(database, "tenants", DEMO_TENANT, "relations", "owns-account"),
        { label: "owns account" },
      ),
      setDoc(
        doc(database, "tenants", DEMO_TENANT, "questions", "cq-001"),
        { question: "Who owns this account?" },
      ),
      setDoc(
        doc(database, "tenants", DEMO_TENANT, "auditEvents", "audit-001"),
        { action: "proposal.created" },
      ),
      setDoc(
        doc(
          database,
          "tenants",
          DEMO_TENANT,
          "verificationRuns",
          "verify-001",
        ),
        { status: "complete" },
      ),
      setDoc(
        doc(
          database,
          "tenants",
          DEMO_TENANT,
          "taskExecutions",
          "task-001",
        ),
        { status: "complete" },
      ),
      setDoc(
        doc(database, "tenants", DEMO_TENANT, "settings", "private"),
        { verifier: "mock" },
      ),
      setDoc(
        doc(
          database,
          "tenants",
          DEMO_TENANT,
          "concepts",
          "party",
          "evidence",
          "source-001",
        ),
        { coordinate: "crm.csv#party_id" },
      ),
      setDoc(doc(database, "tenants", "other-bank", "concepts", "party"), {
        label: "Other Party",
      }),
    ]);
  });
}

beforeAll(async () => {
  if (
    process.env.FIRESTORE_EMULATOR_HOST === undefined ||
    process.env.FIREBASE_STORAGE_EMULATOR_HOST === undefined
  ) {
    throw new Error(
      "Security-rule tests must run through Firebase emulators:exec; refusing any non-emulator target.",
    );
  }

  testEnvironment = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      rules: await readFile(FIRESTORE_RULES, "utf8"),
    },
    storage: {
      rules: await readFile(STORAGE_RULES, "utf8"),
    },
  });
});

beforeEach(async () => {
  await Promise.all([
    testEnvironment.clearFirestore(),
    testEnvironment.clearStorage(),
  ]);
});

afterAll(async () => {
  await testEnvironment.cleanup();
});

describe("Firestore security rules", () => {
  it.each(["admin", "steward", "auditor"])(
    "allows a %s to read only the tenant's published semantic view",
    async (role) => {
      await seedFirestore();
      const database = authenticatedContext([role]).firestore();

      await assertSucceeds(getDoc(doc(database, "tenants", DEMO_TENANT)));
      await assertSucceeds(
        getDoc(
          doc(database, "tenants", DEMO_TENANT, "ontologyVersions", "v1"),
        ),
      );
      await assertSucceeds(
        getDoc(doc(database, "tenants", DEMO_TENANT, "concepts", "party")),
      );
      await assertSucceeds(
        getDoc(
          doc(
            database,
            "tenants",
            DEMO_TENANT,
            "relations",
            "owns-account",
          ),
        ),
      );
      await assertSucceeds(
        getDoc(doc(database, "tenants", DEMO_TENANT, "questions", "cq-001")),
      );
      const concepts = await assertSucceeds(
        getDocs(collection(database, "tenants", DEMO_TENANT, "concepts")),
      );
      expect(concepts.size).toBe(1);
    },
  );

  it("denies anonymous and cross-tenant reads", async () => {
    await seedFirestore();
    const anonymousDatabase = testEnvironment.unauthenticatedContext().firestore();
    const crossTenantDatabase = authenticatedContext(
      ["admin"],
      "other-bank",
    ).firestore();

    await assertFails(
      getDoc(
        doc(anonymousDatabase, "tenants", DEMO_TENANT, "concepts", "party"),
      ),
    );
    await assertFails(
      getDoc(
        doc(crossTenantDatabase, "tenants", DEMO_TENANT, "concepts", "party"),
      ),
    );
  });

  it.each([
    [[], DEMO_TENANT],
    [["viewer"], DEMO_TENANT],
    ["admin", DEMO_TENANT],
    [["admin"], 42],
  ])("denies malformed or unauthorized claims %#", async (roles, tenantId) => {
    await seedFirestore();
    const database = authenticatedContext(roles, tenantId).firestore();

    await assertFails(
      getDoc(doc(database, "tenants", DEMO_TENANT, "concepts", "party")),
    );
  });

  it.each(["auditEvents", "verificationRuns", "taskExecutions", "settings"])(
    "keeps internal %s documents unreadable to browser administrators",
    async (collectionName) => {
      await seedFirestore();
      const database = authenticatedContext(["admin"]).firestore();
      const documentIdByCollection: Record<string, string> = {
        auditEvents: "audit-001",
        settings: "private",
        taskExecutions: "task-001",
        verificationRuns: "verify-001",
      };

      await assertFails(
        getDoc(
          doc(
            database,
            "tenants",
            DEMO_TENANT,
            collectionName,
            documentIdByCollection[collectionName]!,
          ),
        ),
      );
    },
  );

  it("denies nested evidence reads even when the parent concept is readable", async () => {
    await seedFirestore();
    const database = authenticatedContext(["steward"]).firestore();

    await assertSucceeds(
      getDoc(doc(database, "tenants", DEMO_TENANT, "concepts", "party")),
    );
    await assertFails(
      getDoc(
        doc(
          database,
          "tenants",
          DEMO_TENANT,
          "concepts",
          "party",
          "evidence",
          "source-001",
        ),
      ),
    );
  });

  it("denies all browser writes, including semantic and internal state", async () => {
    await seedFirestore();
    const database = authenticatedContext(["admin"]).firestore();
    const concept = doc(
      database,
      "tenants",
      DEMO_TENANT,
      "concepts",
      "party",
    );

    await assertFails(setDoc(concept, { label: "Changed" }));
    await assertFails(updateDoc(concept, { label: "Changed" }));
    await assertFails(deleteDoc(concept));
    await assertFails(
      setDoc(
        doc(
          database,
          "tenants",
          DEMO_TENANT,
          "taskExecutions",
          "task-browser",
        ),
        { status: "queued" },
      ),
    );
    await assertFails(
      setDoc(
        doc(
          database,
          "tenants",
          DEMO_TENANT,
          "auditEvents",
          "audit-browser",
        ),
        { action: "forged" },
      ),
    );
  });
});

describe("Cloud Storage security rules", () => {
  it.each(["admin", "steward"])(
    "allows an authenticated %s to create a bound, supported upload",
    async (role) => {
      const storage = authenticatedContext([role]).storage();
      const upload = ref(
        storage,
        `tenants/${DEMO_TENANT}/uploads/crm-${role}/customers.csv`,
      );

      const result = await assertSucceeds(
        uploadBytes(upload, new TextEncoder().encode("customer_id\nC-001\n"), {
          ...uploadMetadata(),
          cacheControl: "no-store",
        }),
      );

      expect(result.metadata.customMetadata).toMatchObject({
        tenantId: DEMO_TENANT,
        uploadedBy: USER_ID,
      });
    },
  );

  it("denies anonymous, auditor, and cross-tenant uploads", async () => {
    const body = new TextEncoder().encode("customer_id\nC-001\n");
    const path = `tenants/${DEMO_TENANT}/uploads/crm/customers.csv`;
    const anonymousStorage = testEnvironment.unauthenticatedContext().storage();
    const auditorStorage = authenticatedContext(["auditor"]).storage();
    const crossTenantStorage = authenticatedContext(
      ["admin"],
      "other-bank",
    ).storage();

    await assertFails(
      uploadBytes(ref(anonymousStorage, path), body, uploadMetadata()),
    );
    await assertFails(
      uploadBytes(ref(auditorStorage, path), body, uploadMetadata()),
    );
    await assertFails(
      uploadBytes(ref(crossTenantStorage, path), body, uploadMetadata()),
    );
  });

  it.each([
    ["metadata tenant differs from the path", uploadMetadata("other-bank")],
    ["uploadedBy differs from the authenticated uid", uploadMetadata(DEMO_TENANT, "impostor")],
    [
      "required custom metadata is absent",
      { contentType: "text/csv" } satisfies UploadMetadata,
    ],
  ])("denies an upload when %s", async (_caseName, metadata) => {
    const storage = authenticatedContext(["steward"]).storage();
    const upload = ref(
      storage,
      `tenants/${DEMO_TENANT}/uploads/metadata/customers.csv`,
    );

    await assertFails(
      uploadBytes(upload, new TextEncoder().encode("id\n1\n"), metadata),
    );
  });

  it("denies unsupported and oversized uploads", async () => {
    const storage = authenticatedContext(["admin"]).storage();

    await assertFails(
      uploadBytes(
        ref(
          storage,
          `tenants/${DEMO_TENANT}/uploads/executable/payload.bin`,
        ),
        new Uint8Array([0, 1, 2, 3]),
        uploadMetadata(DEMO_TENANT, USER_ID, "application/octet-stream"),
      ),
    );
    await assertFails(
      uploadBytes(
        ref(storage, `tenants/${DEMO_TENANT}/uploads/large/export.csv`),
        new Uint8Array(20 * 1024 * 1024),
        uploadMetadata(),
      ),
    );
  });

  it("makes accepted uploads immutable and unreadable to browser clients", async () => {
    const storage = authenticatedContext(["admin"]).storage();
    const upload = ref(
      storage,
      `tenants/${DEMO_TENANT}/uploads/immutable/customers.csv`,
    );

    await assertSucceeds(
      uploadBytes(upload, new TextEncoder().encode("id\n1\n"), uploadMetadata()),
    );
    await assertFails(
      uploadBytes(upload, new TextEncoder().encode("id\n2\n"), uploadMetadata()),
    );
    await assertFails(getMetadata(upload));
    await assertFails(getBytes(upload));
    await assertFails(deleteObject(upload));
  });

  it.each([
    `tenants/${DEMO_TENANT}/sources/crm/customers.csv`,
    `tenants/${DEMO_TENANT}/artifacts/v1/manifest.json`,
    `tenants/${DEMO_TENANT}/exports/export-001/data.csv`,
  ])("denies browser writes to protected path %s", async (path) => {
    const storage = authenticatedContext(["admin"]).storage();

    await assertFails(
      uploadBytes(
        ref(storage, path),
        new TextEncoder().encode("protected"),
        uploadMetadata(),
      ),
    );
  });
});
