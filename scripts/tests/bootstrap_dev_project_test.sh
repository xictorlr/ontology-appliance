#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
suite_root="$(mktemp -d "${TMPDIR:-/tmp}/oa-bootstrap-test.XXXXXX")"
trap 'rm -rf "$suite_root"' EXIT

make_scenario() {
  local name="$1"
  local scenario_root="${suite_root}/${name}"

  mkdir -p \
    "${scenario_root}/repo/scripts" \
    "${scenario_root}/repo/infra/terraform/environments/dev" \
    "${scenario_root}/mock-bin" \
    "${scenario_root}/state"
  cp "${repo_root}/scripts/bootstrap_dev_project.sh" "${scenario_root}/repo/scripts/"

  cat >"${scenario_root}/mock-bin/gcloud" <<'GCLOUD'
#!/usr/bin/env bash
set -euo pipefail

record() {
  printf '%s\n' "$*" >>"${MOCK_STATE_DIR}/mutations"
}

if [[ "$1 $2 $3" == "config get-value account" ]]; then
  echo "owner@example.com"
elif [[ "$1 $2 $3" == "billing accounts describe" ]]; then
  printf '{"name":"billingAccounts/%s","open":true}\n' "$4"
elif [[ "$1 $2" == "projects describe" ]]; then
  if [[ ! -f "${MOCK_STATE_DIR}/project-exists" ]]; then
    exit 1
  fi
  if [[ "$*" == *"value(projectNumber)"* ]]; then
    echo "123456789012"
  else
    project_id="${MOCK_LIVE_PROJECT_ID:-$GCP_PROJECT_ID}"
    project_name="${MOCK_PROJECT_NAME:-Ontology Appliance Dev}"
    lifecycle_state="ACTIVE"
    labels='{"application":"ontology-appliance","environment":"dev","managed_by":"terraform"}'
    parent=""
    case "${MOCK_PROJECT_MODE:-terraform}" in
      firebase)
        labels='{"firebase":"enabled"}'
        ;;
      terraform-firebase)
        labels='{"application":"ontology-appliance","environment":"dev","managed_by":"terraform","firebase":"enabled"}'
        ;;
      inactive-firebase)
        lifecycle_state="DELETE_REQUESTED"
        labels='{"firebase":"enabled"}'
        ;;
      non-firebase)
        labels='{"application":"other"}'
        ;;
    esac
    case "${MOCK_PROJECT_PARENT:-none}" in
      folder)
        parent=',"parent":{"type":"folder","id":"1234567890"}'
        ;;
      organization)
        parent=',"parent":{"type":"organization","id":"9876543210"}'
        ;;
    esac
    printf \
      '{"projectId":"%s","projectNumber":"123456789012","name":"%s","lifecycleState":"%s","labels":%s%s}\n' \
      "$project_id" "$project_name" "$lifecycle_state" "$labels" "$parent"
  fi
elif [[ "$1 $2" == "projects create" ]]; then
  record "$*"
  touch "${MOCK_STATE_DIR}/project-exists"
elif [[ "$1 $2" == "projects update" ]]; then
  record "$*"
elif [[ "$1 $2 $3" == "billing projects describe" ]]; then
  linked=""
  if [[ -f "${MOCK_STATE_DIR}/billing-linked" ]]; then
    linked="$(<"${MOCK_STATE_DIR}/billing-linked")"
  fi
  billing_enabled=false
  if [[ -n "$linked" ]]; then
    billing_enabled=true
  fi
  printf '{"billingAccountName":"%s","billingEnabled":%s}\n' \
    "$linked" "${MOCK_BILLING_ENABLED:-$billing_enabled}"
elif [[ "$1 $2 $3" == "billing projects link" ]]; then
  record "$*"
  for argument in "$@"; do
    if [[ "$argument" == --billing-account=* ]]; then
      printf 'billingAccounts/%s\n' "${argument#--billing-account=}" >"${MOCK_STATE_DIR}/billing-linked"
    fi
  done
elif [[ "$1 $2" == "services enable" ]]; then
  record "$*"
elif [[ "$1 $2 $3" == "storage buckets describe" ]]; then
  [[ "$*" == *" --raw "* ]] || {
    echo "Bucket identity checks must use raw API metadata." >&2
    exit 69
  }
  [[ -f "${MOCK_STATE_DIR}/bucket-exists" ]] || exit 1
  bucket_project="123456789012"
  labels='"application":"ontology-appliance","environment":"dev","purpose":"terraform-state","managed_by":"bootstrap"'
  if [[ "${MOCK_BUCKET_MODE:-exact}" == "foreign" ]]; then
    bucket_project="999999999999"
    labels='"application":"other"'
  elif [[ "${MOCK_BUCKET_MODE:-exact}" == "unlabeled" ]]; then
    labels='{}'
  fi
  if [[ "$labels" == "{}" ]]; then
    printf '{"projectNumber":"%s","location":"europe-west4","labels":{}}\n' "$bucket_project"
  else
    printf '{"projectNumber":"%s","location":"europe-west4","labels":{%s}}\n' "$bucket_project" "$labels"
  fi
elif [[ "$1 $2 $3" == "storage buckets create" ]]; then
  record "$*"
  touch "${MOCK_STATE_DIR}/bucket-exists"
elif [[ "$1 $2 $3" == "storage buckets update" ]]; then
  record "$*"
elif [[ "$1 $2" == "storage ls" ]]; then
  if [[ -n "${MOCK_BUCKET_HISTORY:-}" ]]; then
    echo "${MOCK_BUCKET_HISTORY}"
  fi
else
  echo "Unexpected mocked gcloud invocation: $*" >&2
  exit 70
fi
GCLOUD

  cat >"${scenario_root}/mock-bin/terraform" <<'TERRAFORM'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$*" == *" init "* || "$*" == *" init" ]]; then
  exit 0
elif [[ "$*" == *" state list"* ]]; then
  case "${MOCK_TF_STATE_MODE:-empty}" in
    imported|project)
      echo 'module.platform.google_project.this[0]'
      ;;
    both)
      echo 'module.platform.google_project.this[0]'
      echo 'module.platform.google_firebase_project.this[0]'
      ;;
    both-with-data)
      echo 'module.platform.data.google_compute_default_service_account.functions_build[0]'
      echo 'module.platform.data.google_storage_project_service_account.gcs[0]'
      echo 'module.platform.google_project.this[0]'
      echo 'module.platform.google_firebase_project.this[0]'
      ;;
    project-unrelated)
      echo 'module.platform.google_project.this[0]'
      echo 'module.platform.google_storage_bucket.unrelated[0]'
      ;;
    firebase)
      echo 'module.platform.google_firebase_project.this[0]'
      ;;
    unrelated)
      echo 'module.platform.google_storage_bucket.unrelated[0]'
      ;;
    empty)
      echo 'No state file was found!' >&2
      exit 1
      ;;
  esac
elif [[ "$*" == *" state show "* ]]; then
  if [[ "$*" == *"google_firebase_project"* ]]; then
    printf '    project = "%s"\n' "${MOCK_STATE_FIREBASE_PROJECT_ID:-$GCP_PROJECT_ID}"
  else
    printf '    project_id = "%s"\n' "${MOCK_STATE_PROJECT_ID:-$GCP_PROJECT_ID}"
  fi
elif [[ "$*" == *" import "* ]]; then
  printf '%s\n' "$*" >>"${MOCK_STATE_DIR}/mutations"
  touch "${MOCK_STATE_DIR}/tf-imported"
else
  echo "Unexpected mocked terraform invocation: $*" >&2
  exit 71
fi
TERRAFORM

  chmod +x "${scenario_root}/mock-bin/gcloud" "${scenario_root}/mock-bin/terraform"
  printf '%s\n' "$scenario_root"
}

run_bootstrap() {
  local scenario_root="$1"
  shift
  env \
    PATH="${scenario_root}/mock-bin:${PATH}" \
    MOCK_STATE_DIR="${scenario_root}/state" \
    GCP_PROJECT_ID="ontology-appliance-dev-unit" \
    BILLING_ACCOUNT_ID="ABCDEF-123456-ABCDEF" \
    CONFIRM_GCP_PROJECT_ID="ontology-appliance-dev-unit" \
    BUDGET_NOTIFICATION_EMAIL="owner@example.com" \
    GITHUB_REPOSITORY="xictorlr/ontology-appliance" \
    "$@" \
    bash "${scenario_root}/repo/scripts/bootstrap_dev_project.sh"
}

new_root="$(make_scenario new)"
run_bootstrap "$new_root" >/dev/null
grep -Fq 'services enable cloudresourcemanager.googleapis.com compute.googleapis.com serviceusage.googleapis.com storage.googleapis.com' \
  "${new_root}/state/mutations"
grep -Fqx 'project_id         = "ontology-appliance-dev-unit"' \
  "${new_root}/repo/infra/terraform/environments/dev/terraform.tfvars"
grep -Fq 'projects create ontology-appliance-dev-unit' "${new_root}/state/mutations"
grep -Fq " import module.platform.google_project.this[0] ontology-appliance-dev-unit" \
  "${new_root}/state/mutations"

MOCK_TF_STATE_MODE=imported run_bootstrap "$new_root" RESUME_BOOTSTRAP=true >/dev/null

printf 'billingAccounts/FFFFFF-FFFFFF-FFFFFF\n' >"${new_root}/state/billing-linked"
if MOCK_TF_STATE_MODE=imported run_bootstrap "$new_root" RESUME_BOOTSTRAP=true >/dev/null 2>&1; then
  echo "Expected a different linked billing account to be rejected." >&2
  exit 1
fi

default_existing_root="$(make_scenario default-existing-firebase)"
touch "${default_existing_root}/state/project-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' \
  >"${default_existing_root}/state/billing-linked"
if MOCK_PROJECT_MODE=firebase \
  run_bootstrap "$default_existing_root" >/dev/null 2>&1; then
  echo "Expected an existing Firebase project to be rejected without explicit adoption." >&2
  exit 1
fi
if [[ -s "${default_existing_root}/state/mutations" ]]; then
  echo "Default existing-project rejection must happen before cloud mutations." >&2
  exit 1
fi

unconfirmed_root="$(make_scenario unconfirmed-adoption)"
touch "${unconfirmed_root}/state/project-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${unconfirmed_root}/state/billing-linked"
if MOCK_PROJECT_MODE=firebase ADOPT_EXISTING_FIREBASE_PROJECT=true \
  run_bootstrap "$unconfirmed_root" >/dev/null 2>&1; then
  echo "Expected adoption without the exact second project-ID confirmation to fail." >&2
  exit 1
fi

adopt_root="$(make_scenario adopt-existing-firebase)"
touch "${adopt_root}/state/project-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${adopt_root}/state/billing-linked"
MOCK_PROJECT_MODE=firebase \
MOCK_PROJECT_NAME=ontology-apliance \
ADOPT_EXISTING_FIREBASE_PROJECT=true \
CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$adopt_root" >/dev/null
if grep -Fq 'projects create' "${adopt_root}/state/mutations"; then
  echo "Adoption must never create a replacement project." >&2
  exit 1
fi
grep -Fq \
  'projects update ontology-appliance-dev-unit --name=Ontology Appliance Dev' \
  "${adopt_root}/state/mutations"
grep -Fq \
  ' import module.platform.google_project.this[0] ontology-appliance-dev-unit' \
  "${adopt_root}/state/mutations"
grep -Fq \
  ' import module.platform.google_firebase_project.this[0] ontology-appliance-dev-unit' \
  "${adopt_root}/state/mutations"

nonfirebase_root="$(make_scenario nonfirebase-adoption)"
touch "${nonfirebase_root}/state/project-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${nonfirebase_root}/state/billing-linked"
if MOCK_PROJECT_MODE=non-firebase \
  ADOPT_EXISTING_FIREBASE_PROJECT=true \
  CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$nonfirebase_root" >/dev/null 2>&1; then
  echo "Expected adoption of a project without firebase=enabled to fail." >&2
  exit 1
fi

inactive_root="$(make_scenario inactive-adoption)"
touch "${inactive_root}/state/project-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${inactive_root}/state/billing-linked"
if MOCK_PROJECT_MODE=inactive-firebase \
  ADOPT_EXISTING_FIREBASE_PROJECT=true \
  CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$inactive_root" >/dev/null 2>&1; then
  echo "Expected adoption of a non-ACTIVE Firebase project to fail." >&2
  exit 1
fi

adoption_billing_root="$(make_scenario adoption-billing)"
touch "${adoption_billing_root}/state/project-exists"
printf 'billingAccounts/FFFFFF-FFFFFF-FFFFFF\n' \
  >"${adoption_billing_root}/state/billing-linked"
if MOCK_PROJECT_MODE=firebase \
  ADOPT_EXISTING_FIREBASE_PROJECT=true \
  CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$adoption_billing_root" >/dev/null 2>&1; then
  echo "Expected adoption with a different linked billing account to fail." >&2
  exit 1
fi
if [[ -s "${adoption_billing_root}/state/mutations" ]]; then
  echo "Billing mismatch must be rejected before adoption mutates the project." >&2
  exit 1
fi

parent_root="$(make_scenario adoption-parent)"
touch "${parent_root}/state/project-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${parent_root}/state/billing-linked"
if MOCK_PROJECT_MODE=firebase MOCK_PROJECT_PARENT=folder \
  ADOPT_EXISTING_FIREBASE_PROJECT=true \
  CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$parent_root" >/dev/null 2>&1; then
  echo "Expected adoption with an unconfirmed project parent to fail." >&2
  exit 1
fi

project_only_state_root="$(make_scenario adoption-project-only-state)"
touch \
  "${project_only_state_root}/state/project-exists" \
  "${project_only_state_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' \
  >"${project_only_state_root}/state/billing-linked"
MOCK_PROJECT_MODE=terraform-firebase \
MOCK_TF_STATE_MODE=project \
ADOPT_EXISTING_FIREBASE_PROJECT=true \
CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$project_only_state_root" RESUME_BOOTSTRAP=true >/dev/null
if grep -Fq \
  ' import module.platform.google_project.this[0]' \
  "${project_only_state_root}/state/mutations"; then
  echo "A coherently owned project must not be imported twice." >&2
  exit 1
fi
grep -Fq \
  ' import module.platform.google_firebase_project.this[0] ontology-appliance-dev-unit' \
  "${project_only_state_root}/state/mutations"

firebase_only_state_root="$(make_scenario adoption-firebase-only-state)"
touch \
  "${firebase_only_state_root}/state/project-exists" \
  "${firebase_only_state_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' \
  >"${firebase_only_state_root}/state/billing-linked"
if MOCK_PROJECT_MODE=terraform-firebase MOCK_TF_STATE_MODE=firebase \
  ADOPT_EXISTING_FIREBASE_PROJECT=true \
  CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$firebase_only_state_root" RESUME_BOOTSTRAP=true >/dev/null 2>&1; then
  echo "Expected Firebase-only Terraform ownership to be rejected as incoherent." >&2
  exit 1
fi

foreign_firebase_state_root="$(make_scenario adoption-foreign-firebase-state)"
touch \
  "${foreign_firebase_state_root}/state/project-exists" \
  "${foreign_firebase_state_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' \
  >"${foreign_firebase_state_root}/state/billing-linked"
if MOCK_PROJECT_MODE=terraform-firebase MOCK_TF_STATE_MODE=both \
  MOCK_STATE_FIREBASE_PROJECT_ID=another-project \
  ADOPT_EXISTING_FIREBASE_PROJECT=true \
  CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$foreign_firebase_state_root" RESUME_BOOTSTRAP=true >/dev/null 2>&1; then
  echo "Expected Terraform Firebase ownership for another project to be rejected." >&2
  exit 1
fi

foreign_resource_state_root="$(make_scenario adoption-foreign-resource-state)"
touch \
  "${foreign_resource_state_root}/state/project-exists" \
  "${foreign_resource_state_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' \
  >"${foreign_resource_state_root}/state/billing-linked"
if MOCK_PROJECT_MODE=terraform-firebase MOCK_TF_STATE_MODE=project-unrelated \
  ADOPT_EXISTING_FIREBASE_PROJECT=true \
  CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$foreign_resource_state_root" RESUME_BOOTSTRAP=true >/dev/null 2>&1; then
  echo "Expected adoption into Terraform state with a foreign resource to fail." >&2
  exit 1
fi

expected_data_state_root="$(make_scenario adoption-expected-data-state)"
touch \
  "${expected_data_state_root}/state/project-exists" \
  "${expected_data_state_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' \
  >"${expected_data_state_root}/state/billing-linked"
MOCK_PROJECT_MODE=terraform-firebase MOCK_TF_STATE_MODE=both-with-data \
ADOPT_EXISTING_FIREBASE_PROJECT=true \
CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID=ontology-appliance-dev-unit \
  run_bootstrap "$expected_data_state_root" RESUME_BOOTSTRAP=true >/dev/null
if rg -q ' import module\.platform\.google_(project|firebase_project)\.this' \
  "${expected_data_state_root}/state/mutations"; then
  echo "Expected data sources must not trigger duplicate ownership imports." >&2
  exit 1
fi

foreign_root="$(make_scenario foreign-bucket)"
touch "${foreign_root}/state/project-exists" "${foreign_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${foreign_root}/state/billing-linked"
if MOCK_BUCKET_MODE=foreign run_bootstrap "$foreign_root" RESUME_BOOTSTRAP=true >/dev/null 2>&1; then
  echo "Expected a foreign state bucket to be rejected." >&2
  exit 1
fi

history_root="$(make_scenario historical-bucket)"
touch "${history_root}/state/project-exists" "${history_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${history_root}/state/billing-linked"
if MOCK_BUCKET_MODE=unlabeled MOCK_BUCKET_HISTORY='gs://historical/state.tfstate#1' \
  run_bootstrap "$history_root" RESUME_BOOTSTRAP=true >/dev/null 2>&1; then
  echo "Expected a bucket with historical state to be rejected." >&2
  exit 1
fi

state_root="$(make_scenario state-owner)"
touch "${state_root}/state/project-exists" "${state_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${state_root}/state/billing-linked"
if MOCK_TF_STATE_MODE=project MOCK_STATE_PROJECT_ID=another-project \
  run_bootstrap "$state_root" RESUME_BOOTSTRAP=true >/dev/null 2>&1; then
  echo "Expected Terraform state owned by another project to be rejected." >&2
  exit 1
fi

unrelated_root="$(make_scenario unrelated-state)"
touch "${unrelated_root}/state/project-exists" "${unrelated_root}/state/bucket-exists"
printf 'billingAccounts/ABCDEF-123456-ABCDEF\n' >"${unrelated_root}/state/billing-linked"
if MOCK_TF_STATE_MODE=unrelated run_bootstrap "$unrelated_root" RESUME_BOOTSTRAP=true >/dev/null 2>&1; then
  echo "Expected non-empty Terraform state without the project resource to be rejected." >&2
  exit 1
fi

echo "Bootstrap guardrail tests passed."
