#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---check}"

SSD_MOUNT="${SSD_MOUNT:-/mnt/didier_ssd}"
DIDIER_ROOT="${DIDIER_ROOT:-${SSD_MOUNT}/didier}"
DOCKER_ROOT="${DOCKER_ROOT:-${SSD_MOUNT}/docker_root}"
USER_HOME="${USER_HOME:-/home/tchernobog}"
DOCKER_DAEMON_JSON="${DOCKER_DAEMON_JSON:-/etc/docker/daemon.json}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

FAILED=0

usage() {
  cat <<EOF
Usage: $0 [--check|--fix]

  --check   Verify SSD migration health (default, no writes)
  --fix     Repair common SSD migration drifts (requires root)
EOF
}

info() {
  echo "[INFO] $*"
}

ok() {
  echo "[ OK ] $*"
}

warn() {
  echo "[WARN] $*"
}

fail() {
  echo "[FAIL] $*"
  FAILED=1
}

must_be_root_for_fix() {
  if [ "$MODE" = "--fix" ] && [ "${EUID}" -ne 0 ]; then
    echo "Mode --fix requires root (sudo)." >&2
    exit 1
  fi
}

path_target() {
  local path="$1"
  readlink -f "$path" 2>/dev/null || true
}

copy_tree() {
  local src="$1"
  local dst="$2"
  if command -v rsync >/dev/null 2>&1; then
    rsync -aHAX "${src}/" "${dst}/"
  else
    cp -a "${src}/." "${dst}/"
  fi
}

ensure_dir() {
  local dir="$1"
  if [ "$MODE" = "--fix" ]; then
    mkdir -p "$dir"
  fi
  if [ -d "$dir" ]; then
    ok "Directory present: $dir"
  else
    fail "Directory missing: $dir"
  fi
}

check_mount() {
  if mountpoint -q "$SSD_MOUNT"; then
    ok "SSD mounted on $SSD_MOUNT"
  else
    fail "SSD is not mounted on $SSD_MOUNT"
  fi
}

sync_and_link() {
  local src="$1"
  local dst="$2"
  local label="$3"

  ensure_dir "$(dirname "$dst")"
  ensure_dir "$dst"

  if [ -L "$src" ]; then
    local current
    current="$(path_target "$src")"
    if [ "$current" = "$dst" ]; then
      ok "$label link already correct: $src -> $dst"
      return 0
    fi
    if [ "$MODE" = "--fix" ]; then
      ln -sfn "$dst" "$src"
      ok "$label relinked: $src -> $dst"
      return 0
    fi
    fail "$label wrong link target: $src -> ${current:-<none>} (expected $dst)"
    return 0
  fi

  if [ -e "$src" ] && [ ! -d "$src" ]; then
    if [ "$MODE" = "--fix" ]; then
      mv "$src" "${src}.bak-${TIMESTAMP}"
      ln -sfn "$dst" "$src"
      ok "$label moved non-directory source then linked: $src -> $dst"
      return 0
    fi
    fail "$label source is not a directory/symlink: $src"
    return 0
  fi

  if [ -d "$src" ]; then
    if [ "$MODE" = "--fix" ]; then
      info "$label syncing $src -> $dst"
      copy_tree "$src" "$dst"
      mv "$src" "${src}.bak-${TIMESTAMP}"
      ln -sfn "$dst" "$src"
      ok "$label migrated and linked: $src -> $dst"
      return 0
    fi
    fail "$label is still a directory (not symlink): $src"
    return 0
  fi

  if [ "$MODE" = "--fix" ]; then
    ln -sfn "$dst" "$src"
    ok "$label source missing, link created: $src -> $dst"
    return 0
  fi
  fail "$label missing source/link: $src"
}

docker_services_stop() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  systemctl stop docker.socket || true
  systemctl stop docker || true
  systemctl stop containerd || true
}

docker_services_start() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  systemctl start containerd || true
  systemctl start docker || true
}

ensure_docker_daemon_json() {
  if [ "$MODE" != "--fix" ]; then
    if command -v python3 >/dev/null 2>&1 && [ -f "$DOCKER_DAEMON_JSON" ]; then
      local current_root
      current_root="$(
        python3 - <<'PY' "$DOCKER_DAEMON_JSON"
import json, sys
path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh) or {}
except Exception:
    print("")
    raise SystemExit(0)
print(data.get("data-root", ""))
PY
      )"
      if [ "$current_root" = "${DOCKER_ROOT}/docker" ]; then
        ok "Docker data-root is ${DOCKER_ROOT}/docker"
      else
        fail "Docker data-root is '${current_root:-<unset>}' (expected ${DOCKER_ROOT}/docker)"
      fi
    else
      warn "Cannot verify docker daemon json (python3/file missing)"
    fi
    return 0
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 is required to update $DOCKER_DAEMON_JSON"
    return 0
  fi

  python3 - <<'PY' "$DOCKER_DAEMON_JSON" "$DOCKER_ROOT"
import json, os, sys
path = sys.argv[1]
docker_root = sys.argv[2]
data = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception:
        data = {}
data["data-root"] = f"{docker_root}/docker"
data.setdefault("storage-driver", "overlay2")
data.setdefault("log-driver", "json-file")
opts = data.get("log-opts", {})
if not isinstance(opts, dict):
    opts = {}
opts.setdefault("max-size", "50m")
opts.setdefault("max-file", "5")
data["log-opts"] = opts
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, sort_keys=False)
    fh.write("\n")
PY
  ok "Updated Docker daemon config: $DOCKER_DAEMON_JSON"
}

check_or_fix() {
  local docker_needs_offline_migration=0

  check_mount
  if ! mountpoint -q "$SSD_MOUNT"; then
    return 0
  fi

  ensure_dir "$DIDIER_ROOT"
  ensure_dir "$DOCKER_ROOT"
  ensure_dir "${DOCKER_ROOT}/docker"
  ensure_dir "${DOCKER_ROOT}/containerd"
  ensure_dir "${DIDIER_ROOT}/workspace"
  ensure_dir "${DIDIER_ROOT}/.vscode-server"
  ensure_dir "${DIDIER_ROOT}/models_system"
  ensure_dir "${DIDIER_ROOT}/logs"
  ensure_dir "${DIDIER_ROOT}/models"

  sync_and_link "${USER_HOME}/workspace" "${DIDIER_ROOT}/workspace" "Workspace"
  sync_and_link "${USER_HOME}/.vscode-server" "${DIDIER_ROOT}/.vscode-server" "VSCode Server"
  sync_and_link "/data/models" "${DIDIER_ROOT}/models_system" "System Models"

  if [ "$MODE" = "--check" ]; then
    if [ -L /var/lib/docker ] && [ "$(path_target /var/lib/docker)" = "${DOCKER_ROOT}/docker" ]; then
      ok "/var/lib/docker link is correct"
    else
      fail "/var/lib/docker is not linked to ${DOCKER_ROOT}/docker"
    fi
    if [ -L /var/lib/containerd ] && [ "$(path_target /var/lib/containerd)" = "${DOCKER_ROOT}/containerd" ]; then
      ok "/var/lib/containerd link is correct"
    else
      fail "/var/lib/containerd is not linked to ${DOCKER_ROOT}/containerd"
    fi
  else
    if [ ! -L /var/lib/docker ] || [ "$(path_target /var/lib/docker)" != "${DOCKER_ROOT}/docker" ]; then
      docker_needs_offline_migration=1
    fi
    if [ ! -L /var/lib/containerd ] || [ "$(path_target /var/lib/containerd)" != "${DOCKER_ROOT}/containerd" ]; then
      docker_needs_offline_migration=1
    fi

    if [ "$docker_needs_offline_migration" -eq 1 ]; then
      info "Stopping Docker services for safe migration"
      docker_services_stop
    fi

    sync_and_link "/var/lib/docker" "${DOCKER_ROOT}/docker" "Docker Root"
    sync_and_link "/var/lib/containerd" "${DOCKER_ROOT}/containerd" "Containerd Root"
    ensure_docker_daemon_json

    if [ "$docker_needs_offline_migration" -eq 1 ]; then
      info "Starting Docker services"
      docker_services_start
    fi
  fi

  ensure_docker_daemon_json

  if [ "$MODE" = "--fix" ]; then
    if id -u tchernobog >/dev/null 2>&1; then
      chown -R tchernobog:tchernobog "${DIDIER_ROOT}/workspace" "${DIDIER_ROOT}/.vscode-server" || true
      ok "Ensured ownership for workspace and .vscode-server data"
    fi
  fi
}

main() {
  case "$MODE" in
    --check|--fix) ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 1
      ;;
  esac

  must_be_root_for_fix

  info "SSD migration health mode: $MODE"
  check_or_fix

  if [ "$FAILED" -eq 0 ]; then
    ok "SSD migration state is stable."
    exit 0
  fi
  fail "SSD migration state requires attention."
  exit 1
}

main "$@"
