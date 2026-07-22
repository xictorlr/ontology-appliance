"""Provider-neutral semantic proposal generation and verification policy.

The policy deliberately distinguishes a deterministic development mock from an
independent model verifier. A mock result can exercise workflow plumbing, but it
can never manufacture model agreement or auto-approve a proposal.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import Field

from .models import ApiModel


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class VerificationVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    ABSTAINED = "ABSTAINED"


class ProposalStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    AUTO_APPROVED = "AUTO_APPROVED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    REJECTED = "REJECTED"
    ABSTAINED = "ABSTAINED"


class GenerationRequest(ApiModel):
    objective: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    counterevidence_ids: list[str] = Field(default_factory=list, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)


class SemanticProposal(ApiModel):
    """Internal provider DTO, not the canonical immutable proposal record.

    The persisted record contract lives in ``contract_records.SemanticProposalRecord``.
    Keeping these boundaries explicit prevents a provider response from being
    mistaken for a verified or publishable proposal.
    """

    proposal_id: str = Field(min_length=1, max_length=256)
    statement: str = Field(min_length=1, max_length=10_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    counterevidence_ids: list[str] = Field(default_factory=list, max_length=100)
    risk: RiskLevel
    model_dependent: bool
    generator_provider: str = Field(min_length=1, max_length=100)
    generator_model: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)
    generator_rationale: str | None = Field(default=None, max_length=10_000)
    generator_response_id: str | None = Field(default=None, max_length=500)
    generator_latency_ms: int = Field(default=0, ge=0)
    generator_input_tokens: int | None = Field(default=None, ge=0)
    generator_output_tokens: int | None = Field(default=None, ge=0)
    generator_parameters: dict[str, Any] = Field(default_factory=dict)
    deterministic_input_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class VerificationDecision(ApiModel):
    verdict: VerificationVerdict
    rationale: str = Field(min_length=1, max_length=10_000)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    provider: str
    model: str
    prompt_version: str
    independent_model: bool
    response_id: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    refusal: bool = False
    refusal_reason: str | None = Field(default=None, max_length=10_000)


class VerificationOutcome(ApiModel):
    proposal_id: str
    status: ProposalStatus
    model_agreement: bool | None
    requires_human_review: bool
    policy_reason: str
    decision: VerificationDecision


@runtime_checkable
class Generator(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    def generate(self, request: GenerationRequest) -> SemanticProposal: ...


@runtime_checkable
class Verifier(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    def verify(self, proposal: SemanticProposal) -> VerificationDecision: ...


class ProviderDisabledError(RuntimeError):
    """Raised before network access when a provider is not explicitly enabled."""


class GenerationAbstainedError(RuntimeError):
    """The generator safely produced no proposal, for example after a content block."""


class ProviderProtocolError(RuntimeError):
    """The provider returned a response that does not satisfy the contract."""


class DeterministicMockGenerator:
    """Creates stable proposals for local workflow and policy tests."""

    provider = "deterministic-mock"
    enabled = True

    def __init__(self, *, risk: RiskLevel = RiskLevel.MEDIUM, model_dependent: bool = True) -> None:
        self.risk = risk
        self.model_dependent = model_dependent

    def generate(self, request: GenerationRequest) -> SemanticProposal:
        input_hash = _generation_input_hash(request)
        return SemanticProposal(
            proposal_id=f"mock-{input_hash[:24]}",
            statement=request.objective,
            evidence_ids=request.evidence_ids,
            counterevidence_ids=request.counterevidence_ids,
            risk=self.risk,
            model_dependent=self.model_dependent,
            generator_provider=self.provider,
            generator_model="fixture-generator-v1",
            prompt_version="fixture-v1",
            generator_rationale="Deterministic local fixture; no model participated.",
            generator_parameters={"mode": "deterministic"},
            deterministic_input_hash=input_hash,
        )


VERTEX_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "statement",
        "rationale",
        "evidence_ids",
        "counterevidence_ids",
        "risk",
    ],
    "properties": {
        "statement": {"type": "string"},
        "rationale": {"type": "string"},
        "evidence_ids": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "counterevidence_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risk": {"type": "string", "enum": [item.value for item in RiskLevel]},
    },
}


class _GeneratedProposal(ApiModel):
    statement: str = Field(min_length=1, max_length=10_000)
    rationale: str = Field(min_length=1, max_length=10_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    counterevidence_ids: list[str] = Field(default_factory=list, max_length=100)
    risk: RiskLevel


class VertexGeminiGenerator:
    """Vertex AI Gemini adapter using ADC and controlled JSON generation.

    Construction alone never enables a paid request. The adapter will call
    Vertex AI only when ``provider_mode`` is exactly ``vertex-ai``; the
    environment factory obtains that value from ``GENERATOR_PROVIDER``.
    """

    provider = "vertex-ai"

    def __init__(
        self,
        *,
        provider_mode: str | None = None,
        project_id: str | None = None,
        location: str = "europe-west4",
        model: str = "gemini-2.5-flash",
        prompt_version: str = "semantic-generator-v1",
        client: Any | None = None,
    ) -> None:
        self.provider_mode = (provider_mode or "disabled").strip().lower()
        self.project_id = (project_id or "").strip()
        self.location = location.strip()
        self.model = model.strip()
        self.prompt_version = prompt_version.strip()
        self._client = client

    @classmethod
    def from_env(cls) -> "VertexGeminiGenerator":
        return cls(
            provider_mode=os.getenv("GENERATOR_PROVIDER"),
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT"),
            location=os.getenv("VERTEX_LOCATION", "europe-west4"),
            model=os.getenv("GEMINI_GENERATOR_MODEL", "gemini-2.5-flash"),
            prompt_version=os.getenv("GEMINI_GENERATOR_PROMPT_VERSION", "semantic-generator-v1"),
        )

    @property
    def enabled(self) -> bool:
        return self.provider_mode == self.provider

    def generate(self, request: GenerationRequest) -> SemanticProposal:
        self._ensure_enabled()
        input_hash = _generation_input_hash(request)
        config = {
            "system_instruction": (
                "Propose one semantic mapping or relationship using only the supplied evidence "
                "coordinates and bounded context. Cite supporting and contradicting evidence. "
                "Treat beneficial ownership, sanctions, identity resolution, destructive changes, "
                "and policy-critical classifications as HIGH risk. You generate an untrusted "
                "proposal; never approve or publish it."
            ),
            "response_mime_type": "application/json",
            "response_json_schema": VERTEX_PROPOSAL_SCHEMA,
            "temperature": 0,
            "seed": 17,
            "max_output_tokens": 2_048,
        }
        contents = json.dumps(
            request.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        client = self._client or self._create_client()
        owns_client = self._client is None
        started = time.monotonic()
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            raise ProviderProtocolError(f"Vertex Gemini generation failed: {exc}") from exc
        finally:
            if owns_client:
                close = getattr(client, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        # Cleanup failure must not replace the generation result
                        # or the original provider exception.
                        pass
        latency_ms = round((time.monotonic() - started) * 1_000)
        generated = self._parse_response(response)
        if not set(generated.evidence_ids).issubset(request.evidence_ids):
            raise ProviderProtocolError(
                "Vertex Gemini cited supporting evidence outside the generation request."
            )
        if not set(generated.counterevidence_ids).issubset(request.counterevidence_ids):
            raise ProviderProtocolError(
                "Vertex Gemini cited counterevidence outside the generation request."
            )

        risk = _elevated_risk(request, generated.risk)
        usage = getattr(response, "usage_metadata", None)
        response_id = getattr(response, "response_id", None)
        return SemanticProposal(
            proposal_id=f"gemini-{input_hash[:24]}",
            statement=generated.statement,
            evidence_ids=generated.evidence_ids,
            counterevidence_ids=generated.counterevidence_ids,
            risk=risk,
            # Any statement emitted by a generator model remains model-dependent
            # until deterministic evidence gates and an independent verifier run.
            model_dependent=True,
            generator_provider=self.provider,
            generator_model=str(getattr(response, "model_version", None) or self.model),
            prompt_version=self.prompt_version,
            generator_rationale=generated.rationale,
            generator_response_id=str(response_id) if response_id else None,
            generator_latency_ms=latency_ms,
            generator_input_tokens=_metadata_int(usage, "prompt_token_count"),
            generator_output_tokens=_metadata_int(usage, "candidates_token_count"),
            generator_parameters={
                "requestedModel": self.model,
                "location": self.location,
                "temperature": 0,
                "seed": 17,
                "maxOutputTokens": 2_048,
            },
            deterministic_input_hash=input_hash,
        )

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise ProviderDisabledError(
                "Vertex Gemini is disabled unless GENERATOR_PROVIDER=vertex-ai."
            )
        if self.location != "europe-west4":
            raise ProviderDisabledError(
                "Vertex Gemini location must be europe-west4 for the pilot data-residency policy."
            )
        if not self.project_id:
            raise ProviderDisabledError(
                "GOOGLE_CLOUD_PROJECT is required before Vertex Gemini can use ADC."
            )
        if not self.model:
            raise ProviderDisabledError("GEMINI_GENERATOR_MODEL cannot be empty.")

    def _create_client(self) -> Any:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - production packaging guard
            raise ProviderDisabledError(
                "Vertex Gemini requires the optional 'vertex' dependencies."
            ) from exc
        return genai.Client(
            vertexai=True,
            project=self.project_id,
            location=self.location,
            http_options=types.HttpOptions(api_version="v1"),
        )

    @staticmethod
    def _parse_response(response: Any) -> _GeneratedProposal:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, _GeneratedProposal):
            return parsed
        if isinstance(parsed, dict):
            try:
                return _GeneratedProposal.model_validate(parsed)
            except Exception as exc:
                raise ProviderProtocolError(
                    f"Vertex Gemini parsed output was invalid: {exc}"
                ) from exc
        try:
            text = getattr(response, "text", None)
        except Exception as exc:
            raise GenerationAbstainedError(
                f"Vertex Gemini produced no usable candidate: {exc}"
            ) from exc
        if not isinstance(text, str) or not text.strip():
            feedback = getattr(response, "prompt_feedback", None)
            reason = (
                getattr(feedback, "block_reason_message", None)
                or getattr(feedback, "block_reason", None)
                or "blocked or incomplete response"
            )
            raise GenerationAbstainedError(
                f"Vertex Gemini returned no structured proposal: {reason}."
            )
        try:
            return _GeneratedProposal.model_validate_json(text)
        except Exception as exc:
            raise ProviderProtocolError(
                f"Vertex Gemini structured output was invalid: {exc}"
            ) from exc


class DeterministicMockVerifier:
    """Exercises the verifier boundary without pretending to be independent."""

    provider = "deterministic-mock"
    enabled = True

    def verify(self, proposal: SemanticProposal) -> VerificationDecision:
        return VerificationDecision(
            verdict=VerificationVerdict.ABSTAINED,
            rationale=(
                "Deterministic mock mode records no independent model judgment; "
                "evidence and human policy gates remain authoritative."
            ),
            confidence=0,
            evidence_ids=proposal.evidence_ids,
            provider=self.provider,
            model="fixture-verifier-v1",
            prompt_version="fixture-v1",
            independent_model=False,
        )


class VerificationPolicy:
    """Pure policy: model output is evidence, never the production publisher."""

    def __init__(self, *, auto_approve_threshold: float = 0.95) -> None:
        if not 0 <= auto_approve_threshold <= 1:
            raise ValueError("auto_approve_threshold must be between 0 and 1")
        self.auto_approve_threshold = auto_approve_threshold

    def evaluate(
        self,
        proposal: SemanticProposal,
        decision: VerificationDecision,
    ) -> VerificationOutcome:
        # Adapters calculate this when they receive the provider response, but
        # the policy repeats the check so a stale/custom adapter cannot turn a
        # generator/verifier collision into an approval signal. Independence
        # requires both a different provider and a different model family.
        if decision.independent_model and not _is_independent_model(
            proposal,
            verifier_provider=decision.provider,
            verifier_model=decision.model,
        ):
            decision = decision.model_copy(update={"independent_model": False})

        if decision.independent_model:
            if decision.verdict == VerificationVerdict.SUPPORTED:
                model_agreement: bool | None = True
            elif decision.verdict == VerificationVerdict.REJECTED:
                model_agreement = False
            else:
                model_agreement = None
        else:
            model_agreement = None

        if proposal.risk == RiskLevel.HIGH:
            status = ProposalStatus.HUMAN_REVIEW
            reason = "High-risk proposals always require a human decision."
        elif proposal.model_dependent and not decision.independent_model:
            status = ProposalStatus.HUMAN_REVIEW
            reason = "Model-dependent proposal has no independent verifier."
        elif decision.verdict == VerificationVerdict.REJECTED:
            status = ProposalStatus.REJECTED
            reason = "Independent verification rejected the proposal."
        elif decision.verdict == VerificationVerdict.ABSTAINED:
            status = ProposalStatus.ABSTAINED
            reason = "Verifier abstained; no approval signal exists."
        elif (
            decision.independent_model
            and decision.confidence >= self.auto_approve_threshold
            and bool(decision.evidence_ids)
            and set(decision.evidence_ids).issubset(proposal.evidence_ids)
        ):
            status = ProposalStatus.AUTO_APPROVED
            reason = "Independent support, evidence, and the approval threshold all passed."
        else:
            status = ProposalStatus.HUMAN_REVIEW
            reason = (
                "Support did not satisfy every automatic approval gate, including "
                "the requirement that cited evidence belong to the proposal."
            )

        return VerificationOutcome(
            proposal_id=proposal.proposal_id,
            status=status,
            model_agreement=model_agreement,
            requires_human_review=status == ProposalStatus.HUMAN_REVIEW,
            policy_reason=reason,
            decision=decision,
        )


OPENAI_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "rationale", "confidence", "evidence_ids"],
    "properties": {
        "verdict": {"type": "string", "enum": [item.value for item in VerificationVerdict]},
        "rationale": {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
}

# Anthropic's raw structured-output API accepts a deliberately smaller JSON
# Schema subset than Pydantic. Constraints that are not sent here are still
# enforced locally by ``_ProviderResult`` before a decision can leave the
# adapter.
ANTHROPIC_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "rationale", "confidence", "evidence_ids"],
    "properties": {
        "verdict": {"type": "string", "enum": [item.value for item in VerificationVerdict]},
        "rationale": {
            "type": "string",
            "description": "A non-empty verification rationale of at most 10000 characters.",
        },
        "confidence": {
            "type": "number",
            "description": "A calibrated value between 0 and 1 inclusive.",
        },
        "evidence_ids": {
            "type": "array",
            "description": "At most 100 identifiers copied from the supplied proposal.",
            "items": {"type": "string"},
        },
    },
}


class _ProviderResult(ApiModel):
    verdict: VerificationVerdict
    rationale: str = Field(min_length=1, max_length=10_000)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    refusal_reason: str | None = Field(default=None, max_length=10_000)


class OpenAIResponsesVerifier:
    """OpenAI Responses adapter; disabled by construction when no key is set."""

    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "gpt-5.6-terra",
        prompt_version: str = "semantic-verifier-v1",
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.prompt_version = prompt_version
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    @classmethod
    def from_env(cls) -> "OpenAIResponsesVerifier":
        return cls(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=os.getenv("OA_OPENAI_VERIFIER_MODEL", "gpt-5.6-terra"),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def verify(self, proposal: SemanticProposal) -> VerificationDecision:
        if not self.enabled:
            raise ProviderDisabledError(
                "OpenAI verifier is disabled until OPENAI_API_KEY is supplied and eval gates pass."
            )

        payload = self._request_payload(proposal)
        started = time.monotonic()
        try:
            if self._client is None:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/responses",
                        headers=self._headers(),
                        json=payload,
                    )
            else:
                response = self._client.post(
                    f"{self.base_url}/responses",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderProtocolError(f"OpenAI Responses request failed: {exc}") from exc
        if not isinstance(body, dict):
            raise ProviderProtocolError("OpenAI Responses returned a non-object JSON document.")
        latency_ms = round((time.monotonic() - started) * 1_000)

        provider_result = self._parse_result(body)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        returned_model = _required_nonempty_string(
            body.get("model"),
            "OpenAI response model",
        )
        return VerificationDecision(
            verdict=provider_result.verdict,
            rationale=provider_result.rationale,
            confidence=provider_result.confidence,
            evidence_ids=provider_result.evidence_ids,
            provider=self.provider,
            model=returned_model,
            prompt_version=self.prompt_version,
            independent_model=_is_independent_model(
                proposal,
                verifier_provider=self.provider,
                verifier_model=returned_model,
            ),
            response_id=str(body.get("id")) if body.get("id") else None,
            latency_ms=latency_ms,
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            refusal=provider_result.refusal_reason is not None,
            refusal_reason=provider_result.refusal_reason,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request_payload(self, proposal: SemanticProposal) -> dict[str, Any]:
        return {
            "model": self.model,
            "store": False,
            "reasoning": {"effort": "low"},
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Independently verify the semantic proposal against only the supplied "
                                "evidence identifiers. Abstain when evidence is insufficient. Return "
                                "exactly the requested structured result; do not approve publication."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                proposal.model_dump(mode="json", by_alias=True), sort_keys=True
                            ),
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "semantic_verification",
                    "strict": True,
                    "schema": OPENAI_RESULT_SCHEMA,
                }
            },
        }

    @staticmethod
    def _parse_result(body: dict[str, Any]) -> _ProviderResult:
        if body.get("status") == "incomplete":
            raise ProviderProtocolError("OpenAI response was incomplete.")
        output_text = body.get("output_text")
        if not isinstance(output_text, str):
            for item in body.get("output", []):
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if isinstance(content, dict) and content.get("type") == "refusal":
                        refusal_reason = str(
                            content.get("refusal") or "Provider refused verification."
                        )
                        return _ProviderResult(
                            verdict=VerificationVerdict.ABSTAINED,
                            rationale=refusal_reason,
                            confidence=0,
                            evidence_ids=[],
                            refusalReason=refusal_reason,
                        )
                    if isinstance(content, dict) and content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
                if isinstance(output_text, str):
                    break
        if not isinstance(output_text, str):
            raise ProviderProtocolError("OpenAI response contained no structured output text.")
        try:
            return _ProviderResult.model_validate_json(output_text)
        except Exception as exc:
            raise ProviderProtocolError(f"OpenAI structured output was invalid: {exc}") from exc


class AnthropicMessagesVerifier:
    """Anthropic Messages adapter with explicit paid-call opt-in.

    The adapter uses raw HTTP so the request contract remains visible and
    independently testable. Construction never performs I/O, and a missing
    ``ANTHROPIC_API_KEY`` fails before a client can be called.
    """

    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "claude-sonnet-5",
        prompt_version: str = "semantic-verifier-v1",
        base_url: str = "https://api.anthropic.com/v1",
        timeout_seconds: float = 30,
        max_tokens: int = 2_048,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.prompt_version = prompt_version.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self._client = client

    @classmethod
    def from_env(cls) -> "AnthropicMessagesVerifier":
        return cls(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("OA_ANTHROPIC_VERIFIER_MODEL", "claude-sonnet-5"),
            prompt_version=os.getenv(
                "OA_ANTHROPIC_VERIFIER_PROMPT_VERSION",
                "semantic-verifier-v1",
            ),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def verify(self, proposal: SemanticProposal) -> VerificationDecision:
        self._ensure_enabled()
        payload = self._request_payload(proposal)
        started = time.monotonic()
        try:
            if self._client is None:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/messages",
                        headers=self._headers(),
                        json=payload,
                    )
            else:
                response = self._client.post(
                    f"{self.base_url}/messages",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderProtocolError(f"Anthropic Messages request failed: {exc}") from exc
        if not isinstance(body, dict):
            raise ProviderProtocolError("Anthropic Messages returned a non-object JSON document.")
        latency_ms = round((time.monotonic() - started) * 1_000)

        # These fields are part of the evidence trace, including for a refusal.
        # Never substitute the requested model or silently turn malformed token
        # usage into ``None``: without returned metadata this response is not a
        # reproducible verification record.
        returned_model = _required_nonempty_string(
            body.get("model"),
            "Anthropic response model",
        )
        response_id = _required_nonempty_string(
            body.get("id"),
            "Anthropic response id",
        )
        usage = body.get("usage")
        if not isinstance(usage, dict):
            raise ProviderProtocolError("Anthropic response usage must be an object.")
        input_tokens = _required_nonnegative_int(
            usage.get("input_tokens"),
            "Anthropic usage input_tokens",
        )
        output_tokens = _required_nonnegative_int(
            usage.get("output_tokens"),
            "Anthropic usage output_tokens",
        )

        provider_result = self._parse_result(body)
        if not set(provider_result.evidence_ids).issubset(proposal.evidence_ids):
            raise ProviderProtocolError(
                "Anthropic Messages cited evidence outside the supplied proposal."
            )
        return VerificationDecision(
            verdict=provider_result.verdict,
            rationale=provider_result.rationale,
            confidence=provider_result.confidence,
            evidence_ids=provider_result.evidence_ids,
            provider=self.provider,
            model=returned_model,
            prompt_version=self.prompt_version,
            independent_model=_is_independent_model(
                proposal,
                verifier_provider=self.provider,
                verifier_model=returned_model,
            ),
            response_id=response_id,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            refusal=provider_result.refusal_reason is not None,
            refusal_reason=provider_result.refusal_reason,
        )

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise ProviderDisabledError(
                "Anthropic verifier is disabled until ANTHROPIC_API_KEY is supplied "
                "and eval gates pass."
            )
        if not self.model:
            raise ProviderDisabledError("OA_ANTHROPIC_VERIFIER_MODEL cannot be empty.")
        if not self.prompt_version:
            raise ProviderDisabledError("OA_ANTHROPIC_VERIFIER_PROMPT_VERSION cannot be empty.")
        if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool):
            raise ProviderDisabledError("Anthropic max_tokens must be an integer.")
        if not 1 <= self.max_tokens <= 128_000:
            raise ProviderDisabledError("Anthropic max_tokens must be between 1 and 128000.")

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _request_payload(self, proposal: SemanticProposal) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "thinking": {"type": "disabled"},
            "system": (
                "Independently verify the semantic proposal against only the supplied "
                "evidence identifiers. Abstain when evidence is insufficient. Return "
                "exactly the requested structured result; do not approve publication."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        proposal.model_dump(mode="json", by_alias=True),
                        sort_keys=True,
                    ),
                }
            ],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": ANTHROPIC_RESULT_SCHEMA,
                }
            },
        }

    @staticmethod
    def _parse_result(body: dict[str, Any]) -> _ProviderResult:
        stop_reason = body.get("stop_reason")
        if stop_reason == "refusal":
            stop_details = body.get("stop_details")
            explanation = (
                stop_details.get("explanation")
                if isinstance(stop_details, dict)
                and isinstance(stop_details.get("explanation"), str)
                else None
            )
            refusal_reason = explanation or "Provider refused verification."
            return _ProviderResult(
                verdict=VerificationVerdict.ABSTAINED,
                rationale=refusal_reason,
                confidence=0,
                evidence_ids=[],
                refusalReason=refusal_reason,
            )
        if stop_reason == "max_tokens":
            raise ProviderProtocolError("Anthropic structured output was truncated at max_tokens.")
        if stop_reason != "end_turn":
            raise ProviderProtocolError(
                f"Anthropic Messages ended with unsupported stop_reason {stop_reason!r}."
            )

        content = body.get("content")
        if not isinstance(content, list):
            raise ProviderProtocolError("Anthropic response contained no content blocks.")
        text_blocks = [
            item.get("text")
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        if len(text_blocks) != 1 or not text_blocks[0].strip():
            raise ProviderProtocolError(
                "Anthropic response contained no single structured output text block."
            )
        try:
            parsed = json.loads(text_blocks[0])
            if isinstance(parsed, dict) and isinstance(parsed.get("verdict"), str):
                parsed["verdict"] = parsed["verdict"].upper()
            return _ProviderResult.model_validate(parsed)
        except Exception as exc:
            raise ProviderProtocolError(f"Anthropic structured output was invalid: {exc}") from exc


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _required_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderProtocolError(f"{label} must be a non-empty string.")
    return value.strip()


def _required_nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderProtocolError(f"{label} must be a non-negative integer.")
    return value


_IDENTIFIER_SEPARATOR = re.compile(r"[^a-z0-9]+")
_MODEL_PROVIDER_PREFIX = re.compile(
    r"^(?:google-vertex-ai|vertex-ai|anthropic|openai|google|models?)-+"
)
_MODEL_SNAPSHOT_SUFFIXES = (
    re.compile(r"-(?:vertex|preview|snapshot)-20\d{6}$"),
    re.compile(r"-20\d{2}-\d{2}-\d{2}$"),
    re.compile(r"-20\d{6}$"),
    re.compile(r"-(?:latest|stable)$"),
)
_PROVIDER_ALIASES = {
    "anthropic": "anthropic",
    "anthropic-ai": "anthropic",
    "claude": "anthropic",
    "open-ai": "openai",
    "openai": "openai",
    "gemini": "google-vertex-ai",
    "google": "google-vertex-ai",
    "google-cloud-vertex-ai": "google-vertex-ai",
    "google-genai": "google-vertex-ai",
    "google-generative-ai": "google-vertex-ai",
    "google-vertex": "google-vertex-ai",
    "google-vertex-ai": "google-vertex-ai",
    "vertex": "google-vertex-ai",
    "vertex-ai": "google-vertex-ai",
}


def _normalized_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return _IDENTIFIER_SEPARATOR.sub("-", normalized).strip("-")


def _normalized_provider(value: str) -> str:
    normalized = _normalized_identifier(value)
    return _PROVIDER_ALIASES.get(normalized, normalized)


def _normalized_model(value: str) -> str:
    # Provider APIs may return resource paths, mixed separators, aliases such
    # as ``latest``, or dated snapshots of the same model family. Normalizing
    # those spellings prevents an alias from manufacturing independence.
    leaf = value.strip().rstrip("/").rsplit("/", 1)[-1]
    normalized = _normalized_identifier(leaf)
    normalized = _MODEL_PROVIDER_PREFIX.sub("", normalized)
    previous = None
    while normalized and normalized != previous:
        previous = normalized
        for suffix in _MODEL_SNAPSHOT_SUFFIXES:
            normalized = suffix.sub("", normalized)
    return normalized


def _is_independent_model(
    proposal: SemanticProposal,
    *,
    verifier_provider: str,
    verifier_model: str,
) -> bool:
    generator_provider = _normalized_provider(proposal.generator_provider)
    returned_provider = _normalized_provider(verifier_provider)
    generator_model = _normalized_model(proposal.generator_model)
    returned_model = _normalized_model(verifier_model)
    if not all((generator_provider, returned_provider, generator_model, returned_model)):
        return False
    return generator_provider != returned_provider and generator_model != returned_model


def _metadata_int(metadata: Any, field: str) -> int | None:
    if isinstance(metadata, dict):
        return _optional_int(metadata.get(field))
    return _optional_int(getattr(metadata, field, None))


def _generation_input_hash(request: GenerationRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _elevated_risk(request: GenerationRequest, proposed: RiskLevel) -> RiskLevel:
    serialized = json.dumps(
        request.model_dump(mode="json", by_alias=True),
        sort_keys=True,
    ).casefold()
    policy_critical_terms = (
        "beneficial owner",
        "beneficial ownership",
        "ubo",
        "sanction",
        "identity resolution",
        "delete",
        "deletion",
        "destructive",
        "policy-critical",
    )
    if any(term in serialized for term in policy_critical_terms):
        return RiskLevel.HIGH
    return proposed


def generator_from_env() -> Generator:
    """Select Gemini only through the explicit paid-provider feature flag."""

    mode = os.getenv("GENERATOR_PROVIDER", "mock").strip().lower()
    if mode == "mock":
        return DeterministicMockGenerator()
    if mode == "vertex-ai":
        return VertexGeminiGenerator.from_env()
    raise ValueError("GENERATOR_PROVIDER must be 'mock' or 'vertex-ai'")


def verifier_from_env() -> Verifier:
    """Select the explicit verifier mode without silently enabling paid calls."""

    provider_mode = os.getenv("VERIFIER_PROVIDER")
    legacy_mode = os.getenv("OPENAI_VERIFIER_MODE")
    if provider_mode is None:
        mode = (legacy_mode or "mock").strip().lower()
        if mode not in {"mock", "openai"}:
            raise ValueError(
                "Legacy OPENAI_VERIFIER_MODE must be 'mock' or 'openai'; use "
                "VERIFIER_PROVIDER=anthropic for the Anthropic adapter"
            )
    else:
        mode = provider_mode.strip().lower()
        normalized_legacy = (legacy_mode or "").strip().lower()
        if normalized_legacy not in {"", "mock", mode}:
            raise ValueError(
                "VERIFIER_PROVIDER conflicts with legacy OPENAI_VERIFIER_MODE; "
                "remove the legacy setting before selecting a different paid provider"
            )
    if mode == "mock":
        return DeterministicMockVerifier()
    if mode == "openai":
        return OpenAIResponsesVerifier.from_env()
    if mode == "anthropic":
        return AnthropicMessagesVerifier.from_env()
    raise ValueError(
        "VERIFIER_PROVIDER must be 'mock', 'openai', or 'anthropic'; legacy "
        "OPENAI_VERIFIER_MODE supports only 'mock' or 'openai'"
    )
