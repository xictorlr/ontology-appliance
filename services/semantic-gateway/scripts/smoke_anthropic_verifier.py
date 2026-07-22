"""Run exactly one explicitly confirmed paid Anthropic verifier request."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

_ALLOWED_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "OA_ANTHROPIC_VERIFIER_MODEL",
    "OA_ANTHROPIC_VERIFIER_PROMPT_VERSION",
    "OPENAI_VERIFIER_MODE",
    "VERIFIER_PROVIDER",
}
_MAX_ENV_FILE_BYTES = 64 * 1024


def _gateway_verification_module() -> ModuleType:
    # Deliberately deferred: when requested, system trust must be injected
    # before httpx and its TLS stack are imported by the gateway module.
    from ontology_appliance_gateway import verification

    return verification


def _inject_system_truststore(parser: argparse.ArgumentParser) -> None:
    try:
        import truststore
    except ImportError:
        parser.error(
            "--use-system-truststore requires the development dependency truststore>=0.10,<1"
        )
    try:
        truststore.inject_into_ssl()
    except Exception as exc:
        parser.error(f"could not initialize the system trust store: {exc}")


def _load_env_file(path: Path) -> None:
    """Load an allowlisted dotenv file without shell evaluation or interpolation."""

    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise ValueError(f"cannot open env file {path}: {exc.strerror}") from exc
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("env file must be a regular, non-symlink file")
    if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
        raise ValueError("env file must be owned by the current user")
    if file_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError("env file permissions are too broad; run chmod 600 on it")
    if file_stat.st_size > _MAX_ENV_FILE_BYTES:
        raise ValueError("env file exceeds the 64 KiB safety limit")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read env file {path}") from exc
    assignments: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ValueError(f"invalid env assignment at line {line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in _ALLOWED_ENV_NAMES:
            continue
        if name in assignments:
            raise ValueError(f"duplicate env assignment for {name} at line {line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError(f"invalid env value at line {line_number}")
        assignments[name] = value

    # Apply only after the complete file has passed validation, so a malformed
    # later line cannot leave a partially loaded credential configuration.
    for name, value in assignments.items():
        os.environ.setdefault(name, value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Send one synthetic semantic-verification request to Anthropic. "
            "This is a paid network call."
        )
    )
    parser.add_argument(
        "--confirm-paid-call",
        action="store_true",
        help="Confirm that exactly one paid Anthropic Messages request may be sent.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help=(
            "Explicitly load allowlisted settings from a chmod-600 .env.local file; "
            "the file is not opened before paid-call confirmation."
        ),
    )
    parser.add_argument(
        "--use-system-truststore",
        action="store_true",
        help=(
            "Verify TLS with the operating-system trust store (useful for managed "
            "corporate CAs); certificate verification remains enabled."
        ),
    )
    args = parser.parse_args(argv)
    if not args.confirm_paid_call:
        parser.error("refusing network access without --confirm-paid-call")
    if args.env_file is not None:
        try:
            _load_env_file(args.env_file)
        except ValueError as exc:
            parser.error(str(exc))

    if args.use_system_truststore:
        _inject_system_truststore(parser)
    gateway = _gateway_verification_module()

    try:
        verifier = gateway.verifier_from_env()
    except ValueError as exc:
        parser.error(str(exc))
    if not isinstance(verifier, gateway.AnthropicMessagesVerifier):
        parser.error("set VERIFIER_PROVIDER=anthropic before confirming the paid call")
    if not verifier.enabled:
        parser.error("ANTHROPIC_API_KEY is required in the process environment")

    decision = verifier.verify(
        gateway.SemanticProposal(
            proposalId="anthropic-smoke-synthetic-1",
            statement="synthetic_customer_id maps to the governed Customer Identifier concept",
            evidenceIds=["synthetic:schema:customer_id"],
            counterevidenceIds=[],
            risk=gateway.RiskLevel.LOW,
            modelDependent=True,
            generatorProvider="deterministic-smoke-fixture",
            generatorModel="fixture-generator-v1",
            promptVersion="anthropic-smoke-v1",
        )
    )
    # Deliberately omit prompts, rationale, headers, and credential material.
    print(
        json.dumps(
            {
                "provider": decision.provider,
                "model": decision.model,
                "responseId": decision.response_id,
                "verdict": decision.verdict,
                "refusal": decision.refusal,
                "latencyMs": decision.latency_ms,
                "inputTokens": decision.input_tokens,
                "outputTokens": decision.output_tokens,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
