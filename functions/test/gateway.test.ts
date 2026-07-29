import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock, fetchIdTokenMock, getIdTokenClientMock } = vi.hoisted(() => {
  const requestMock = vi.fn<(options: unknown) => Promise<unknown>>();
  const fetchIdTokenMock = vi.fn(async () => "signed-oidc-token");
  const getIdTokenClientMock = vi.fn(async () => ({
    idTokenProvider: { fetchIdToken: fetchIdTokenMock },
    request: requestMock,
  }));
  return { requestMock, fetchIdTokenMock, getIdTokenClientMock };
});

vi.mock("google-auth-library", () => ({
  GoogleAuth: class {
    getIdTokenClient = getIdTokenClientMock;
  },
}));

import { logger } from "firebase-functions";

import {
  requestIndependentVerification,
  type SemanticProposalRequest,
  verificationRequestFromProposal,
} from "../src/lib/gateway";
import { buildIngestionProposal } from "../src/lib/workflows";
import type { SourceProfile } from "../src/lib/profiling";

const GATEWAY_URL =
  "https://europe-west4-demo-project.cloudfunctions.net/semanticGatewayHttp";

const proposalRequest: SemanticProposalRequest = {
  proposalId: "ingestion-abc",
  statement: "assertion: gs://demo/parties.csv#generation=1 -> urn:x",
  evidenceIds: ["evidence-1"],
  counterevidenceIds: [],
  risk: "LOW",
  modelDependent: false,
  generatorProvider: "ontology-appliance",
  generatorModel: "firebase-metadata-profiler-v1",
  promptVersion: "not-applicable",
};

function envelope(): { data: Record<string, unknown> } {
  return {
    data: {
      proposalId: proposalRequest.proposalId,
      status: "ABSTAINED",
      modelAgreement: null,
      requiresHumanReview: false,
      policyReason: "Verifier abstained; no approval signal exists.",
      decision: {
        verdict: "ABSTAINED",
        rationale: "Deterministic mock mode records no independent model judgment.",
        confidence: 0,
        evidenceIds: ["evidence-1"],
        provider: "deterministic-mock",
        model: "fixture-verifier-v1",
        promptVersion: "fixture-v1",
        independentModel: false,
      },
    },
  };
}

describe("requestIndependentVerification", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(logger, "warn").mockImplementation(() => undefined);
  });

  it("treats an empty or whitespace URL as verification disabled", async () => {
    await expect(
      requestIndependentVerification("", GATEWAY_URL, "demo-bank", proposalRequest),
    ).resolves.toBeNull();
    await expect(
      requestIndependentVerification("   ", GATEWAY_URL, "demo-bank", proposalRequest),
    ).resolves.toBeNull();
    expect(getIdTokenClientMock).not.toHaveBeenCalled();
    expect(logger.warn).not.toHaveBeenCalled();
  });

  it("refuses plain HTTP against a non-local host without minting a token", async () => {
    await expect(
      requestIndependentVerification(
        "http://gateway.example.com",
        GATEWAY_URL,
        "demo-bank",
        proposalRequest,
      ),
    ).resolves.toBeNull();
    expect(getIdTokenClientMock).not.toHaveBeenCalled();
    expect(logger.warn).toHaveBeenCalledOnce();
  });

  it("allows the local emulator loopback over plain HTTP", async () => {
    requestMock.mockResolvedValueOnce({ status: 200, data: envelope() });
    const outcome = await requestIndependentVerification(
      "http://127.0.0.1:5001",
      "http://127.0.0.1:5001",
      "demo-bank",
      proposalRequest,
    );
    expect(outcome?.decision.provider).toBe("deterministic-mock");
    expect(requestMock).toHaveBeenCalledOnce();
  });

  it("posts the proposal with the smoke-test auth headers and parses the outcome", async () => {
    requestMock.mockResolvedValueOnce({ status: 200, data: envelope() });
    const outcome = await requestIndependentVerification(
      `${GATEWAY_URL}/`,
      GATEWAY_URL,
      "demo-bank",
      proposalRequest,
    );
    expect(outcome).toEqual({
      proposalId: proposalRequest.proposalId,
      status: "ABSTAINED",
      modelAgreement: null,
      requiresHumanReview: false,
      policyReason: "Verifier abstained; no approval signal exists.",
      decision: {
        verdict: "ABSTAINED",
        provider: "deterministic-mock",
        model: "fixture-verifier-v1",
        promptVersion: "fixture-v1",
        independentModel: false,
      },
    });
    expect(getIdTokenClientMock).toHaveBeenCalledWith(GATEWAY_URL);
    expect(fetchIdTokenMock).toHaveBeenCalledWith(GATEWAY_URL);
    expect(requestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        url: `${GATEWAY_URL}/v1/verify`,
        method: "POST",
        data: proposalRequest,
        headers: expect.objectContaining({
          "X-Serverless-Authorization": "Bearer signed-oidc-token",
          "x-ontology-service-auth": "google-id-token",
          "x-ontology-tenant-id": "demo-bank",
        }),
      }),
    );
  });

  it("records no result when the gateway returns a non-OK status", async () => {
    requestMock.mockResolvedValueOnce({ status: 503, data: {} });
    await expect(
      requestIndependentVerification(GATEWAY_URL, GATEWAY_URL, "demo-bank", proposalRequest),
    ).resolves.toBeNull();
    expect(logger.warn).toHaveBeenCalledOnce();
  });

  it("records no result when the response body violates the contract", async () => {
    const invalid = envelope();
    (invalid.data.decision as Record<string, unknown>).verdict = "APPROVED";
    requestMock.mockResolvedValueOnce({ status: 200, data: invalid });
    await expect(
      requestIndependentVerification(GATEWAY_URL, GATEWAY_URL, "demo-bank", proposalRequest),
    ).resolves.toBeNull();

    requestMock.mockResolvedValueOnce({ status: 200, data: { data: { decision: {} } } });
    await expect(
      requestIndependentVerification(GATEWAY_URL, GATEWAY_URL, "demo-bank", proposalRequest),
    ).resolves.toBeNull();
    expect(logger.warn).toHaveBeenCalledTimes(2);
  });

  it("records no result when the transport fails", async () => {
    requestMock.mockRejectedValueOnce(new Error("connect ETIMEDOUT"));
    await expect(
      requestIndependentVerification(GATEWAY_URL, GATEWAY_URL, "demo-bank", proposalRequest),
    ).resolves.toBeNull();
    expect(logger.warn).toHaveBeenCalledOnce();
  });
});

describe("verificationRequestFromProposal", () => {
  const profile: SourceProfile = {
    sha256: "a".repeat(64),
    byteSize: 42,
    recordCount: 2,
    mediaType: "text/csv",
    extractorVersion: "firebase-evidence-profiler/1.0.0",
  };

  function proposal() {
    return buildIngestionProposal({
      tenantId: "demo-bank",
      sourceId: "crm",
      bucket: "demo-input",
      objectName: "tenants/demo-bank/uploads/crm/parties.csv",
      generation: "1721640000000000",
      contentType: "text/csv",
      sizeBytes: 42,
      observedAt: "2026-07-22T13:51:12.123Z",
      activeOntologyVersion: "2026.07.1-candidate",
      profile,
    });
  }

  it("maps the frozen proposal onto the camel-case wire contract", () => {
    const frozen = proposal();
    const mapped = verificationRequestFromProposal(frozen.proposal_id, frozen);
    expect(mapped).toEqual({
      proposalId: frozen.proposal_id,
      statement: `assertion: ${frozen.source_locator} -> ${frozen.target_iri}`,
      evidenceIds: [frozen.evidence[0]?.evidence_id],
      counterevidenceIds: [],
      risk: "LOW",
      modelDependent: false,
      generatorProvider: "ontology-appliance",
      generatorModel: "firebase-metadata-profiler-v1",
      promptVersion: "not-applicable",
    });
  });

  it("refuses to build a request without supporting evidence identifiers", () => {
    const frozen = proposal();
    expect(
      verificationRequestFromProposal(frozen.proposal_id, { ...frozen, evidence: [] }),
    ).toBeNull();
  });

  it("refuses to build a request for an unknown risk level", () => {
    const frozen = proposal();
    expect(
      verificationRequestFromProposal(frozen.proposal_id, { ...frozen, risk: "extreme" }),
    ).toBeNull();
  });
});
