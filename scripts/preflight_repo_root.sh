#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

required_paths=(
  "core"
  "web"
  "scripts"
  "VERSION"
)

required_files=(
  "core/api.py"
  "scripts/run_picobot_bridge.py"
)

assert_repo_layout() {
  local missing=0
  local item
  for item in "${required_paths[@]}"; do
    if [[ ! -e "${REPO_ROOT}/${item}" ]]; then
      printf '[FATAL] required path missing: %s\n' "${REPO_ROOT}/${item}" >&2
      missing=1
    fi
  done
  for item in "${required_files[@]}"; do
    if [[ ! -f "${REPO_ROOT}/${item}" ]]; then
      printf '[FATAL] required file missing: %s\n' "${REPO_ROOT}/${item}" >&2
      missing=1
    fi
  done
  if [[ "${missing}" -ne 0 ]]; then
    return 2
  fi
}

assert_repo_layout

mode="${1:-print}"
case "${mode}" in
  print)
    printf '%s\n' "${REPO_ROOT}"
    ;;
  --cd)
    cd "${REPO_ROOT}"
    pwd -P
    ;;
  --assert-cwd)
    current_pwd="$(pwd -P)"
    if [[ "${current_pwd}" != "${REPO_ROOT}" ]]; then
      printf '[FATAL] wrong working directory: %s\n' "${current_pwd}" >&2
      printf '[FATAL] expected repository root: %s\n' "${REPO_ROOT}" >&2
      exit 3
    fi
    printf '[OK] repo root: %s\n' "${REPO_ROOT}"
    ;;
  *)
    printf 'Usage: %s [print|--cd|--assert-cwd]\n' "$0" >&2
    exit 64
    ;;
esac
