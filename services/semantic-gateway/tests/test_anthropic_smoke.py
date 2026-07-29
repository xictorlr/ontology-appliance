from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_smoke_module() -> ModuleType:
    script = Path(__file__).parents[1] / "scripts" / "smoke_anthropic_verifier.py"
    spec = importlib.util.spec_from_file_location("anthropic_smoke", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_file_loader_accepts_only_allowlisted_settings(tmp_path, monkeypatch) -> None:
    smoke = _load_smoke_module()
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "VERIFIER_PROVIDER=anthropic\n"
        "ANTHROPIC_API_KEY='test-only-key'\n"
        "UNRELATED_SECRET=must-not-be-loaded\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    for name in ("VERIFIER_PROVIDER", "ANTHROPIC_API_KEY", "UNRELATED_SECRET"):
        # delenv on a missing name records nothing to restore, so the loader's
        # direct os.environ writes would leak into later tests; setenv first
        # guarantees monkeypatch removes the name again at teardown.
        monkeypatch.setenv(name, "teardown-guard")
        monkeypatch.delenv(name)

    smoke._load_env_file(env_file)

    assert os.environ["VERIFIER_PROVIDER"] == "anthropic"
    assert os.environ["ANTHROPIC_API_KEY"] == "test-only-key"
    assert "UNRELATED_SECRET" not in os.environ


@pytest.mark.parametrize(
    "contents",
    [
        "VERIFIER_PROVIDER=anthropic\nVERIFIER_PROVIDER=mock\n",
        "ANTHROPIC_API_KEY=test-key\nANTHROPIC_API_KEY=second-key\n",
    ],
)
def test_env_file_loader_rejects_duplicate_allowlisted_settings(
    tmp_path, monkeypatch, contents: str
) -> None:
    smoke = _load_smoke_module()
    env_file = tmp_path / ".env.local"
    env_file.write_text(contents, encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.delenv("VERIFIER_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValueError, match="duplicate env assignment"):
        smoke._load_env_file(env_file)
    assert "VERIFIER_PROVIDER" not in os.environ
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_env_file_loader_rejects_broad_permissions(tmp_path) -> None:
    smoke = _load_smoke_module()
    env_file = tmp_path / ".env.local"
    env_file.write_text("ANTHROPIC_API_KEY=test-key\n", encoding="utf-8")
    env_file.chmod(0o640)

    with pytest.raises(ValueError, match="chmod 600"):
        smoke._load_env_file(env_file)


def test_paid_confirmation_is_checked_before_env_file_access(tmp_path, capsys) -> None:
    smoke = _load_smoke_module()
    missing_file = tmp_path / "missing.env.local"

    with pytest.raises(SystemExit) as exc_info:
        smoke.main(["--env-file", str(missing_file)])

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "refusing network access without --confirm-paid-call" in stderr
    assert "cannot open env file" not in stderr


def test_confirmed_smoke_invokes_exactly_one_verification_without_exposing_key(
    monkeypatch, capsys
) -> None:
    smoke = _load_smoke_module()
    gateway = smoke._gateway_verification_module()
    calls = 0
    events: list[str] = []

    truststore_module = ModuleType("truststore")

    def inject_into_ssl() -> None:
        events.append("truststore")

    truststore_module.inject_into_ssl = inject_into_ssl

    def deferred_gateway_import():
        assert events == ["truststore"]
        events.append("gateway")
        return gateway

    def fake_verify(_verifier, proposal):
        nonlocal calls
        calls += 1
        events.append("verify")
        assert proposal.proposal_id == "anthropic-smoke-synthetic-1"
        return SimpleNamespace(
            provider="anthropic",
            model="claude-sonnet-5",
            response_id="msg_mocked",
            verdict="ABSTAINED",
            refusal=False,
            latency_ms=12,
            input_tokens=20,
            output_tokens=8,
        )

    monkeypatch.setenv("VERIFIER_PROVIDER", "anthropic")
    monkeypatch.delenv("OPENAI_VERIFIER_MODE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-secret-that-must-not-appear")
    monkeypatch.setitem(sys.modules, "truststore", truststore_module)
    monkeypatch.setattr(smoke, "_gateway_verification_module", deferred_gateway_import)
    monkeypatch.setattr(gateway.AnthropicMessagesVerifier, "verify", fake_verify)

    assert smoke.main(["--use-system-truststore", "--confirm-paid-call"]) == 0
    assert calls == 1
    assert events == ["truststore", "gateway", "verify"]
    rendered = capsys.readouterr().out
    assert "test-secret-that-must-not-appear" not in rendered
    assert json.loads(rendered) == {
        "inputTokens": 20,
        "latencyMs": 12,
        "model": "claude-sonnet-5",
        "outputTokens": 8,
        "provider": "anthropic",
        "refusal": False,
        "responseId": "msg_mocked",
        "verdict": "ABSTAINED",
    }
