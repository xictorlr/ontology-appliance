"""Deterministic semantic operations over the active RDF snapshot."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, SKOS, URIRef
from rdflib.plugins.sparql.parser import parseQuery

from .artifacts import ArtifactSnapshot
from .config import Settings
from .errors import ApiProblem
from .isolated import IsolatedSemanticExecutor
from .models import (
    ConceptContext,
    ExplainRequest,
    ExplainResult,
    ExplanationStep,
    QueryAnswer,
    ResolvedConcept,
    SemanticRelation,
    SparqlResult,
    ValidateRequest,
    ValidationResult,
)

OA = Namespace("urn:ontology-appliance:vocab:")
OAI = Namespace("urn:ontology-appliance:demo-bank:resource:")


COMPETENCY_QUESTIONS: dict[str, dict[str, Any]] = {
    "CQ-001": {
        "question": "Which accounts are linked to sanctioned parties through beneficial ownership?",
        "explanation": "Traverses sanctions target → beneficial owner → legal entity → account.",
        "evidence_iris": (
            str(OAI["evidence-sanctions-eu-998"]),
            str(OAI["evidence-crm-p-1001"]),
            str(OAI["evidence-kyc-document-1001"]),
            str(OAI["evidence-accounts-snapshot"]),
        ),
        "sparql": """
PREFIX oa: <urn:ontology-appliance:vocab:>
SELECT DISTINCT ?sanction ?party ?entity ?account WHERE {
  ?sanction a oa:SanctionsEntry ; oa:targetsParty ?party .
  ?party oa:beneficialOwnerOf ?entity .
  ?entity oa:hasAccount ?account .
}
ORDER BY ?account
""".strip(),
    },
    "CQ-002": {
        "question": "Which payments originate from accounts linked to sanctioned beneficial owners?",
        "explanation": "Extends CQ-001 from each affected account to its outbound payments.",
        "evidence_iris": (
            str(OAI["evidence-sanctions-eu-998"]),
            str(OAI["evidence-crm-p-1001"]),
            str(OAI["evidence-kyc-document-1001"]),
            str(OAI["evidence-accounts-snapshot"]),
            str(OAI["evidence-payments-snapshot"]),
        ),
        "sparql": """
PREFIX oa: <urn:ontology-appliance:vocab:>
SELECT DISTINCT ?payment ?account ?amount ?currency ?beneficiaryAccount WHERE {
  ?sanction a oa:SanctionsEntry ; oa:targetsParty ?party .
  ?party oa:beneficialOwnerOf ?entity .
  ?entity oa:hasAccount ?account .
  ?payment a oa:Payment ; oa:fromAccount ?account ; oa:amount ?amount ; oa:currency ?currency .
  OPTIONAL { ?payment oa:toAccount ?beneficiaryAccount }
}
ORDER BY ?payment
""".strip(),
    },
    "CQ-003": {
        "question": "Which party records are potential duplicates across sources, and what evidence supports that?",
        "explanation": "Returns explicitly proposed duplicate links and the source evidence used to support them.",
        "evidence_iris": (
            str(OAI["evidence-aml-77"]),
            str(OAI["evidence-crm-p-1001"]),
        ),
        "sparql": """
PREFIX oa: <urn:ontology-appliance:vocab:>
SELECT DISTINCT ?party ?duplicate ?partySource ?duplicateSource ?evidence WHERE {
  ?party oa:possibleDuplicateOf ?duplicate ; oa:sourceSystem ?partySource ; oa:evidence ?evidence .
  ?duplicate oa:sourceSystem ?duplicateSource .
  FILTER(STR(?party) < STR(?duplicate))
}
ORDER BY ?party ?duplicate
""".strip(),
    },
    "CQ-004": {
        "question": "Why is cif_no mapped to Customer Identifier, and what counterexamples were found?",
        "explanation": "Explains the proposed mapping using its evidence, confidence dimensions, and recorded counterexamples.",
        "evidence_iris": (
            str(OAI["evidence-crm-schema-cif"]),
            str(OAI["evidence-crm-profile-cif"]),
            str(OAI["evidence-crm-cif-duplicate-0042"]),
        ),
        "sparql": """
PREFIX oa: <urn:ontology-appliance:vocab:>
SELECT ?mapping ?field ?concept ?evidence ?counterevidence ?counterexample ?lexical ?structural ?instance WHERE {
  ?mapping a oa:MappingProposal ;
    oa:mappingId "mapping-crm-cif" ;
    oa:fieldName ?field ;
    oa:mapsToConcept ?concept ;
    oa:evidence ?evidence ;
    oa:counterevidence ?counterevidence .
  OPTIONAL { ?mapping oa:counterexample ?counterexample }
  OPTIONAL { ?mapping oa:confidenceLexical ?lexical }
  OPTIONAL { ?mapping oa:confidenceStructural ?structural }
  OPTIONAL { ?mapping oa:confidenceInstance ?instance }
}
ORDER BY ?mapping ?evidence ?counterevidence
""".strip(),
    },
    "CQ-005": {
        "question": "What is impacted if the ubo field mapping is deleted?",
        "explanation": "Shows the mapping, derived relation, and competency questions that depend on the ubo field.",
        "evidence_iris": (
            str(OAI["evidence-crm-schema-ubo"]),
            str(OAI["evidence-kyc-document-1001"]),
        ),
        "sparql": """
PREFIX oa: <urn:ontology-appliance:vocab:>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT DISTINCT ?mapping ?concept ?dependency ?dependencyType WHERE {
  ?mapping a oa:MappingProposal ; oa:fieldName "ubo" ; oa:mapsToConcept ?concept .
  ?dependency oa:dependsOn ?mapping ; a ?dependencyType .
  FILTER(?dependencyType != owl:Thing)
}
ORDER BY ?dependency
""".strip(),
    },
}


def _value(node: Any) -> Any:
    if isinstance(node, Literal):
        return node.toPython()
    if isinstance(node, (URIRef, BNode)):
        return str(node)
    return node


def _local_name(node: URIRef | str) -> str:
    value = str(node)
    return value.rsplit(":", 1)[-1].rsplit("/", 1)[-1].rsplit("#", 1)[-1]


class SemanticEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._isolated = IsolatedSemanticExecutor(
            timeout_seconds=settings.semantic_timeout_seconds,
            max_concurrency=settings.max_semantic_concurrency,
        )

    @staticmethod
    def label(graph: Graph, resource: URIRef) -> str:
        for predicate in (SKOS.prefLabel, RDFS.label):
            label = graph.value(resource, predicate)
            if label is not None:
                return str(label)
        return _local_name(resource).replace("-", " ").replace("_", " ")

    def resolve(self, snapshot: ArtifactSnapshot, term: str, limit: int) -> list[ResolvedConcept]:
        graph = snapshot.graph
        query = term.casefold().strip()
        candidates: dict[URIRef, ResolvedConcept] = {}
        label_predicates = (SKOS.prefLabel, SKOS.altLabel, RDFS.label)
        for predicate in label_predicates:
            for subject, label_node in graph.subject_objects(predicate):
                if not isinstance(subject, URIRef) or not isinstance(label_node, Literal):
                    continue
                label = str(label_node)
                normalized = label.casefold()
                ratio = SequenceMatcher(None, query, normalized).ratio()
                if query == normalized:
                    score = 1.0
                elif query in normalized or normalized in query:
                    score = max(0.84, ratio)
                else:
                    score = ratio * 0.78
                if score < 0.25:
                    continue
                definition = graph.value(subject, SKOS.definition) or graph.value(
                    subject, RDFS.comment
                )
                resource_type = next(
                    (obj for obj in graph.objects(subject, RDF.type) if isinstance(obj, URIRef)),
                    None,
                )
                proposed = ResolvedConcept(
                    iri=str(subject),
                    label=self.label(graph, subject),
                    definition=str(definition) if definition is not None else None,
                    concept_type=str(resource_type) if resource_type is not None else None,
                    score=round(score, 4),
                    matched_on=_local_name(predicate),
                )
                existing = candidates.get(subject)
                if existing is None or proposed.score > existing.score:
                    candidates[subject] = proposed
        return sorted(candidates.values(), key=lambda item: (-item.score, item.label))[:limit]

    def context(
        self,
        snapshot: ArtifactSnapshot,
        *,
        concept_iri: str | None,
        term: str | None,
        include_neighbors: bool,
        limit: int,
    ) -> ConceptContext:
        graph = snapshot.graph
        if concept_iri:
            resource = URIRef(concept_iri)
        else:
            resolved = self.resolve(snapshot, term or "", 1)
            if not resolved:
                raise ApiProblem(
                    404,
                    "Concept not found",
                    f"No concept matched '{term}'.",
                    code="concept-not-found",
                )
            resource = URIRef(resolved[0].iri)
        if not any(graph.triples((resource, None, None))) and not any(
            graph.triples((None, None, resource))
        ):
            raise ApiProblem(
                404,
                "Concept not found",
                f"Resource '{resource}' is not in the active graph.",
                code="concept-not-found",
            )

        definition = graph.value(resource, SKOS.definition) or graph.value(resource, RDFS.comment)
        types = sorted(
            str(obj) for obj in graph.objects(resource, RDF.type) if isinstance(obj, URIRef)
        )
        relations: list[SemanticRelation] = []
        if include_neighbors:
            for subject, predicate, obj in graph.triples((resource, None, None)):
                if predicate in {
                    RDF.type,
                    RDFS.label,
                    SKOS.prefLabel,
                    SKOS.altLabel,
                    SKOS.definition,
                }:
                    continue
                relations.append(
                    SemanticRelation(
                        subject=str(subject),
                        predicate=str(predicate),
                        object=str(obj),
                        object_label=self.label(graph, obj) if isinstance(obj, URIRef) else None,
                    )
                )
            for subject, predicate, obj in graph.triples((None, None, resource)):
                relations.append(
                    SemanticRelation(
                        subject=str(subject),
                        predicate=str(predicate),
                        object=str(obj),
                        object_label=self.label(graph, resource),
                    )
                )
            relations = sorted(relations, key=lambda rel: (rel.predicate, rel.subject, rel.object))[
                :limit
            ]

        mappings: list[dict[str, Any]] = []
        for mapping in graph.subjects(OA.mapsToConcept, resource):
            mappings.append(
                {
                    "mappingIri": str(mapping),
                    "fieldName": _value(graph.value(mapping, OA.fieldName)),
                    "sourceSystem": _value(graph.value(mapping, OA.sourceSystem)),
                    "status": _value(graph.value(mapping, OA.proposalStatus)),
                }
            )
        return ConceptContext(
            iri=str(resource),
            label=self.label(graph, resource),
            definition=str(definition) if definition is not None else None,
            types=types,
            relations=relations,
            mappings=mappings,
        )

    @staticmethod
    def recognize_competency_question(question: str | None) -> str | None:
        normalized = (question or "").casefold()
        if "cif_no" in normalized:
            return "CQ-004"
        if "ubo" in normalized and any(
            word in normalized for word in ("impact", "delete", "delet", "elimin")
        ):
            return "CQ-005"
        if any(word in normalized for word in ("duplicate", "duplicad")):
            return "CQ-003"
        if any(word in normalized for word in ("payment", "pago", "transfer")) and any(
            word in normalized for word in ("sanction", "sancion", "beneficial", "ubo")
        ):
            return "CQ-002"
        if "account" in normalized or "cuenta" in normalized:
            if any(word in normalized for word in ("sanction", "sancion", "beneficial", "ubo")):
                return "CQ-001"
        return None

    def competency_query(
        self,
        snapshot: ArtifactSnapshot,
        competency_question_id: str | None,
        question: str | None,
    ) -> QueryAnswer | None:
        question_id = competency_question_id or self.recognize_competency_question(question)
        if question_id is None:
            return None
        definition = COMPETENCY_QUESTIONS[question_id]
        rows = self._select(
            snapshot.graph, definition["sparql"], limit=self.settings.max_sparql_rows
        )
        return QueryAnswer(
            competency_question_id=question_id,
            question=question or definition["question"],
            rows=rows,
            explanation=definition["explanation"],
            sparql=definition["sparql"],
        )

    def explain(self, snapshot: ArtifactSnapshot, request: ExplainRequest) -> ExplainResult:
        graph = snapshot.graph
        if request.mapping_id:
            candidate = URIRef(str(OAI) + request.mapping_id)
            if (candidate, RDF.type, OA.MappingProposal) not in graph:
                candidate = next(
                    (
                        subject
                        for subject in graph.subjects(RDF.type, OA.MappingProposal)
                        if _local_name(subject) == request.mapping_id
                        or str(graph.value(subject, OA.mappingId) or "") == request.mapping_id
                    ),
                    candidate,
                )
            resource = candidate
        else:
            resource = URIRef(request.resource_iri or "")
        if not any(graph.triples((resource, None, None))):
            raise ApiProblem(
                404,
                "Resource not found",
                f"Resource '{resource}' is not in the active graph.",
                code="resource-not-found",
            )

        steps: list[ExplanationStep] = []
        evidence_nodes = [
            obj for obj in graph.objects(resource, OA.evidence) if isinstance(obj, URIRef)
        ]
        for predicate in (OA.fieldName, OA.mapsToConcept, OA.derivedRelation, OA.proposalStatus):
            for obj in graph.objects(resource, predicate):
                steps.append(
                    ExplanationStep(
                        order=len(steps) + 1,
                        statement=f"{_local_name(predicate)} = {_value(obj)}",
                    )
                )
        for evidence in evidence_nodes:
            evidence_label = self.label(graph, evidence)
            locator = graph.value(evidence, OA.locator)
            steps.append(
                ExplanationStep(
                    order=len(steps) + 1,
                    statement=f"Evidence: {evidence_label}" + (f" at {locator}" if locator else ""),
                    evidence_iri=str(evidence),
                )
            )
        if not steps:
            for _subject, predicate, obj in list(graph.triples((resource, None, None)))[:10]:
                if predicate not in {RDF.type, RDFS.label, SKOS.prefLabel}:
                    steps.append(
                        ExplanationStep(
                            order=len(steps) + 1,
                            statement=f"{_local_name(predicate)} = {_value(obj)}",
                        )
                    )

        confidence_values = {
            "lexical": graph.value(resource, OA.confidenceLexical),
            "structural": graph.value(resource, OA.confidenceStructural),
            "instance": graph.value(resource, OA.confidenceInstance),
            "provenance": graph.value(resource, OA.confidenceProvenance),
        }
        confidence: dict[str, float] = {}
        for key, value in confidence_values.items():
            if not isinstance(value, Literal):
                continue
            try:
                confidence[key] = float(value.toPython())
            except (TypeError, ValueError):
                continue
        counterexamples = [str(obj) for obj in graph.objects(resource, OA.counterexample)]
        rationale_node = graph.value(resource, OA.rationale) or graph.value(
            resource, SKOS.definition
        )
        return ExplainResult(
            resource_iri=str(resource),
            label=self.label(graph, resource),
            rationale=str(
                rationale_node
                or "The explanation is derived only from the hash-verified bundle; its publication "
                "state is reported separately in the response envelope."
            ),
            confidence=confidence or None,
            steps=steps,
            counterexamples=counterexamples,
        )

    def validate(self, snapshot: ArtifactSnapshot, request: ValidateRequest) -> ValidationResult:
        payload = self._isolated.run(
            "validation",
            {
                "data": request.data_turtle
                if request.data_turtle is not None
                else list(snapshot.graph),
                "data_format": "turtle" if request.data_turtle is not None else "triples",
                "shapes": request.shapes_turtle
                if request.shapes_turtle is not None
                else list(snapshot.shapes),
                "shapes_format": "turtle" if request.shapes_turtle is not None else "triples",
                "include_owl_rl_closure": request.include_owl_rl_closure,
                "max_data_triples": self.settings.max_validation_triples,
                "max_shape_triples": self.settings.max_shape_triples,
                "max_inferred_triples": self.settings.max_inferred_triples,
                "max_issues": 250,
            },
        )
        return ValidationResult.model_validate(payload)

    def sparql(
        self, snapshot: ArtifactSnapshot, query: str, requested_max_rows: int
    ) -> SparqlResult:
        if len(query) > self.settings.max_sparql_query_length:
            raise ApiProblem(
                413,
                "SPARQL query too large",
                "Query exceeds the configured size limit.",
                code="query-too-large",
            )
        form = self._read_query_form(query)
        self._check_query_complexity(query)
        max_rows = min(requested_max_rows, self.settings.max_sparql_rows)
        payload = self._isolated.run(
            "sparql",
            {
                "graph_triples": list(snapshot.graph),
                "query": query,
                "form": form,
                "max_rows": max_rows,
            },
        )
        return SparqlResult.model_validate(payload)

    @staticmethod
    def _check_query_complexity(query: str) -> None:
        normalized = re.sub(r"#[^\n]*", "", query)
        if len(re.findall(r"\bSELECT\b", normalized, re.IGNORECASE)) > 1:
            raise ApiProblem(
                422,
                "SPARQL query too complex",
                "Nested SELECT queries are not enabled on the interactive endpoint.",
                code="query-too-complex",
            )
        if re.search(r"\b(COUNT|SUM|AVG|GROUP\s+BY|HAVING)\b", normalized, re.IGNORECASE):
            raise ApiProblem(
                422,
                "SPARQL query too complex",
                "Aggregations are available only as reviewed competency-query templates.",
                code="query-too-complex",
            )
        if len(re.findall(r"[?$][A-Za-z_][A-Za-z0-9_-]*", normalized)) > 64:
            raise ApiProblem(
                422,
                "SPARQL query too complex",
                "The query exceeds the interactive graph-pattern budget.",
                code="query-too-complex",
            )

    @staticmethod
    def _read_query_form(query: str) -> str:
        update_keyword = re.compile(
            r"\b(INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|COPY|MOVE|ADD|WITH)\b",
            re.IGNORECASE,
        )
        try:
            parsed = parseQuery(query)
        except Exception as exc:
            if update_keyword.search(query):
                raise ApiProblem(
                    403,
                    "SPARQL operation not allowed",
                    "Only local read-only SELECT, ASK, CONSTRUCT, and DESCRIBE queries are accepted.",
                    code="sparql-read-only",
                ) from exc
            raise ApiProblem(422, "Invalid SPARQL query", str(exc), code="invalid-sparql") from exc

        query_node = parsed[1]
        query_type = {
            "SelectQuery": "SELECT",
            "AskQuery": "ASK",
            "ConstructQuery": "CONSTRUCT",
            "DescribeQuery": "DESCRIBE",
        }.get(getattr(query_node, "name", ""))
        has_external_dataset = "datasetClause" in query_node and bool(query_node["datasetClause"])
        has_service = SemanticEngine._contains_parse_node(query_node, "ServiceGraphPattern")
        if not query_type or has_external_dataset or has_service:
            raise ApiProblem(
                403,
                "SPARQL operation not allowed",
                "Only local read-only SELECT, ASK, CONSTRUCT, and DESCRIBE queries are accepted.",
                code="sparql-read-only",
            )
        return query_type

    @staticmethod
    def _contains_parse_node(value: Any, node_name: str) -> bool:
        if getattr(value, "name", None) == node_name:
            return True
        if isinstance(value, dict):
            return any(
                SemanticEngine._contains_parse_node(item, node_name) for item in value.values()
            )
        if isinstance(value, (list, tuple)):
            return any(SemanticEngine._contains_parse_node(item, node_name) for item in value)
        return False

    @staticmethod
    def _select(graph: Graph, query: str, limit: int) -> list[dict[str, Any]]:
        result = graph.query(query)
        variables = [str(variable) for variable in result.vars]
        rows = []
        for index, row in enumerate(result):
            if index >= limit:
                break
            rows.append({variable: _value(row.get(variable)) for variable in variables})
        return rows
