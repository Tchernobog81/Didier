#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${CONFIG_PATH:-$ROOT_DIR/config/config.json}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/ensure_devices.log}"
FORCE_MODE="${FORCE_MODE:-0}"
BT_CONNECT_TIMEOUT="${BT_CONNECT_TIMEOUT:-10s}"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

read_config() {
  python3 - <<PY
import json, sys
path = "${CONFIG_PATH}"
try:
    data = json.load(open(path, "r", encoding="utf-8"))
except Exception as e:
    print(f"ERROR:{e}")
    sys.exit(1)
print(data.get("vision", {}).get("camera_device", "/dev/video1"))
print(data.get("bluetooth", {}).get("mac_address", ""))
print(data.get("bluetooth", {}).get("sink_name", ""))
PY
}

mapfile -t CFG < <(read_config)
CAM_DEV="${CFG[0]:-/dev/video1}"
BT_MAC="${CFG[1]:-}"
SINK_NAME="${CFG[2]:-}"

echo "== Didier Device Check =="
echo "Camera device: ${CAM_DEV}"
echo "Bluetooth MAC: ${BT_MAC}"
echo "Soundboks sink: ${SINK_NAME}"
echo

check_camera() {
  if [ ! -e "${CAM_DEV}" ]; then
    echo "[CAM] ${CAM_DEV} missing"
    return 1
  fi
  if command -v v4l2-ctl >/dev/null 2>&1; then
    if v4l2-ctl -d "${CAM_DEV}" --all >/dev/null 2>&1; then
      echo "[CAM] device present"
      return 0
    fi
  fi
  echo "[CAM] device present but not responding"
  return 1
}

force_camera_up() {
  if [ "${FORCE_MODE}" -ne 1 ]; then
    echo "[CAM] force mode disabled; skipping camera reset"
    return 1
  fi
  echo "[CAM] trying to reset uvcvideo"
  if command -v lsof >/dev/null 2>&1; then
    echo "[CAM] killing processes using ${CAM_DEV}"
    sudo lsof -t "${CAM_DEV}" | xargs -r sudo kill -9 || true
  elif command -v fuser >/dev/null 2>&1; then
    echo "[CAM] killing processes using ${CAM_DEV}"
    sudo fuser -k "${CAM_DEV}" || true
  fi
  sudo modprobe -r uvcvideo || true
  sudo modprobe uvcvideo || true
  sleep 1
}

check_soundboks_sink() {
  if ! command -v pactl >/dev/null 2>&1; then
    echo "[BT] pactl not found"
    return 1
  fi
  if pactl list short sinks | grep -q "${SINK_NAME}"; then
    echo "[BT] sink available"
    return 0
  fi
  echo "[BT] sink missing"
  return 1
}

force_bluetooth_up() {
  if [ "${FORCE_MODE}" -ne 1 ]; then
    echo "[BT] force mode disabled; skipping bluetooth reconnect"
    return 1
  fi
  if ! command -v bluetoothctl >/dev/null 2>&1; then
    echo "[BT] bluetoothctl not found"
    return 1
  fi
  if [ -z "${BT_MAC}" ]; then
    echo "[BT] MAC not configured"
    return 1
  fi
  echo "[BT] powering on + connecting ${BT_MAC}"
  local -a bt_cmd=("bluetoothctl")
  if command -v timeout >/dev/null 2>&1; then
    bt_cmd=("timeout" "${BT_CONNECT_TIMEOUT}" "bluetoothctl")
  fi
  if ! "${bt_cmd[@]}" <<EOF
power on
agent on
default-agent
connect ${BT_MAC}
trust ${BT_MAC}
EOF
  then
    echo "[BT] bluetoothctl connect failed or timed out"
    return 1
  fi
  return 0
}

audio_test() {
  if ! command -v paplay >/dev/null 2>&1; then
    echo "[AUDIO] paplay not available"
    return 1
  fi
  if [ -z "${SINK_NAME}" ]; then
    echo "[AUDIO] sink not configured"
    return 1
  fi
  python3 - <<'PY'
import math, wave, struct, os
path = "data/soundboks_test.wav"
os.makedirs("data", exist_ok=True)
framerate = 22050
duration = 0.8
frequency = 440.0
amplitude = 0.2
frames = int(duration * framerate)
with wave.open(path, "w") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(framerate)
    for i in range(frames):
        val = int(amplitude * 32767.0 * math.sin(2 * math.pi * frequency * i / framerate))
        wf.writeframesraw(struct.pack("<h", val))
print(path)
PY
  local wav_path
  wav_path="$(python3 - <<'PY'
print("data/soundboks_test.wav")
PY
)"
  echo "[AUDIO] playing test tone on ${SINK_NAME}"
  paplay -d "${SINK_NAME}" "${wav_path}" || return 1
  return 0
}

cam_ok=0
bt_ok=0

check_camera || cam_ok=1
check_soundboks_sink || bt_ok=1

if [ "${cam_ok}" -ne 0 ]; then
  force_camera_up
  check_camera || cam_ok=1
fi

if [ "${bt_ok}" -ne 0 ]; then
  force_bluetooth_up || true
  sleep 2
  check_soundboks_sink || bt_ok=1
fi

echo
if [ "${cam_ok}" -eq 0 ]; then
  echo "[CAM] OK"
else
  echo "[CAM] NOT OK"
fi
if [ "${bt_ok}" -eq 0 ]; then
  echo "[BT] OK"
else
  echo "[BT] NOT OK"
fi

if [ "${bt_ok}" -eq 0 ]; then
  audio_test || echo "[AUDIO] test failed"
fi

exit $((cam_ok + bt_ok))
