#!/usr/bin/env bash
set -euo pipefail

repository="${GITHUB_REPOSITORY:-xictorlr/ontology-appliance}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
policy_file="${repo_root}/infra/github/main-branch-protection.json"

[[ "$repository" =~ ^[^/[:space:]]+/[^/[:space:]]+$ ]] || {
  echo "GITHUB_REPOSITORY must use the owner/repository form." >&2
  exit 2
}
jq -e . "$policy_file" >/dev/null

gh api --method PUT "repos/${repository}/branches/main/protection" \
  --input "$policy_file" --silent
protection="$(gh api "repos/${repository}/branches/main/protection")"
if ! jq -e '
  .required_status_checks.strict == true and
  (.required_status_checks.contexts | index("web-and-functions") != null) and
  (.required_status_checks.contexts | index("semantic-gateway") != null) and
  (.required_status_checks.contexts | index("contracts-skills-infra") != null) and
  .enforce_admins.enabled == true and
  .required_pull_request_reviews.required_approving_review_count >= 1 and
  .required_pull_request_reviews.require_last_push_approval == true and
  .required_linear_history.enabled == true and
  .allow_force_pushes.enabled == false and
  .allow_deletions.enabled == false and
  .required_conversation_resolution.enabled == true
' >/dev/null <<<"$protection"; then
  echo "GitHub main branch protection does not match the required CI gate." >&2
  exit 1
fi

echo "Protected ${repository}:main with required CI checks, independent review, and no direct/force pushes."
