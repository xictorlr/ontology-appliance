#!/usr/bin/env bash
set -euo pipefail

# Read-only proof that the App Hosting backend serves one exact Git commit.
# The verifier intentionally inspects the control-plane resources separately so
# a successful rollout name cannot mask traffic or resolved-source drift.

backend_id="${APPHOSTING_BACKEND_ID:-ontology-appliance-web}"
region="${APPHOSTING_REGION:-europe-west4}"
branch="${APPHOSTING_BRANCH:-main}"
expected_sha="${APPHOSTING_GIT_SHA:-}"
repository_resource="${APPHOSTING_REPOSITORY_RESOURCE:-}"
rollout_id="${APPHOSTING_ROLLOUT_ID:-}"
apphosting_api_origin="${APPHOSTING_API_ORIGIN:-https://firebaseapphosting.googleapis.com}"
access_token=""

backend_resource_name() {
  printf 'projects/%s/locations/%s/backends/%s\n' "$GCP_PROJECT_ID" "$region" "$backend_id"
}

validate_inputs() {
  : "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID to the App Hosting project.}"
  : "${expected_sha:?Set APPHOSTING_GIT_SHA to the exact deployed commit.}"
  : "${repository_resource:?Set APPHOSTING_REPOSITORY_RESOURCE to the exact Developer Connect GitRepositoryLink.}"

  [[ "$GCP_PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || {
    echo "GCP_PROJECT_ID must be a valid 6-30 character project ID." >&2
    return 1
  }
  [[ "$region" == "europe-west4" ]] || {
    echo "APPHOSTING_REGION must remain europe-west4." >&2
    return 1
  }
  [[ "$branch" == "main" ]] || {
    echo "APPHOSTING_BRANCH must remain main." >&2
    return 1
  }
  [[ "$backend_id" =~ ^[a-z][a-z0-9-]{0,28}[a-z0-9]$ ]] || {
    echo "APPHOSTING_BACKEND_ID must be a valid 2-30 character backend ID." >&2
    return 1
  }
  [[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || {
    echo "APPHOSTING_GIT_SHA must be an exact lowercase 40-character Git SHA." >&2
    return 1
  }
  [[ "$repository_resource" =~ ^projects/${GCP_PROJECT_ID}/locations/${region}/connections/[^/[:space:]]+/gitRepositoryLinks/[^/[:space:]]+$ ]] || {
    echo "APPHOSTING_REPOSITORY_RESOURCE must be a europe-west4 GitRepositoryLink in GCP_PROJECT_ID." >&2
    return 1
  }
  if [[ -z "$rollout_id" ]]; then
    rollout_id="rollout-${expected_sha:0:12}"
  fi
  [[ "$rollout_id" =~ ^[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] || {
    echo "APPHOSTING_ROLLOUT_ID is invalid." >&2
    return 1
  }
}

verify_exact_rollout() {
  local backend_json="$1"
  local traffic_json="$2"
  local build_json="$3"
  local rollout_json="$4"
  local expected_backend expected_traffic expected_rollout
  local backend_name locality backend_repository
  local traffic_name traffic_branch traffic_disabled reconciling split_count
  local active_build active_percent build_name build_state resolved_sha build_repository
  local rollout_name rollout_state rollout_build

  expected_backend="$(backend_resource_name)"
  expected_traffic="${expected_backend}/traffic"
  expected_rollout="${expected_backend}/rollouts/${rollout_id}"

  backend_name="$(jq -r '(.result // .).name // empty' <<<"$backend_json")"
  locality="$(jq -r '(.result // .).servingLocality // empty' <<<"$backend_json")"
  backend_repository="$(jq -r '(.result // .).codebase.repository // empty' <<<"$backend_json")"
  [[ "$backend_name" == "$expected_backend" ]] || {
    echo "App Hosting backend drift: expected $expected_backend, got ${backend_name:-missing}." >&2
    return 1
  }
  [[ "$locality" == "GLOBAL_ACCESS" ]] || {
    echo "App Hosting locality drift: GLOBAL_ACCESS is the currently supported App Hosting mode." >&2
    return 1
  }
  [[ "$backend_repository" == "$repository_resource" ]] || {
    echo "App Hosting backend repository drift." >&2
    return 1
  }

  traffic_name="$(jq -r '(.result // .).name // empty' <<<"$traffic_json")"
  traffic_branch="$(jq -r '(.result // .).rolloutPolicy.codebaseBranch // empty' <<<"$traffic_json")"
  traffic_disabled="$(jq -r '(.result // .).rolloutPolicy.disabled // false' <<<"$traffic_json")"
  reconciling="$(jq -r '(.result // .).reconciling // false' <<<"$traffic_json")"
  split_count="$(jq -r '((.result // .).current.splits // []) | length' <<<"$traffic_json")"
  active_build="$(jq -r '(.result // .).current.splits[0].build // empty' <<<"$traffic_json")"
  active_percent="$(jq -r '(.result // .).current.splits[0].percent // empty' <<<"$traffic_json")"
  [[ "$traffic_name" == "$expected_traffic" ]] || {
    echo "App Hosting traffic drift: expected $expected_traffic, got ${traffic_name:-missing}." >&2
    return 1
  }
  [[ "$traffic_branch" == "$branch" && "$traffic_disabled" == "false" ]] || {
    echo "App Hosting automatic rollout policy must watch protected main." >&2
    return 1
  }
  [[ "$reconciling" == "false" ]] || {
    echo "App Hosting traffic is still reconciling." >&2
    return 1
  }
  [[ "$split_count" == "1" && "$active_percent" == "100" ]] || {
    echo "App Hosting must route exactly 100 percent of traffic to one build." >&2
    return 1
  }
  [[ "$active_build" =~ ^${expected_backend}/builds/[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] || {
    echo "App Hosting active build is missing or belongs to another backend." >&2
    return 1
  }

  build_name="$(jq -r '(.result // .).name // empty' <<<"$build_json")"
  build_state="$(jq -r '(.result // .).state // empty' <<<"$build_json")"
  resolved_sha="$(jq -r '(.result // .).source.codebase.hash // empty' <<<"$build_json")"
  build_repository="$(jq -r '(.result // .).source.codebase.repository // empty' <<<"$build_json")"
  [[ "$build_name" == "$active_build" ]] || {
    echo "App Hosting build evidence does not match the active traffic split." >&2
    return 1
  }
  [[ "$build_state" == "READY" ]] || {
    echo "App Hosting active build is not READY." >&2
    return 1
  }
  [[ "$resolved_sha" == "$expected_sha" ]] || {
    echo "App Hosting active build resolves to ${resolved_sha:-missing}, not $expected_sha." >&2
    return 1
  }
  [[ "$build_repository" == "$repository_resource" ]] || {
    echo "App Hosting active build repository drift." >&2
    return 1
  }

  rollout_name="$(jq -r '(.result // .).name // empty' <<<"$rollout_json")"
  rollout_state="$(jq -r '(.result // .).state // empty' <<<"$rollout_json")"
  rollout_build="$(jq -r '(.result // .).build // empty' <<<"$rollout_json")"
  [[ "$rollout_name" == "$expected_rollout" ]] || {
    echo "App Hosting rollout drift: expected $expected_rollout, got ${rollout_name:-missing}." >&2
    return 1
  }
  [[ "$rollout_state" == "SUCCEEDED" ]] || {
    echo "App Hosting pinned rollout is not SUCCEEDED." >&2
    return 1
  }
  [[ "$rollout_build" == "$active_build" ]] || {
    echo "App Hosting pinned rollout is not the active build." >&2
    return 1
  }
}

api_get() {
  local resource_name="$1"
  curl \
    --fail \
    --silent \
    --show-error \
    --header "Authorization: Bearer ${access_token}" \
    --header 'Accept: application/json' \
    "${apphosting_api_origin%/}/v1beta/${resource_name}"
}

main() {
  local backend_name backend_json traffic_json active_build build_json rollout_json backend_url
  validate_inputs
  for command_name in curl gcloud jq; do
    command -v "$command_name" >/dev/null 2>&1 || {
      echo "Missing required command: $command_name" >&2
      return 1
    }
  done

  access_token="$(gcloud auth print-access-token)"
  backend_name="$(backend_resource_name)"
  backend_json="$(api_get "$backend_name")"
  traffic_json="$(api_get "${backend_name}/traffic")"
  active_build="$(jq -r '(.result // .).current.splits[0].build // empty' <<<"$traffic_json")"
  [[ -n "$active_build" ]] || {
    echo "App Hosting traffic has no active build." >&2
    return 1
  }
  build_json="$(api_get "$active_build")"
  rollout_json="$(api_get "${backend_name}/rollouts/${rollout_id}")"

  verify_exact_rollout "$backend_json" "$traffic_json" "$build_json" "$rollout_json"
  backend_url="$(jq -r '(.result // .).uri // empty' <<<"$backend_json")"
  echo "App Hosting exact-rollout proof passed."
  echo "APPHOSTING_GIT_SHA=$expected_sha"
  echo "APPHOSTING_ACTIVE_BUILD=$active_build"
  echo "APPHOSTING_ROLLOUT=${backend_name}/rollouts/${rollout_id}"
  [[ "$backend_url" == https://* ]] && echo "APP_HOSTING_URL=$backend_url"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
