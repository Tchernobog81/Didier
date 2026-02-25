#!/usr/bin/env bash
set -euo pipefail

ENTRY_BASE="${DIDIER_ENTRY_BASE:-http://127.0.0.1:5010}"
API_BASE="${DIDIER_API_BASE:-${ENTRY_BASE}}"
VISION_BASE="${DIDIER_VISION_BASE:-http://127.0.0.1:5011}"
BRAIN_BASE="${DIDIER_BRAIN_BASE:-http://127.0.0.1:5012}"
AUDIO_BASE="${DIDIER_AUDIO_BASE:-http://127.0.0.1:5013}"
ASR_BASE="${DIDIER_ASR_BASE:-http://127.0.0.1:5014}"
VISION_SOCK="${DIDIER_VISION_SOCK:-/tmp/didier_vision.sock}"
BRAIN_SOCK="${DIDIER_BRAIN_SOCK:-/tmp/didier_brain.sock}"
AUDIO_SOCK="${DIDIER_AUDIO_SOCK:-/tmp/didier_audio.sock}"
HITS="${DIDIER_CHECK_HITS:-10}"
CURL_TIMEOUT="${DIDIER_CHECK_TIMEOUT:-2}"
LLM_TIMEOUT="${DIDIER_CHECK_LLM_TIMEOUT:-12}"
TTS_TIMEOUT="${DIDIER_CHECK_TTS_TIMEOUT:-5}"

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

check_port_closed() {
  local port="$1"
  if (echo >"/dev/tcp/127.0.0.1/${port}") >/dev/null 2>&1; then
    printf "PORT 127.0.0.1:%s => FAIL (must be closed)\n" "${port}"
    FAILURES=$((FAILURES + 1))
  else
    printf "PORT 127.0.0.1:%s => OK (closed)\n" "${port}"
  fi
}

check_socket() {
  local sock="$1"
  if [[ -S "${sock}" ]]; then
    printf "SOCKET %s => OK\n" "${sock}"
  else
    printf "SOCKET %s => FAIL\n" "${sock}"
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

check_health_socket() {
  local name="$1"
  local sock="$2"
  local body status
  body="$(curl -sS --unix-socket "${sock}" --max-time "${CURL_TIMEOUT}" "http://localhost/health" || true)"
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
  local timeout_s="${5:-${CURL_TIMEOUT}}"
  local ok=0 fail=0 sum=0 avg=0
  local p95="NA"
  local i out code latency
  local tmp_lat

  tmp_lat="$(mktemp)"
  for ((i = 1; i <= HITS; i++)); do
    if [[ "${method}" == "POST" ]]; then
      out="$(curl -sS -o /dev/null --max-time "${timeout_s}" -w "%{http_code} %{time_total}" \
        -X POST -H "Content-Type: application/json" --data "${data}" "${url}" || true)"
    else
      out="$(curl -sS -o /dev/null --max-time "${timeout_s}" -w "%{http_code} %{time_total}" \
        "${url}" || true)"
    fi
    code="$(printf "%s\n" "${out}" | awk '{print $1}')"
    latency="$(printf "%s\n" "${out}" | awk '{print $2}')"
    if [[ "${code}" =~ ^2[0-9][0-9]$ || "${code}" =~ ^3[0-9][0-9]$ ]]; then
      ok=$((ok + 1))
      sum="$(awk -v a="${sum}" -v b="${latency}" 'BEGIN { printf "%.6f", a + b }')"
      printf "%s\n" "${latency}" >> "${tmp_lat}"
    else
      fail=$((fail + 1))
    fi
  done

  if (( ok > 0 )); then
    avg="$(awk -v s="${sum}" -v n="${ok}" 'BEGIN { printf "%.4f", s / n }')"
    p95="$(sort -n "${tmp_lat}" | awk '
      { vals[++n] = $1 }
      END {
        if (n == 0) { print "NA"; exit }
        idx = int((n * 95 + 99) / 100)
        if (idx < 1) idx = 1
        if (idx > n) idx = n
        printf "%.4f", vals[idx]
      }
    ')"
  else
    avg="NA"
  fi

  rm -f "${tmp_lat}"
  printf "BENCH %-22s => avg_s=%-8s p95_s=%-8s ok=%-2s fail=%-2s\n" "${name}" "${avg}" "${p95}" "${ok}" "${fail}"
  if (( fail > 0 )); then
    FAILURES=$((FAILURES + 1))
  fi
}

bench_socket() {
  local name="$1"
  local method="$2"
  local sock="$3"
  local path="$4"
  local data="${5:-}"
  local timeout_s="${6:-${CURL_TIMEOUT}}"
  local ok=0 fail=0 sum=0 avg=0
  local p95="NA"
  local i out code latency
  local tmp_lat

  tmp_lat="$(mktemp)"
  for ((i = 1; i <= HITS; i++)); do
    if [[ "${method}" == "POST" ]]; then
      out="$(curl -sS -o /dev/null --unix-socket "${sock}" --max-time "${timeout_s}" -w "%{http_code} %{time_total}" \
        -X POST -H "Content-Type: application/json" --data "${data}" "http://localhost${path}" || true)"
    else
      out="$(curl -sS -o /dev/null --unix-socket "${sock}" --max-time "${timeout_s}" -w "%{http_code} %{time_total}" \
        "http://localhost${path}" || true)"
    fi
    code="$(printf "%s\n" "${out}" | awk '{print $1}')"
    latency="$(printf "%s\n" "${out}" | awk '{print $2}')"
    if [[ "${code}" =~ ^2[0-9][0-9]$ || "${code}" =~ ^3[0-9][0-9]$ ]]; then
      ok=$((ok + 1))
      sum="$(awk -v a="${sum}" -v b="${latency}" 'BEGIN { printf "%.6f", a + b }')"
      printf "%s\n" "${latency}" >> "${tmp_lat}"
    else
      fail=$((fail + 1))
    fi
  done

  if (( ok > 0 )); then
    avg="$(awk -v s="${sum}" -v n="${ok}" 'BEGIN { printf "%.4f", s / n }')"
    p95="$(sort -n "${tmp_lat}" | awk '
      { vals[++n] = $1 }
      END {
        if (n == 0) { print "NA"; exit }
        idx = int((n * 95 + 99) / 100)
        if (idx < 1) idx = 1
        if (idx > n) idx = n
        printf "%.4f", vals[idx]
      }
    ')"
  else
    avg="NA"
  fi

  rm -f "${tmp_lat}"
  printf "BENCH %-22s => avg_s=%-8s p95_s=%-8s ok=%-2s fail=%-2s\n" "${name}" "${avg}" "${p95}" "${ok}" "${fail}"
  if (( fail > 0 )); then
    FAILURES=$((FAILURES + 1))
  fi
}

single_speak_stub() {
  local out code latency
  out="$(curl -sS -o /dev/null --unix-socket "${AUDIO_SOCK}" --max-time "${CURL_TIMEOUT}" -w "%{http_code} %{time_total}" \
    -X POST -H "Content-Type: application/json" --data '{"text":"check edge"}' "http://localhost/speak" || true)"
  code="$(printf "%s\n" "${out}" | awk '{print $1}')"
  latency="$(printf "%s\n" "${out}" | awk '{print $2}')"
  printf "SPEAK_STUB audio/speak     => code=%-3s latency_s=%s\n" "${code:-NA}" "${latency:-NA}"
  if [[ ! "${code}" =~ ^2[0-9][0-9]$ ]]; then
    FAILURES=$((FAILURES + 1))
  fi
}

print_proc_stats() {
  echo "PROCESS CPU/RAM (workers)"
  ps -eo pid,pcpu,pmem,rss,cmd | awk '
    /uvicorn core\.api:app/ && /--port 5010/ { printf "didier-api    pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    /scripts\/run_api.py/   { printf "didier-api    pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    /scripts\/run_vision.py/{ printf "didier-vision pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    /scripts\/run_brain.py/ { printf "didier-brain  pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    /scripts\/run_audio.py/ { printf "didier-audio  pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    /scripts\/run_asr.py/   { printf "didier-asr    pid=%s cpu=%s%% mem=%s%% rss_mb=%.1f\n", $1, $2, $3, $4/1024; found=1 }
    END {
      if (!found) {
        print "no worker processes found"
      }
    }
  '
}

print_runtime_summary() {
  local load1 load5 load15 temp_c
  read -r load1 load5 load15 < <(awk '{print $1, $2, $3}' /proc/loadavg)
  if [[ -r /sys/class/thermal/thermal_zone0/temp ]]; then
    temp_c="$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp)"
  else
    temp_c="NA"
  fi
  echo "runtime_load_1m=${load1}"
  echo "runtime_load_5m=${load5}"
  echo "runtime_load_15m=${load15}"
  echo "runtime_temp_c=${temp_c}"
}

echo "== Didier Edge Check =="
echo "-- Ports --"
check_port_closed 5003
check_port 5010
check_port 5014
check_socket "${VISION_SOCK}"
check_socket "${BRAIN_SOCK}"
check_socket "${AUDIO_SOCK}"

echo "-- Health --"
check_health "entry-5010" "${ENTRY_BASE}/health"
check_health "didier-api" "${API_BASE}/health"
check_health "didier-asr" "${ASR_BASE}/health"
check_health_socket "didier-vision" "${VISION_SOCK}"
check_health_socket "didier-brain" "${BRAIN_SOCK}"
check_health_socket "didier-audio" "${AUDIO_SOCK}"

echo "-- Bench (${HITS} hits) --"
bench "5010/metrics" "GET" "${ENTRY_BASE}/metrics"
bench "5010/device-status" "GET" "${ENTRY_BASE}/device-status"
bench "5010/workers-diagram" "GET" "${ENTRY_BASE}/docker/diagram"
bench "5014/health" "GET" "${ASR_BASE}/health"
bench_socket "audio/health(sock)" "GET" "${AUDIO_SOCK}" "/health"
bench_socket "brain/generate(sock)" "POST" "${BRAIN_SOCK}" "/generate" '{"prompt":"bonjour"}' "${LLM_TIMEOUT}"
bench_socket "audio/speak(sock)" "POST" "${AUDIO_SOCK}" "/speak" '{"text":"check edge"}' "${TTS_TIMEOUT}"

echo "-- Speak Stub --"
single_speak_stub

echo "-- Process --"
print_proc_stats

END_TS="$(date +%s.%N)"
TOTAL_S="$(awk -v s="${START_TS}" -v e="${END_TS}" 'BEGIN { printf "%.3f", e - s }')"

echo "-- Summary --"
echo "total_time_s=${TOTAL_S}"
print_runtime_summary
echo "failures=${FAILURES}"
if (( FAILURES > 0 )); then
  echo "result=FAIL"
  exit 1
fi
echo "result=PASS"
