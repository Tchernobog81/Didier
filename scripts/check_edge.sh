#!/usr/bin/env bash
set -euo pipefail

LEGACY_BASE="${DIDIER_LEGACY_BASE:-http://127.0.0.1:5003}"
API_BASE="${DIDIER_API_BASE:-http://127.0.0.1:5010}"
VISION_BASE="${DIDIER_VISION_BASE:-http://127.0.0.1:5011}"
BRAIN_BASE="${DIDIER_BRAIN_BASE:-http://127.0.0.1:5012}"
AUDIO_BASE="${DIDIER_AUDIO_BASE:-http://127.0.0.1:5013}"
HITS="${DIDIER_CHECK_HITS:-10}"
CURL_TIMEOUT="${DIDIER_CHECK_TIMEOUT:-2}"

FAILURES=0
START_TS="$(date +%s.%N)"

check_port() {
  local port="$1"
  if (echo >"/dev/tcp/127.0.0.1/${port}") >/dev/null 2>&1; then
    printf "PORT 127.0.0.1:%s => OK\n" "${port}"
  else
    printf "PORT 127.0.0.1:%s => FAIL\n" "${port}"
    FAILURES=$((FAILURES + 1))
  fi
}

extract_status() {
  awk '
    /"status"[[:space:]]*:[[:space:]]*"/ {
      line=$0
      sub(/^.*"status"[[:space:]]*:[[:space:]]*"/, "", line)
      sub(/".*$/, "", line)
      print line
      exit
    }
  '
}

check_health() {
  local name="$1"
  local url="$2"
  local body status
  body="$(curl -sS --max-time "${CURL_TIMEOUT}" "${url}" || true)"
  status="$(printf "%s" "${body}" | extract_status)"
  if [[ "${status}" == "ok" || "${status}" == "degraded" ]]; then
    printf "HEALTH %-13s => %-8s (%s)\n" "${name}" "OK" "${status}"
  else
    printf "HEALTH %-13s => %-8s (%s)\n" "${name}" "FAIL" "${status:-no-status}"
    FAILURES=$((FAILURES + 1))
  fi
}

bench() {
  local name="$1"
  local method="$2"
  local url="$3"
  local data="${4:-}"
  local ok=0 fail=0 sum=0 avg=0
  local i out code latency

  for ((i = 1; i <= HITS; i++)); do
    if [[ "${method}" == "POST" ]]; then
      out="$(curl -sS -o /dev/null --max-time "${CURL_TIMEOUT}" -w "%{http_code} %{time_total}" \
        -X POST -H "Content-Type: application/json" --data "${data}" "${url}" || true)"
    else
      out="$(curl -sS -o /dev/null --max-time "${CURL_TIMEOUT}" -w "%{http_code} %{time_total}" \
        "${url}" || true)"
    fi
    code="$(printf "%s\n" "${out}" | awk '{print $1}')"
    latency="$(printf "%s\n" "${out}" | awk '{print $2}')"
    if [[ "${code}" =~ ^2[0-9][0-9]$ || "${code}" =~ ^3[0-9][0-9]$ ]]; then
      ok=$((ok + 1))
      sum="$(awk -v a="${sum}" -v b="${latency}" 'BEGIN { printf "%.6f", a + b }')"
    else
      fail=$((fail + 1))
    fi
  done

  if (( ok > 0 )); then
    avg="$(awk -v s="${sum}" -v n="${ok}" 'BEGIN { printf "%.4f", s / n }')"
  else
    avg="NA"
  fi

  printf "BENCH %-22s => avg_s=%-8s ok=%-2s fail=%-2s\n" "${name}" "${avg}" "${ok}" "${fail}"
  if (( fail > 0 )); then
    FAILURES=$((FAILURES + 1))
  fi
}

single_speak_stub() {
  local out code latency
  out="$(curl -sS -o /dev/null --max-time "${CURL_TIMEOUT}" -w "%{http_code} %{time_total}" \
    -X POST -H "Content-Type: application/json" \
    --data '{"text":"check edge"}' "${AUDIO_BASE}/speak" || true)"
  code="$(printf "%s\n" "${out}" | awk '{print $1}')"
  latency="$(printf "%s\n" "${out}" | awk '{print $2}')"
  printf "SPEAK_STUB 5013/speak      => code=%-3s latency_s=%s\n" "${code:-NA}" "${latency:-NA}"
  if [[ ! "${code}" =~ ^2[0-9][0-9]$ ]]; then
    FAILURES=$((FAILURES + 1))
  fi
}

print_proc_stats() {
  echo "PROCESS CPU/RAM (workers)"
  ps -eo pid,pcpu,pmem,rss,cmd | awk '
    /scripts\/run_api.py/   { printf "didier-api    pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    /scripts\/run_vision.py/{ printf "didier-vision pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    /scripts\/run_brain.py/ { printf "didier-brain  pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    /scripts\/run_audio.py/ { printf "didier-audio  pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    END {
      if (!found) {
        print "no worker processes found"
      }
    }
  '
}

echo "== Didier Edge Check =="
echo "-- Ports --"
check_port 5003
check_port 5010
check_port 5011
check_port 5012
check_port 5013

echo "-- Health --"
check_health "legacy-5003" "${LEGACY_BASE}/health"
check_health "didier-api" "${API_BASE}/health"
check_health "didier-vision" "${VISION_BASE}/health"
check_health "didier-brain" "${BRAIN_BASE}/health"
check_health "didier-audio" "${AUDIO_BASE}/health"

echo "-- Bench (10 hits) --"
bench "5003/metrics" "GET" "${LEGACY_BASE}/metrics"
bench "5003/device-status" "GET" "${LEGACY_BASE}/device-status"
bench "5003/docker/diagram" "GET" "${LEGACY_BASE}/docker/diagram"
bench "5013/health" "GET" "${AUDIO_BASE}/health"

echo "-- Speak Stub --"
single_speak_stub

echo "-- Process --"
print_proc_stats

END_TS="$(date +%s.%N)"
TOTAL_S="$(awk -v s="${START_TS}" -v e="${END_TS}" 'BEGIN { printf "%.3f", e - s }')"

echo "-- Summary --"
echo "total_time_s=${TOTAL_S}"
echo "failures=${FAILURES}"
if (( FAILURES > 0 )); then
  echo "result=FAIL"
  exit 1
fi
echo "result=PASS"
