#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$("${SCRIPT_DIR}/preflight_repo_root.sh")"
cd "${REPO_ROOT}"

BASE_URL="${BASE_URL:-http://127.0.0.1:5010}"
CURL_TIMEOUT="${CURL_TIMEOUT:-20}"
READY_WAIT_S="${READY_WAIT_S:-45}"

PASS=0
FAIL=0

print_sep() {
  printf '\n%s\n' "------------------------------------------------------------"
}

mark_pass() {
  PASS=$((PASS + 1))
  printf '[OK] %s\n' "$1"
}

mark_fail() {
  FAIL=$((FAIL + 1))
  printf '[KO] %s\n' "$1"
}

post_json() {
  local path="$1"
  local payload="$2"
  curl -sS -m "${CURL_TIMEOUT}" \
    -H 'Content-Type: application/json' \
    -X POST "${BASE_URL}${path}" \
    -d "${payload}"
}

get_json() {
  local path="$1"
  curl -sS -m "${CURL_TIMEOUT}" "${BASE_URL}${path}"
}

wait_api_ready() {
  local waited=0
  while [ "${waited}" -lt "${READY_WAIT_S}" ]; do
    if curl -sS -m 2 "${BASE_URL}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

check_contains() {
  local label="$1"
  local body="$2"
  local token="$3"
  if printf '%s' "${body}" | grep -q "${token}"; then
    mark_pass "${label}"
  else
    mark_fail "${label}"
  fi
}

print_sep
printf 'Didier Alive Check\n'
printf 'BASE_URL=%s\n' "${BASE_URL}"
if wait_api_ready; then
  printf 'API ready after startup wait.\n'
else
  printf 'API not reachable after %ss startup wait.\n' "${READY_WAIT_S}"
fi

print_sep
printf '1) Health API\n'
health="$(get_json "/health" 2>/dev/null || true)"
printf '%s\n' "${health}"
check_contains "API health endpoint reachable" "${health}" "\"status\""

print_sep
printf '2) Scenario task voice-like -> Picobot\n'
s1_payload='{"prompt":"Yo Didier, allume la lumiere de la cuisine","force_task":true}'
s1="$(post_json "/ask-and-speak" "${s1_payload}" 2>/dev/null || true)"
printf '%s\n' "${s1}"
check_contains "Scenario 1 response present" "${s1}" "\"response\""
if printf '%s' "${s1}" | grep -q "\"route\":\"picobot\""; then
  mark_pass "Scenario 1 routed to picobot"
else
  mark_fail "Scenario 1 route=picobot missing"
fi

print_sep
printf '3) Scenario vision glance\n'
s2_payload='{"prompt":"Yo Didier, comment je suis habille ?","is_voice":true,"vision_glance":true,"force_task":true}'
s2="$(post_json "/ask-and-speak" "${s2_payload}" 2>/dev/null || true)"
printf '%s\n' "${s2}"
check_contains "Scenario 2 response present" "${s2}" "\"response\""
check_contains "Scenario 2 vision payload present" "${s2}" "\"vision\""

print_sep
printf '4) Scenario chat task creation\n'
s3_payload='{"prompt":"Rappelle-moi d arroser les plantes demain","force_task":true}'
s3="$(post_json "/ask" "${s3_payload}" 2>/dev/null || true)"
printf '%s\n' "${s3}"
check_contains "Scenario 3 response present" "${s3}" "\"response\""

print_sep
printf '5) Picobot tasks snapshot\n'
tasks="$(get_json "/agent/tasks" 2>/dev/null || true)"
printf '%s\n' "${tasks}"
check_contains "/agent/tasks endpoint reachable" "${tasks}" "\"tasks\""

print_sep
printf '6) Picobot metrics snapshot\n'
metrics="$(get_json "/agent/metrics?timeout_s=2" 2>/dev/null || true)"
printf '%s\n' "${metrics}"
check_contains "/agent/metrics endpoint reachable" "${metrics}" "\"ok\""

print_sep
printf '7) Load average (idle target < 0.30)\n'
load1="$(uptime | awk -F'load average: ' '{print $2}' | awk -F',' '{gsub(/ /,"",$1); print $1}')"
printf 'load1=%s\n' "${load1:-unknown}"
if awk "BEGIN { exit !(${load1:-99} < 0.30) }"; then
  mark_pass "Load idle target respected (<0.30)"
else
  mark_fail "Load idle target not reached (<0.30)"
fi

print_sep
printf 'SUMMARY: PASS=%s FAIL=%s\n' "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
  exit 1
fi
exit 0
