#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$("${SCRIPT_DIR}/preflight_repo_root.sh")"
cd "${REPO_ROOT}"

mkdir -p .githooks
chmod +x .githooks/pre-commit scripts/enforce_release_bump.sh scripts/preflight_repo_root.sh scripts/bump_release.sh scripts/codex_entry.sh
git config core.hooksPath .githooks

printf '[hooks] core.hooksPath=%s\n' "$(git config --get core.hooksPath)"
printf '[hooks] pre-commit guard installed.\n'
