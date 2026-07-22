#!/usr/bin/env bash
set -euo pipefail

expected_sha="${EXPECTED_RELEASE_SHA:-${GITHUB_SHA:-}}"
remote="${RELEASE_GIT_REMOTE:-origin}"

[[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "EXPECTED_RELEASE_SHA must be the full lowercase SHA-1 checked out for release." >&2
  exit 2
}
[[ "$remote" =~ ^[A-Za-z0-9._/-]+$ ]] || {
  echo "RELEASE_GIT_REMOTE contains unsupported characters." >&2
  exit 2
}

checked_out_sha="$(git rev-parse HEAD)"
[[ "$checked_out_sha" == "$expected_sha" ]] || {
  echo "Release checkout drift: expected $expected_sha, checked out $checked_out_sha." >&2
  exit 1
}

remote_line="$(git ls-remote --exit-code "$remote" refs/heads/main)"
read -r current_main_sha current_main_ref trailing <<<"$remote_line"
[[ -z "${trailing:-}" && "$current_main_ref" == "refs/heads/main" ]] || {
  echo "Could not resolve exactly one current main ref from $remote." >&2
  exit 1
}
[[ "$current_main_sha" == "$expected_sha" ]] || {
  echo "Historical release refused: $expected_sha is not current main ($current_main_sha)." >&2
  exit 1
}

echo "Release revision $expected_sha is the current protected main head."
