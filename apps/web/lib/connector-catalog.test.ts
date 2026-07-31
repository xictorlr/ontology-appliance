import { describe, expect, it } from "vitest";
import { connectorCatalog, isActiveFileConnector } from "./connector-catalog";
import { sourceTypes } from "./source-contract";

describe("enterprise connector catalog", () => {
  it("activates exactly the implemented adapters", () => {
    expect(connectorCatalog.filter(isActiveFileConnector).map((connector) => connector.id)).toEqual(
      sourceTypes,
    );
  });

  it("lists requested database, object-storage, and lakehouse options", () => {
    const identifiers = connectorCatalog.map((connector) => connector.id);
    expect(identifiers).toEqual(expect.arrayContaining([
      "postgresql",
      "mysql",
      "sql-server",
      "oracle",
      "amazon-s3",
      "azure-blob",
      "google-cloud-storage",
      "databricks",
      "bigquery",
      "snowflake",
    ]));
  });

  it("activates PostgreSQL as metadata-first snapshot intake, never a browser upload", () => {
    const postgresql = connectorCatalog.find((connector) => connector.id === "postgresql");
    expect(postgresql?.availability).toBe("active");
    expect(postgresql?.credentialBoundary).toBe("secret-manager");
    expect(postgresql?.accept).toBe("");
    expect(postgresql && isActiveFileConnector(postgresql)).toBe(false);
    expect(postgresql?.activationRequirements).toEqual(expect.arrayContaining([
      "read-only-adapter",
      "secret-reference",
      "metadata-only-snapshot",
      "sha256-evidence",
      "fail-closed-normalizer-test",
    ]));
  });

  it("never asks the browser for a secret on a planned connector", () => {
    const planned = connectorCatalog.filter((connector) => connector.availability === "planned");
    expect(planned.length).toBeGreaterThan(0);
    expect(planned.every((connector) => connector.credentialBoundary !== "none")).toBe(true);
    expect(planned.every((connector) => connector.activationRequirements.includes("integration-test"))).toBe(true);
  });

  it("uses unique stable connector IDs", () => {
    expect(new Set(connectorCatalog.map((connector) => connector.id)).size).toBe(
      connectorCatalog.length,
    );
  });
});
