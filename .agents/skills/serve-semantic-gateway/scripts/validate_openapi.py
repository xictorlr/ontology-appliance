#!/usr/bin/env python3
"""Validate core Semantic Gateway requirements in an OpenAPI JSON/YAML document."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_PATHS = (
    "/v1/resolve",
    "/v1/context",
    "/v1/query",
    "/v1/explain",
    "/v1/validate",
    "/v1/sparql",
)
REQUIRED_SCHEMAS = {"ResponseEnvelope", "ProblemDetails"}


def validate(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["OpenAPI document must be a JSON object"]
    version = document.get("openapi")
    if not isinstance(version, str) or not version.startswith("3.1."):
        errors.append("openapi must be a 3.1.x version")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return errors + ["paths must be an object"]

    operation_ids: set[str] = set()
    root_security = document.get("security")
    for path in REQUIRED_PATHS:
        item = paths.get(path)
        if not isinstance(item, dict):
            errors.append(f"missing path: {path}")
            continue
        operation = item.get("post")
        if not isinstance(operation, dict):
            errors.append(f"{path} must define POST")
            continue
        operation_id = operation.get("operationId")
        if not isinstance(operation_id, str) or not operation_id:
            errors.append(f"{path} POST requires operationId")
        elif operation_id in operation_ids:
            errors.append(f"duplicate operationId: {operation_id}")
        else:
            operation_ids.add(operation_id)
        if not isinstance(operation.get("requestBody"), dict):
            errors.append(f"{path} POST requires requestBody")
        responses = operation.get("responses")
        if not isinstance(responses, dict) or "200" not in responses or "default" not in responses:
            errors.append(f"{path} POST requires 200 and default responses")
        security = operation.get("security", root_security)
        if not isinstance(security, list) or not security:
            errors.append(f"{path} POST requires security")

    sparql = paths.get("/v1/sparql", {}).get("post", {})
    if sparql.get("x-read-only") is not True:
        errors.append("/v1/sparql POST must set x-read-only: true")

    components = document.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        errors.append("components.schemas must be an object")
    else:
        missing = REQUIRED_SCHEMAS - set(schemas)
        if missing:
            errors.append(f"missing component schemas: {sorted(missing)}")
    return errors


def valid_example() -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for index, path in enumerate(REQUIRED_PATHS):
        operation: dict[str, Any] = {
            "operationId": f"semanticOperation{index}",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}},
            "responses": {"200": {"description": "OK"}, "default": {"description": "Problem"}},
        }
        if path == "/v1/sparql":
            operation["x-read-only"] = True
        paths[path] = {"post": operation}
    return {
        "openapi": "3.1.0",
        "security": [{"bearerAuth": []}],
        "paths": paths,
        "components": {"schemas": {"ResponseEnvelope": {}, "ProblemDetails": {}}},
    }


def self_test() -> int:
    assert validate(valid_example()) == []
    broken = valid_example()
    del broken["paths"]["/v1/explain"]
    broken["paths"]["/v1/sparql"]["post"]["x-read-only"] = False
    errors = validate(broken)
    assert any("/v1/explain" in error for error in errors)
    assert any("x-read-only" in error for error in errors)
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", type=Path, help="OpenAPI document encoded as JSON or YAML")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.document is None:
        parser.error("document is required unless --self-test is used")
    try:
        raw_document = args.document.read_text(encoding="utf-8")
    except OSError as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 2
    try:
        document = json.loads(raw_document)
    except json.JSONDecodeError:
        try:
            import yaml

            document = yaml.safe_load(raw_document)
        except (ImportError, yaml.YAMLError) as exc:
            print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
            return 2
    errors = validate(document)
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
