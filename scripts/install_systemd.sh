#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${ROOT_DIR}/services"
DST_DIR="/etc/systemd/system"
UNITS=(didier-api didier-vision didier-brain didier-audio)
OPTIONAL_UNITS=(didier)

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

for unit in "${OPTIONAL_UNITS[@]}"; do
  src="${SRC_DIR}/${unit}.service"
  dst="${DST_DIR}/${unit}.service"
  if [[ ! -f "${src}" ]]; then
    echo "Missing optional unit file: ${src}" >&2
    continue
  fi
  if ! sudo -n cmp -s "${src}" "${dst}" 2>/dev/null; then
    sudo -n cp "${src}" "${dst}"
    changed=1
  fi
done

if [[ "${changed}" -eq 1 ]]; then
  sudo -n systemctl daemon-reload
fi

for unit in "${UNITS[@]}"; do
  sudo -n systemctl enable "${unit}.service"
  if [[ "${changed}" -eq 1 ]]; then
    sudo -n systemctl restart "${unit}.service"
  elif ! sudo -n systemctl is-active --quiet "${unit}.service"; then
    sudo -n systemctl start "${unit}.service"
  fi
done

if [[ "${INSTALL_DIDIER_SERVICE:-0}" == "1" ]]; then
  sudo -n systemctl enable didier.service
  if [[ "${changed}" -eq 1 ]]; then
    sudo -n systemctl restart didier.service
  elif ! sudo -n systemctl is-active --quiet didier.service; then
    sudo -n systemctl start didier.service
  fi
  sudo -n systemctl --no-pager --full status didier.service
else
  echo "didier.service installed only (set INSTALL_DIDIER_SERVICE=1 to enable/start)."
fi

sudo -n systemctl --no-pager --full status \
  didier-api.service didier-vision.service didier-brain.service didier-audio.service
