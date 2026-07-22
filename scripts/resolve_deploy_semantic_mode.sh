#!/usr/bin/env bash
set -euo pipefail

# Resolves the gateway mode after cloud authentication. Automatic deployments
# preserve a published ontology whenever the governed active pointer exists.

: "${ARTIFACT_BUCKET:?Set ARTIFACT_BUCKET.}"
: "${DEPLOYMENT_SCOPE:?Set DEPLOYMENT_SCOPE to bootstrap or full.}"
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID.}"
: "${GITHUB_ENV:?Set GITHUB_ENV to the GitHub Actions environment file.}"

requested_mode="${REQUESTED_SEMANTIC_MODE:-}"
pointer_name="tenants/demo-bank/ontology/active.json"
pointer_uri="gs://${ARTIFACT_BUCKET}/${pointer_name}"

[[ "$ARTIFACT_BUCKET" =~ ^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$ ]] || {
  echo "ARTIFACT_BUCKET is not a valid conservative Cloud Storage bucket name." >&2
  exit 2
}
case "$DEPLOYMENT_SCOPE" in
  bootstrap | full) ;;
  *) echo "DEPLOYMENT_SCOPE must be bootstrap or full." >&2; exit 2 ;;
esac
case "$requested_mode" in
  "" | candidate | published) ;;
  *) echo "REQUESTED_SEMANTIC_MODE must be empty, candidate, or published." >&2; exit 2 ;;
esac

# Listing an exact object URI returns an empty successful result when it is
# absent. Permission/API failures remain fatal under set -e.
listed_pointer="$(gcloud storage objects list "$pointer_uri" \
  --project="$GCP_PROJECT_ID" \
  --limit=2 \
  --format='value(name)')"

case "$listed_pointer" in
  "")
    pointer_exists=false
    active_pointer_generation=""
    ;;
  "$pointer_name")
    pointer_exists=true
    active_pointer_generation="$(gcloud storage objects describe "$pointer_uri" \
      --project="$GCP_PROJECT_ID" \
      --format='value(generation)')"
    [[ "$active_pointer_generation" =~ ^[0-9]+$ ]] || {
      echo "Active pointer generation is missing or invalid." >&2
      exit 1
    }
    ;;
  *)
    echo "Active-pointer lookup returned an unexpected object set; refusing deployment." >&2
    exit 1
    ;;
esac

if [[ -z "$requested_mode" ]]; then
  if [[ "$pointer_exists" == "true" ]]; then
    semantic_mode="published"
  else
    semantic_mode="candidate"
  fi
elif [[ "$requested_mode" == "published" && "$pointer_exists" != "true" ]]; then
  echo "Published mode requires the governed active pointer $pointer_uri." >&2
  exit 1
elif [[ "$requested_mode" == "candidate" && "$pointer_exists" == "true" ]]; then
  echo "Refusing to downgrade a published ontology to the demo candidate; use governed rollback." >&2
  exit 1
else
  semantic_mode="$requested_mode"
fi

if [[ "$DEPLOYMENT_SCOPE" == "bootstrap" && "$semantic_mode" != "candidate" ]]; then
  echo "Bootstrap cannot activate or preserve published semantics." >&2
  exit 1
fi

if [[ "$semantic_mode" == "published" ]]; then
  expected_publication_state="PUBLISHED"
else
  expected_publication_state="CANDIDATE"
fi

{
  printf 'SEMANTIC_MODE=%s\n' "$semantic_mode"
  printf 'EXPECTED_PUBLICATION_STATE=%s\n' "$expected_publication_state"
  printf 'ACTIVE_POINTER_GENERATION=%s\n' "$active_pointer_generation"
} >>"$GITHUB_ENV"

echo "Resolved semantic deployment mode: $semantic_mode."
