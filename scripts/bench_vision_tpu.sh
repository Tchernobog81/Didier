#!/usr/bin/env bash
set -euo pipefail

VISION_SOCK="${DIDIER_VISION_SOCK:-/tmp/didier_vision.sock}"
SAMPLES="${DIDIER_VISION_BENCH_SAMPLES:-15}"
INTERVAL_S="${DIDIER_VISION_BENCH_INTERVAL_S:-1}"
TARGET_FPS="${DIDIER_VISION_TARGET_FPS:-30}"
MIN_AVG_FPS="${DIDIER_VISION_MIN_AVG_FPS:-24}"

failures=0
fps_tmp="$(mktemp)"
monitor_tmp="$(mktemp)"

cleanup() {
  rm -f "${fps_tmp}" "${monitor_tmp}"
}
trap cleanup EXIT

if [[ ! -S "${VISION_SOCK}" ]]; then
  echo "VISION_SOCK missing: ${VISION_SOCK}"
  exit 2
fi

json_get_string() {
  local key="$1"
  awk -v k="\"${key}\":\"" '
    index($0, k) {
      line = substr($0, index($0, k) + length(k))
      split(line, a, "\"")
      print a[1]
      exit
    }
  '
}

json_get_bool() {
  local key="$1"
  awk -v k="\"${key}\":" '
    index($0, k) {
      line = substr($0, index($0, k) + length(k))
      gsub(/^[[:space:]]+/, "", line)
      if (line ~ /^true/) { print "true"; exit }
      if (line ~ /^false/) { print "false"; exit }
    }
  '
}

json_get_number() {
  local key="$1"
  awk -v k="\"${key}\":" '
    index($0, k) {
      line = substr($0, index($0, k) + length(k))
      split(line, a, ",")
      gsub(/[^0-9.]/, "", a[1])
      print a[1]
      exit
    }
  '
}

echo "[1/4] health check..."
health="$(curl -sS --unix-socket "${VISION_SOCK}" --max-time 2 http://localhost/health || true)"
mode="$(printf "%s" "${health}" | json_get_string "mode")"
tappas_started="$(printf "%s" "${health}" | json_get_bool "started")"
tappas_backend="$(printf "%s" "${health}" | json_get_string "backend")"

if [[ "${mode}" != "hailo_mode" ]]; then
  echo "FAIL: vision mode is ${mode:-unknown}, expected hailo_mode"
  failures=$((failures + 1))
fi
if [[ "${tappas_started}" != "true" ]]; then
  echo "FAIL: tappas started is ${tappas_started:-unknown}, expected true"
  failures=$((failures + 1))
fi
echo "mode=${mode:-unknown} tappas_started=${tappas_started:-unknown} backend=${tappas_backend:-unknown}"

echo "[2/4] sampling metrics (${SAMPLES}x every ${INTERVAL_S}s)..."
for ((i = 1; i <= SAMPLES; i++)); do
  metrics="$(curl -sS --unix-socket "${VISION_SOCK}" --max-time 2 http://localhost/metrics || true)"
  fps="$(printf "%s" "${metrics}" | json_get_number "fps")"
  if [[ -n "${fps}" ]]; then
    printf "%s\n" "${fps}" >> "${fps_tmp}"
  fi
  sleep "${INTERVAL_S}"
done

read -r fps_count fps_avg fps_min fps_max <<<"$(
  awk '
    { c++; s+=$1; if (NR==1 || $1<mi) mi=$1; if (NR==1 || $1>ma) ma=$1 }
    END {
      if (c==0) { print "0 0 0 0"; exit }
      printf "%d %.2f %.2f %.2f\n", c, s/c, mi, ma
    }
  ' "${fps_tmp}"
)"
fps_jitter="$(awk -v a="${fps_max}" -v b="${fps_min}" 'BEGIN { printf "%.2f", a-b }')"
echo "fps: samples=${fps_count} avg=${fps_avg} min=${fps_min} max=${fps_max} jitter=${fps_jitter} target=${TARGET_FPS}"

if awk -v a="${fps_avg}" -v b="${MIN_AVG_FPS}" 'BEGIN { exit !(a+0 < b+0) }'; then
  echo "FAIL: avg fps ${fps_avg} below threshold ${MIN_AVG_FPS}"
  failures=$((failures + 1))
fi

echo "[3/4] process load snapshot..."
gst_pid="$(pgrep -f 'gst-launch-1.0.*hailonet' | head -n 1 || true)"
vision_pid="$(pgrep -f 'scripts/run_vision.py' | head -n 1 || true)"
gst_cpu="n/a"
vision_cpu="n/a"
if [[ -n "${gst_pid}" ]]; then
  gst_cpu="$(ps -p "${gst_pid}" -o %cpu= | awk '{print $1}')"
fi
if [[ -n "${vision_pid}" ]]; then
  vision_cpu="$(ps -p "${vision_pid}" -o %cpu= | awk '{print $1}')"
fi
echo "gst_pid=${gst_pid:-none} gst_cpu=${gst_cpu}"
echo "vision_pid=${vision_pid:-none} vision_cpu=${vision_cpu}"

echo "[4/4] hailort monitor probe..."
if command -v hailortcli >/dev/null 2>&1; then
  timeout 3s hailortcli monitor > "${monitor_tmp}" 2>/dev/null || true
  monitor_lines="$(sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' "${monitor_tmp}" | grep -E "Utilization|Model|Device ID|did not retrieve|[0-9]+[[:space:]]*$" | head -n 20 || true)"
  if [[ -n "${monitor_lines}" ]]; then
    printf "%s\n" "${monitor_lines}"
  else
    echo "hailort monitor: no parsable lines"
  fi
else
  echo "hailortcli not available"
fi

echo "----"
if (( failures > 0 )); then
  echo "RESULT: FAIL (${failures})"
  exit 1
fi
echo "RESULT: OK"
