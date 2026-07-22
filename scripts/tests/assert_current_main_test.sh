#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT

cat >"$test_dir/git" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  rev-parse)
    printf '%s\n' "${LOCAL_SHA:?}"
    ;;
  ls-remote)
    printf '%s\trefs/heads/main\n' "${REMOTE_SHA:?}"
    ;;
  *)
    exit 64
    ;;
esac
EOF
chmod +x "$test_dir/git"

release_sha="0123456789abcdef0123456789abcdef01234567"
other_sha="89abcdef0123456789abcdef0123456789abcdef"

env PATH="$test_dir:$PATH" LOCAL_SHA="$release_sha" REMOTE_SHA="$release_sha" \
  EXPECTED_RELEASE_SHA="$release_sha" bash "$repo_root/scripts/assert_current_main.sh" >/dev/null

if env PATH="$test_dir:$PATH" LOCAL_SHA="$release_sha" REMOTE_SHA="$other_sha" \
  EXPECTED_RELEASE_SHA="$release_sha" bash "$repo_root/scripts/assert_current_main.sh" >/dev/null 2>&1; then
  echo "Expected a historical release revision to be rejected." >&2
  exit 1
fi

if env PATH="$test_dir:$PATH" LOCAL_SHA="$other_sha" REMOTE_SHA="$release_sha" \
  EXPECTED_RELEASE_SHA="$release_sha" bash "$repo_root/scripts/assert_current_main.sh" >/dev/null 2>&1; then
  echo "Expected checkout drift to be rejected." >&2
  exit 1
fi

echo "Current-main release guard tests passed."
