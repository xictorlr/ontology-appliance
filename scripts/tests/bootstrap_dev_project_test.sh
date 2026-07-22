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
    cat <<JSON
{"projectId":"${GCP_PROJECT_ID}","projectNumber":"123456789012","name":"Ontology Appliance Dev","lifecycleState":"ACTIVE","labels":{"application":"ontology-appliance","environment":"dev","managed_by":"terraform"}}
JSON
  fi
elif [[ "$1 $2" == "projects create" ]]; then
  record "$*"
  touch "${MOCK_STATE_DIR}/project-exists"
elif [[ "$1 $2 $3" == "billing projects describe" ]]; then
  linked=""
  if [[ -f "${MOCK_STATE_DIR}/billing-linked" ]]; then
    linked="$(<"${MOCK_STATE_DIR}/billing-linked")"
  fi
  printf '{"billingAccountName":"%s"}\n' "$linked"
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
    unrelated)
      echo 'module.platform.google_storage_bucket.unrelated[0]'
      ;;
    empty)
      echo 'No state file was found!' >&2
      exit 1
      ;;
  esac
elif [[ "$*" == *" state show "* ]]; then
  printf '    project_id = "%s"\n' "${MOCK_STATE_PROJECT_ID:-$GCP_PROJECT_ID}"
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
