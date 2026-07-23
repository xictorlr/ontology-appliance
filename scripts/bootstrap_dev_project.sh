#!/usr/bin/env bash
set -euo pipefail

# Creates only the project shell and its recoverable Terraform-state bucket.
# The reviewed Terraform plan remains the authority for every runtime resource.

: "${GCP_PROJECT_ID:?Set the globally unique development project ID.}"
: "${BILLING_ACCOUNT_ID:?Set the selected billing account ID.}"
: "${CONFIRM_GCP_PROJECT_ID:?Repeat the exact project ID in CONFIRM_GCP_PROJECT_ID.}"

if [[ "$CONFIRM_GCP_PROJECT_ID" != "$GCP_PROJECT_ID" ]]; then
  echo "CONFIRM_GCP_PROJECT_ID does not match GCP_PROJECT_ID." >&2
  exit 1
fi

if [[ ! "$GCP_PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
  echo "GCP_PROJECT_ID must be 6-30 lowercase letters, digits, or hyphens." >&2
  exit 1
fi

if [[ ! "$BILLING_ACCOUNT_ID" =~ ^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$ ]]; then
  echo "BILLING_ACCOUNT_ID must use the 000000-000000-000000 form." >&2
  exit 1
fi

for command_name in gcloud jq terraform; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Missing required command: $command_name" >&2
    exit 1
  }
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cd "$repo_root"

region="${GCP_REGION:-europe-west4}"
repository="${GITHUB_REPOSITORY:-xictorlr/ontology-appliance}"
terraform_dir="infra/terraform/environments/dev"
state_bucket="${TERRAFORM_STATE_BUCKET:-${GCP_PROJECT_ID}-oa-tfstate}"
active_account="$(gcloud config get-value account 2>/dev/null)"
budget_email="${BUDGET_NOTIFICATION_EMAIL:-$active_account}"
folder_id="${GCP_FOLDER_ID:-}"
organization_id="${GCP_ORGANIZATION_ID:-}"
resume_bootstrap="${RESUME_BOOTSTRAP:-false}"
adopt_existing_firebase_project="${ADOPT_EXISTING_FIREBASE_PROJECT:-false}"
confirm_adopt_existing_firebase_project_id="${CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID:-}"
tfvars_path="${terraform_dir}/terraform.tfvars"
backend_path="${terraform_dir}/backend.hcl"

if [[ "$region" != "europe-west4" ]]; then
  echo "GCP_REGION must remain europe-west4 for this governed pilot." >&2
  exit 1
fi

if [[ -n "$folder_id" && -n "$organization_id" ]]; then
  echo "Set at most one of GCP_FOLDER_ID or GCP_ORGANIZATION_ID." >&2
  exit 1
fi

if [[ -n "$folder_id" && ! "$folder_id" =~ ^[0-9]+$ ]]; then
  echo "GCP_FOLDER_ID must be numeric." >&2
  exit 1
fi

if [[ -n "$organization_id" && ! "$organization_id" =~ ^[0-9]+$ ]]; then
  echo "GCP_ORGANIZATION_ID must be numeric." >&2
  exit 1
fi

if [[ ! "$state_bucket" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]]; then
  echo "TERRAFORM_STATE_BUCKET must be a conservative 3-63 character GCS name." >&2
  exit 1
fi

if [[ "$resume_bootstrap" != "true" && "$resume_bootstrap" != "false" ]]; then
  echo "RESUME_BOOTSTRAP must be true or false." >&2
  exit 1
fi

if [[ "$adopt_existing_firebase_project" != "true" && \
  "$adopt_existing_firebase_project" != "false" ]]; then
  echo "ADOPT_EXISTING_FIREBASE_PROJECT must be true or false." >&2
  exit 1
fi

if [[ "$adopt_existing_firebase_project" == "true" ]]; then
  if [[ "$confirm_adopt_existing_firebase_project_id" != "$GCP_PROJECT_ID" ]]; then
    echo "CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID must exactly match GCP_PROJECT_ID." >&2
    exit 1
  fi
elif [[ -n "$confirm_adopt_existing_firebase_project_id" ]]; then
  echo "CONFIRM_ADOPT_EXISTING_FIREBASE_PROJECT_ID is valid only with ADOPT_EXISTING_FIREBASE_PROJECT=true." >&2
  exit 1
fi

if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "GITHUB_REPOSITORY must use the owner/repository form." >&2
  exit 1
fi

if [[ ! "$budget_email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$ ]]; then
  echo "Set a valid BUDGET_NOTIFICATION_EMAIL." >&2
  exit 1
fi

billing_account_json="$(gcloud billing accounts describe "$BILLING_ACCOUNT_ID" --format=json)"
if ! jq -e --arg name "billingAccounts/${BILLING_ACCOUNT_ID}" \
  '.name == $name and .open == true' >/dev/null <<<"$billing_account_json"; then
  echo "The selected billing account is missing or closed; no project was created." >&2
  exit 1
fi

validate_local_configuration() {
  local expected_folder expected_organization
  if [[ -n "$folder_id" ]]; then
    expected_folder="folder_id       = \"${folder_id}\""
  else
    expected_folder="folder_id       = null"
  fi
  if [[ -n "$organization_id" ]]; then
    expected_organization="organization_id = \"${organization_id}\""
  else
    expected_organization="organization_id = null"
  fi
  grep -Fqx "project_id         = \"${GCP_PROJECT_ID}\"" "$tfvars_path" &&
    grep -Fqx "billing_account_id = \"${BILLING_ACCOUNT_ID}\"" "$tfvars_path" &&
    grep -Fqx "$expected_folder" "$tfvars_path" &&
    grep -Fqx "$expected_organization" "$tfvars_path" &&
    grep -Fqx "budget_notification_emails = [\"${budget_email}\"]" "$tfvars_path" &&
    grep -Fqx "github_repository = \"${repository}\"" "$tfvars_path" &&
    grep -Fqx "bucket = \"${state_bucket}\"" "$backend_path" &&
    grep -Fqx 'prefix = "ontology-appliance/dev"' "$backend_path"
}

if [[ -e "$tfvars_path" || -e "$backend_path" ]]; then
  if [[ ! -f "$tfvars_path" || ! -f "$backend_path" ]]; then
    echo "Terraform bootstrap configuration is incomplete; refusing cloud changes." >&2
    exit 1
  fi
  if [[ "$resume_bootstrap" != "true" ]]; then
    echo "Bootstrap configuration already exists. Set RESUME_BOOTSTRAP=true only after reviewing it." >&2
    exit 1
  fi
  if ! validate_local_configuration; then
    echo "Existing Terraform bootstrap configuration does not match the confirmed inputs." >&2
    exit 1
  fi
else
  umask 077
  tfvars_temp="$(mktemp "${TMPDIR:-/tmp}/oa-dev-tfvars.XXXXXX")"
  backend_temp="$(mktemp "${TMPDIR:-/tmp}/oa-dev-backend.XXXXXX")"
  trap 'rm -f "$tfvars_temp" "$backend_temp"' EXIT

  {
    printf 'project_id         = "%s"\n' "$GCP_PROJECT_ID"
    printf 'billing_account_id = "%s"\n\n' "$BILLING_ACCOUNT_ID"
    if [[ -n "$folder_id" ]]; then
      printf 'folder_id       = "%s"\n' "$folder_id"
    else
      printf 'folder_id       = null\n'
    fi
    if [[ -n "$organization_id" ]]; then
      printf 'organization_id = "%s"\n\n' "$organization_id"
    else
      printf 'organization_id = null\n\n'
    fi
    printf 'budget_notification_emails = ["%s"]\n' "$budget_email"
    printf 'github_repository = "%s"\n' "$repository"
  } >"$tfvars_temp"

  {
    printf 'bucket = "%s"\n' "$state_bucket"
    printf 'prefix = "ontology-appliance/dev"\n'
  } >"$backend_temp"

  mv "$tfvars_temp" "$tfvars_path"
  mv "$backend_temp" "$backend_path"
fi

project_json=""
project_exists=false
live_firebase_project=false
normalize_project_name=false
billing_json=""
linked_billing=""
expected_billing="billingAccounts/${BILLING_ACCOUNT_ID}"
if project_json="$(gcloud projects describe "$GCP_PROJECT_ID" --format=json 2>/dev/null)"; then
  project_exists=true
  if [[ "$adopt_existing_firebase_project" != "true" && "$resume_bootstrap" != "true" ]]; then
    echo "The project already exists. Set RESUME_BOOTSTRAP=true only to resume this exact bootstrap." >&2
    exit 1
  fi

  if [[ "$adopt_existing_firebase_project" == "true" ]]; then
    if ! jq -e --arg project_id "$GCP_PROJECT_ID" '
      .projectId == $project_id and
      .lifecycleState == "ACTIVE" and
      .labels.firebase == "enabled"
    ' >/dev/null <<<"$project_json"; then
      echo "Adoption requires an ACTIVE project with the exact firebase=enabled label." >&2
      exit 1
    fi
    live_firebase_project=true
  else
    if ! jq -e --arg project_id "$GCP_PROJECT_ID" --arg project_name "Ontology Appliance Dev" '
      .projectId == $project_id and
      .lifecycleState == "ACTIVE" and
      .name == $project_name and
      .labels.application == "ontology-appliance" and
      .labels.environment == "dev" and
      .labels.managed_by == "terraform"
    ' >/dev/null <<<"$project_json"; then
      echo "The existing project does not match the exact Ontology Appliance bootstrap identity." >&2
      exit 1
    fi
    if jq -e '.labels.firebase == "enabled"' >/dev/null <<<"$project_json"; then
      live_firebase_project=true
    fi
  fi

  if [[ -n "$folder_id" ]] && ! jq -e --arg id "$folder_id" \
    '.parent.type == "folder" and .parent.id == $id' >/dev/null <<<"$project_json"; then
    echo "The existing project is not in the confirmed folder." >&2
    exit 1
  fi
  if [[ -n "$organization_id" ]] && ! jq -e --arg id "$organization_id" \
    '.parent.type == "organization" and .parent.id == $id' >/dev/null <<<"$project_json"; then
    echo "The existing project is not in the confirmed organization." >&2
    exit 1
  fi
  if [[ -z "$folder_id" && -z "$organization_id" ]] && \
    jq -e '.parent != null' >/dev/null <<<"$project_json"; then
    echo "The existing project has a parent; confirm it with GCP_FOLDER_ID or GCP_ORGANIZATION_ID." >&2
    exit 1
  fi

  billing_json="$(gcloud billing projects describe "$GCP_PROJECT_ID" --format=json)"
  linked_billing="$(jq -r '.billingAccountName // empty' <<<"$billing_json")"
  if [[ "$adopt_existing_firebase_project" == "true" ]]; then
    if [[ "$linked_billing" != "$expected_billing" ]] || \
      ! jq -e '.billingEnabled == true' >/dev/null <<<"$billing_json"; then
      echo "Adoption requires the project to have the exact confirmed billing account enabled." >&2
      exit 1
    fi
    if ! jq -e --arg project_name "Ontology Appliance Dev" \
      '.name == $project_name' >/dev/null <<<"$project_json"; then
      normalize_project_name=true
    fi
    echo "Adopting the existing, confirmed Firebase project $GCP_PROJECT_ID."
  else
    echo "Using the existing, correctly labeled project $GCP_PROJECT_ID."
  fi
else
  if [[ "$adopt_existing_firebase_project" == "true" ]]; then
    echo "ADOPT_EXISTING_FIREBASE_PROJECT=true requires the confirmed project to already exist." >&2
    exit 1
  fi
  create_arguments=(
    projects create "$GCP_PROJECT_ID"
    "--name=Ontology Appliance Dev"
    "--labels=application=ontology-appliance,environment=dev,managed_by=terraform"
  )
  if [[ -n "$folder_id" ]]; then
    create_arguments+=("--folder=$folder_id")
  elif [[ -n "$organization_id" ]]; then
    create_arguments+=("--organization=$organization_id")
  fi
  gcloud "${create_arguments[@]}"
  echo "Created project $GCP_PROJECT_ID."
fi

if [[ "$project_exists" != "true" ]]; then
  billing_json="$(gcloud billing projects describe "$GCP_PROJECT_ID" --format=json)"
  linked_billing="$(jq -r '.billingAccountName // empty' <<<"$billing_json")"
fi
if [[ -n "$linked_billing" && "$linked_billing" != "$expected_billing" ]]; then
  echo "Project is already linked to a different billing account; refusing to relink it." >&2
  exit 1
fi
if [[ "$adopt_existing_firebase_project" != "true" && "$linked_billing" != "$expected_billing" ]]; then
  gcloud billing projects link "$GCP_PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"
fi

gcloud services enable \
  cloudresourcemanager.googleapis.com \
  compute.googleapis.com \
  serviceusage.googleapis.com \
  storage.googleapis.com \
  --project "$GCP_PROJECT_ID"

project_number="$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')"
bucket_json=""
if bucket_json="$(gcloud storage buckets describe "gs://${state_bucket}" --raw --format=json 2>/dev/null)"; then
  if [[ "$resume_bootstrap" != "true" ]]; then
    echo "The Terraform state bucket already exists; explicit bootstrap resume is required." >&2
    exit 1
  fi
  bucket_identity_matches=false
  if jq -e \
    --arg project_number "$project_number" \
    --arg location "$region" '
      (.projectNumber | tostring) == $project_number and
      (.location | ascii_downcase) == ($location | ascii_downcase) and
      .labels.application == "ontology-appliance" and
      .labels.environment == "dev" and
      .labels.purpose == "terraform-state" and
      .labels.managed_by == "bootstrap"
    ' >/dev/null <<<"$bucket_json"; then
    bucket_identity_matches=true
  fi
  if [[ "$bucket_identity_matches" != "true" ]]; then
    live_and_versioned_listing="$(gcloud storage ls --all-versions --recursive "gs://${state_bucket}")"
    soft_deleted_listing="$(gcloud storage ls --soft-deleted --recursive "gs://${state_bucket}")"
    if [[ "$state_bucket" != "${GCP_PROJECT_ID}-oa-tfstate" || \
      -n "$live_and_versioned_listing" || -n "$soft_deleted_listing" ]] || ! jq -e \
      --arg project_number "$project_number" \
      --arg location "$region" '
        (.projectNumber | tostring) == $project_number and
        (.location | ascii_downcase) == ($location | ascii_downcase)
      ' >/dev/null <<<"$bucket_json"; then
      echo "The existing state bucket is not the exact labeled bootstrap bucket." >&2
      exit 1
    fi
    echo "Repairing labels on the empty default bootstrap bucket after an explicit resume."
  fi
else
  gcloud storage buckets create "gs://${state_bucket}" \
    --project "$GCP_PROJECT_ID" \
    --location "$region" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi
gcloud storage buckets update "gs://${state_bucket}" \
  --versioning \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --update-labels=application=ontology-appliance,environment=dev,purpose=terraform-state,managed_by=bootstrap

terraform -chdir="$terraform_dir" init -reconfigure -backend-config=backend.hcl
state_resources=""
if ! state_resources="$(terraform -chdir="$terraform_dir" state list -no-color 2>&1)"; then
  if grep -Eiq 'no (stored )?state (snapshot )?(was )?found|no state file was found' <<<"$state_resources"; then
    state_resources=""
  else
    echo "$state_resources" >&2
    echo "Could not inspect remote Terraform state; refusing import." >&2
    exit 1
  fi
fi
project_state_address='module.platform.google_project.this[0]'
firebase_state_address='module.platform.google_firebase_project.this[0]'
compute_data_state_address='module.platform.data.google_compute_default_service_account.functions_build[0]'
storage_data_state_address='module.platform.data.google_storage_project_service_account.gcs[0]'
project_in_state=false
firebase_in_state=false

if [[ "$adopt_existing_firebase_project" == "true" ]]; then
  unexpected_state_resources="$(awk \
    -v project_address="$project_state_address" \
    -v firebase_address="$firebase_state_address" \
    -v compute_data_address="$compute_data_state_address" \
    -v storage_data_address="$storage_data_state_address" \
    'NF && $0 != project_address && $0 != firebase_address && \
      $0 != compute_data_address && $0 != storage_data_address' <<<"$state_resources")"
  if [[ -n "$unexpected_state_resources" ]]; then
    echo "Adoption requires empty state or only the confirmed project/Firebase resources and their expected read-only data sources." >&2
    echo "$unexpected_state_resources" >&2
    exit 1
  fi
fi

if grep -Fxq "$project_state_address" <<<"$state_resources"; then
  project_in_state=true
  state_project="$(terraform -chdir="$terraform_dir" state show -no-color \
    "$project_state_address" | awk -F'"' '/^[[:space:]]*project_id[[:space:]]*=/{print $2; exit}')"
  if [[ "$state_project" != "$GCP_PROJECT_ID" ]]; then
    echo "Remote state owns a different project; refusing to continue." >&2
    exit 1
  fi
  echo "Terraform already owns the project resource."
fi

if grep -Fxq "$firebase_state_address" <<<"$state_resources"; then
  firebase_in_state=true
  state_firebase_project="$(terraform -chdir="$terraform_dir" state show -no-color \
    "$firebase_state_address" | awk -F'"' '/^[[:space:]]*project[[:space:]]*=/{print $2; exit}')"
  if [[ "$state_firebase_project" != "$GCP_PROJECT_ID" ]]; then
    echo "Remote state owns a Firebase resource for a different project; refusing to continue." >&2
    exit 1
  fi
  if [[ "$project_in_state" != "true" ]]; then
    echo "Remote state contains Firebase ownership without project ownership; refusing to continue." >&2
    exit 1
  fi
  if [[ "$live_firebase_project" != "true" ]]; then
    echo "Remote state contains Firebase ownership but the live project lacks firebase=enabled." >&2
    exit 1
  fi
  echo "Terraform already owns the Firebase project resource."
fi

if [[ "$project_in_state" != "true" ]]; then
  if [[ -n "$state_resources" ]]; then
    echo "Remote state is non-empty but does not own the confirmed project; refusing import." >&2
    exit 1
  fi
  terraform -chdir="$terraform_dir" import "$project_state_address" "$GCP_PROJECT_ID"
fi

if [[ "$live_firebase_project" == "true" && "$firebase_in_state" != "true" ]]; then
  terraform -chdir="$terraform_dir" import "$firebase_state_address" "$GCP_PROJECT_ID"
fi

if [[ "$normalize_project_name" == "true" ]]; then
  gcloud projects update "$GCP_PROJECT_ID" --name="Ontology Appliance Dev"
  echo "Normalized the adopted project display name to Ontology Appliance Dev."
fi

echo "Bootstrap complete. Review this plan before applying anything else:"
echo "terraform -chdir=${terraform_dir} plan -out=dev.tfplan"
