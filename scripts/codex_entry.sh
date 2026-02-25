#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$("${SCRIPT_DIR}/preflight_repo_root.sh")"

cd "${REPO_ROOT}"

if [[ "$#" -eq 0 ]]; then
  exec "${SHELL:-/bin/bash}" -l
fi

exec "$@"
