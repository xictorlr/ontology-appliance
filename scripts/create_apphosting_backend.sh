#!/usr/bin/env bash
set -euo pipefail

# Reproducibly provisions the App Hosting control-plane resources. The exact
# protected GitHub repository must already be linked through the Firebase App
# Hosting GitHub App; this script consumes that explicit Developer Connect
# resource and never launches an interactive Firebase CLI flow.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_id="${APPHOSTING_BACKEND_ID:-ontology-appliance-web}"
region="${APPHOSTING_REGION:-europe-west4}"
gateway_secret="${GATEWAY_URL_SECRET:-oa-dev-semantic-gateway-url}"
repository="${GITHUB_REPOSITORY:-xictorlr/ontology-appliance}"
branch="${APPHOSTING_BRANCH:-main}"
root_directory="${APPHOSTING_ROOT_DIRECTORY:-apps/web}"
expected_sha="${APPHOSTING_GIT_SHA:-}"
repository_resource="${APPHOSTING_REPOSITORY_RESOURCE:-}"
apply_changes="${APPHOSTING_APPLY:-false}"
wait_timeout_seconds="${APPHOSTING_WAIT_TIMEOUT_SECONDS:-1800}"
poll_interval_seconds="${APPHOSTING_POLL_INTERVAL_SECONDS:-5}"
apphosting_api_origin="${APPHOSTING_API_ORIGIN:-https://firebaseapphosting.googleapis.com}"
developer_connect_api_origin="${DEVELOPER_CONNECT_API_ORIGIN:-https://developerconnect.googleapis.com}"
access_token=""

github_repository_from_clone_uri() {
  local clone_uri="$1"
  local repository_slug

  case "$clone_uri" in
    https://github.com/*)
      repository_slug="${clone_uri#https://github.com/}"
      ;;
    http://github.com/*)
      repository_slug="${clone_uri#http://github.com/}"
      ;;
    git://github.com/*)
      repository_slug="${clone_uri#git://github.com/}"
      ;;
    ssh://git@github.com/*)
      repository_slug="${clone_uri#ssh://git@github.com/}"
      ;;
    git@github.com:*)
      repository_slug="${clone_uri#git@github.com:}"
      ;;
    *)
      return 1
      ;;
  esac

  repository_slug="${repository_slug%/}"
  repository_slug="${repository_slug%.git}"
  repository_slug="${repository_slug%/}"
  [[ "$repository_slug" =~ ^[^/[:space:]]+/[^/[:space:]]+$ ]] || return 1
  printf '%s\n' "$repository_slug"
}

lowercase() {
  LC_ALL=C tr '[:upper:]' '[:lower:]'
}

backend_resource_name() {
  printf 'projects/%s/locations/%s/backends/%s\n' "$GCP_PROJECT_ID" "$region" "$backend_id"
}

build_id_for_sha() {
  printf 'build-%s\n' "${expected_sha:0:12}"
}

rollout_id_for_sha() {
  printf 'rollout-%s\n' "${expected_sha:0:12}"
}

# Derive stable, distinct RFC 4122-shaped request IDs from the immutable commit.
# Firebase uses these values only for request de-duplication; they are not secrets.
request_id_for_sha() {
  local discriminator="$1"
  local discriminator_hex
  case "$discriminator" in
    backend) discriminator_hex="1" ;;
    traffic-disable) discriminator_hex="2" ;;
    build) discriminator_hex="3" ;;
    rollout) discriminator_hex="4" ;;
    traffic-enable) discriminator_hex="5" ;;
    *) return 1 ;;
  esac
  printf '%s-%s-%s%s-%s-%s\n' \
    "${expected_sha:0:8}" \
    "${expected_sha:8:4}" \
    "$discriminator_hex" \
    "${expected_sha:13:3}" \
    "8${expected_sha:17:3}" \
    "${expected_sha:20:12}"
}

validate_inputs() {
  : "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID to the Terraform-created development project.}"
  : "${APPHOSTING_SERVICE_ACCOUNT:?Set APPHOSTING_SERVICE_ACCOUNT to the Terraform apphosting service-account output.}"
  : "${APPHOSTING_WEB_APP_ID:?Set APPHOSTING_WEB_APP_ID to the Terraform firebase_web_app_id output.}"
  : "${repository_resource:?Set APPHOSTING_REPOSITORY_RESOURCE to the existing Developer Connect GitRepositoryLink.}"
  : "${expected_sha:?Set APPHOSTING_GIT_SHA to the exact 40-character commit on main.}"

  [[ "$GCP_PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || {
    echo "GCP_PROJECT_ID must be a valid 6-30 character project ID." >&2
    return 1
  }
  [[ "$region" == "europe-west4" ]] || {
    echo "APPHOSTING_REGION must remain europe-west4." >&2
    return 1
  }
  [[ "$branch" == "main" ]] || {
    echo "APPHOSTING_BRANCH must remain main for the protected rollout contract." >&2
    return 1
  }
  [[ "$root_directory" == "apps/web" ]] || {
    echo "APPHOSTING_ROOT_DIRECTORY must remain apps/web." >&2
    return 1
  }
  [[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
    echo "GITHUB_REPOSITORY must use the owner/repository form." >&2
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
  [[ "$APPHOSTING_SERVICE_ACCOUNT" =~ ^[a-z][a-z0-9-]{2,28}@${GCP_PROJECT_ID}\.iam\.gserviceaccount\.com$ ]] || {
    echo "APPHOSTING_SERVICE_ACCOUNT must be a service account in GCP_PROJECT_ID." >&2
    return 1
  }
  [[ "$APPHOSTING_WEB_APP_ID" =~ ^[0-9]+:[0-9]+:web:[A-Za-z0-9]+$ ]] || {
    echo "APPHOSTING_WEB_APP_ID is not a valid Firebase Web App ID." >&2
    return 1
  }
  [[ "$repository_resource" =~ ^projects/${GCP_PROJECT_ID}/locations/${region}/connections/[^/[:space:]]+/gitRepositoryLinks/[^/[:space:]]+$ ]] || {
    echo "APPHOSTING_REPOSITORY_RESOURCE must be a europe-west4 GitRepositoryLink in GCP_PROJECT_ID." >&2
    return 1
  }
  [[ "$wait_timeout_seconds" =~ ^[0-9]+$ ]] && ((wait_timeout_seconds >= 60 && wait_timeout_seconds <= 3600)) || {
    echo "APPHOSTING_WAIT_TIMEOUT_SECONDS must be between 60 and 3600." >&2
    return 1
  }
  [[ "$poll_interval_seconds" =~ ^[0-9]+$ ]] && ((poll_interval_seconds >= 1 && poll_interval_seconds <= 30)) || {
    echo "APPHOSTING_POLL_INTERVAL_SECONDS must be between 1 and 30." >&2
    return 1
  }
  [[ "$apply_changes" == "true" || "$apply_changes" == "false" ]] || {
    echo "APPHOSTING_APPLY must be true or false." >&2
    return 1
  }
  if [[ "$apply_changes" != "true" ]]; then
    echo "APPHOSTING_APPLY must be true for this mutating provisioning script; use verify_apphosting_rollout.sh for read-only verification." >&2
    return 1
  fi
  [[ "${CONFIRM_GCP_PROJECT_ID:-}" == "$GCP_PROJECT_ID" ]] || {
    echo "CONFIRM_GCP_PROJECT_ID must repeat the exact target project ID." >&2
    return 1
  }
  [[ "${CONFIRM_APPHOSTING_GIT_SHA:-}" == "$expected_sha" ]] || {
    echo "CONFIRM_APPHOSTING_GIT_SHA must repeat the exact commit SHA." >&2
    return 1
  }
}

verify_branch_protection() {
  local protection_json="$1"
  jq -e '
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
  ' >/dev/null <<<"$protection_json" || {
    echo "Refusing App Hosting: main is not protected by the required review and CI checks." >&2
    return 1
  }
}

verify_repository_link() {
  local repository_json="$1"
  local github_repository_json="$2"
  local actual_name clone_uri actual_repository_slug expected_repository_slug
  local actual_repository_key expected_repository_key

  actual_name="$(jq -r '.name // empty' <<<"$repository_json")"
  clone_uri="$(jq -r '.cloneUri // empty' <<<"$repository_json")"
  expected_repository_slug="$(jq -r '.nameWithOwner // empty' <<<"$github_repository_json")"

  [[ "$actual_name" == "$repository_resource" ]] || {
    echo "Developer Connect repository drift: expected $repository_resource, got ${actual_name:-missing}." >&2
    return 1
  }
  if ! actual_repository_slug="$(github_repository_from_clone_uri "$clone_uri")"; then
    echo "Developer Connect repository drift: unsupported or missing GitHub clone URI." >&2
    return 1
  fi
  [[ -n "$expected_repository_slug" ]] || {
    echo "Could not resolve the expected GitHub repository $repository." >&2
    return 1
  }

  actual_repository_key="$(printf '%s' "$actual_repository_slug" | lowercase)"
  expected_repository_key="$(printf '%s' "$expected_repository_slug" | lowercase)"
  [[ "$actual_repository_key" == "$expected_repository_key" ]] || {
    echo "Developer Connect repository drift: expected $expected_repository_slug, got $actual_repository_slug." >&2
    return 1
  }
}

verify_github_ref() {
  local ref_json="$1"
  local actual_sha
  actual_sha="$(jq -r '.object.sha // empty' <<<"$ref_json")"
  [[ "$actual_sha" == "$expected_sha" ]] || {
    echo "Refusing rollout: $repository $branch points to ${actual_sha:-missing}, not $expected_sha." >&2
    return 1
  }
}

verify_backend_configuration() {
  local backend_json="$1"
  local actual_name expected_name actual_account actual_root actual_repository
  local actual_app_id actual_uri expected_uri actual_locality

  actual_name="$(jq -r '(.result // .).name // empty' <<<"$backend_json")"
  expected_name="$(backend_resource_name)"
  actual_account="$(jq -r '(.result // .).serviceAccount // empty' <<<"$backend_json")"
  actual_root="$(jq -r '(.result // .).codebase.rootDirectory // empty' <<<"$backend_json")"
  actual_repository="$(jq -r '(.result // .).codebase.repository // empty' <<<"$backend_json")"
  actual_app_id="$(jq -r '(.result // .).appId // empty' <<<"$backend_json")"
  actual_uri="$(jq -r '(.result // .).uri // empty' <<<"$backend_json")"
  actual_locality="$(jq -r '(.result // .).servingLocality // empty' <<<"$backend_json")"
  expected_uri="https://${backend_id}--${GCP_PROJECT_ID}.${region}.hosted.app"

  [[ "$actual_name" == "$expected_name" ]] || {
    echo "App Hosting backend drift: expected $expected_name, got ${actual_name:-missing}." >&2
    return 1
  }
  [[ "$actual_locality" == "GLOBAL_ACCESS" ]] || {
    echo "App Hosting locality drift: GLOBAL_ACCESS is the currently supported App Hosting mode." >&2
    return 1
  }
  [[ "$actual_account" == "$APPHOSTING_SERVICE_ACCOUNT" ]] || {
    echo "App Hosting service-account drift." >&2
    return 1
  }
  [[ "$actual_root" == "$root_directory" ]] || {
    echo "App Hosting root-directory drift: expected $root_directory." >&2
    return 1
  }
  [[ "$actual_repository" == "$repository_resource" ]] || {
    echo "App Hosting repository drift: expected $repository_resource." >&2
    return 1
  }
  [[ "$actual_app_id" == "$APPHOSTING_WEB_APP_ID" ]] || {
    echo "App Hosting Web App drift: expected $APPHOSTING_WEB_APP_ID, got ${actual_app_id:-missing}." >&2
    return 1
  }
  if [[ -n "$actual_uri" && "$actual_uri" != "$expected_uri" ]]; then
    echo "App Hosting URI drift: expected $expected_uri, got $actual_uri." >&2
    return 1
  fi
}

verify_traffic_policy() {
  local traffic_json="$1"
  local expected_disabled="$2"
  local actual_name expected_name actual_branch disabled

  actual_name="$(jq -r '(.result // .).name // empty' <<<"$traffic_json")"
  expected_name="$(backend_resource_name)/traffic"
  actual_branch="$(jq -r '(.result // .).rolloutPolicy.codebaseBranch // empty' <<<"$traffic_json")"
  disabled="$(jq -r '(.result // .).rolloutPolicy.disabled // false' <<<"$traffic_json")"

  [[ "$actual_name" == "$expected_name" ]] || {
    echo "App Hosting traffic drift: expected $expected_name, got ${actual_name:-missing}." >&2
    return 1
  }
  [[ "$actual_branch" == "$branch" ]] || {
    echo "App Hosting branch drift: expected $branch, got ${actual_branch:-missing}." >&2
    return 1
  }
  [[ "$disabled" == "$expected_disabled" ]] || {
    echo "App Hosting rollout-policy drift: disabled must be $expected_disabled." >&2
    return 1
  }
}

verify_backend() {
  local backend_json="$1"
  local traffic_json="$2"
  local repository_json="$3"
  local github_repository_json="$4"
  local actual_uri

  verify_repository_link "$repository_json" "$github_repository_json" || return 1
  verify_backend_configuration "$backend_json" || return 1
  verify_traffic_policy "$traffic_json" "false" || return 1
  actual_uri="$(jq -r '(.result // .).uri // empty' <<<"$backend_json")"
  [[ "$actual_uri" == https://* ]] || {
    echo "App Hosting has not exposed an HTTPS backend URL after the pinned rollout." >&2
    return 1
  }
}

backend_payload() {
  jq -cn \
    --arg repository "$repository_resource" \
    --arg root "$root_directory" \
    --arg service_account "$APPHOSTING_SERVICE_ACCOUNT" \
    --arg app_id "$APPHOSTING_WEB_APP_ID" \
    '{
      displayName: "Ontology Appliance web",
      servingLocality: "GLOBAL_ACCESS",
      codebase: {repository: $repository, rootDirectory: $root},
      serviceAccount: $service_account,
      appId: $app_id,
      environment: "development",
      labels: {application: "ontology-appliance", environment: "dev", managed_by: "apphosting-api"}
    }'
}

traffic_payload() {
  local disabled="$1"
  jq -cn \
    --arg name "$(backend_resource_name)/traffic" \
    --arg branch "$branch" \
    --argjson disabled "$disabled" \
    '{name: $name, rolloutPolicy: {codebaseBranch: $branch, disabled: $disabled}}'
}

build_payload() {
  jq -cn \
    --arg commit "$expected_sha" \
    '{
      displayName: "Pinned main commit",
      source: {codebase: {commit: $commit}},
      labels: {application: "ontology-appliance", environment: "dev", source: "pinned-commit"}
    }'
}

rollout_payload() {
  jq -cn \
    --arg build "$(backend_resource_name)/builds/$(build_id_for_sha)" \
    '{
      displayName: "Pinned main rollout",
      build: $build,
      labels: {application: "ontology-appliance", environment: "dev", source: "pinned-commit"}
    }'
}

api_request() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local response_file http_status response
  local -a curl_arguments

  response_file="$(mktemp "${TMPDIR:-/tmp}/oa-apphosting-response.XXXXXX")"
  curl_arguments=(
    --silent
    --show-error
    --request "$method"
    --header "Authorization: Bearer ${access_token}"
    --header "Accept: application/json"
    --output "$response_file"
    --write-out '%{http_code}'
  )
  if [[ -n "$body" ]]; then
    curl_arguments+=(--header 'Content-Type: application/json' --data "$body")
  fi

  if ! http_status="$(curl "${curl_arguments[@]}" "$url")"; then
    rm -f "$response_file"
    return 1
  fi
  response="$(<"$response_file")"
  rm -f "$response_file"

  if [[ "$http_status" == "404" ]]; then
    return 44
  fi
  if [[ ! "$http_status" =~ ^2[0-9][0-9]$ ]]; then
    echo "App Hosting API $method failed with HTTP $http_status." >&2
    jq -r '.error.message // "No structured API error was returned."' <<<"${response:-{}}" >&2 || true
    return 1
  fi
  printf '%s\n' "$response"
}

wait_for_operation() {
  local operation_json="$1"
  local operation_name started_at done error_message
  operation_name="$(jq -r '.name // empty' <<<"$operation_json")"
  [[ -n "$operation_name" ]] || {
    echo "App Hosting API did not return an operation name." >&2
    return 1
  }

  started_at="$SECONDS"
  while true; do
    operation_json="$(api_request GET "${apphosting_api_origin%/}/v1beta/${operation_name}")"
    done="$(jq -r '.done // false' <<<"$operation_json")"
    if [[ "$done" == "true" ]]; then
      error_message="$(jq -r '.error.message // empty' <<<"$operation_json")"
      [[ -z "$error_message" ]] || {
        echo "App Hosting operation failed: $error_message" >&2
        return 1
      }
      return 0
    fi
    if ((SECONDS - started_at >= wait_timeout_seconds)); then
      echo "Timed out waiting for App Hosting operation $operation_name." >&2
      return 1
    fi
    sleep "$poll_interval_seconds"
  done
}

get_optional_resource() {
  local url="$1"
  local response status
  if response="$(api_request GET "$url")"; then
    printf '%s\n' "$response"
    return 0
  else
    status="$?"
  fi
  [[ "$status" == "44" ]] && return 44
  return "$status"
}

get_or_create_backend() {
  local name url response status operation
  name="$(backend_resource_name)"
  url="${apphosting_api_origin%/}/v1beta/${name}"
  if response="$(get_optional_resource "$url")"; then
    verify_backend_configuration "$response" || return 1
    printf '%s\n' "$response"
    return 0
  else
    status="$?"
  fi
  [[ "$status" == "44" ]] || return "$status"

  operation="$(api_request POST \
    "${apphosting_api_origin%/}/v1beta/projects/${GCP_PROJECT_ID}/locations/${region}/backends?backendId=${backend_id}&requestId=$(request_id_for_sha backend)" \
    "$(backend_payload)")"
  wait_for_operation "$operation"
  response="$(api_request GET "$url")"
  verify_backend_configuration "$response" || return 1
  printf '%s\n' "$response"
}

ensure_traffic_policy() {
  local disabled="$1"
  local discriminator traffic_url traffic_json operation
  traffic_url="${apphosting_api_origin%/}/v1beta/$(backend_resource_name)/traffic"
  traffic_json="$(api_request GET "$traffic_url")"
  if verify_traffic_policy "$traffic_json" "$disabled" >/dev/null 2>&1; then
    printf '%s\n' "$traffic_json"
    return 0
  fi

  if [[ "$disabled" == "true" ]]; then
    discriminator="traffic-disable"
  else
    discriminator="traffic-enable"
  fi
  operation="$(api_request PATCH \
    "${traffic_url}?updateMask=rolloutPolicy&requestId=$(request_id_for_sha "$discriminator")" \
    "$(traffic_payload "$disabled")")"
  wait_for_operation "$operation"
  traffic_json="$(api_request GET "$traffic_url")"
  verify_traffic_policy "$traffic_json" "$disabled"
  printf '%s\n' "$traffic_json"
}

verify_build_reference() {
  local build_json="$1"
  local expected_name actual_name requested_commit resolved_sha actual_repository
  expected_name="$(backend_resource_name)/builds/$(build_id_for_sha)"
  actual_name="$(jq -r '.name // empty' <<<"$build_json")"
  requested_commit="$(jq -r '.source.codebase.commit // empty' <<<"$build_json")"
  resolved_sha="$(jq -r '.source.codebase.hash // empty' <<<"$build_json")"
  actual_repository="$(jq -r '.source.codebase.repository // empty' <<<"$build_json")"

  [[ "$actual_name" == "$expected_name" ]] || {
    echo "App Hosting build drift: expected $expected_name." >&2
    return 1
  }
  [[ "$requested_commit" == "$expected_sha" || "$resolved_sha" == "$expected_sha" ]] || {
    echo "App Hosting build does not resolve the pinned SHA $expected_sha." >&2
    return 1
  }
  if [[ -n "$actual_repository" && "$actual_repository" != "$repository_resource" ]]; then
    echo "App Hosting build repository drift." >&2
    return 1
  fi
}

get_or_create_build() {
  local name url response status operation
  name="$(backend_resource_name)/builds/$(build_id_for_sha)"
  url="${apphosting_api_origin%/}/v1beta/${name}"
  if response="$(get_optional_resource "$url")"; then
    verify_build_reference "$response" || return 1
    printf '%s\n' "$response"
    return 0
  else
    status="$?"
  fi
  [[ "$status" == "44" ]] || return "$status"

  operation="$(api_request POST \
    "${apphosting_api_origin%/}/v1beta/$(backend_resource_name)/builds?buildId=$(build_id_for_sha)&requestId=$(request_id_for_sha build)" \
    "$(build_payload)")"
  wait_for_operation "$operation"
  response="$(api_request GET "$url")"
  verify_build_reference "$response" || return 1
  printf '%s\n' "$response"
}

verify_rollout_reference() {
  local rollout_json="$1"
  local expected_name expected_build actual_name actual_build state
  expected_name="$(backend_resource_name)/rollouts/$(rollout_id_for_sha)"
  expected_build="$(backend_resource_name)/builds/$(build_id_for_sha)"
  actual_name="$(jq -r '.name // empty' <<<"$rollout_json")"
  actual_build="$(jq -r '.build // empty' <<<"$rollout_json")"
  state="$(jq -r '.state // "STATE_UNSPECIFIED"' <<<"$rollout_json")"

  [[ "$actual_name" == "$expected_name" && "$actual_build" == "$expected_build" ]] || {
    echo "App Hosting rollout does not reference the pinned build." >&2
    return 1
  }
  [[ "$state" != "FAILED" && "$state" != "CANCELLED" && "$state" != "SKIPPED" ]] || {
    echo "The existing pinned App Hosting rollout is terminal with state $state." >&2
    return 1
  }
}

get_or_create_rollout() {
  local name url response status operation
  name="$(backend_resource_name)/rollouts/$(rollout_id_for_sha)"
  url="${apphosting_api_origin%/}/v1beta/${name}"
  if response="$(get_optional_resource "$url")"; then
    verify_rollout_reference "$response" || return 1
    printf '%s\n' "$response"
    return 0
  else
    status="$?"
  fi
  [[ "$status" == "44" ]] || return "$status"

  operation="$(api_request POST \
    "${apphosting_api_origin%/}/v1beta/$(backend_resource_name)/rollouts?rolloutId=$(rollout_id_for_sha)&requestId=$(request_id_for_sha rollout)" \
    "$(rollout_payload)")"
  wait_for_operation "$operation"
  response="$(api_request GET "$url")"
  verify_rollout_reference "$response" || return 1
  printf '%s\n' "$response"
}

wait_for_rollout() {
  local rollout_url rollout_json state error_message started_at
  rollout_url="${apphosting_api_origin%/}/v1beta/$(backend_resource_name)/rollouts/$(rollout_id_for_sha)"
  started_at="$SECONDS"
  while true; do
    rollout_json="$(api_request GET "$rollout_url")"
    state="$(jq -r '.state // "STATE_UNSPECIFIED"' <<<"$rollout_json")"
    case "$state" in
      SUCCEEDED)
        return 0
        ;;
      FAILED|CANCELLED|SKIPPED)
        error_message="$(jq -r '.error.message // "no structured error"' <<<"$rollout_json")"
        echo "Pinned App Hosting rollout ended as $state: $error_message" >&2
        return 1
        ;;
    esac
    if ((SECONDS - started_at >= wait_timeout_seconds)); then
      echo "Timed out waiting for pinned App Hosting rollout $(rollout_id_for_sha)." >&2
      return 1
    fi
    sleep "$poll_interval_seconds"
  done
}

run_exact_rollout_verifier() {
  GCP_PROJECT_ID="$GCP_PROJECT_ID" \
  APPHOSTING_BACKEND_ID="$backend_id" \
  APPHOSTING_REGION="$region" \
  APPHOSTING_BRANCH="$branch" \
  APPHOSTING_GIT_SHA="$expected_sha" \
  APPHOSTING_REPOSITORY_RESOURCE="$repository_resource" \
  APPHOSTING_ROLLOUT_ID="$(rollout_id_for_sha)" \
    bash "$script_dir/verify_apphosting_rollout.sh"
}

emit_backend_url() {
  local backend_json="$1"
  local backend_url
  backend_url="$(jq -r '(.result // .).uri // empty' <<<"$backend_json")"
  [[ "$backend_url" == https://* ]] || {
    echo "App Hosting has not exposed an HTTPS backend URL after the pinned rollout." >&2
    return 1
  }
  echo "APP_HOSTING_URL=${backend_url}"
}

main() {
  validate_inputs
  for command_name in curl gcloud gh jq; do
    command -v "$command_name" >/dev/null 2>&1 || {
      echo "Missing required command: $command_name" >&2
      return 1
    }
  done

  local branch_protection_json repository_json github_repository_json github_ref_json
  local secret_version backend_json traffic_json
  branch_protection_json="$(gh api "repos/${repository}/branches/${branch}/protection")"
  verify_branch_protection "$branch_protection_json"
  github_repository_json="$(gh repo view "$repository" --json nameWithOwner,isPrivate)"
  github_ref_json="$(gh api "repos/${repository}/git/ref/heads/${branch}")"
  verify_github_ref "$github_ref_json"

  secret_version="$(gcloud secrets versions list "$gateway_secret" \
    --project "$GCP_PROJECT_ID" \
    --filter='state=ENABLED' \
    --limit=1 \
    --format='value(name)')"
  if [[ -z "$secret_version" ]]; then
    echo "Deploy the semantic gateway first so $gateway_secret has an enabled version." >&2
    return 1
  fi

  access_token="$(gcloud auth print-access-token)"
  repository_json="$(api_request GET "${developer_connect_api_origin%/}/v1/${repository_resource}")"
  verify_repository_link "$repository_json" "$github_repository_json"

  backend_json="$(get_or_create_backend)"

  # A completed rerun is read-only: prove the exact active commit first and
  # return without toggling the automatic rollout policy.
  if traffic_json="$(api_request GET "${apphosting_api_origin%/}/v1beta/$(backend_resource_name)/traffic")" &&
    verify_traffic_policy "$traffic_json" "false" >/dev/null 2>&1 &&
    run_exact_rollout_verifier >/dev/null 2>&1; then
    verify_backend "$backend_json" "$traffic_json" "$repository_json" "$github_repository_json"
    echo "App Hosting backend $backend_id already serves the exact governed commit $expected_sha."
    emit_backend_url "$backend_json"
    return 0
  fi

  # Hold automatic branch rollouts while the explicitly pinned commit is built
  # and promoted. Re-enable main only after the exact rollout succeeds.
  ensure_traffic_policy "true" >/dev/null
  get_or_create_build >/dev/null
  get_or_create_rollout >/dev/null
  wait_for_rollout
  traffic_json="$(ensure_traffic_policy "false")"
  backend_json="$(api_request GET "${apphosting_api_origin%/}/v1beta/$(backend_resource_name)")"
  verify_backend "$backend_json" "$traffic_json" "$repository_json" "$github_repository_json"
  run_exact_rollout_verifier

  echo "App Hosting backend $backend_id serves pinned commit $expected_sha and watches protected main."
  emit_backend_url "$backend_json"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
