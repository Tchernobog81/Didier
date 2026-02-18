#!/usr/bin/env bash
set -euo pipefail

VISION_BASE="${DIDIER_VISION_BASE:-http://127.0.0.1:5011}"
HEF_PATH="${DIDIER_HAILO_HEF:-/mnt/didier_ssd/didier/models/hailo/hailo_model.hef}"
DURATION_S="${DIDIER_VISION_BENCH_DURATION:-20}"
INTERVAL_S="${DIDIER_VISION_BENCH_INTERVAL:-1}"
MIN_AVG_FPS="${DIDIER_VISION_MIN_AVG_FPS:-10}"
CURL_TIMEOUT="${DIDIER_VISION_BENCH_TIMEOUT:-2}"

samples=0
ok_samples=0
fail_samples=0
tappas_started_count=0
hef_cmd_count=0
cpu_mode_count=0
hailo_mode_count=0
tmp_fps="$(mktemp)"
trap 'rm -f "${tmp_fps}"' EXIT

extract_num() {
  local key="$1"
  sed -n "s/.*\"${key}\":\\([0-9.]*\\).*/\\1/p"
}

extract_str() {
  local key="$1"
  sed -n "s/.*\"${key}\":\"\\([^\"]*\\)\".*/\\1/p"
}

echo "== Didier Vision Prod Benchmark =="
echo "vision_base=${VISION_BASE}"
echo "hef_path=${HEF_PATH}"
echo "duration_s=${DURATION_S} interval_s=${INTERVAL_S} min_avg_fps=${MIN_AVG_FPS}"

health="$(curl -sS --max-time "${CURL_TIMEOUT}" "${VISION_BASE}/health" || true)"
if [[ -z "${health}" ]]; then
  echo "health=FAIL (worker unreachable)"
  exit 1
fi
health_status="$(printf "%s" "${health}" | extract_str "status")"
echo "health_status=${health_status:-unknown}"

steps="$(awk -v d="${DURATION_S}" -v i="${INTERVAL_S}" 'BEGIN { n=int(d/i); if (n < 1) n=1; print n }')"
for ((n=1; n<=steps; n++)); do
  samples=$((samples + 1))
  body="$(curl -sS --max-time "${CURL_TIMEOUT}" "${VISION_BASE}/metrics" || true)"
  if [[ -z "${body}" ]]; then
    fail_samples=$((fail_samples + 1))
    echo "sample=${n} status=FAIL reason=metrics_unreachable"
    sleep "${INTERVAL_S}"
    continue
  fi

  mode="$(printf "%s" "${body}" | extract_str "mode")"
  fps="$(printf "%s" "${body}" | extract_num "fps")"
  started="false"
  if printf "%s" "${body}" | grep -q '"started":true'; then
    started="true"
    tappas_started_count=$((tappas_started_count + 1))
  fi
  if [[ "${mode}" == "hailo_mode" ]]; then
    hailo_mode_count=$((hailo_mode_count + 1))
  elif [[ "${mode}" == "cpu_mode" ]]; then
    cpu_mode_count=$((cpu_mode_count + 1))
  fi
  if printf "%s" "${body}" | grep -q "${HEF_PATH}"; then
    hef_cmd_count=$((hef_cmd_count + 1))
  fi

  if [[ -n "${fps}" ]]; then
    printf "%s\n" "${fps}" >> "${tmp_fps}"
    ok_samples=$((ok_samples + 1))
    echo "sample=${n} status=OK mode=${mode:-unknown} tappas_started=${started} fps=${fps}"
  else
    fail_samples=$((fail_samples + 1))
    echo "sample=${n} status=FAIL reason=fps_missing mode=${mode:-unknown} tappas_started=${started}"
  fi
  sleep "${INTERVAL_S}"
done

avg_fps="NA"
min_fps="NA"
p95_fps="NA"
if (( ok_samples > 0 )); then
  avg_fps="$(awk '{ s+=$1 } END { if (NR>0) printf "%.2f", s/NR; else print "NA" }' "${tmp_fps}")"
  min_fps="$(sort -n "${tmp_fps}" | head -n 1)"
  p95_fps="$(sort -n "${tmp_fps}" | awk '
    { vals[++n]=$1 }
    END {
      if (n==0) { print "NA"; exit }
      idx = int((n * 95 + 99) / 100)
      if (idx < 1) idx = 1
      if (idx > n) idx = n
      printf "%.2f", vals[idx]
    }'
  )"
fi

echo "-- Summary --"
echo "samples=${samples} ok=${ok_samples} fail=${fail_samples}"
echo "mode_hailo_count=${hailo_mode_count} mode_cpu_count=${cpu_mode_count}"
echo "tappas_started_count=${tappas_started_count}"
echo "hef_command_match_count=${hef_cmd_count}"
echo "avg_fps=${avg_fps} min_fps=${min_fps} p95_fps=${p95_fps}"

result="PASS"
if (( ok_samples == 0 )); then
  result="FAIL:no_valid_metrics"
elif (( tappas_started_count == 0 )); then
  result="FAIL:tappas_not_started"
elif (( hef_cmd_count == 0 )); then
  result="FAIL:hef_not_in_command"
else
  avg_ok="$(awk -v avg="${avg_fps}" -v min="${MIN_AVG_FPS}" 'BEGIN { if (avg+0 >= min+0) print 1; else print 0 }')"
  if [[ "${avg_ok}" != "1" ]]; then
    result="WARN:avg_fps_below_target"
  fi
fi
echo "result=${result}"

if [[ "${result}" == FAIL:* ]]; then
  exit 1
fi
exit 0
