#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID.}"
: "${GATEWAY_URL:?Set GATEWAY_URL.}"
: "${INPUT_BUCKET:?Set INPUT_BUCKET.}"

require_app_hosting="${REQUIRE_APP_HOSTING:-true}"
case "$require_app_hosting" in
  true)
    : "${APP_HOSTING_URL:?Set APP_HOSTING_URL.}"
    [[ "$APP_HOSTING_URL" == https://* ]] || {
      echo "APP_HOSTING_URL must use HTTPS." >&2
      exit 2
    }
    ;;
  false) ;;
  *)
    echo "REQUIRE_APP_HOSTING must be true or false." >&2
    exit 2
    ;;
esac

region="${GCP_REGION:-europe-west4}"
service="${GATEWAY_SERVICE:-oa-dev-semantic-gateway}"
expected_publication_state="${EXPECTED_PUBLICATION_STATE:-CANDIDATE}"

case "$expected_publication_state" in
  CANDIDATE)
    expected_serving_mode="DEMO_ONLY"
    expected_is_published=false
    ;;
  PUBLISHED)
    expected_serving_mode="ACTIVE"
    expected_is_published=true
    ;;
  *)
    echo "EXPECTED_PUBLICATION_STATE must be CANDIDATE or PUBLISHED." >&2
    exit 2
    ;;
esac

identity_token="$(gcloud auth print-identity-token --audiences="$GATEWAY_URL")"
health="$(curl --fail --silent --show-error \
  --header "Authorization: Bearer ${identity_token}" \
  "${GATEWAY_URL%/}/healthz")"
jq -e \
  --arg state "$expected_publication_state" \
  --arg serving "$expected_serving_mode" \
  --argjson published "$expected_is_published" \
  '.status == "ok" and .publicationState == $state and
   .servingMode == $serving and .isPublished == $published' \
  <<<"$health" >/dev/null
if [[ -n "${EXPECTED_ONTOLOGY_VERSION:-}" ]]; then
  jq -e --arg version "$EXPECTED_ONTOLOGY_VERSION" \
    '.ontologyVersion == $version' <<<"$health" >/dev/null
fi

unauthenticated_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "${GATEWAY_URL%/}/healthz")"
[[ "$unauthenticated_status" == "401" || "$unauthenticated_status" == "403" ]] || {
  echo "Expected Cloud Run IAM denial, got HTTP $unauthenticated_status." >&2
  exit 1
}

application_auth_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --request POST \
  --header "X-Serverless-Authorization: Bearer ${identity_token}" \
  --header 'Authorization: Bearer deliberately-invalid-firebase-session' \
  --header 'Content-Type: application/json' \
  --data '{"term":"Party"}' \
  "${GATEWAY_URL%/}/v1/resolve")"
[[ "$application_auth_status" == "401" ]] || {
  echo "Expected application authentication denial, got HTTP $application_auth_status." >&2
  exit 1
}

for function_name in sourceObjectFinalized proposalCreated processIngestionTask \
  processVerificationTask enqueueDailyDriftChecks processDriftTask; do
  gcloud functions describe "$function_name" \
    --gen2 \
    --project "$GCP_PROJECT_ID" \
    --region "$region" \
    --format='value(state)' | grep -Fxq ACTIVE
done

for queue_name in processIngestionTask processVerificationTask processDriftTask; do
  gcloud tasks queues describe "$queue_name" \
    --project "$GCP_PROJECT_ID" \
    --location "$region" \
    --format='value(state)' | grep -Fxq RUNNING
done

if [[ "$require_app_hosting" == "true" ]]; then
  curl --fail --silent --show-error --location --output /dev/null "$APP_HOSTING_URL"
fi

firestore_url="https://firestore.googleapis.com/v1/projects/${GCP_PROJECT_ID}/databases/(default)/documents"

firestore_document() {
  local path="$1"
  local token
  token="$(gcloud auth print-access-token)"
  curl --fail --silent --show-error \
    --header "Authorization: Bearer ${token}" \
    "${firestore_url}/${path}" 2>/dev/null
}

firestore_query() {
  local query_json="$1"
  local token
  token="$(gcloud auth print-access-token)"
  curl --fail --silent --show-error \
    --request POST \
    --header "Authorization: Bearer ${token}" \
    --header 'Content-Type: application/json' \
    --data "$query_json" \
    "${firestore_url}/tenants/demo-bank:runQuery" 2>/dev/null
}

tenant_document="$(firestore_document 'tenants/demo-bank')"
jq -e '
  .fields.tenantId.stringValue == "demo-bank" and
  .fields.status.stringValue == "ACTIVE" and
  .fields.dataClassification.stringValue == "SYNTHETIC_ONLY" and
  .fields.managedBy.stringValue == "terraform"
' >/dev/null <<<"$tenant_document"
tenant_audit="$(firestore_document 'tenants/demo-bank/auditEvents/terraform-bootstrap-v1')"
jq -e '
  .fields.eventType.stringValue == "TENANT_BOOTSTRAPPED" and
  .fields.tenantId.stringValue == "demo-bank" and
  .fields.status.stringValue == "SUCCEEDED" and
  .fields.actorId.stringValue == "terraform"
' >/dev/null <<<"$tenant_audit"

if [[ "${RUN_FUNCTIONS_E2E:-true}" == "true" ]]; then
  smoke_day="$(date -u +%Y%m%d)"
  scheduled_day="$(date -u +%Y-%m-%d)"
  smoke_id="${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-0}-$(date -u +%s)"
  source_id="smoke-${smoke_day}"
  object_prefix="tenants/demo-bank/uploads/${source_id}"
  baseline_object="${object_prefix}/baseline-${smoke_id}.csv"
  changed_object="${object_prefix}/changed-${smoke_id}.csv"
  smoke_dir="$(mktemp -d)"
  trap 'rm -rf "$smoke_dir"' EXIT
  printf 'id,name\n1,Alice\n' >"${smoke_dir}/baseline.csv"
  printf 'id,name\n1,Alice\n2,Bob\n' >"${smoke_dir}/changed.csv"
  baseline_sha="$(sha256sum "${smoke_dir}/baseline.csv" | awk '{print $1}')"
  changed_sha="$(sha256sum "${smoke_dir}/changed.csv" | awk '{print $1}')"
  wait_for_profile() {
    local expected_object="$1"
    local expected_sha="$2"
    local expected_changed="$3"
    local profile=""
    for _attempt in {1..36}; do
      profile="$(firestore_document "tenants/demo-bank/sourceProfiles/${source_id}" || true)"
      if [[ -n "$profile" ]] && jq -e \
        --arg object "$expected_object" \
        --arg digest "$expected_sha" \
        --arg changed "$expected_changed" \
        '.fields.objectName.stringValue == $object and
         .fields.sha256.stringValue == $digest and
         ($changed == "any" or
          .fields.contentChanged.booleanValue == ($changed == "true"))' \
        <<<"$profile" >/dev/null; then
        return 0
      fi
      sleep 5
    done
    echo "Timed out waiting for the exact source profile for ${expected_object}." >&2
    return 1
  }

  upload_smoke_object() {
    local file="$1"
    local object="$2"
    gcloud storage cp "$file" "gs://${INPUT_BUCKET}/${object}" \
      --project "$GCP_PROJECT_ID" \
      --content-type=text/csv \
      --custom-metadata="tenantId=demo-bank,uploadedBy=cloud-smoke" \
      --if-generation-match=0
  }

  wait_for_terminal_proposal() {
    local source_locator="$1"
    local expected_kind="$2"
    local query_json result proposal
    query_json="$(jq -nc --arg locator "$source_locator" '{
      structuredQuery: {
        from: [{collectionId: "proposals"}],
        where: {fieldFilter: {
          field: {fieldPath: "source_locator"},
          op: "EQUAL",
          value: {stringValue: $locator}
        }},
        limit: 2
      }
    }')"
    for _attempt in {1..36}; do
      result="$(firestore_query "$query_json" || true)"
      proposal="$(jq -c '[.[] | .document // empty] | if length == 1 then .[0] else empty end' <<<"${result:-[]}")"
      if [[ -n "$proposal" ]] && jq -e \
        --arg kind "$expected_kind" \
        '.fields.kind.stringValue == $kind and
         .fields.status.stringValue == "HUMAN_REVIEW" and
         (.fields.verificationRunId.stringValue | length) > 0 and
         (.fields.proposal_id.stringValue | length) > 0' \
        <<<"$proposal" >/dev/null; then
        printf '%s\n' "$proposal"
        return 0
      fi
      sleep 5
    done
    echo "Timed out waiting for a terminal ${expected_kind} proposal at ${source_locator}." >&2
    return 1
  }

  verify_terminal_run() {
    local proposal_document="$1"
    local run_id proposal_id run gates
    run_id="$(jq -er '.fields.verificationRunId.stringValue' <<<"$proposal_document")"
    proposal_id="$(jq -er '.fields.proposal_id.stringValue' <<<"$proposal_document")"
    run="$(firestore_document "tenants/demo-bank/verificationRuns/${run_id}")"
    jq -e \
      --arg run "$run_id" \
      --arg proposal "$proposal_id" \
      '.fields.verification_run_id.stringValue == $run and
       .fields.proposal_id.stringValue == $proposal and
       .fields.status.stringValue == "HUMAN_REVIEW" and
       (.fields.gate_result_ids.arrayValue.values | length) == 8 and
       .fields.models.mapValue.fields.mode.stringValue == "disabled"' \
      <<<"$run" >/dev/null
    gates="$(firestore_document "tenants/demo-bank/verificationRuns/${run_id}/gateResults?pageSize=20")"
    jq -e '
      (.documents | length) == 8 and
      ([.documents[].fields.gate.stringValue] | unique | length) == 8 and
      any(.documents[]; .fields.gate.stringValue == "HUMAN_ADJUDICATION" and
        .fields.status.stringValue == "REVIEW_REQUIRED")
    ' <<<"$gates" >/dev/null
  }

  upload_smoke_object "${smoke_dir}/baseline.csv" "$baseline_object"
  # A previous same-day smoke may make this transition true; the exact hash and
  # object name still prove that this upload was profiled.
  wait_for_profile "$baseline_object" "$baseline_sha" any

  upload_smoke_object "${smoke_dir}/changed.csv" "$changed_object"
  wait_for_profile "$changed_object" "$changed_sha" true
  changed_generation="$(gcloud storage objects describe \
    "gs://${INPUT_BUCKET}/${changed_object}" \
    --project "$GCP_PROJECT_ID" --format='value(generation)')"
  [[ "$changed_generation" =~ ^[0-9]+$ ]]
  changed_locator="gs://${INPUT_BUCKET}/${changed_object}#generation=${changed_generation}"
  ingestion_proposal="$(wait_for_terminal_proposal "$changed_locator" assertion)"
  verify_terminal_run "$ingestion_proposal"

  drift_execution_id="$(node functions/scripts/enqueue-drift-smoke.cjs \
    "$GCP_PROJECT_ID" "$region" demo-bank "$scheduled_day" "$smoke_id")"
  [[ "$drift_execution_id" =~ ^[0-9a-f]{64}$ ]]
  drift_check=""
  for _attempt in {1..36}; do
    drift_check="$(firestore_document "tenants/demo-bank/driftChecks/${scheduled_day}" || true)"
    if [[ -n "$drift_check" ]] && jq -e \
      --arg execution "$drift_execution_id" \
      --arg source "$source_id" \
      '.fields.executionId.stringValue == $execution and
       .fields.status.stringValue == "CHANGES_REQUIRE_REVIEW" and
       any(.fields.changedSources.arrayValue.values[]?; .stringValue == $source)' \
      <<<"$drift_check" >/dev/null; then
      break
    fi
    drift_check=""
    sleep 5
  done
  [[ -n "$drift_check" ]] || {
    echo "Timed out waiting for the exact drift result ${drift_execution_id}." >&2
    exit 1
  }
  drift_proposal_id="$(jq -er '.fields.proposalId.stringValue' <<<"$drift_check")"
  drift_proposal=""
  for _attempt in {1..36}; do
    drift_proposal="$(firestore_document "tenants/demo-bank/proposals/${drift_proposal_id}" || true)"
    if [[ -n "$drift_proposal" ]] && jq -e \
      --arg proposal "$drift_proposal_id" \
      --arg source "$source_id" \
      '.fields.proposal_id.stringValue == $proposal and
       .fields.kind.stringValue == "drift" and
       .fields.status.stringValue == "HUMAN_REVIEW" and
       any(.fields.evidence.arrayValue.values[]?;
         .mapValue.fields.source_id.stringValue == $source)' \
      <<<"$drift_proposal" >/dev/null; then
      break
    fi
    drift_proposal=""
    sleep 5
  done
  [[ -n "$drift_proposal" ]] || {
    echo "Timed out waiting for drift proposal ${drift_proposal_id}." >&2
    exit 1
  }
  verify_terminal_run "$drift_proposal"
fi

gcloud run revisions list \
  --service "$service" \
  --project "$GCP_PROJECT_ID" \
  --region "$region" \
  --limit=2 \
  --format='table(metadata.name,status.conditions[0].status,metadata.creationTimestamp)'

echo "Cloud smoke tests passed for $GCP_PROJECT_ID."
