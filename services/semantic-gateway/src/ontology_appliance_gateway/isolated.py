"""Hard-deadline workers for user-controlled semantic workloads.

RDFlib, OWL-RL and pySHACL are CPU-bound and cannot be safely cancelled when
they run in the API process. Each advanced request therefore runs in a child
process that can be terminated at the configured deadline.
"""

from __future__ import annotations

import multiprocessing
from multiprocessing.queues import Queue
from queue import Empty
from threading import BoundedSemaphore
from typing import Any

from owlrl import DeductiveClosure, OWLRL_Semantics
from pyshacl import validate as shacl_validate
from rdflib import BNode, Graph, Literal, RDF, URIRef
from rdflib.namespace import SH

from .errors import ApiProblem


def _value(node: Any) -> Any:
    if isinstance(node, Literal):
        return node.toPython()
    if isinstance(node, (URIRef, BNode)):
        return str(node)
    return node


def _local_name(node: Any) -> str:
    value = str(node)
    return value.rsplit(":", 1)[-1].rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _sparql(payload: dict[str, Any]) -> dict[str, Any]:
    graph = Graph()
    for triple in payload["graph_triples"]:
        graph.add(triple)
    result = graph.query(payload["query"])
    form = payload["form"]
    max_rows = payload["max_rows"]

    if form == "ASK":
        return {
            "query_type": form,
            "variables": [],
            "rows": [],
            "boolean": bool(result.askAnswer),
            "truncated": False,
        }
    if form in {"CONSTRUCT", "DESCRIBE"}:
        triples: list[dict[str, Any]] = []
        truncated = False
        for index, (subject, predicate, obj) in enumerate(result.graph):
            if index >= max_rows:
                truncated = True
                break
            triples.append(
                {"subject": _value(subject), "predicate": _value(predicate), "object": _value(obj)}
            )
        return {
            "query_type": form,
            "variables": ["subject", "predicate", "object"],
            "rows": triples,
            "boolean": None,
            "truncated": truncated,
        }

    variables = [str(variable) for variable in result.vars]
    rows: list[dict[str, Any]] = []
    truncated = False
    for index, row in enumerate(result):
        if index >= max_rows:
            truncated = True
            break
        rows.append({variable: _value(row.get(variable)) for variable in variables})
    return {
        "query_type": form,
        "variables": variables,
        "rows": rows,
        "boolean": None,
        "truncated": truncated,
    }


def _validation(payload: dict[str, Any]) -> dict[str, Any]:
    data_graph = Graph()
    shapes_graph = Graph()
    if payload["data_format"] == "triples":
        for triple in payload["data"]:
            data_graph.add(triple)
    else:
        data_graph.parse(data=payload["data"], format=payload["data_format"])
    if payload["shapes_format"] == "triples":
        for triple in payload["shapes"]:
            shapes_graph.add(triple)
    else:
        shapes_graph.parse(data=payload["shapes"], format=payload["shapes_format"])
    if len(data_graph) > payload["max_data_triples"]:
        raise ValueError("candidate data exceeds the configured triple limit")
    if len(shapes_graph) > payload["max_shape_triples"]:
        raise ValueError("candidate shapes exceed the configured triple limit")

    original_count = len(data_graph)
    if payload["include_owl_rl_closure"]:
        DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False).expand(data_graph)
        if len(data_graph) > payload["max_inferred_triples"]:
            raise ValueError("OWL-RL closure exceeds the configured triple limit")
    inferred = max(0, len(data_graph) - original_count)
    conforms, report_graph, report_text = shacl_validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        abort_on_first=False,
        allow_infos=True,
        allow_warnings=True,
    )
    issues: list[dict[str, Any]] = []
    for result in report_graph.subjects(RDF.type, SH.ValidationResult):
        if len(issues) >= payload["max_issues"]:
            break
        severity = report_graph.value(result, SH.resultSeverity)
        focus = report_graph.value(result, SH.focusNode)
        path = report_graph.value(result, SH.resultPath)
        message = report_graph.value(result, SH.resultMessage)
        source_shape = report_graph.value(result, SH.sourceShape)
        issues.append(
            {
                "severity": _local_name(severity) if severity else "Violation",
                "focus_node": str(focus) if focus else None,
                "path": str(path) if path else None,
                "message": str(message or "SHACL constraint failed.")[:2_000],
                "source_shape": str(source_shape) if source_shape else None,
            }
        )
    return {
        "conforms": bool(conforms),
        "issues": issues,
        "report_text": str(report_text)[:100_000],
        "inferred_triples": inferred,
    }


def _worker(queue: Queue, operation: str, payload: dict[str, Any]) -> None:
    try:
        if operation == "sparql":
            result = _sparql(payload)
        elif operation == "validation":
            result = _validation(payload)
        else:
            raise ValueError("unsupported isolated operation")
        queue.put(("ok", result))
    except Exception as exc:  # pragma: no cover - exercised via the parent process
        queue.put(("error", exc.__class__.__name__, str(exc)[:2_000]))


class IsolatedSemanticExecutor:
    """Runs bounded semantic work outside the API process."""

    def __init__(self, *, timeout_seconds: float, max_concurrency: int) -> None:
        self.timeout_seconds = timeout_seconds
        self._slots = BoundedSemaphore(max_concurrency)
        self._context = multiprocessing.get_context("spawn")

    def run(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._slots.acquire(blocking=False):
            raise ApiProblem(
                429,
                "Semantic worker capacity reached",
                "Try the governed operation again after the current workload completes.",
                code="semantic-capacity",
            )
        queue = self._context.Queue(maxsize=1)
        process = self._context.Process(
            target=_worker, args=(queue, operation, payload), daemon=True
        )
        try:
            process.start()
            process.join(self.timeout_seconds)
            if process.is_alive():
                process.terminate()
                process.join(1)
                if process.is_alive():  # pragma: no cover - defensive hard kill
                    process.kill()
                    process.join(1)
                raise ApiProblem(
                    504,
                    "Semantic operation timed out",
                    "The operation exceeded the governed execution deadline.",
                    code="semantic-timeout",
                )
            try:
                outcome = queue.get(timeout=0.5)
            except Empty as exc:
                raise ApiProblem(
                    422,
                    "Semantic operation failed",
                    "The isolated worker could not complete this request.",
                    code="semantic-worker-failed",
                ) from exc
            if outcome[0] == "error":
                raise ApiProblem(
                    422,
                    "Semantic operation rejected",
                    outcome[2],
                    code="semantic-operation-rejected",
                )
            return outcome[1]
        finally:
            if process.is_alive():
                process.terminate()
                process.join(1)
            queue.close()
            queue.join_thread()
            self._slots.release()
