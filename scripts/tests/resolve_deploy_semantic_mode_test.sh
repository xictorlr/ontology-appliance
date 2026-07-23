#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
suite_root="$(mktemp -d "${TMPDIR:-/tmp}/oa-semantic-mode-test.XXXXXX")"
trap 'rm -rf "$suite_root"' EXIT

mkdir -p "$suite_root/bin"
cat >"$suite_root/bin/gcloud" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == storage\ objects\ describe\ gs://oa-dev-artifacts/tenants/demo-bank/ontology/active.json* ]]; then
  [[ "${MOCK_POINTER_MODE:-absent}" == "present" ]] || exit 92
  printf '%s\n' '42'
  exit 0
fi
[[ "$*" == storage\ objects\ list\ gs://oa-dev-artifacts/tenants/demo-bank/ontology/active.json* ]] || exit 90
case "${MOCK_POINTER_MODE:-absent}" in
  absent) ;;
  present) printf '%s\n' 'tenants/demo-bank/ontology/active.json' ;;
  multiple) printf '%s\n' 'tenants/demo-bank/ontology/active.json' 'unexpected' ;;
  error) exit 7 ;;
  *) exit 91 ;;
esac
MOCK
chmod +x "$suite_root/bin/gcloud"

run_resolver() {
  local output_file="$1"
  shift
  env \
    PATH="$suite_root/bin:$PATH" \
    ARTIFACT_BUCKET=oa-dev-artifacts \
    DEPLOYMENT_SCOPE=full \
    GCP_PROJECT_ID=ontology-appliance-dev-test \
    GITHUB_ENV="$output_file" \
    "$@" \
    bash "$repo_root/scripts/resolve_deploy_semantic_mode.sh"
}

absent_env="$suite_root/absent.env"
run_resolver "$absent_env" MOCK_POINTER_MODE=absent >/dev/null
grep -Fqx 'SEMANTIC_MODE=candidate' "$absent_env"
grep -Fqx 'EXPECTED_PUBLICATION_STATE=CANDIDATE' "$absent_env"
grep -Fqx 'ACTIVE_POINTER_GENERATION=' "$absent_env"

present_env="$suite_root/present.env"
run_resolver "$present_env" MOCK_POINTER_MODE=present >/dev/null
grep -Fqx 'SEMANTIC_MODE=published' "$present_env"
grep -Fqx 'EXPECTED_PUBLICATION_STATE=PUBLISHED' "$present_env"
grep -Fqx 'ACTIVE_POINTER_GENERATION=42' "$present_env"

manual_published_env="$suite_root/manual-published.env"
run_resolver "$manual_published_env" \
  MOCK_POINTER_MODE=present REQUESTED_SEMANTIC_MODE=published >/dev/null
grep -Fqx 'SEMANTIC_MODE=published' "$manual_published_env"

if run_resolver "$suite_root/no-pointer.env" \
  MOCK_POINTER_MODE=absent REQUESTED_SEMANTIC_MODE=published >/dev/null 2>&1; then
  echo "Expected published mode without an active pointer to fail." >&2
  exit 1
fi
if run_resolver "$suite_root/downgrade.env" \
  MOCK_POINTER_MODE=present REQUESTED_SEMANTIC_MODE=candidate >/dev/null 2>&1; then
  echo "Expected a published-to-candidate downgrade to fail." >&2
  exit 1
fi
if run_resolver "$suite_root/lookup-error.env" \
  MOCK_POINTER_MODE=error >/dev/null 2>&1; then
  echo "Expected an active-pointer lookup error to fail closed." >&2
  exit 1
fi
if run_resolver "$suite_root/multiple.env" \
  MOCK_POINTER_MODE=multiple >/dev/null 2>&1; then
  echo "Expected an unexpected pointer listing to fail closed." >&2
  exit 1
fi
backend_env="$suite_root/backend.env"
env \
  PATH="$suite_root/bin:$PATH" \
  ARTIFACT_BUCKET=oa-dev-artifacts \
  DEPLOYMENT_SCOPE=backend \
  GCP_PROJECT_ID=ontology-appliance-dev-test \
  REQUESTED_SEMANTIC_MODE=candidate \
  MOCK_POINTER_MODE=absent \
  GITHUB_ENV="$backend_env" \
  bash "$repo_root/scripts/resolve_deploy_semantic_mode.sh" >/dev/null
grep -Fqx 'SEMANTIC_MODE=candidate' "$backend_env"
if env \
  PATH="$suite_root/bin:$PATH" \
  ARTIFACT_BUCKET=oa-dev-artifacts \
  DEPLOYMENT_SCOPE=backend \
  GCP_PROJECT_ID=ontology-appliance-dev-test \
  REQUESTED_SEMANTIC_MODE=published \
  MOCK_POINTER_MODE=present \
  GITHUB_ENV="$suite_root/backend-published.env" \
  bash "$repo_root/scripts/resolve_deploy_semantic_mode.sh" >/dev/null 2>&1; then
  echo "Expected backend published mode to fail." >&2
  exit 1
fi
if env \
  PATH="$suite_root/bin:$PATH" \
  ARTIFACT_BUCKET=oa-dev-artifacts \
  DEPLOYMENT_SCOPE=bootstrap \
  GCP_PROJECT_ID=ontology-appliance-dev-test \
  REQUESTED_SEMANTIC_MODE=published \
  MOCK_POINTER_MODE=present \
  GITHUB_ENV="$suite_root/bootstrap.env" \
  bash "$repo_root/scripts/resolve_deploy_semantic_mode.sh" >/dev/null 2>&1; then
  echo "Expected bootstrap published mode to fail." >&2
  exit 1
fi

echo "Semantic deployment mode tests passed."
