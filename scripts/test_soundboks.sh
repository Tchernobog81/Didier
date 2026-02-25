#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-https://127.0.0.1}"

curl -k -sS -X POST "${HOST}/audio/test" | cat
echo
