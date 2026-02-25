#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${ROOT_DIR}/services"
DST_DIR="/etc/systemd/system"
LOGROTATE_SRC="${ROOT_DIR}/config/logrotate.d/didier"
LOGROTATE_DST="/etc/logrotate.d/didier"
NM_WAIT_OVERRIDE_SRC="${ROOT_DIR}/services/NetworkManager-wait-online.override.conf"
NM_WAIT_OVERRIDE_DIR="/etc/systemd/system/NetworkManager-wait-online.service.d"
NM_WAIT_OVERRIDE_DST="${NM_WAIT_OVERRIDE_DIR}/override.conf"
UNITS=(didier-api didier-vision didier-brain didier-audio didier-asr didier-soundboks didier-picobot)
AUX_UNITS=()

if [[ ! -d "${SRC_DIR}" ]]; then
  echo "Missing directory: ${SRC_DIR}" >&2
  exit 1
fi

changed=0
for unit in "${UNITS[@]}"; do
  src="${SRC_DIR}/${unit}.service"
  dst="${DST_DIR}/${unit}.service"
  if [[ ! -f "${src}" ]]; then
    echo "Missing unit file: ${src}" >&2
    exit 1
  fi
  if ! sudo -n cmp -s "${src}" "${dst}" 2>/dev/null; then
    sudo -n cp "${src}" "${dst}"
    changed=1
  fi
done

for unit in "${AUX_UNITS[@]}"; do
  src="${SRC_DIR}/${unit}.service"
  dst="${DST_DIR}/${unit}.service"
  if [[ ! -f "${src}" ]]; then
    echo "Missing unit file: ${src}" >&2
    exit 1
  fi
  if ! sudo -n cmp -s "${src}" "${dst}" 2>/dev/null; then
    sudo -n cp "${src}" "${dst}"
    changed=1
  fi
done

legacy_src="${ROOT_DIR}/run_didier.service"
legacy_dst="${DST_DIR}/run_didier.service"
if [[ -f "${legacy_src}" ]]; then
  if ! sudo -n cmp -s "${legacy_src}" "${legacy_dst}" 2>/dev/null; then
    sudo -n cp "${legacy_src}" "${legacy_dst}"
    changed=1
  fi
fi

if [[ "${changed}" -eq 1 ]]; then
  sudo -n systemctl daemon-reload
fi

if [[ -f "${LOGROTATE_SRC}" ]]; then
  if ! sudo -n cmp -s "${LOGROTATE_SRC}" "${LOGROTATE_DST}" 2>/dev/null; then
    sudo -n cp "${LOGROTATE_SRC}" "${LOGROTATE_DST}"
  fi
fi

if [[ -f "${NM_WAIT_OVERRIDE_SRC}" ]]; then
  sudo -n mkdir -p "${NM_WAIT_OVERRIDE_DIR}"
  if ! sudo -n cmp -s "${NM_WAIT_OVERRIDE_SRC}" "${NM_WAIT_OVERRIDE_DST}" 2>/dev/null; then
    sudo -n cp "${NM_WAIT_OVERRIDE_SRC}" "${NM_WAIT_OVERRIDE_DST}"
    sudo -n systemctl daemon-reload
  fi
fi

for unit in "${UNITS[@]}"; do
  sudo -n systemctl enable "${unit}.service"
  if [[ "${changed}" -eq 1 ]]; then
    sudo -n systemctl restart "${unit}.service"
  elif ! sudo -n systemctl is-active --quiet "${unit}.service"; then
    sudo -n systemctl start "${unit}.service"
  fi
done

for legacy_unit in run_didier.service didier.service; do
  if sudo -n systemctl is-enabled --quiet "${legacy_unit}" 2>/dev/null; then
    sudo -n systemctl disable "${legacy_unit}" || true
  fi
  if sudo -n systemctl is-active --quiet "${legacy_unit}" 2>/dev/null; then
    sudo -n systemctl stop "${legacy_unit}" || true
  fi
done

echo "Legacy services disabled: run_didier.service, didier.service"

sudo -n systemctl --no-pager --full status \
  didier-api.service didier-vision.service didier-brain.service didier-audio.service didier-asr.service didier-soundboks.service didier-picobot.service
