"""Canonical request/response contracts exposed through OpenAPI 3.1."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class ResponseStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    ABSTAINED = "ABSTAINED"


class PublicationState(StrEnum):
    CANDIDATE = "CANDIDATE"
    PUBLISHED = "PUBLISHED"


class ServingMode(StrEnum):
    DEMO_ONLY = "DEMO_ONLY"
    ACTIVE = "ACTIVE"


class ProblemDetails(ApiModel):
    """RFC 9457-style error envelope shared by every semantic operation."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str
    code: str
    trace_id: str


class EvidenceReference(ApiModel):
    artifact: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str | None = None
    source_system: str | None = None
    source_record_id: str | None = None


PayloadT = TypeVar("PayloadT")


class ResponseEnvelope(ApiModel, Generic[PayloadT]):
    data: PayloadT
    ontology_version: str
    trace_id: str
    tenant_id: str
    publication_state: PublicationState
    serving_mode: ServingMode
    is_published: bool
    evidence: list[EvidenceReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: ResponseStatus = ResponseStatus.OK
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HealthResponse(ApiModel):
    status: str
    ontology_version: str
    artifact_status: str
    publication_state: PublicationState
    serving_mode: ServingMode
    is_published: bool
    triple_count: int = Field(ge=0)
    loaded_at: datetime


class ResolveRequest(ApiModel):
    term: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)


class ResolvedConcept(ApiModel):
    iri: str
    label: str
    definition: str | None = None
    concept_type: str | None = None
    score: float = Field(ge=0, le=1)
    matched_on: str


class ResolveResult(ApiModel):
    term: str
    concepts: list[ResolvedConcept]


class ContextRequest(ApiModel):
    concept_iri: str | None = Field(default=None, min_length=1, max_length=2_048)
    term: str | None = Field(default=None, min_length=1, max_length=300)
    include_neighbors: bool = True
    limit: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def require_locator(self) -> "ContextRequest":
        if not self.concept_iri and not self.term:
            raise ValueError("conceptIri or term is required")
        return self


class SemanticRelation(ApiModel):
    subject: str
    predicate: str
    object: str
    object_label: str | None = None


class ConceptContext(ApiModel):
    iri: str
    label: str
    definition: str | None = None
    types: list[str]
    relations: list[SemanticRelation]
    mappings: list[dict[str, Any]]


class QueryRequest(ApiModel):
    question: str | None = Field(default=None, min_length=1, max_length=2_000)
    competency_question_id: str | None = Field(default=None, pattern=r"^CQ-00[1-5]$")
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_question(self) -> "QueryRequest":
        if not self.question and not self.competency_question_id:
            raise ValueError("question or competencyQuestionId is required")
        return self


class QueryAnswer(ApiModel):
    competency_question_id: str | None = None
    question: str
    rows: list[dict[str, Any]]
    explanation: str
    sparql: str | None = None


class ExplainRequest(ApiModel):
    resource_iri: str | None = Field(default=None, min_length=1, max_length=2_048)
    mapping_id: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def require_resource(self) -> "ExplainRequest":
        if not self.resource_iri and not self.mapping_id:
            raise ValueError("resourceIri or mappingId is required")
        return self


class ExplanationStep(ApiModel):
    order: int = Field(ge=1)
    statement: str
    evidence_iri: str | None = None


class ExplainResult(ApiModel):
    resource_iri: str
    label: str
    rationale: str
    confidence: dict[str, float] | None = None
    steps: list[ExplanationStep]
    counterexamples: list[str] = Field(default_factory=list)


class ValidateRequest(ApiModel):
    data_turtle: str | None = Field(default=None, max_length=1_000_000)
    shapes_turtle: str | None = Field(default=None, max_length=1_000_000)
    include_owl_rl_closure: bool = True


class ValidationIssue(ApiModel):
    severity: str
    focus_node: str | None = None
    path: str | None = None
    message: str
    source_shape: str | None = None


class ValidationResult(ApiModel):
    conforms: bool
    issues: list[ValidationIssue]
    report_text: str
    inferred_triples: int = Field(ge=0)


class SparqlRequest(ApiModel):
    query: str = Field(min_length=1, max_length=20_000)
    max_rows: int = Field(default=100, ge=1, le=1_000)


class SparqlResult(ApiModel):
    query_type: Literal["SELECT", "ASK", "CONSTRUCT", "DESCRIBE"]
    variables: list[str]
    rows: list[dict[str, Any]]
    boolean: bool | None
    truncated: bool
