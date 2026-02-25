#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${ROOT_DIR}/didier.conf"
LOCK_FILE="/tmp/didier_soundboks_watchdog.lock"
INTERVAL_S="${DIDIER_SB_WATCHDOG_INTERVAL:-8}"
MAX_WAIT_STEPS="${DIDIER_SB_WATCHDOG_WAIT_STEPS:-20}"
TARGET_MAC="${DIDIER_SOUNDBOKS_MAC:-}"
CONNECT_SCRIPT="${ROOT_DIR}/connect_soundboks.sh"

if [[ -z "${TARGET_MAC}" && -f "${CONFIG_FILE}" ]]; then
  # shellcheck source=/dev/null
  source "${CONFIG_FILE}"
  TARGET_MAC="${SOUNDBOKS_MAC:-}"
fi

if [[ -z "${TARGET_MAC}" ]]; then
  echo "soundboks-watchdog: missing SOUNDBOKS_MAC"
  exit 1
fi

if ! command -v bluetoothctl >/dev/null 2>&1; then
  echo "soundboks-watchdog: bluetoothctl missing"
  exit 1
fi

if ! command -v pactl >/dev/null 2>&1; then
  echo "soundboks-watchdog: pactl missing"
  exit 1
fi

MAC_STR="$(echo "${TARGET_MAC}" | tr ':' '_')"
CARD="bluez_card.${MAC_STR}"
SINK_PREFIX="bluez_output.${MAC_STR}"

connected_now() {
  bluetoothctl info "${TARGET_MAC}" 2>/dev/null | grep -q "Connected: yes"
}

find_sink() {
  pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -m1 "^${SINK_PREFIX}" || true
}

default_sink() {
  pactl info 2>/dev/null | awk -F': ' '/^Default Sink:/{print $2; exit}'
}

heal_once() {
  exec 9>"${LOCK_FILE}"
  flock -n 9 || return 0

  echo "soundboks-watchdog: heal start (mac=${TARGET_MAC})"
  bluetoothctl power on >/dev/null 2>&1 || true
  bluetoothctl trust "${TARGET_MAC}" >/dev/null 2>&1 || true
  if ! connected_now; then
    bluetoothctl connect "${TARGET_MAC}" >/dev/null 2>&1 || true
    sleep 1
  fi
  if ! connected_now && [[ -x "${CONNECT_SCRIPT}" ]]; then
    echo "soundboks-watchdog: fallback connect_soundboks.sh"
    timeout 30 "${CONNECT_SCRIPT}" >/dev/null 2>&1 || true
  fi

  for _ in $(seq 1 "${MAX_WAIT_STEPS}"); do
    if pactl list cards short 2>/dev/null | awk '{print $2}' | grep -q "^${CARD}$"; then
      break
    fi
    sleep 0.3
  done

  pactl set-card-profile "${CARD}" a2dp-sink >/dev/null 2>&1 || true
  sleep 0.2

  local sink
  sink="$(find_sink)"
  if [[ -n "${sink}" ]]; then
    pactl set-default-sink "${sink}" >/dev/null 2>&1 || true
    while read -r input_id _; do
      [[ -n "${input_id}" ]] && pactl move-sink-input "${input_id}" "${sink}" >/dev/null 2>&1 || true
    done < <(pactl list short sink-inputs 2>/dev/null)
  fi
  if connected_now; then
    echo "soundboks-watchdog: heal ok (sink=${sink:-none})"
  else
    echo "soundboks-watchdog: heal pending (still disconnected)"
  fi
}

echo "soundboks-watchdog: start for ${TARGET_MAC}"
while true; do
  sink_name="$(find_sink)"
  def_sink="$(default_sink)"
  if ! connected_now || [[ -z "${sink_name}" ]] || [[ "${def_sink}" != "${sink_name}" ]]; then
    heal_once
  fi
  sleep "${INTERVAL_S}"
done
