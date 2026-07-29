import { logger } from "firebase-functions";
import { GoogleAuth } from "google-auth-library";

import type { IndependentVerdict, IndependentVerification } from "./workflows";

const REQUEST_TIMEOUT_MS = 10_000;
const LOCAL_HOSTNAMES = new Set(["127.0.0.1", "localhost"]);
const VERDICTS = new Set<IndependentVerdict>(["SUPPORTED", "REJECTED", "ABSTAINED"]);
const RISKS = new Set(["LOW", "MEDIUM", "HIGH"]);
const MAX_STATEMENT_LENGTH = 10_000;

/** Camel-case wire DTO for the gateway POST /v1/verify request body. */
export interface SemanticProposalRequest {
  proposalId: string;
  statement: string;
  evidenceIds: string[];
  counterevidenceIds: string[];
  risk: "LOW" | "MEDIUM" | "HIGH";
  modelDependent: boolean;
  generatorProvider: string;
  generatorModel: string;
  promptVersion: string;
}

/** Validated subset of the gateway verification outcome envelope. */
export interface VerificationOutcomePayload extends IndependentVerification {
  proposalId: string;
  status: string;
  requiresHumanReview: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function stringIds(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const ids = value
    .map((item) => (isRecord(item) ? item.evidence_id : null))
    .filter(nonEmptyString);
  return ids.length === value.length ? ids : null;
}

/**
 * Maps a frozen control-plane proposal onto the gateway verification DTO.
 * Returns null when the proposal cannot satisfy the wire contract, in which
 * case no verification request must be sent.
 */
export function verificationRequestFromProposal(
  proposalId: string,
  proposal: Record<string, unknown>,
): SemanticProposalRequest | null {
  if (
    !nonEmptyString(proposal.kind) ||
    !nonEmptyString(proposal.source_locator) ||
    !nonEmptyString(proposal.target_iri)
  ) {
    return null;
  }
  const risk = typeof proposal.risk === "string" ? proposal.risk.toUpperCase() : "";
  if (!RISKS.has(risk)) return null;
  const evidenceIds = stringIds(proposal.evidence);
  const counterevidenceIds = stringIds(proposal.counterevidence);
  // The gateway contract requires at least one supporting evidence identifier.
  if (evidenceIds === null || evidenceIds.length === 0 || counterevidenceIds === null) {
    return null;
  }
  const generator = isRecord(proposal.generator) ? proposal.generator : {};
  return {
    proposalId,
    statement:
      `${proposal.kind}: ${proposal.source_locator} -> ${proposal.target_iri}`.slice(
        0,
        MAX_STATEMENT_LENGTH,
      ),
    evidenceIds,
    counterevidenceIds,
    risk: risk as SemanticProposalRequest["risk"],
    modelDependent: generator.model_participated === true,
    generatorProvider: nonEmptyString(generator.provider)
      ? generator.provider
      : "ontology-appliance",
    generatorModel: nonEmptyString(generator.model) ? generator.model : "unknown",
    promptVersion: nonEmptyString(generator.prompt_version)
      ? generator.prompt_version
      : "not-applicable",
  };
}

function parseOutcome(body: unknown): VerificationOutcomePayload | null {
  if (!isRecord(body) || !isRecord(body.data)) return null;
  const data = body.data;
  const decision = data.decision;
  if (!isRecord(decision)) return null;
  const verdict = decision.verdict;
  if (typeof verdict !== "string" || !VERDICTS.has(verdict as IndependentVerdict)) {
    return null;
  }
  if (
    !nonEmptyString(data.proposalId) ||
    !nonEmptyString(data.status) ||
    !nonEmptyString(data.policyReason) ||
    !nonEmptyString(decision.provider) ||
    !nonEmptyString(decision.model) ||
    !nonEmptyString(decision.promptVersion)
  ) {
    return null;
  }
  if (
    typeof data.requiresHumanReview !== "boolean" ||
    typeof decision.independentModel !== "boolean" ||
    (data.modelAgreement !== null && typeof data.modelAgreement !== "boolean")
  ) {
    return null;
  }
  return {
    proposalId: data.proposalId,
    status: data.status,
    modelAgreement: data.modelAgreement,
    requiresHumanReview: data.requiresHumanReview,
    policyReason: data.policyReason,
    decision: {
      verdict: verdict as IndependentVerdict,
      provider: decision.provider,
      model: decision.model,
      promptVersion: decision.promptVersion,
      independentModel: decision.independentModel,
    },
  };
}

function allowedGatewayOrigin(baseUrl: string): URL | null {
  let url: URL;
  try {
    url = new URL(baseUrl);
  } catch {
    return null;
  }
  if (url.username || url.password) return null;
  if (url.protocol === "https:") return url;
  // Plain HTTP is acceptable only against the local emulator loopback.
  if (url.protocol === "http:" && LOCAL_HOSTNAMES.has(url.hostname)) return url;
  return null;
}

/**
 * Shared fail-safe transport for every private semantic gateway operation.
 *
 * An unset URL, an untrusted origin, or any transport or status failure
 * returns null instead of failing the calling task. It mirrors the cloud
 * smoke auth: one Google OIDC token minted for the gateway audience travels
 * in X-Serverless-Authorization for the Cloud Run IAM layer while the same
 * token in Authorization satisfies the gateway's hybrid trusted-service
 * principal.
 */
async function postToGateway(
  baseUrl: string,
  path: string,
  audience: string,
  tenantId: string,
  body: object,
  operation: string,
  context: Record<string, unknown>,
): Promise<unknown | null> {
  const trimmed = baseUrl.trim();
  if (trimmed === "") return null;
  const origin = allowedGatewayOrigin(trimmed);
  if (origin === null) {
    logger.warn(`Refusing an untrusted semantic gateway URL; skipping ${operation}`, context);
    return null;
  }
  try {
    const auth = new GoogleAuth();
    const client = await auth.getIdTokenClient(audience);
    const token = await client.idTokenProvider.fetchIdToken(audience);
    const response = await client.request<unknown>({
      url: `${trimmed.replace(/\/+$/u, "")}${path}`,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Serverless-Authorization": `Bearer ${token}`,
        "x-ontology-service-auth": "google-id-token",
        "x-ontology-tenant-id": tenantId,
      },
      data: body,
      timeout: REQUEST_TIMEOUT_MS,
      retry: false,
    });
    if (response.status !== 200) {
      logger.warn(`Semantic gateway ${operation} returned a non-OK status`, {
        ...context,
        status: response.status,
      });
      return null;
    }
    return response.data;
  } catch (error) {
    logger.warn(`Semantic gateway ${operation} failed; recording no result`, {
      ...context,
      error: error instanceof Error ? error.message.slice(0, 1_000) : "Unknown error",
    });
    return null;
  }
}

/**
 * Calls the private semantic gateway for an independent verification judgment.
 * Fail-safe by design: any transport, status, or contract failure records no
 * model result (null) so verification falls back to the
 * verifier-not-configured behavior instead of failing the task.
 */
export async function requestIndependentVerification(
  baseUrl: string,
  audience: string,
  tenantId: string,
  proposal: SemanticProposalRequest,
): Promise<VerificationOutcomePayload | null> {
  const body = await postToGateway(
    baseUrl,
    "/v1/verify",
    audience,
    tenantId,
    proposal,
    "verification",
    { proposalId: proposal.proposalId },
  );
  if (body === null) return null;
  const outcome = parseOutcome(body);
  if (outcome === null) {
    logger.warn("Semantic gateway verification response violated the contract", {
      proposalId: proposal.proposalId,
    });
    return null;
  }
  return outcome;
}

/** Validated subset of one governed concept returned by POST /v1/resolve. */
export interface ResolvedConceptPayload {
  iri: string;
  label: string;
  score: number;
  matchedOn: string;
  conceptType: string | null;
}

export interface ResolveOutcomePayload {
  concepts: ResolvedConceptPayload[];
}

function parseResolveOutcome(body: unknown): ResolveOutcomePayload | null {
  if (!isRecord(body) || !isRecord(body.data)) return null;
  const concepts = body.data.concepts;
  if (!Array.isArray(concepts)) return null;
  const parsed: ResolvedConceptPayload[] = [];
  for (const item of concepts) {
    if (!isRecord(item)) return null;
    const { iri, label, score, matchedOn, conceptType } = item;
    if (!nonEmptyString(iri) || !nonEmptyString(label) || !nonEmptyString(matchedOn)) {
      return null;
    }
    if (typeof score !== "number" || !Number.isFinite(score) || score < 0 || score > 1) {
      return null;
    }
    if (conceptType !== undefined && conceptType !== null && typeof conceptType !== "string") {
      return null;
    }
    parsed.push({
      iri,
      label,
      score,
      matchedOn,
      conceptType: typeof conceptType === "string" ? conceptType : null,
    });
  }
  return { concepts: parsed };
}

/**
 * Resolves one column name against the governed ontology through the private
 * gateway. Null-on-any-failure, exactly like independent verification: the
 * caller must skip the column rather than fail the ingestion workflow.
 */
export async function resolveTerm(
  baseUrl: string,
  audience: string,
  tenantId: string,
  term: string,
  limit: number,
): Promise<ResolveOutcomePayload | null> {
  const body = await postToGateway(
    baseUrl,
    "/v1/resolve",
    audience,
    tenantId,
    { term, limit },
    "resolution",
    { term },
  );
  if (body === null) return null;
  const outcome = parseResolveOutcome(body);
  if (outcome === null) {
    logger.warn("Semantic gateway resolution response violated the contract", { term });
    return null;
  }
  return outcome;
}
