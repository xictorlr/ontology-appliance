#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../verify_apphosting_rollout.sh
source "$repo_root/scripts/verify_apphosting_rollout.sh"

GCP_PROJECT_ID="ontology-appliance-dev-test"
backend_id="ontology-appliance-web"
region="europe-west4"
branch="main"
expected_sha="0123456789abcdef0123456789abcdef01234567"
repository_resource="projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance"
rollout_id="rollout-0123456789ab"

backend_name="projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web"
active_build="${backend_name}/builds/build-0123456789ab"
backend_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web","servingLocality":"GLOBAL_ACCESS","uri":"https://ontology-appliance-web--ontology-appliance-dev-test.europe-west4.hosted.app","codebase":{"rootDirectory":"apps/web","repository":"projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance"}}'
traffic_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web/traffic","reconciling":false,"rolloutPolicy":{"codebaseBranch":"main","disabled":false},"current":{"splits":[{"build":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web/builds/build-0123456789ab","percent":100}]}}'
build_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web/builds/build-0123456789ab","state":"READY","source":{"codebase":{"repository":"projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance","commit":"0123456789abcdef0123456789abcdef01234567","hash":"0123456789abcdef0123456789abcdef01234567"}}}'
rollout_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web/rollouts/rollout-0123456789ab","state":"SUCCEEDED","build":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web/builds/build-0123456789ab"}'

validate_inputs
verify_exact_rollout "$backend_json" "$traffic_json" "$build_json" "$rollout_json"

expect_rejection() {
  local description="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "Expected rejection: $description" >&2
    exit 1
  fi
}

wrong_sha_json="$(jq '.source.codebase.hash = "ffffffffffffffffffffffffffffffffffffffff"' <<<"$build_json")"
expect_rejection "active build SHA drift" \
  verify_exact_rollout "$backend_json" "$traffic_json" "$wrong_sha_json" "$rollout_json"

requested_only_json="$(jq 'del(.source.codebase.hash)' <<<"$build_json")"
expect_rejection "requested commit without a resolved hash" \
  verify_exact_rollout "$backend_json" "$traffic_json" "$requested_only_json" "$rollout_json"

extra_split_json="$(jq '.current.splits += [{"build":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web/builds/other-build","percent":0}]' <<<"$traffic_json")"
expect_rejection "more than one traffic split" \
  verify_exact_rollout "$backend_json" "$extra_split_json" "$build_json" "$rollout_json"

partial_traffic_json="$(jq '.current.splits[0].percent = 99' <<<"$traffic_json")"
expect_rejection "less than 100 percent traffic" \
  verify_exact_rollout "$backend_json" "$partial_traffic_json" "$build_json" "$rollout_json"

reconciling_json="$(jq '.reconciling = true' <<<"$traffic_json")"
expect_rejection "traffic still reconciling" \
  verify_exact_rollout "$backend_json" "$reconciling_json" "$build_json" "$rollout_json"

disabled_json="$(jq '.rolloutPolicy.disabled = true' <<<"$traffic_json")"
expect_rejection "automatic main rollout left disabled" \
  verify_exact_rollout "$backend_json" "$disabled_json" "$build_json" "$rollout_json"

building_json="$(jq '.state = "BUILDING"' <<<"$build_json")"
expect_rejection "active build not READY" \
  verify_exact_rollout "$backend_json" "$traffic_json" "$building_json" "$rollout_json"

failed_rollout_json="$(jq '.state = "FAILED"' <<<"$rollout_json")"
expect_rejection "pinned rollout not SUCCEEDED" \
  verify_exact_rollout "$backend_json" "$traffic_json" "$build_json" "$failed_rollout_json"

other_rollout_build_json="$(jq '.build = "projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web/builds/other-build"' <<<"$rollout_json")"
expect_rejection "pinned rollout does not own active build" \
  verify_exact_rollout "$backend_json" "$traffic_json" "$build_json" "$other_rollout_build_json"

unsupported_locality_backend_json="$(jq '.servingLocality = "REGIONAL_STRICT"' <<<"$backend_json")"
expect_rejection "backend locality not currently supported" \
  verify_exact_rollout "$unsupported_locality_backend_json" "$traffic_json" "$build_json" "$rollout_json"

other_repo_build_json="$(jq '.source.codebase.repository = "projects/ontology-appliance-dev-test/locations/europe-west4/connections/other/gitRepositoryLinks/other"' <<<"$build_json")"
expect_rejection "resolved build repository drift" \
  verify_exact_rollout "$backend_json" "$traffic_json" "$other_repo_build_json" "$rollout_json"

[[ "$active_build" == "$(jq -r '.current.splits[0].build' <<<"$traffic_json")" ]]
echo "App Hosting exact-rollout verification tests passed."
