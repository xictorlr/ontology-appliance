#!/usr/bin/env python3
"""Evaluate deterministic semantic proposal gates and return a routing status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DIMENSIONS = ("lexical", "structural", "instance", "external", "model", "evidence_coverage")
RISKS = {"low", "medium", "high"}


def malformed(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["proposal must be a JSON object"]
    for field in ("proposal_id", "tenant_id"):
        if not isinstance(data.get(field), str) or not data.get(field, "").strip():
            errors.append(f"{field} must be a non-empty string")
    if data.get("risk") not in RISKS:
        errors.append(f"risk must be one of {sorted(RISKS)}")
    if not isinstance(data.get("evidence"), list):
        errors.append("evidence must be an array")
    confidence = data.get("confidence")
    if not isinstance(confidence, dict):
        errors.append("confidence must be an object")
    else:
        for name in DIMENSIONS:
            value = confidence.get(name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                errors.append(f"confidence.{name} must be between 0 and 1")
    checks = data.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be an object")
    else:
        for name in ("provenance_complete", "schema_valid", "shacl_valid", "sql_valid"):
            if not isinstance(checks.get(name), bool):
                errors.append(f"checks.{name} must be boolean")
        for name in ("competency_questions_passed", "competency_questions_total"):
            value = checks.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"checks.{name} must be a non-negative integer")
    models = data.get("models")
    if not isinstance(models, dict) or models.get("mode") not in {"mock", "live"}:
        errors.append("models.mode must be 'mock' or 'live'")
    return errors


def evaluate(data: Any) -> dict[str, Any]:
    errors = malformed(data)
    gates: list[dict[str, Any]] = []
    if errors:
        return {"status": "QUARANTINED", "reason_codes": ["CONTRACT_INVALID"], "errors": errors, "gates": gates}

    checks = data["checks"]
    evidence = data["evidence"]
    confidence = data["confidence"]
    models = data["models"]

    provenance_ok = checks["provenance_complete"] and bool(evidence)
    gates.append({"gate": "provenance", "passed": provenance_ok})
    if not provenance_ok:
        return {"status": "QUARANTINED", "reason_codes": ["PROVENANCE_INCOMPLETE"], "gates": gates}

    # ``sql_valid`` is retained in the frozen fixture for compatibility. The
    # MVP does not execute SQL; it records a fixture-backed source assertion.
    deterministic = {
        "schema": checks["schema_valid"],
        "shacl": checks["shacl_valid"],
        "source_assertion_fixture": checks["sql_valid"],
    }
    gates.extend({"gate": name, "passed": passed} for name, passed in deterministic.items())
    if not all(deterministic.values()):
        failed = [name.upper() + "_FAILED" for name, passed in deterministic.items() if not passed]
        return {"status": "REJECTED", "reason_codes": failed, "gates": gates}

    total = checks["competency_questions_total"]
    passed = checks["competency_questions_passed"]
    cq_ok = total > 0 and passed <= total and passed / total >= 0.8
    gates.append({"gate": "competency_questions", "passed": cq_ok, "passed_count": passed, "total": total})
    if not cq_ok:
        return {"status": "REJECTED", "reason_codes": ["COMPETENCY_QUESTIONS_FAILED"], "gates": gates}

    if confidence["evidence_coverage"] < 0.25:
        gates.append({"gate": "evidence_coverage", "passed": False})
        return {"status": "ABSTAINED", "reason_codes": ["INSUFFICIENT_EVIDENCE"], "gates": gates}
    gates.append({"gate": "evidence_coverage", "passed": True})

    generator = models.get("generator")
    verifier = models.get("verifier")
    agreement = models.get("independent_agreement")
    independent = (
        models["mode"] == "live"
        and isinstance(generator, dict)
        and isinstance(verifier, dict)
        and generator.get("provider")
        and verifier.get("provider")
        and generator.get("provider") != verifier.get("provider")
        and generator.get("model") != verifier.get("model")
        and agreement is True
    )
    gates.append({"gate": "independent_verification", "passed": independent})

    risk_requires_human = data["risk"] in {"medium", "high"}
    gates.append(
        {
            "gate": "risk",
            "passed": not risk_requires_human,
            **({"requires_human": True} if risk_requires_human else {}),
        }
    )
    human_reason_codes: list[str] = []
    if not independent:
        human_reason_codes.append(
            "MOCK_REQUIRES_HUMAN" if models["mode"] == "mock" else "NO_INDEPENDENT_AGREEMENT"
        )
    if risk_requires_human:
        human_reason_codes.append("RISK_REQUIRES_HUMAN")
    if human_reason_codes:
        return {"status": "HUMAN_REVIEW", "reason_codes": human_reason_codes, "gates": gates}

    strong = (
        confidence["lexical"] >= 0.85
        and confidence["structural"] >= 0.85
        and confidence["instance"] >= 0.85
        and confidence["external"] >= 0.70
        and confidence["model"] >= 0.80
        and confidence["evidence_coverage"] >= 0.95
    )
    gates.append({"gate": "confidence_policy", "passed": strong})
    if not strong:
        return {"status": "HUMAN_REVIEW", "reason_codes": ["CONFIDENCE_REQUIRES_HUMAN"], "gates": gates}
    return {"status": "AUTO_APPROVED", "reason_codes": ["ALL_GATES_PASSED"], "gates": gates}


def valid_example(mode: str = "live") -> dict[str, Any]:
    return {
        "proposal_id": "p-1",
        "tenant_id": "demo-bank",
        "risk": "low",
        "evidence": [{"evidence_id": "e-1"}],
        "confidence": {
            "lexical": 0.90,
            "structural": 0.92,
            "instance": 0.91,
            "external": 0.80,
            "model": 0.90,
            "evidence_coverage": 1.0,
        },
        "checks": {
            "provenance_complete": True,
            "schema_valid": True,
            "shacl_valid": True,
            "sql_valid": True,
            "competency_questions_passed": 5,
            "competency_questions_total": 5,
        },
        "models": {
            "mode": mode,
            "generator": {"provider": "vertex", "model": "gemini-flash"},
            "verifier": {"provider": "openai", "model": "gpt-verifier"},
            "independent_agreement": True if mode == "live" else None,
        },
    }


def self_test() -> int:
    assert evaluate(valid_example())["status"] == "AUTO_APPROVED"
    mock = evaluate(valid_example("mock"))
    assert mock["status"] == "HUMAN_REVIEW"
    assert mock["reason_codes"] == ["MOCK_REQUIRES_HUMAN"]
    high_risk = valid_example()
    high_risk["risk"] = "high"
    high_risk_result = evaluate(high_risk)
    assert high_risk_result["status"] == "HUMAN_REVIEW"
    assert high_risk_result["reason_codes"] == ["RISK_REQUIRES_HUMAN"]
    no_lineage = valid_example()
    no_lineage["evidence"] = []
    assert evaluate(no_lineage)["status"] == "QUARANTINED"
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.proposal is None:
        parser.error("proposal is required unless --self-test is used")
    try:
        data = json.loads(args.proposal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "QUARANTINED", "errors": [str(exc)]}, indent=2))
        return 2
    result = evaluate(data)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"AUTO_APPROVED", "HUMAN_REVIEW", "ABSTAINED"} else 1


if __name__ == "__main__":
    sys.exit(main())
