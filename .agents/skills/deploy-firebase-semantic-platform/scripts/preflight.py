#!/usr/bin/env python3
"""Check local toolchain versions required to deploy the semantic platform."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

VERSION = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


@dataclass(frozen=True)
class Requirement:
    command: tuple[str, ...]
    minimum: tuple[int, int, int]
    maximum_major: int | None = None
    required: bool = True


REQUIREMENTS = {
    "node": Requirement(("node", "--version"), (22, 0, 0), maximum_major=22),
    "npm": Requirement(("npm", "--version"), (10, 0, 0)),
    "pnpm": Requirement(("pnpm", "--version"), (9, 0, 0)),
    "firebase": Requirement(("firebase", "--version"), (14, 0, 0)),
    "gcloud": Requirement(("gcloud", "--version"), (500, 0, 0)),
    "git": Requirement(("git", "--version"), (2, 39, 0)),
    "python3": Requirement(("python3", "--version"), (3, 12, 0)),
    "terraform": Requirement(("terraform", "--version"), (1, 8, 0)),
    "java": Requirement(("java", "-version"), (21, 0, 0)),
    "docker": Requirement(("docker", "--version"), (24, 0, 0), required=False),
}


def parse_version(output: str) -> tuple[int, int, int] | None:
    match = VERSION.search(output)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def inspect(
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    results: dict[str, object] = {}
    ready = True
    for name, requirement in REQUIREMENTS.items():
        executable = requirement.command[0]
        path = which(executable)
        if not path:
            status = "missing" if requirement.required else "optional_missing"
            results[name] = {"status": status, "required": requirement.required}
            ready = ready and not requirement.required
            continue
        try:
            process = run(
                requirement.command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            raw = (process.stdout + "\n" + process.stderr).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            results[name] = {"status": "error", "required": requirement.required, "detail": str(exc)}
            ready = ready and not requirement.required
            continue
        version = parse_version(raw)
        valid = version is not None and version >= requirement.minimum
        if valid and requirement.maximum_major is not None:
            valid = version[0] <= requirement.maximum_major
        status = "ok" if valid else "unsupported"
        results[name] = {
            "status": status,
            "required": requirement.required,
            "version": ".".join(map(str, version)) if version else None,
            "minimum": ".".join(map(str, requirement.minimum)),
            "maximum_major": requirement.maximum_major,
        }
        ready = ready and (valid or not requirement.required)
    return {"ready": ready, "tools": results}


def self_test() -> int:
    versions = {
        "node": "v22.14.0",
        "npm": "10.9.0",
        "pnpm": "9.12.3",
        "firebase": "14.26.0",
        "gcloud": "Google Cloud SDK 536.0.1",
        "git": "git version 2.39.5",
        "python3": "Python 3.12.8",
        "terraform": "Terraform v1.14.9",
        "java": 'openjdk version "21.0.8"',
        "docker": "Docker version 28.4.0",
    }

    def fake_which(name: str) -> str:
        return f"/mock/{name}"

    def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=versions[command[0]], stderr="")

    result = inspect(fake_which, fake_run)
    assert result["ready"] is True
    versions["node"] = "v24.7.0"
    result = inspect(fake_which, fake_run)
    assert result["ready"] is False
    assert result["tools"]["node"]["status"] == "unsupported"
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    result = inspect()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
