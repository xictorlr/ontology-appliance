import { describe, expect, it } from "vitest";
import { industryPacks } from "./industry-catalog";

describe("industry semantic pack catalog", () => {
  it("keeps the implemented KYC/AML vertical as the only active pack", () => {
    expect(industryPacks.filter((pack) => pack.availability === "active").map((pack) => pack.id)).toEqual([
      "financial-crime-kyc-aml",
    ]);
  });

  it("includes Oil & Gas and a broad cross-industry roadmap", () => {
    expect(industryPacks.map((pack) => pack.id)).toEqual(expect.arrayContaining([
      "oil-gas",
      "energy-utilities",
      "insurance",
      "manufacturing",
      "healthcare-life-sciences",
      "retail-cpg",
      "telecommunications",
      "public-sector",
    ]));
  });

  it("requires deterministic and human governance gates for every pack", () => {
    expect(industryPacks.every((pack) =>
      pack.activationRequirements.includes("shacl-shapes") &&
      pack.activationRequirements.includes("competency-questions") &&
      pack.activationRequirements.includes("independent-verification"),
    )).toBe(true);
  });
});
