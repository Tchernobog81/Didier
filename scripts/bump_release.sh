#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$("${SCRIPT_DIR}/preflight_repo_root.sh")"
cd "${REPO_ROOT}"

current_version="$(tr -d '\r' < VERSION | head -n 1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
release_id="${1:-}"
summary="${2:-Code update}"
timestamp_utc="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

next_release() {
  local current="$1"
  if [[ "${current}" =~ ^didier-v([0-9]+)r([0-9]+)(.*)$ ]]; then
    local major="${BASH_REMATCH[1]}"
    local revision="${BASH_REMATCH[2]}"
    local rest="${BASH_REMATCH[3]}"
    local next_revision=$((revision + 1))
    printf 'didier-v%sr%s%s\n' "${major}" "${next_revision}" "${rest}"
    return 0
  fi
  printf 'didier-v4r1-%s\n' "$(date -u '+%Y-%m-%d')"
}

if [[ -z "${release_id}" ]]; then
  release_id="$(next_release "${current_version}")"
fi

if ! [[ "${release_id}" =~ ^didier-v[0-9]+r[0-9]+.*$ ]]; then
  printf 'Invalid release id: %s\n' "${release_id}" >&2
  printf 'Expected format: didier-v<major>r<revision>-...\n' >&2
  exit 64
fi

printf '%s\n' "${release_id}" > VERSION

if [[ ! -f RELEASE_NOTES.md ]]; then
  cat > RELEASE_NOTES.md <<'EOF'
# Release Notes

EOF
fi

{
  printf '## %s - %s\n' "${release_id}" "${timestamp_utc}"
  printf -- '- %s\n' "${summary}"
  printf '\n'
} >> RELEASE_NOTES.md

git add VERSION RELEASE_NOTES.md
printf '[release] VERSION=%s\n' "${release_id}"
