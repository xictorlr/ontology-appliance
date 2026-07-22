#!/usr/bin/env bash
set -euo pipefail

failures=0

check() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "ok      $1"
  else
    echo "missing $1"
    failures=$((failures + 1))
  fi
}

for command_name in node pnpm python3 uv java firebase gcloud git gh jq curl terraform; do
  check "$command_name"
done

node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [[ "$node_major" != "22" ]]; then
  echo "invalid Node 22 is required by Functions and CI; found ${node_major}"
  failures=$((failures + 1))
fi

java_specification="$(java -XshowSettings:properties -version 2>&1 |
  awk -F= '/^[[:space:]]*java\.specification\.version[[:space:]]*=/{gsub(/[[:space:]]/, "", $2); print $2; exit}' || true)"
java_major="${java_specification#1.}"
if [[ ! "$java_major" =~ ^[0-9]+$ || "$java_major" -lt 21 ]]; then
  echo "invalid Java 21 or newer is required by Firebase emulators; found ${java_specification:-unknown}"
  failures=$((failures + 1))
fi

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  echo "ok      OpenAI verifier credential is present in the environment"
else
  echo "info    OpenAI verifier remains in safe deterministic mock mode"
fi

if [[ "$failures" -gt 0 ]]; then
  exit 1
fi
