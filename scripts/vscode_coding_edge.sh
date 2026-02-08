#!/usr/bin/env bash
set -euo pipefail

OLLAMA_BASE="${DIDIER_OLLAMA_URL:-http://127.0.0.1:11434}"
MODEL="${DIDIER_CODING_MODEL:-qwen2.5-coder:1.5b}"
TIMEOUT="${DIDIER_CODING_TIMEOUT:-180}"
SYSTEM_PROMPT="${DIDIER_CODING_SYSTEM:-Tu es un assistant de code précis, concis, et pragmatique. Donne des réponses courtes et exécutables.}"

if [ "$#" -gt 0 ]; then
  PROMPT="$*"
else
  PROMPT="$(cat)"
fi

PROMPT="$(printf '%s' "$PROMPT" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
if [ -z "$PROMPT" ]; then
  echo "Prompt vide. Usage: scripts/vscode_coding_edge.sh \"ta demande\""
  exit 1
fi

escape_json() {
  printf '%s' "$1" | sed ':a;N;$!ba;s/\\/\\\\/g;s/"/\\"/g;s/\r/\\r/g;s/\n/\\n/g;s/\t/\\t/g'
}

decode_json_string() {
  local s
  s="$(cat)"
  s="${s//\\\"/\"}"
  s="${s//\\\//\/}"
  printf '%b' "$s"
}

payload_prompt="$(escape_json "$PROMPT")"
payload_system="$(escape_json "$SYSTEM_PROMPT")"
payload='{"model":"'"$MODEL"'","prompt":"'"$payload_prompt"'","system":"'"$payload_system"'","stream":false,"options":{"num_predict":400,"temperature":0.2}}'

tmp_file="$(mktemp)"
http_code="$(
  curl -sS -o "$tmp_file" -w '%{http_code}' \
    --max-time "$TIMEOUT" \
    -H "Content-Type: application/json" \
    -X POST "$OLLAMA_BASE/api/generate" \
    --data "$payload" || true
)"

if [ "${http_code:-000}" -lt 200 ] || [ "${http_code:-000}" -ge 300 ]; then
  err="$(cat "$tmp_file" 2>/dev/null || true)"
  rm -f "$tmp_file"
  echo "Erreur agent coding edge local (HTTP ${http_code:-000})"
  [ -n "$err" ] && echo "$err"
  exit 1
fi

raw="$(cat "$tmp_file")"
rm -f "$tmp_file"

response="$(printf '%s' "$raw" | sed -n 's/.*"response"[[:space:]]*:[[:space:]]*"\(.*\)","done".*/\1/p' | decode_json_string)"
if [ -n "$response" ]; then
  printf '%s\n' "$response"
else
  printf '%s\n' "$raw"
fi
