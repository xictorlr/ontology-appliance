#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT

cat >"$test_dir/gcloud" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${GCLOUD_CALL_LOG:?}"
case "$1 $2 $3" in
  "storage objects describe") printf '42\n' ;;
  "storage cat gs://"*)
    printf '%s\n' '{"manifestObject":"tenants/demo-bank/ontology/releases/v1/manifest.json","manifestSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","bundleVersion":"2026.07.1","operation":"PUBLISH"}'
    ;;
  "run services describe")
    if [[ " $* " == *" --format=json "* ]]; then
      printf '%s\n' '{"spec":{"template":{"spec":{"containers":[{"env":[{"name":"OA_ACTIVE_POINTER_GENERATION","value":"42"}]}]}}},"status":{"latestReadyRevisionName":"revision-2","traffic":[{"percent":100,"revisionName":"revision-2"}],"url":"https://gateway.example"}}'
    else
      printf 'revision-1\n'
    fi
    ;;
  "run revisions describe") printf '%s\n' "${REVISION_DIGEST:?}" ;;
  "run services update") ;;
  "run services update-traffic") ;;
  "auth print-identity-token "*) printf 'identity-token\n' ;;
  *) echo "Unexpected gcloud call: $*" >&2; exit 64 ;;
esac
EOF

cat >"$test_dir/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' '{"status":"ok","artifactStatus":"READY","ontologyVersion":"2026.07.1","publicationState":"PUBLISHED","servingMode":"ACTIVE","isPublished":true}'
EOF
chmod +x "$test_dir/gcloud" "$test_dir/curl"

digest="europe-west4-docker.pkg.dev/demo/repo/gateway@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
env PATH="$test_dir:$PATH" GCLOUD_CALL_LOG="$test_dir/calls" REVISION_DIGEST="$digest" \
  GCP_PROJECT_ID=demo ARTIFACT_BUCKET=artifacts EXPECTED_POINTER_GENERATION=42 \
  EXPECTED_MANIFEST_OBJECT=tenants/demo-bank/ontology/releases/v1/manifest.json \
  EXPECTED_MANIFEST_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  EXPECTED_ONTOLOGY_VERSION=2026.07.1 \
  bash "$repo_root/scripts/rollout_semantic_gateway.sh" >/dev/null
grep -F -- "--image $digest" "$test_dir/calls" >/dev/null

if env PATH="$test_dir:$PATH" GCLOUD_CALL_LOG="$test_dir/bad-calls" REVISION_DIGEST="gateway:mutable" \
  GCP_PROJECT_ID=demo ARTIFACT_BUCKET=artifacts EXPECTED_POINTER_GENERATION=42 \
  EXPECTED_MANIFEST_OBJECT=tenants/demo-bank/ontology/releases/v1/manifest.json \
  EXPECTED_MANIFEST_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  EXPECTED_ONTOLOGY_VERSION=2026.07.1 \
  bash "$repo_root/scripts/rollout_semantic_gateway.sh" >/dev/null 2>&1; then
  echo "Expected a mutable executable image reference to be rejected." >&2
  exit 1
fi

echo "Semantic rollout digest tests passed."
