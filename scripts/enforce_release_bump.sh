#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$("${SCRIPT_DIR}/preflight_repo_root.sh")"
cd "${REPO_ROOT}"

mapfile -t staged_files < <(git diff --cached --name-only --diff-filter=ACMR)
if [[ "${#staged_files[@]}" -eq 0 ]]; then
  exit 0
fi

is_code_change=0
has_version=0
has_release_notes=0

is_code_path() {
  case "$1" in
    core/*|scripts/*|web/*|services/*|shared/*|tentacles/*|orchestrator/*|tests/*)
      return 0
      ;;
    docker-compose*.yml|Dockerfile|didier_orchestrator.py|main.py|audio_service.py)
      return 0
      ;;
    *.py|*.js|*.ts|*.tsx|*.css|*.html|*.ps1|*.service|*.sh)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

for path in "${staged_files[@]}"; do
  [[ "${path}" == "VERSION" ]] && has_version=1
  [[ "${path}" == "RELEASE_NOTES.md" ]] && has_release_notes=1
  if is_code_path "${path}"; then
    is_code_change=1
  fi
done

if [[ "${is_code_change}" -eq 0 ]]; then
  exit 0
fi

if [[ "${has_version}" -eq 0 || "${has_release_notes}" -eq 0 ]]; then
  printf '\n[RELEASE GUARD] Code changes detected, but release metadata is missing in commit.\n' >&2
  printf '[RELEASE GUARD] Required staged files: VERSION and RELEASE_NOTES.md\n' >&2
  printf '[RELEASE GUARD] Suggested command: bash scripts/bump_release.sh "<release-id>" "<summary>"\n\n' >&2
  exit 1
fi

if git rev-parse --verify HEAD >/dev/null 2>&1; then
  if git diff --cached --quiet -- VERSION; then
    printf '\n[RELEASE GUARD] VERSION is staged but unchanged.\n' >&2
    exit 1
  fi
  if git diff --cached --quiet -- RELEASE_NOTES.md; then
    printf '\n[RELEASE GUARD] RELEASE_NOTES.md is staged but unchanged.\n' >&2
    exit 1
  fi
fi

new_version="$(git show :VERSION 2>/dev/null | tr -d '\r' | head -n 1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
if [[ -z "${new_version}" ]]; then
  printf '\n[RELEASE GUARD] VERSION cannot be empty.\n' >&2
  exit 1
fi

if ! [[ "${new_version}" =~ ^didier-v[0-9]+r[0-9]+.*$ ]]; then
  printf '\n[RELEASE GUARD] VERSION format must start with didier-v<major>r<revision>.\n' >&2
  printf '[RELEASE GUARD] Current staged VERSION: %s\n' "${new_version}" >&2
  exit 1
fi

if ! git show :RELEASE_NOTES.md 2>/dev/null | rg -n --fixed-strings "${new_version}" >/dev/null; then
  printf '\n[RELEASE GUARD] RELEASE_NOTES.md must include the staged VERSION: %s\n' "${new_version}" >&2
  exit 1
fi

printf '[RELEASE GUARD] OK: %s\n' "${new_version}"
