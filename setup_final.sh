#!/usr/bin/env bash
set -euo pipefail

SSD_MOUNT="/mnt/didier_ssd"
DIDIER_ROOT="${SSD_MOUNT}/didier"
DOCKER_ROOT="${SSD_MOUNT}/docker_root"
SWAPFILE="${SSD_MOUNT}/swapfile"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

log() {
  echo "[setup_final] $*"
}

require_root() {
  if [ "${EUID}" -ne 0 ]; then
    echo "Ce script doit être exécuté en root (sudo)." >&2
    exit 1
  fi
}

require_mount() {
  if ! mountpoint -q "${SSD_MOUNT}"; then
    echo "SSD non monté sur ${SSD_MOUNT}. Abandon." >&2
    exit 1
  fi
}

json_set_docker_root() {
  local daemon_json="/etc/docker/daemon.json"
  python3 - <<'PY'
import json
import os

path = "/etc/docker/daemon.json"
data = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception:
        data = {}

data["data-root"] = "/mnt/didier_ssd/docker_root/docker"

with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, sort_keys=False)
    fh.write("\n")
PY
}

move_and_link_dir() {
  local src="$1"
  local dst="$2"

  if [ -L "${src}" ]; then
    log "Symlink déjà en place: ${src} -> $(readlink -f "${src}")"
    return
  fi

  mkdir -p "$(dirname "${dst}")"
  mkdir -p "${dst}"

  if [ -d "${src}" ]; then
    log "Copie ${src} -> ${dst}"
    rsync -aHAX "${src}/" "${dst}/"
    mv "${src}" "${src}.bak-${TIMESTAMP}"
  else
    log "Source absente: ${src} (création du lien vers ${dst})"
  fi

  ln -sfn "${dst}" "${src}"
}

ensure_swap() {
  local target_size=4294967296

  if [ -f "${SWAPFILE}" ]; then
    local size
    size="$(stat -c%s "${SWAPFILE}")"
    if [ "${size}" -ne "${target_size}" ]; then
      swapoff "${SWAPFILE}" 2>/dev/null || true
      rm -f "${SWAPFILE}"
    fi
  fi

  if [ ! -f "${SWAPFILE}" ]; then
    if command -v fallocate >/dev/null 2>&1; then
      fallocate -l 4G "${SWAPFILE}"
    else
      dd if=/dev/zero of="${SWAPFILE}" bs=1M count=4096 status=progress
    fi
    chmod 600 "${SWAPFILE}"
    mkswap "${SWAPFILE}"
  fi

  swapon "${SWAPFILE}" || true

  if ! grep -q "${SWAPFILE}" /etc/fstab; then
    echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
  fi
}

set_swappiness() {
  echo "vm.swappiness=10" > /etc/sysctl.d/99-didier.conf
  sysctl -w vm.swappiness=10 >/dev/null
}

set_cpu_governor() {
  local any=false
  for gov in /sys/devices/system/cpu/cpufreq/policy*/scaling_governor; do
    if [ -w "${gov}" ]; then
      echo performance > "${gov}"
      any=true
    fi
  done
  if [ "${any}" = false ]; then
    log "Aucun governor modifiable (cpufreq non disponible)."
  fi
}

set_ssd_scheduler() {
  local dev
  local parent
  local sched

  dev="$(findmnt -no SOURCE "${SSD_MOUNT}" || true)"
  if [ -z "${dev}" ]; then
    log "Impossible de détecter le périphérique SSD."
    return
  fi

  parent="$(lsblk -no PKNAME "${dev}" | head -n1 || true)"
  if [ -z "${parent}" ]; then
    log "Impossible de déterminer le périphérique parent pour ${dev}."
    return
  fi

  sched="/sys/block/${parent}/queue/scheduler"
  if [ ! -w "${sched}" ]; then
    log "Scheduler non modifiable: ${sched}"
    return
  fi

  if grep -q "none" "${sched}"; then
    echo none > "${sched}"
    log "Scheduler SSD réglé sur none."
  elif grep -q "mq-deadline" "${sched}"; then
    echo mq-deadline > "${sched}"
    log "Scheduler SSD réglé sur mq-deadline."
  else
    log "Scheduler SSD inchangé (ni none ni mq-deadline disponibles)."
  fi
}

install_perf_service() {
  local script_path="/usr/local/sbin/didier-perf.sh"
  local service_path="/etc/systemd/system/didier-perf.service"

  cat > "${script_path}" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

for gov in /sys/devices/system/cpu/cpufreq/policy*/scaling_governor; do
  if [ -w "${gov}" ]; then
    echo performance > "${gov}"
  fi
done

if mountpoint -q /mnt/didier_ssd; then
  dev="$(findmnt -no SOURCE /mnt/didier_ssd || true)"
  parent="$(lsblk -no PKNAME "${dev}" | head -n1 || true)"
  if [ -n "${parent}" ] && [ -w "/sys/block/${parent}/queue/scheduler" ]; then
    sched="/sys/block/${parent}/queue/scheduler"
    if grep -q "none" "${sched}"; then
      echo none > "${sched}"
    elif grep -q "mq-deadline" "${sched}"; then
      echo mq-deadline > "${sched}"
    fi
  fi
fi
EOS

  chmod +x "${script_path}"

  cat > "${service_path}" <<'EOS'
[Unit]
Description=Didier performance tuning
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/didier-perf.sh

[Install]
WantedBy=multi-user.target
EOS

  systemctl daemon-reload
  systemctl enable --now didier-perf.service
}

main() {
  require_root
  require_mount

  log "Prune Docker"
  if command -v docker >/dev/null 2>&1; then
    docker system prune -a --volumes -f
  fi

  log "Arrêt Docker/containerd"
  systemctl stop docker.socket || true
  systemctl stop docker || true
  systemctl stop containerd || true

  log "Migration Docker vers SSD"
  mkdir -p "${DOCKER_ROOT}/docker" "${DOCKER_ROOT}/containerd"
  rsync -aHAX --info=progress2 /var/lib/docker/ "${DOCKER_ROOT}/docker/"
  rsync -aHAX --info=progress2 /var/lib/containerd/ "${DOCKER_ROOT}/containerd/"

  if [ -d /var/lib/docker ] && [ ! -L /var/lib/docker ]; then
    mv /var/lib/docker "/var/lib/docker.bak-${TIMESTAMP}"
  fi
  if [ -d /var/lib/containerd ] && [ ! -L /var/lib/containerd ]; then
    mv /var/lib/containerd "/var/lib/containerd.bak-${TIMESTAMP}"
  fi

  ln -sfn "${DOCKER_ROOT}/docker" /var/lib/docker
  ln -sfn "${DOCKER_ROOT}/containerd" /var/lib/containerd

  log "Mise à jour /etc/docker/daemon.json"
  json_set_docker_root

  log "Redémarrage Docker/containerd"
  systemctl start containerd || true
  systemctl start docker || true

  log "Migration des dossiers utilisateurs"
  move_and_link_dir "/home/tchernobog/.vscode-server" "${DIDIER_ROOT}/.vscode-server"
  move_and_link_dir "/home/tchernobog/workspace" "${DIDIER_ROOT}/workspace"
  move_and_link_dir "/data/models" "${DIDIER_ROOT}/models_system"

  log "Swap + sysctl"
  ensure_swap
  set_swappiness

  log "CPU governor + scheduler SSD"
  set_cpu_governor
  set_ssd_scheduler
  install_perf_service

  log "Terminé"
}

main "$@"
