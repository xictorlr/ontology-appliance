#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../create_apphosting_backend.sh
source "$repo_root/scripts/create_apphosting_backend.sh"

GCP_PROJECT_ID="ontology-appliance-dev-test"
APPHOSTING_SERVICE_ACCOUNT="oa-dev-apphosting@ontology-appliance-dev-test.iam.gserviceaccount.com"
APPHOSTING_WEB_APP_ID="1:123456789:web:abcdef012345"
backend_id="ontology-appliance-web"
region="europe-west4"
repository="xictorlr/ontology-appliance"
branch="main"
root_directory="apps/web"
expected_sha="0123456789abcdef0123456789abcdef01234567"
repository_resource="projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance"
apply_changes="true"
CONFIRM_GCP_PROJECT_ID="$GCP_PROJECT_ID"
CONFIRM_APPHOSTING_GIT_SHA="$expected_sha"

backend_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web","servingLocality":"REGIONAL_STRICT","serviceAccount":"oa-dev-apphosting@ontology-appliance-dev-test.iam.gserviceaccount.com","appId":"1:123456789:web:abcdef012345","uri":"https://ontology-appliance-web--ontology-appliance-dev-test.europe-west4.hosted.app","codebase":{"rootDirectory":"apps/web","repository":"projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance"}}'
traffic_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/backends/ontology-appliance-web/traffic","rolloutPolicy":{"codebaseBranch":"main","disabled":false}}'
repository_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance","cloneUri":"https://github.com/xictorlr/ontology-appliance.git"}'
github_repository_json='{"nameWithOwner":"xictorlr/ontology-appliance","isPrivate":true}'
github_ref_json='{"ref":"refs/heads/main","object":{"type":"commit","sha":"0123456789abcdef0123456789abcdef01234567"}}'
branch_protection_json='{"required_status_checks":{"strict":true,"contexts":["web-and-functions","semantic-gateway","contracts-skills-infra"]},"enforce_admins":{"enabled":true},"required_pull_request_reviews":{"required_approving_review_count":1,"require_last_push_approval":true},"required_linear_history":{"enabled":true},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":false},"required_conversation_resolution":{"enabled":true}}'

validate_inputs
verify_branch_protection "$branch_protection_json"
verify_github_ref "$github_ref_json"
verify_backend "$backend_json" "$traffic_json" "$repository_json" "$github_repository_json"

jq -e \
  --arg repository "$repository_resource" \
  --arg account "$APPHOSTING_SERVICE_ACCOUNT" \
  --arg app_id "$APPHOSTING_WEB_APP_ID" \
  '.servingLocality == "REGIONAL_STRICT" and
   .codebase.repository == $repository and
   .codebase.rootDirectory == "apps/web" and
   .serviceAccount == $account and
   .appId == $app_id' \
  >/dev/null <<<"$(backend_payload)"
jq -e --arg sha "$expected_sha" '.source.codebase.commit == $sha' >/dev/null <<<"$(build_payload)"
jq -e \
  --arg build "$(backend_resource_name)/builds/$(build_id_for_sha)" \
  '.build == $build' >/dev/null <<<"$(rollout_payload)"
jq -e \
  '.rolloutPolicy.codebaseBranch == "main" and .rolloutPolicy.disabled == false' \
  >/dev/null <<<"$(traffic_payload false)"

backend_request_id="$(request_id_for_sha backend)"
build_request_id="$(request_id_for_sha build)"
[[ "$backend_request_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$ ]]
[[ "$backend_request_id" != "$build_request_id" ]]
[[ "$(build_id_for_sha)" == "build-0123456789ab" ]]
[[ "$(rollout_id_for_sha)" == "rollout-0123456789ab" ]]

ssh_repository_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance","cloneUri":"git@github.com:XictorLR/Ontology-Appliance.git"}'
verify_backend "$backend_json" "$traffic_json" "$ssh_repository_json" "$github_repository_json"

expect_rejection() {
  local description="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "Expected rejection: $description" >&2
    exit 1
  fi
}

wrong_locality_json="$(jq '.servingLocality = "GLOBAL_ACCESS"' <<<"$backend_json")"
expect_rejection "non-strict App Hosting locality" \
  verify_backend "$wrong_locality_json" "$traffic_json" "$repository_json" "$github_repository_json"

missing_web_app_json="$(jq 'del(.appId)' <<<"$backend_json")"
expect_rejection "backend without its Terraform-managed Web App" \
  verify_backend "$missing_web_app_json" "$traffic_json" "$repository_json" "$github_repository_json"

wrong_uri_json="$(jq '.uri = "https://unexpected.example"' <<<"$backend_json")"
expect_rejection "backend URI drift" \
  verify_backend "$wrong_uri_json" "$traffic_json" "$repository_json" "$github_repository_json"

unprotected_branch_json="$(jq '.required_pull_request_reviews.required_approving_review_count = 0' <<<"$branch_protection_json")"
expect_rejection "main without an independent approval" \
  verify_branch_protection "$unprotected_branch_json"

last_push_unprotected_json="$(jq '.required_pull_request_reviews.require_last_push_approval = false' <<<"$branch_protection_json")"
expect_rejection "main allowing the last pusher to approve" \
  verify_branch_protection "$last_push_unprotected_json"

wrong_ref_json="$(jq '.object.sha = "ffffffffffffffffffffffffffffffffffffffff"' <<<"$github_ref_json")"
expect_rejection "GitHub main ref not equal to the pinned SHA" \
  verify_github_ref "$wrong_ref_json"

wrong_branch_json="$(jq '.rolloutPolicy.codebaseBranch = "release"' <<<"$traffic_json")"
expect_rejection "automatic rollout branch drift" \
  verify_backend "$backend_json" "$wrong_branch_json" "$repository_json" "$github_repository_json"

disabled_rollout_json="$(jq '.rolloutPolicy.disabled = true' <<<"$traffic_json")"
expect_rejection "disabled automatic rollouts after success" \
  verify_backend "$backend_json" "$disabled_rollout_json" "$repository_json" "$github_repository_json"

wrong_repository_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/other","cloneUri":"https://github.com/example/other.git"}'
expect_rejection "Developer Connect resource drift" \
  verify_backend "$backend_json" "$traffic_json" "$wrong_repository_json" "$github_repository_json"

other_repository_json='{"name":"projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance","cloneUri":"https://github.com/example/other.git"}'
expect_rejection "connected GitHub repository drift" \
  verify_backend "$backend_json" "$traffic_json" "$other_repository_json" "$github_repository_json"

expect_rejection "mutation without the explicit apply guard" \
  bash -c '
    set -euo pipefail
    source "$1"
    GCP_PROJECT_ID="ontology-appliance-dev-test"
    APPHOSTING_SERVICE_ACCOUNT="oa-dev-apphosting@ontology-appliance-dev-test.iam.gserviceaccount.com"
    APPHOSTING_WEB_APP_ID="1:123456789:web:abcdef012345"
    expected_sha="0123456789abcdef0123456789abcdef01234567"
    repository_resource="projects/ontology-appliance-dev-test/locations/europe-west4/connections/firebase-app-hosting-github/gitRepositoryLinks/ontology-appliance"
    apply_changes="false"
    validate_inputs
  ' _ "$repo_root/scripts/create_apphosting_backend.sh"

# A 404 must survive both command substitution and the optional-resource helper;
# otherwise idempotent creation paths can silently return success.
api_request() { return 44; }
if get_optional_resource "https://example.invalid/resource"; then
  echo "Expected optional resource lookup to preserve HTTP 404." >&2
  exit 1
else
  [[ "$?" == "44" ]]
fi

echo "App Hosting provisioning guardrail tests passed."
