from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from ontology_appliance_gateway.verification import (
    AnthropicMessagesVerifier,
    DeterministicMockGenerator,
    DeterministicMockVerifier,
    GenerationAbstainedError,
    GenerationRequest,
    Generator,
    OpenAIResponsesVerifier,
    ProposalStatus,
    ProviderDisabledError,
    ProviderProtocolError,
    RiskLevel,
    SemanticProposal,
    VerificationDecision,
    VerificationPolicy,
    VerificationVerdict,
    Verifier,
    VertexGeminiGenerator,
    generator_from_env,
    verifier_from_env,
)


def proposal(*, risk: RiskLevel = RiskLevel.MEDIUM, model_dependent: bool = True):
    return SemanticProposal(
        proposalId="proposal-1",
        statement="crm.cif_no maps to Customer Identifier",
        evidenceIds=["schema:cif_no", "profile:cif_no"],
        risk=risk,
        modelDependent=model_dependent,
        generatorProvider="vertex-ai",
        generatorModel="gemini-flash",
        promptVersion="generator-v1",
    )


def test_provider_neutral_protocols_and_deterministic_generator() -> None:
    generator = DeterministicMockGenerator()
    verifier = DeterministicMockVerifier()
    assert isinstance(generator, Generator)
    assert isinstance(verifier, Verifier)
    generated = generator.generate(
        GenerationRequest(objective="Map cif_no", evidenceIds=["schema:cif_no"])
    )
    assert generated.generator_provider == "deterministic-mock"
    assert (
        generated.proposal_id
        == generator.generate(
            GenerationRequest(objective="Map cif_no", evidenceIds=["schema:cif_no"])
        ).proposal_id
    )


@pytest.mark.parametrize(
    ("risk", "model_dependent", "expected"),
    [
        (RiskLevel.HIGH, False, ProposalStatus.HUMAN_REVIEW),
        (RiskLevel.MEDIUM, True, ProposalStatus.HUMAN_REVIEW),
        (RiskLevel.LOW, False, ProposalStatus.ABSTAINED),
    ],
)
def test_mock_never_creates_independent_agreement(
    risk: RiskLevel, model_dependent: bool, expected: ProposalStatus
) -> None:
    item = proposal(risk=risk, model_dependent=model_dependent)
    decision = DeterministicMockVerifier().verify(item)
    outcome = VerificationPolicy().evaluate(item, decision)
    assert outcome.status == expected
    assert outcome.model_agreement is None
    assert decision.independent_model is False


def test_independent_support_can_auto_approve_only_low_risk() -> None:
    decision = VerificationDecision(
        verdict=VerificationVerdict.SUPPORTED,
        rationale="Evidence supports the mapping.",
        confidence=0.98,
        evidenceIds=["schema:cif_no"],
        provider="openai",
        model="gpt-5.6-terra",
        promptVersion="verifier-v1",
        independentModel=True,
    )
    low = VerificationPolicy().evaluate(
        proposal(risk=RiskLevel.LOW, model_dependent=True), decision
    )
    high = VerificationPolicy().evaluate(
        proposal(risk=RiskLevel.HIGH, model_dependent=True), decision
    )
    assert low.status == ProposalStatus.AUTO_APPROVED
    assert low.model_agreement is True
    assert high.status == ProposalStatus.HUMAN_REVIEW
    assert high.requires_human_review is True


def test_unknown_evidence_cannot_auto_approve() -> None:
    decision = VerificationDecision(
        verdict=VerificationVerdict.SUPPORTED,
        rationale="Claims support from evidence outside the proposal.",
        confidence=0.99,
        evidenceIds=["invented:evidence"],
        provider="openai",
        model="gpt-5.6-terra",
        promptVersion="verifier-v1",
        independentModel=True,
    )
    outcome = VerificationPolicy().evaluate(
        proposal(risk=RiskLevel.LOW, model_dependent=True), decision
    )
    assert outcome.status == ProposalStatus.HUMAN_REVIEW


def test_openai_adapter_is_disabled_before_any_network_call() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = OpenAIResponsesVerifier(api_key=None, client=client)
    assert verifier.enabled is False
    with pytest.raises(ProviderDisabledError, match="OPENAI_API_KEY"):
        verifier.verify(proposal())
    assert called is False
    client.close()


def test_openai_responses_contract_is_stateless_and_structured() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "id": "resp_test_1",
                "status": "completed",
                "model": "gpt-5.6-terra",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "verdict": "SUPPORTED",
                                        "rationale": "Both evidence references support the mapping.",
                                        "confidence": 0.97,
                                        "evidence_ids": ["schema:cif_no", "profile:cif_no"],
                                    }
                                ),
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 101, "output_tokens": 37},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = OpenAIResponsesVerifier(api_key="test-key", client=client)
    decision = verifier.verify(proposal())
    client.close()

    assert captured["store"] is False
    assert captured["model"] == "gpt-5.6-terra"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert decision.verdict == VerificationVerdict.SUPPORTED
    assert decision.independent_model is True
    assert decision.input_tokens == 101
    assert decision.response_id == "resp_test_1"


def test_openai_refusal_is_an_abstention() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_refusal",
                "status": "completed",
                "model": "gpt-5.6-terra",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "Cannot verify safely."}],
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    decision = OpenAIResponsesVerifier(api_key="test-key", client=client).verify(proposal())
    client.close()
    assert decision.verdict == VerificationVerdict.ABSTAINED
    assert decision.confidence == 0
    assert decision.refusal is True
    assert decision.refusal_reason == "Cannot verify safely."


def test_openai_same_provider_or_model_cannot_claim_independence() -> None:
    responses = [
        {
            "id": "resp_same_provider",
            "status": "completed",
            "model": "gpt-5.6-terra",
            "output_text": json.dumps(
                {
                    "verdict": "SUPPORTED",
                    "rationale": "A same-provider verifier is not independent.",
                    "confidence": 0.99,
                    "evidence_ids": ["schema:cif_no"],
                }
            ),
        },
        {
            "id": "resp_same_model",
            "status": "completed",
            "model": "gpt-5.6-terra-2026-07-22",
            "output_text": json.dumps(
                {
                    "verdict": "SUPPORTED",
                    "rationale": "A model alias is not an independent model.",
                    "confidence": 0.99,
                    "evidence_ids": ["schema:cif_no"],
                }
            ),
        },
    ]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        response = responses[calls]
        calls += 1
        return httpx.Response(200, json=response)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = OpenAIResponsesVerifier(api_key="test-key", client=client)

    same_provider = proposal().model_copy(
        update={
            "generator_provider": " Open_AI ",
            "generator_model": "another-model",
            "risk": RiskLevel.LOW,
        }
    )
    same_model = proposal().model_copy(
        update={
            "generator_provider": "anthropic",
            "generator_model": "models/GPT 5.6 TERRA latest",
            "risk": RiskLevel.LOW,
        }
    )
    first = verifier.verify(same_provider)
    second = verifier.verify(same_model)
    client.close()

    assert first.independent_model is False
    assert second.independent_model is False
    assert VerificationPolicy().evaluate(same_provider, first).status == ProposalStatus.HUMAN_REVIEW
    assert VerificationPolicy().evaluate(same_model, second).status == ProposalStatus.HUMAN_REVIEW


def test_anthropic_adapter_is_disabled_before_any_network_call() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = AnthropicMessagesVerifier(api_key=None, client=client)
    assert isinstance(verifier, Verifier)
    assert verifier.enabled is False
    with pytest.raises(ProviderDisabledError, match="ANTHROPIC_API_KEY"):
        verifier.verify(proposal())
    assert called is False
    client.close()


def test_anthropic_messages_contract_is_bounded_and_structured() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.anthropic.com/v1/messages")
        assert request.headers["x-api-key"] == "test-anthropic-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "msg_test_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-20260715",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "verdict": "SUPPORTED",
                                "rationale": "Both supplied evidence records support the mapping.",
                                "confidence": 0.97,
                                "evidence_ids": ["schema:cif_no", "profile:cif_no"],
                            }
                        ),
                    }
                ],
                "stop_reason": "end_turn",
                "stop_details": None,
                "usage": {"input_tokens": 143, "output_tokens": 39},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    decision = AnthropicMessagesVerifier(
        api_key="test-anthropic-key",
        client=client,
    ).verify(proposal())
    client.close()

    assert captured["model"] == "claude-sonnet-5"
    assert captured["max_tokens"] == 2_048
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["output_config"]["format"]["type"] == "json_schema"
    schema = captured["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert "minimum" not in schema["properties"]["confidence"]
    assert {"temperature", "top_p", "top_k"}.isdisjoint(captured)
    assert decision.provider == "anthropic"
    assert decision.model == "claude-sonnet-5-20260715"
    assert decision.response_id == "msg_test_1"
    assert decision.input_tokens == 143
    assert decision.output_tokens == 39
    assert decision.latency_ms >= 0
    assert decision.verdict == VerificationVerdict.SUPPORTED
    assert decision.independent_model is True
    assert decision.refusal is False


def test_anthropic_refusal_is_recorded_as_an_abstention() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_refusal",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [],
                "stop_reason": "refusal",
                "stop_details": {
                    "type": "refusal",
                    "category": "cyber",
                    "explanation": "This verification request was declined.",
                },
                "usage": {"input_tokens": 88, "output_tokens": 0},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    decision = AnthropicMessagesVerifier(api_key="test-key", client=client).verify(proposal())
    client.close()

    assert decision.verdict == VerificationVerdict.ABSTAINED
    assert decision.confidence == 0
    assert decision.evidence_ids == []
    assert decision.refusal is True
    assert decision.refusal_reason == "This verification request was declined."
    assert decision.response_id == "msg_refusal"
    assert decision.input_tokens == 88
    assert decision.output_tokens == 0


def test_anthropic_same_provider_and_snapshot_alias_cannot_claim_independence() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_same_model",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-20260715",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "verdict": "SUPPORTED",
                                "rationale": "The evidence supports the proposal.",
                                "confidence": 0.99,
                                "evidence_ids": ["schema:cif_no"],
                            }
                        ),
                    }
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 80, "output_tokens": 20},
            },
        )

    item = proposal(risk=RiskLevel.LOW).model_copy(
        update={
            "generator_provider": "CLAUDE",
            "generator_model": "anthropic/claude_sonnet_5",
        }
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    decision = AnthropicMessagesVerifier(api_key="test-key", client=client).verify(item)
    client.close()

    assert decision.independent_model is False
    outcome = VerificationPolicy().evaluate(item, decision)
    assert outcome.status == ProposalStatus.HUMAN_REVIEW
    assert outcome.model_agreement is None


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            {
                "id": " ",
                "model": "claude-sonnet-5",
                "stop_reason": "refusal",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
            "response id",
        ),
        (
            {
                "id": "msg_missing_model",
                "stop_reason": "end_turn",
                "content": [],
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
            "response model",
        ),
        (
            {
                "id": "msg_missing_usage",
                "model": "claude-sonnet-5",
                "stop_reason": "end_turn",
                "content": [],
            },
            "usage must be an object",
        ),
        (
            {
                "id": "msg_bad_input_usage",
                "model": "claude-sonnet-5",
                "stop_reason": "end_turn",
                "content": [],
                "usage": {"input_tokens": "1", "output_tokens": 0},
            },
            "input_tokens",
        ),
        (
            {
                "id": "msg_bad_output_usage",
                "model": "claude-sonnet-5",
                "stop_reason": "refusal",
                "usage": {"input_tokens": 1, "output_tokens": True},
            },
            "output_tokens",
        ),
    ],
)
def test_anthropic_requires_real_response_metadata_even_for_refusal(
    body: dict,
    message: str,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    )
    verifier = AnthropicMessagesVerifier(api_key="test-key", client=client)
    with pytest.raises(ProviderProtocolError, match=message):
        verifier.verify(proposal())
    client.close()


def test_anthropic_rejects_truncated_or_schema_invalid_output() -> None:
    responses = [
        {
            "id": "msg_truncated",
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": '{"verdict":"SUPPORTED"'}],
            "stop_reason": "max_tokens",
            "usage": {"input_tokens": 10, "output_tokens": 4},
        },
        {
            "id": "msg_invalid",
            "model": "claude-sonnet-5",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "verdict": "SUPPORTED",
                            "rationale": "Invalid confidence must fail local validation.",
                            "confidence": 1.5,
                            "evidence_ids": ["schema:cif_no"],
                        }
                    ),
                }
            ],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
    ]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        response = responses[calls]
        calls += 1
        return httpx.Response(200, json=response)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = AnthropicMessagesVerifier(api_key="test-key", client=client)
    with pytest.raises(ProviderProtocolError, match="truncated at max_tokens"):
        verifier.verify(proposal())
    with pytest.raises(ProviderProtocolError, match="structured output was invalid"):
        verifier.verify(proposal())
    assert calls == 2
    client.close()


def test_environment_factory_defaults_to_mock_and_never_invents_key(monkeypatch) -> None:
    monkeypatch.delenv("VERIFIER_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_VERIFIER_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OA_ANTHROPIC_VERIFIER_MODEL", raising=False)
    assert isinstance(verifier_from_env(), DeterministicMockVerifier)

    monkeypatch.setenv("OPENAI_VERIFIER_MODE", "openai")
    openai_verifier = verifier_from_env()
    assert isinstance(openai_verifier, OpenAIResponsesVerifier)
    assert openai_verifier.enabled is False

    # The provider-neutral selector intentionally overrides the legacy mock
    # default, but never borrows the OpenAI credential for Anthropic.
    monkeypatch.setenv("OPENAI_VERIFIER_MODE", "mock")
    monkeypatch.setenv("OPENAI_API_KEY", "not-an-anthropic-key")
    monkeypatch.setenv("VERIFIER_PROVIDER", "anthropic")
    anthropic_verifier = verifier_from_env()
    assert isinstance(anthropic_verifier, AnthropicMessagesVerifier)
    assert anthropic_verifier.enabled is False
    assert anthropic_verifier.model == "claude-sonnet-5"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    assert verifier_from_env().enabled is True

    monkeypatch.setenv("OPENAI_VERIFIER_MODE", "openai")
    with pytest.raises(ValueError, match="conflicts"):
        verifier_from_env()

    monkeypatch.delenv("VERIFIER_PROVIDER")
    monkeypatch.setenv("OPENAI_VERIFIER_MODE", "anthropic")
    with pytest.raises(ValueError, match="VERIFIER_PROVIDER=anthropic"):
        verifier_from_env()


class _FakeGeminiModels:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeGeminiClient:
    def __init__(self, response) -> None:
        self.models = _FakeGeminiModels(response)


def _gemini_response(
    *,
    evidence_ids: list[str] | None = None,
    counterevidence_ids: list[str] | None = None,
    risk: str = "LOW",
):
    return SimpleNamespace(
        text=json.dumps(
            {
                "statement": "crm.cif_no maps to Customer Identifier",
                "rationale": "The schema name and profile evidence support the mapping.",
                "evidence_ids": evidence_ids or ["schema:cif_no"],
                "counterevidence_ids": counterevidence_ids or [],
                "risk": risk,
            }
        ),
        parsed=None,
        model_version="gemini-2.5-flash-vertex-20260701",
        response_id="vertex-response-1",
        usage_metadata=SimpleNamespace(
            prompt_token_count=123,
            candidates_token_count=41,
        ),
    )


def test_vertex_generator_is_disabled_before_any_sdk_or_network_call() -> None:
    client = _FakeGeminiClient(_gemini_response())
    generator = VertexGeminiGenerator(
        project_id="ontology-appliance-test",
        client=client,
    )
    assert isinstance(generator, Generator)
    assert generator.enabled is False
    with pytest.raises(ProviderDisabledError, match="GENERATOR_PROVIDER=vertex-ai"):
        generator.generate(GenerationRequest(objective="Map cif_no", evidenceIds=["schema:cif_no"]))
    assert client.models.calls == []


def test_vertex_generator_uses_adc_region_and_structured_json_contract() -> None:
    client = _FakeGeminiClient(_gemini_response())
    generator = VertexGeminiGenerator(
        provider_mode="vertex-ai",
        project_id="ontology-appliance-test",
        client=client,
    )
    request = GenerationRequest(
        objective="Map cif_no to the governed identifier concept",
        evidenceIds=["schema:cif_no", "profile:cif_no"],
        context={"sourceSnapshot": "crm-2026-07-22"},
    )

    generated = generator.generate(request)

    assert len(client.models.calls) == 1
    call = client.models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["response_json_schema"]["additionalProperties"] is False
    assert call["config"]["temperature"] == 0
    assert generated.generator_provider == "vertex-ai"
    assert generated.generator_model == "gemini-2.5-flash-vertex-20260701"
    assert generated.generator_response_id == "vertex-response-1"
    assert generated.generator_input_tokens == 123
    assert generated.generator_output_tokens == 41
    assert generated.generator_parameters["location"] == "europe-west4"
    assert generated.prompt_version == "semantic-generator-v1"
    assert generated.evidence_ids == ["schema:cif_no"]
    assert generated.model_dependent is True
    assert len(generated.deterministic_input_hash or "") == 64


def test_vertex_generator_elevates_policy_critical_risk() -> None:
    client = _FakeGeminiClient(_gemini_response(evidence_ids=["schema:ubo"], risk="LOW"))
    generator = VertexGeminiGenerator(
        provider_mode="vertex-ai",
        project_id="ontology-appliance-test",
        client=client,
    )
    generated = generator.generate(
        GenerationRequest(
            objective="Map the UBO field for sanctions traversal",
            evidenceIds=["schema:ubo"],
        )
    )
    assert generated.risk == RiskLevel.HIGH


def test_vertex_generator_rejects_uncited_or_invented_evidence() -> None:
    client = _FakeGeminiClient(_gemini_response(evidence_ids=["invented:evidence"]))
    generator = VertexGeminiGenerator(
        provider_mode="vertex-ai",
        project_id="ontology-appliance-test",
        client=client,
    )
    with pytest.raises(ProviderProtocolError, match="outside the generation request"):
        generator.generate(GenerationRequest(objective="Map cif_no", evidenceIds=["schema:cif_no"]))


def test_vertex_content_block_is_preserved_as_abstention() -> None:
    blocked = SimpleNamespace(
        text=None,
        parsed=None,
        prompt_feedback=SimpleNamespace(block_reason_message="SAFETY"),
    )
    generator = VertexGeminiGenerator(
        provider_mode="vertex-ai",
        project_id="ontology-appliance-test",
        client=_FakeGeminiClient(blocked),
    )
    with pytest.raises(GenerationAbstainedError, match="SAFETY"):
        generator.generate(GenerationRequest(objective="Map cif_no", evidenceIds=["schema:cif_no"]))


def test_generator_factory_requires_explicit_vertex_selection(monkeypatch) -> None:
    monkeypatch.delenv("GENERATOR_PROVIDER", raising=False)
    assert isinstance(generator_from_env(), DeterministicMockGenerator)

    monkeypatch.setenv("GENERATOR_PROVIDER", "vertex-ai")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "ontology-appliance-test")
    vertex = generator_from_env()
    assert isinstance(vertex, VertexGeminiGenerator)
    assert vertex.enabled is True
    assert vertex.location == "europe-west4"
    assert vertex.model == "gemini-2.5-flash"
