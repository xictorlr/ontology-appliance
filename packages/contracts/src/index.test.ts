import { describe, expect, it } from "vitest";
import connectorSchema from "../../../contracts/schemas/connector-manifest.schema.json";
import proposalSchemaDocument from "../../../contracts/schemas/proposal.schema.json";
import accountsConnector from "../../../data/contracts/core-accounts.connector.json";
import amlConnector from "../../../data/contracts/aml-cases.connector.json";
import crmConnector from "../../../data/contracts/crm-parties.connector.json";
import kycConnector from "../../../data/contracts/kyc-documents.connector.json";
import paymentsConnector from "../../../data/contracts/payments-ledger.connector.json";
import postgresConnector from "../../../data/contracts/postgres.connector.json";
import sanctionsConnector from "../../../data/contracts/sanctions-api.connector.json";
import proposalFixture from "../../../semantic/artifacts/proposals/mapping-crm-cif.json";
import {
  confidenceDimensionNames,
  connectorManifestSchema,
  connectorSourceTypes,
  proposalKinds,
  proposalSchema,
  proposalStatuses,
  responseMetaFieldNames,
  responseMetaSchema,
} from "./index";

describe("canonical connector manifest contract", () => {
  it("accepts every implemented synthetic connector fixture", () => {
    const fixtures = [
      accountsConnector,
      amlConnector,
      crmConnector,
      kycConnector,
      paymentsConnector,
      postgresConnector,
      sanctionsConnector,
    ];
    for (const connector of fixtures) {
      expect(connectorManifestSchema.safeParse(connector)).toMatchObject({ success: true });
    }
  });

  it("keeps source types synchronized with canonical JSON Schema", () => {
    const schema = connectorSchema as {
      properties: { source_type: { enum: string[] } };
    };
    expect([...connectorSourceTypes]).toEqual(schema.properties.source_type.enum);
  });

  it("rejects writable and unknown manifest fields", () => {
    const connector = crmConnector as Record<string, unknown>;
    expect(
      connectorManifestSchema.safeParse({ ...connector, access_mode: "read_write" }).success,
    ).toBe(false);
    expect(connectorManifestSchema.safeParse({ ...connector, password: "secret" }).success).toBe(false);
  });
});

describe("canonical semantic proposal contract", () => {
  const proposal: unknown = proposalFixture;

  it("accepts the committed immutable proposal without approving it", () => {
    const parsed = proposalSchema.parse(proposal);
    expect(parsed.status).toBe("PENDING_VERIFICATION");
    expect(parsed.generator.model_participated).toBe(false);
    expect(parsed.confidence.model).toBe(0);
  });

  it("keeps kinds, statuses, and confidence dimensions synchronized with JSON Schema", () => {
    const schema = proposalSchemaDocument as {
      properties: { kind: { enum: string[] }; status: { enum: string[] } };
      $defs: { confidence: { required: string[] } };
    };
    expect([...proposalKinds]).toEqual(schema.properties.kind.enum);
    expect([...proposalStatuses]).toEqual(schema.properties.status.enum);
    expect([...confidenceDimensionNames]).toEqual(schema.$defs.confidence.required);
  });

  it("rejects evidence-free proposals and unexplained scalar confidence", () => {
    const record = structuredClone(proposal) as Record<string, unknown>;
    record.evidence = [];
    expect(proposalSchema.safeParse(record).success).toBe(false);

    const scalar = structuredClone(proposal) as Record<string, unknown>;
    scalar.confidence = 0.96;
    expect(proposalSchema.safeParse(scalar).success).toBe(false);
  });
});

describe("canonical API response metadata", () => {
  const validMeta = {
    ontologyVersion: "2026.07.1-demo-bank",
    traceId: "integration-trace-123",
    tenantId: "demo-bank",
    publicationState: "CANDIDATE",
    servingMode: "DEMO_ONLY",
    isPublished: false,
    evidence: [],
    warnings: [],
    status: "OK",
    generatedAt: "2026-07-22T19:00:00Z",
  };

  it("keeps the declared metadata field list synchronized with Zod", () => {
    expect(Object.keys(responseMetaSchema.shape)).toEqual([...responseMetaFieldNames]);
    expect(responseMetaSchema.safeParse(validMeta).success).toBe(true);
  });

  it.each(["tenantId", "generatedAt"])("requires %s", (field) => {
    const incomplete = { ...validMeta } as Record<string, unknown>;
    delete incomplete[field];
    expect(responseMetaSchema.safeParse(incomplete).success).toBe(false);
  });
});
