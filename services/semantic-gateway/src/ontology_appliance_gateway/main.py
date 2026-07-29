"""FastAPI application for the read-only semantic gateway."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .artifacts import ArtifactSnapshot, ArtifactStore
from .auth import Principal, principal_dependency, require_roles
from .config import Settings
from .errors import ApiProblem, problem_handler
from .models import (
    ConceptContext,
    ContextRequest,
    ExplainRequest,
    ExplainResult,
    HealthResponse,
    ProblemDetails,
    QueryAnswer,
    QueryRequest,
    ResolveRequest,
    ResolveResult,
    ResponseEnvelope,
    ResponseStatus,
    SparqlRequest,
    SparqlResult,
    ValidateRequest,
    ValidationResult,
)
from .semantic import SemanticEngine
from .verification import (
    ProviderDisabledError,
    ProviderProtocolError,
    SemanticProposal,
    VerificationOutcome,
    VerificationPolicy,
    VerificationVerdict,
    verifier_from_env,
)

LOGGER = logging.getLogger("ontology_appliance.semantic_gateway")
TRACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
DEFAULT_PROBLEM_RESPONSES = {
    "default": {
        "description": "RFC 9457 Problem Details",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}
        },
    }
}


def _install_governed_openapi(application: FastAPI) -> None:
    """Add canonical shared components without weakening typed success responses."""

    default_openapi = application.openapi

    def governed_openapi() -> dict[str, Any]:
        document = default_openapi()
        schemas = document.setdefault("components", {}).setdefault("schemas", {})
        for name, model in (
            ("ResponseEnvelope", ResponseEnvelope),
            ("ProblemDetails", ProblemDetails),
        ):
            component = model.model_json_schema(
                by_alias=True,
                ref_template="#/components/schemas/{model}",
            )
            component.pop("$defs", None)
            schemas[name] = component
        application.openapi_schema = document
        return document

    application.openapi = governed_openapi


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    store = ArtifactStore(runtime_settings)
    engine = SemanticEngine(runtime_settings)
    get_principal = principal_dependency(runtime_settings)
    verifier = verifier_from_env()
    verification_policy = VerificationPolicy()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        snapshot = store.initialize()
        application.state.artifact_store = store
        LOGGER.info(
            "semantic_snapshot_loaded",
            extra={
                "ontology_version": snapshot.version,
                "triple_count": len(snapshot.graph),
                "artifact_status": snapshot.status,
            },
        )
        yield

    application = FastAPI(
        title="Ontology Appliance Semantic Gateway",
        summary="Governed semantic context for enterprise applications and agents",
        description=(
            "A tenant-aware, read-only RDF runtime. Every artifact is hash-verified and "
            "SHACL-validated; every response states whether its bundle is a non-published "
            "demo candidate or an active Publisher-promoted release."
        ),
        version="0.1.0",
        openapi_version="3.1.0",
        docs_url="/docs" if runtime_settings.is_development else None,
        redoc_url="/redoc" if runtime_settings.is_development else None,
        lifespan=lifespan,
    )
    application.state.artifact_store = store
    application.state.settings = runtime_settings
    application.add_exception_handler(ApiProblem, problem_handler)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
        serializable_errors = [
            {key: value for key, value in error.items() if key != "ctx"} for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            headers={"X-Trace-Id": trace_id},
            content={
                "type": "urn:ontology-appliance:problem:request-validation",
                "title": "Request validation failed",
                "status": 422,
                "detail": "The request does not match the published API contract.",
                "instance": request.url.path,
                "code": "request-validation",
                "traceId": trace_id,
                "errors": jsonable_encoder(serializable_errors),
            },
        )

    @application.middleware("http")
    async def trace_middleware(request: Request, call_next):
        supplied = request.headers.get("X-Trace-Id", "")
        trace_id = supplied if TRACE_PATTERN.fullmatch(supplied) else str(uuid.uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    def snapshot() -> ArtifactSnapshot:
        return store.snapshot

    def envelope(
        request: Request,
        principal: Principal,
        payload,
        *,
        status: ResponseStatus = ResponseStatus.OK,
        locator: str | None = None,
        warnings: list[str] | None = None,
    ):
        active = snapshot()
        response_warnings = list(warnings or [])
        if active.status != "READY":
            response_warnings.append(
                "The candidate artifact set failed verification; the last valid ontology remains active."
            )
        if not active.is_published:
            response_warnings.append(
                "NON-PUBLISHED DEMO CANDIDATE: mappings remain proposals and must not be "
                "treated as active governed semantics."
            )
        return ResponseEnvelope(
            data=payload,
            ontology_version=active.version,
            trace_id=request.state.trace_id,
            tenant_id=principal.tenant_id,
            publication_state=active.publication_state,
            serving_mode=active.serving_mode,
            is_published=active.is_published,
            evidence=active.evidence(locator=locator),
            warnings=response_warnings,
            status=status,
        )

    @application.get(
        "/healthz",
        response_model=HealthResponse,
        operation_id="health",
        tags=["operations"],
        summary="Report active semantic snapshot health",
    )
    def healthz() -> HealthResponse:
        active = snapshot()
        return HealthResponse(
            status="ok" if active.status == "READY" else "degraded",
            ontology_version=active.version,
            artifact_status=active.status,
            publication_state=active.publication_state,
            serving_mode=active.serving_mode,
            is_published=active.is_published,
            triple_count=len(active.graph),
            loaded_at=active.loaded_at,
        )

    @application.post(
        "/v1/resolve",
        response_model=ResponseEnvelope[ResolveResult],
        operation_id="resolveTerm",
        responses=DEFAULT_PROBLEM_RESPONSES,
        tags=["semantic"],
        summary="Resolve a business term to governed concepts",
    )
    def resolve(
        body: ResolveRequest,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> ResponseEnvelope[ResolveResult]:
        concepts = engine.resolve(snapshot(), body.term, body.limit)
        status = ResponseStatus.OK if concepts else ResponseStatus.ABSTAINED
        warnings = [] if concepts else ["No governed concept met the lexical resolution threshold."]
        return envelope(
            request,
            principal,
            ResolveResult(term=body.term, concepts=concepts),
            status=status,
            locator=f"term:{body.term}",
            warnings=warnings,
        )

    @application.post(
        "/v1/context",
        response_model=ResponseEnvelope[ConceptContext],
        operation_id="getContext",
        responses=DEFAULT_PROBLEM_RESPONSES,
        tags=["semantic"],
        summary="Retrieve definitions, relations, and source mappings",
    )
    def context(
        body: ContextRequest,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> ResponseEnvelope[ConceptContext]:
        payload = engine.context(
            snapshot(),
            concept_iri=body.concept_iri,
            term=body.term,
            include_neighbors=body.include_neighbors,
            limit=body.limit,
        )
        return envelope(request, principal, payload, locator=payload.iri)

    @application.post(
        "/v1/query",
        response_model=ResponseEnvelope[QueryAnswer],
        operation_id="semanticQuery",
        responses=DEFAULT_PROBLEM_RESPONSES,
        tags=["semantic"],
        summary="Answer one of the governed competency questions",
    )
    def query(
        body: QueryRequest,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> ResponseEnvelope[QueryAnswer]:
        answer = engine.competency_query(snapshot(), body.competency_question_id, body.question)
        if answer is None:
            answer = QueryAnswer(
                question=body.question or "Unrecognized question",
                rows=[],
                explanation=(
                    "The gateway abstained because this request is not one of the five bundled "
                    "competency questions. Use /v1/sparql for an explicitly reviewed read query."
                ),
            )
            return envelope(
                request,
                principal,
                answer,
                status=ResponseStatus.ABSTAINED,
                warnings=["No approved query template matched the question."],
            )
        return envelope(
            request,
            principal,
            answer,
            locator=answer.competency_question_id,
        )

    @application.post(
        "/v1/explain",
        response_model=ResponseEnvelope[ExplainResult],
        operation_id="explainAssertion",
        responses=DEFAULT_PROBLEM_RESPONSES,
        tags=["semantic"],
        summary="Explain a mapping or bundled semantic resource",
    )
    def explain(
        body: ExplainRequest,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> ResponseEnvelope[ExplainResult]:
        explanation = engine.explain(snapshot(), body)
        return envelope(request, principal, explanation, locator=explanation.resource_iri)

    @application.post(
        "/v1/validate",
        response_model=ResponseEnvelope[ValidationResult],
        operation_id="validateProposal",
        responses=DEFAULT_PROBLEM_RESPONSES,
        tags=["verification"],
        summary="Validate RDF data with SHACL and optional OWL-RL closure",
    )
    def validate(
        body: ValidateRequest,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> ResponseEnvelope[ValidationResult]:
        require_roles(principal, "admin", "steward")
        result = engine.validate(snapshot(), body)
        status = ResponseStatus.OK if result.conforms else ResponseStatus.PARTIAL
        return envelope(request, principal, result, status=status, locator="shacl-report")

    @application.post(
        "/v1/verify",
        response_model=ResponseEnvelope[VerificationOutcome],
        operation_id="verifyIndependently",
        responses=DEFAULT_PROBLEM_RESPONSES,
        tags=["verification"],
        summary="Run the independent verifier and evaluate the approval policy",
    )
    def verify(
        body: SemanticProposal,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> ResponseEnvelope[VerificationOutcome]:
        require_roles(principal, "service", "admin")
        try:
            decision = verifier.verify(body)
        except ProviderDisabledError as exc:
            raise ApiProblem(
                503,
                "Independent verifier disabled",
                "The configured verifier provider is not enabled for this deployment.",
                code="verifier-disabled",
            ) from exc
        except ProviderProtocolError as exc:
            raise ApiProblem(
                502,
                "Independent verifier protocol error",
                "The verifier provider returned a response that violates the contract.",
                code="verifier-protocol",
            ) from exc
        outcome = verification_policy.evaluate(body, decision)
        abstained = outcome.decision.verdict == VerificationVerdict.ABSTAINED
        warnings = (
            ["The verifier recorded no independent judgment; policy gates remain authoritative."]
            if abstained
            else None
        )
        return envelope(
            request,
            principal,
            outcome,
            status=ResponseStatus.ABSTAINED if abstained else ResponseStatus.OK,
            locator=f"proposal:{body.proposal_id}",
            warnings=warnings,
        )

    @application.post(
        "/v1/sparql",
        response_model=ResponseEnvelope[SparqlResult],
        operation_id="readOnlySparql",
        responses=DEFAULT_PROBLEM_RESPONSES,
        openapi_extra={"x-read-only": True},
        tags=["advanced"],
        summary="Execute a role-gated, local read-only SPARQL query",
    )
    def sparql(
        body: SparqlRequest,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> ResponseEnvelope[SparqlResult]:
        require_roles(principal, "admin", "steward", "auditor")
        result = engine.sparql(snapshot(), body.query, body.max_rows)
        return envelope(request, principal, result, locator="read-only-sparql")

    _install_governed_openapi(application)
    return application


app = create_app()
