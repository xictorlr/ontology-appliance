#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cd "$repo_root"

repository="${GITHUB_REPOSITORY:-xictorlr/ontology-appliance}"
environment="${GITHUB_ENVIRONMENT:-development}"
publication_environment="${GITHUB_PUBLICATION_ENVIRONMENT:-semantic-publication}"
rollback_environment="${GITHUB_ROLLBACK_ENVIRONMENT:-semantic-rollback}"
reviewer_login="${GITHUB_REVIEWER_LOGIN:-${repository%%/*}}"
publication_reviewer_login="${GITHUB_PUBLICATION_REVIEWER_LOGIN:-$reviewer_login}"
rollback_reviewer_login="${GITHUB_ROLLBACK_REVIEWER_LOGIN:-$publication_reviewer_login}"
configure_mode="${CONFIGURE_MODE:-complete}"
terraform_dir="infra/terraform/environments/dev"

case "$configure_mode" in
  bootstrap | complete) ;;
  *) echo "CONFIGURE_MODE must be bootstrap or complete." >&2; exit 2 ;;
esac
if [[ "$configure_mode" == "complete" ]]; then
  : "${APP_HOSTING_URL:?Set APP_HOSTING_URL to the deployed App Hosting backend URL.}"
  [[ "$APP_HOSTING_URL" == https://* ]] || {
    echo "APP_HOSTING_URL must use HTTPS." >&2
    exit 2
  }
fi

project_id="$(terraform -chdir="$terraform_dir" output -raw project_id)"
terraform_apphosting_url="$(terraform -chdir="$terraform_dir" output -raw apphosting_url)"
firebase_web_app_id="$(terraform -chdir="$terraform_dir" output -raw firebase_web_app_id)"
provider="$(terraform -chdir="$terraform_dir" output -raw github_workload_identity_provider)"
publisher_provider="$(terraform -chdir="$terraform_dir" output -raw github_publisher_workload_identity_provider)"
rollback_provider="$(terraform -chdir="$terraform_dir" output -raw github_rollback_workload_identity_provider)"
rollout_provider="$(terraform -chdir="$terraform_dir" output -raw github_semantic_rollout_workload_identity_provider)"
image="$(terraform -chdir="$terraform_dir" output -raw artifact_registry_image)"
input_bucket="$(terraform -chdir="$terraform_dir" output -raw input_bucket_name)"
artifact_bucket="$(terraform -chdir="$terraform_dir" output -raw artifact_bucket_name)"
accounts="$(terraform -chdir="$terraform_dir" output -json runtime_service_accounts)"

ci_account="$(jq -r '.ci' <<<"$accounts")"
gateway_account="$(jq -r '.semantic' <<<"$accounts")"
apphosting_account="$(jq -r '.apphosting' <<<"$accounts")"
functions_account="$(jq -r '.functions' <<<"$accounts")"
publisher_account="$(jq -r '.publisher' <<<"$accounts")"

for value in "$project_id" "$terraform_apphosting_url" "$firebase_web_app_id" \
  "$provider" "$publisher_provider" "$rollback_provider" \
  "$rollout_provider" "$image" "$input_bucket" "$artifact_bucket" "$ci_account" \
  "$gateway_account" "$apphosting_account" "$functions_account" "$publisher_account"; do
  if [[ -z "$value" || "$value" == "null" ]]; then
    echo "A required Terraform output is empty. Apply the reviewed dev plan first." >&2
    exit 1
  fi
done
if [[ "$configure_mode" == "complete" && "$APP_HOSTING_URL" != "$terraform_apphosting_url" ]]; then
  echo "APP_HOSTING_URL does not match the Terraform-authorized App Hosting URL $terraform_apphosting_url." >&2
  exit 1
fi

reviewer_id="$(gh api "users/${reviewer_login}" --jq '.id')"
publication_reviewer_id="$(gh api "users/${publication_reviewer_login}" --jq '.id')"
rollback_reviewer_id="$(gh api "users/${rollback_reviewer_login}" --jq '.id')"

configure_environment() {
  local name="$1"
  local reviewer="$2"
  local prevent_self_review="$3"
  local policy
  policy="$(jq -n \
    --argjson reviewer_id "$reviewer" \
    --argjson prevent_self_review "$prevent_self_review" \
    '{wait_timer: 0, prevent_self_review: $prevent_self_review, reviewers: [{type: "User", id: $reviewer_id}], deployment_branch_policy: {protected_branches: false, custom_branch_policies: true}}')"
  gh api --method PUT "repos/${repository}/environments/${name}" \
    --input - --silent <<<"$policy"
  if ! gh api "repos/${repository}/environments/${name}/deployment-branch-policies" \
    --jq '.branch_policies[].name' | grep -Fxq main; then
    gh api --method POST \
      "repos/${repository}/environments/${name}/deployment-branch-policies" \
      -f name=main -f type=branch --silent
  fi
}

set_variable() {
  gh variable set "$1" --body "$2" --env "$3" --repo "$repository"
}

GITHUB_REPOSITORY="$repository" scripts/configure_github_branch_protection.sh
configure_environment "$environment" "$reviewer_id" false
set_variable GCP_PROJECT_ID "$project_id" "$environment"
set_variable GCP_WORKLOAD_IDENTITY_PROVIDER "$provider" "$environment"
set_variable GCP_DEPLOY_SERVICE_ACCOUNT "$ci_account" "$environment"
set_variable ARTIFACT_REGISTRY_IMAGE "$image" "$environment"
set_variable GATEWAY_SERVICE_ACCOUNT "$gateway_account" "$environment"
set_variable APPHOSTING_SERVICE_ACCOUNT "$apphosting_account" "$environment"
set_variable APPHOSTING_WEB_APP_ID "$firebase_web_app_id" "$environment"
set_variable FUNCTIONS_SERVICE_ACCOUNT "$functions_account" "$environment"
set_variable INPUT_BUCKET "$input_bucket" "$environment"
set_variable ARTIFACT_BUCKET "$artifact_bucket" "$environment"
if [[ "$configure_mode" == "complete" ]]; then
  set_variable APP_HOSTING_URL "$APP_HOSTING_URL" "$environment"
fi

configure_environment "$publication_environment" "$publication_reviewer_id" true
set_variable GCP_PROJECT_ID "$project_id" "$publication_environment"
set_variable GCP_PUBLISHER_WORKLOAD_IDENTITY_PROVIDER "$publisher_provider" "$publication_environment"
set_variable GCP_SEMANTIC_ROLLOUT_WORKLOAD_IDENTITY_PROVIDER "$rollout_provider" "$publication_environment"
set_variable PUBLISHER_SERVICE_ACCOUNT "$publisher_account" "$publication_environment"
set_variable GCP_DEPLOY_SERVICE_ACCOUNT "$ci_account" "$publication_environment"
set_variable ARTIFACT_BUCKET "$artifact_bucket" "$publication_environment"
set_variable GATEWAY_SERVICE oa-dev-semantic-gateway "$publication_environment"

configure_environment "$rollback_environment" "$rollback_reviewer_id" true
set_variable GCP_PROJECT_ID "$project_id" "$rollback_environment"
set_variable GCP_ROLLBACK_WORKLOAD_IDENTITY_PROVIDER "$rollback_provider" "$rollback_environment"
set_variable GCP_SEMANTIC_ROLLOUT_WORKLOAD_IDENTITY_PROVIDER "$rollout_provider" "$rollback_environment"
set_variable PUBLISHER_SERVICE_ACCOUNT "$publisher_account" "$rollback_environment"
set_variable GCP_DEPLOY_SERVICE_ACCOUNT "$ci_account" "$rollback_environment"
set_variable ARTIFACT_BUCKET "$artifact_bucket" "$rollback_environment"
set_variable GATEWAY_SERVICE oa-dev-semantic-gateway "$rollback_environment"

if [[ "$configure_mode" == "complete" ]]; then
  gh variable set CLOUD_DEPLOY_ENABLED --body true --repo "$repository"
  echo "Configured complete deployment, publication, and rollback environments for ${repository}."
else
  gh variable set CLOUD_DEPLOY_ENABLED --body false --repo "$repository"
  echo "Configured bootstrap credentials with CLOUD_DEPLOY_ENABLED=false."
  echo "Run the manual deploy-dev bootstrap, create App Hosting, then rerun with CONFIGURE_MODE=complete and APP_HOSTING_URL set."
fi

if [[ "$publication_reviewer_login" == "${repository%%/*}" ]]; then
  echo "Warning: publication remains fail-closed for owner-triggered runs until an independent GITHUB_PUBLICATION_REVIEWER_LOGIN is configured." >&2
fi
