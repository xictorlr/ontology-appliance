#!/usr/bin/env python3
"""Validate and rank semantic proposal candidates without approving them."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DIMENSIONS = ("lexical", "structural", "instance", "external", "model", "evidence_coverage")
WEIGHTS = {
    "lexical": 0.18,
    "structural": 0.24,
    "instance": 0.24,
    "external": 0.10,
    "model": 0.10,
    "evidence_coverage": 0.14,
}
RISKS = {"low", "medium", "high"}


def validate_candidate(candidate: Any, line: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(candidate, dict):
        return [f"line {line}: candidate must be a JSON object"]
    if not isinstance(candidate.get("proposal_id"), str) or not candidate.get("proposal_id", "").strip():
        errors.append(f"line {line}: proposal_id must be a non-empty string")
    if candidate.get("risk") not in RISKS:
        errors.append(f"line {line}: risk must be one of {sorted(RISKS)}")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list):
        errors.append(f"line {line}: evidence must be an array")
    confidence = candidate.get("confidence")
    if not isinstance(confidence, dict):
        errors.append(f"line {line}: confidence must be an object")
    else:
        for dimension in DIMENSIONS:
            score = confidence.get(dimension)
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
                errors.append(f"line {line}: confidence.{dimension} must be between 0 and 1")
    return errors


def rank(candidate: dict[str, Any]) -> dict[str, Any]:
    confidence = candidate["confidence"]
    score = sum(float(confidence[name]) * weight for name, weight in WEIGHTS.items())
    evidence_count = len(candidate["evidence"])
    if evidence_count == 0 or confidence["evidence_coverage"] < 0.25:
        route = "ABSTAINED"
        reason = "INSUFFICIENT_EVIDENCE"
    elif candidate["risk"] == "high":
        route = "PENDING_VERIFICATION"
        reason = "HIGH_RISK_REQUIRES_HUMAN_GATE"
    elif score < 0.55:
        route = "ABSTAINED"
        reason = "LOW_CONFIDENCE"
    else:
        route = "PENDING_VERIFICATION"
        reason = "READY_FOR_INDEPENDENT_VERIFICATION"
    result = dict(candidate)
    result["ranking_score"] = round(score, 6)
    result["status"] = route
    result["routing_reason"] = reason
    return result


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [str(exc)]
    for line_number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
            continue
        item_errors = validate_candidate(candidate, line_number)
        errors.extend(item_errors)
        if not item_errors:
            candidates.append(candidate)
    return candidates, errors


def self_test() -> int:
    strong = {
        "proposal_id": "p-1",
        "risk": "low",
        "evidence": [{"evidence_id": "e-1"}],
        "confidence": {name: 0.9 for name in DIMENSIONS},
    }
    ranked = rank(strong)
    assert ranked["status"] == "PENDING_VERIFICATION"
    assert "confidence" in ranked and ranked["ranking_score"] > 0.8
    weak = dict(strong)
    weak["proposal_id"] = "p-2"
    weak["evidence"] = []
    assert rank(weak)["status"] == "ABSTAINED"
    assert validate_candidate(strong, 1) == []
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="input JSONL")
    parser.add_argument("--output", type=Path, help="output JSONL; stdout when omitted")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.input is None:
        parser.error("input is required unless --self-test is used")
    candidates, errors = load_jsonl(args.input)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2), file=sys.stderr)
        return 2
    ranked = sorted((rank(candidate) for candidate in candidates), key=lambda item: item["ranking_score"], reverse=True)
    rendered = "".join(json.dumps(item, sort_keys=True) + "\n" for item in ranked)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
