#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID.}"
: "${ARTIFACT_BUCKET:?Set ARTIFACT_BUCKET.}"
: "${EXPECTED_POINTER_GENERATION:?Set EXPECTED_POINTER_GENERATION.}"
: "${EXPECTED_MANIFEST_OBJECT:?Set EXPECTED_MANIFEST_OBJECT.}"
: "${EXPECTED_MANIFEST_SHA256:?Set EXPECTED_MANIFEST_SHA256.}"
: "${EXPECTED_ONTOLOGY_VERSION:?Set EXPECTED_ONTOLOGY_VERSION.}"

region="${GCP_REGION:-europe-west4}"
service="${GATEWAY_SERVICE:-oa-dev-semantic-gateway}"
pointer_path="tenants/demo-bank/ontology/active.json"
pointer_uri="gs://${ARTIFACT_BUCKET}/${pointer_path}"

[[ "$EXPECTED_POINTER_GENERATION" =~ ^[0-9]+$ ]] || {
  echo "EXPECTED_POINTER_GENERATION must be numeric." >&2
  exit 2
}
[[ "$EXPECTED_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  echo "EXPECTED_MANIFEST_SHA256 must be a lowercase SHA-256 digest." >&2
  exit 2
}

observed_generation="$(gcloud storage objects describe "$pointer_uri" \
  --project "$GCP_PROJECT_ID" --format='value(generation)')"
[[ "$observed_generation" == "$EXPECTED_POINTER_GENERATION" ]] || {
  echo "Active pointer changed before rollout: expected generation $EXPECTED_POINTER_GENERATION, observed $observed_generation." >&2
  exit 1
}
pointer="$(gcloud storage cat "$pointer_uri" --project "$GCP_PROJECT_ID")"
jq -e \
  --arg object "$EXPECTED_MANIFEST_OBJECT" \
  --arg digest "$EXPECTED_MANIFEST_SHA256" \
  --arg version "$EXPECTED_ONTOLOGY_VERSION" \
  '.manifestObject == $object and .manifestSha256 == $digest and
   .bundleVersion == $version and (.operation == "PUBLISH" or .operation == "ROLLBACK")' \
  <<<"$pointer" >/dev/null

current_revision="$(gcloud run services describe "$service" \
  --project "$GCP_PROJECT_ID" --region "$region" \
  --format='value(status.latestReadyRevisionName)')"
[[ -n "$current_revision" ]] || {
  echo "Semantic Gateway must already exist before semantic activation." >&2
  exit 1
}
current_image_digest="$(gcloud run revisions describe "$current_revision" \
  --project "$GCP_PROJECT_ID" --region "$region" \
  --format='value(status.imageDigest)')"
[[ "$current_image_digest" == *@sha256:* ]] || {
  echo "Could not resolve the immutable image digest for revision $current_revision." >&2
  exit 1
}

# Changing a revision-scoped value forces all traffic onto fresh processes that
# resolve and validate the stable pointer during startup. The Publisher never
# receives Cloud Run permissions; this script runs under the deploy identity.
gcloud run services update "$service" \
  --project "$GCP_PROJECT_ID" \
  --region "$region" \
  --image "$current_image_digest" \
  --update-env-vars "ONTOLOGY_ARTIFACT_BUCKET=${ARTIFACT_BUCKET},ONTOLOGY_ARTIFACT_POINTER=${pointer_path},OA_ALLOW_DEMO_CANDIDATE=false,OA_ACTIVE_POINTER_GENERATION=${EXPECTED_POINTER_GENERATION}" \
  --update-labels "oa-pointer-generation=${EXPECTED_POINTER_GENERATION}" \
  --quiet
gcloud run services update-traffic "$service" \
  --project "$GCP_PROJECT_ID" \
  --region "$region" \
  --to-latest \
  --quiet

service_json="$(gcloud run services describe "$service" \
  --project "$GCP_PROJECT_ID" --region "$region" --format=json)"
latest_revision="$(jq -er '.status.latestReadyRevisionName' <<<"$service_json")"
latest_image_digest="$(gcloud run revisions describe "$latest_revision" \
  --project "$GCP_PROJECT_ID" --region "$region" \
  --format='value(status.imageDigest)')"
[[ "$latest_image_digest" == "$current_image_digest" ]] || {
  echo "Semantic rollout changed executable image digest." >&2
  exit 1
}
jq -e \
  --arg revision "$latest_revision" \
  --arg generation "$EXPECTED_POINTER_GENERATION" \
  '([.spec.template.spec.containers[0].env[] |
      select(.name == "OA_ACTIVE_POINTER_GENERATION") | .value] == [$generation]) and
   (.status.traffic | length == 1) and .status.traffic[0].percent == 100 and
   (.status.traffic[0].revisionName == $revision or .status.traffic[0].latestRevision == true)' \
  <<<"$service_json" >/dev/null

gateway_url="$(jq -er '.status.url' <<<"$service_json")"
identity_token="$(gcloud auth print-identity-token --audiences="$gateway_url")"
health=""
for _attempt in {1..12}; do
  if health="$(curl --fail --silent --show-error \
    --header "Authorization: Bearer ${identity_token}" \
    "${gateway_url%/}/healthz" 2>/dev/null)" &&
    jq -e \
      --arg version "$EXPECTED_ONTOLOGY_VERSION" \
      '.status == "ok" and .artifactStatus == "READY" and
       .ontologyVersion == $version and .publicationState == "PUBLISHED" and
       .servingMode == "ACTIVE" and .isPublished == true' \
      <<<"$health" >/dev/null; then
    break
  fi
  health=""
  sleep 5
done
[[ -n "$health" ]] || {
  echo "The fresh gateway revision did not load the expected published ontology." >&2
  exit 1
}

echo "Gateway revision ${latest_revision} serves ${EXPECTED_ONTOLOGY_VERSION} from pointer generation ${EXPECTED_POINTER_GENERATION}."
