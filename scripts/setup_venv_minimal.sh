#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --venv)
      VENV_DIR="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

MANDATORY_PKGS=(
  flask
  requests
  soundfile
  kokoro-onnx
  psutil
  numpy
)

# Optional Hailo stack: attempted only, non-blocking on failure.
OPTIONAL_PKGS=(
  hailo-tappas
  hailo-platform
)

run() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] $*"
    return 0
  fi
  "$@"
}

echo "== Didier venv setup (minimal) =="
echo "root: ${ROOT_DIR}"
echo "venv: ${VENV_DIR}"
echo "python: ${PYTHON_BIN}"

if [[ ! -d "${VENV_DIR}" ]]; then
  run "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

PIP="${VENV_DIR}/bin/pip"
PY="${VENV_DIR}/bin/python"

if [[ ! -x "${PIP}" || ! -x "${PY}" ]]; then
  echo "venv incomplete: ${VENV_DIR}" >&2
  exit 1
fi

run "${PIP}" install --upgrade pip setuptools wheel
run "${PIP}" install "${MANDATORY_PKGS[@]}"

for pkg in "${OPTIONAL_PKGS[@]}"; do
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] ${PIP} install ${pkg} (optional)"
    continue
  fi
  if ! "${PIP}" install "${pkg}"; then
    echo "warn: optional package unavailable: ${pkg}" >&2
  fi
done

run "${PY}" - <<'PY'
import importlib
mods = ["flask", "requests", "soundfile", "kokoro_onnx", "psutil", "numpy"]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
if missing:
    raise SystemExit(f"missing imports: {missing}")
print("imports: ok")
PY

echo "== Didier venv setup done =="
