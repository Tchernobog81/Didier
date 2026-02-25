#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:-qwen3-coder-next:cloud}"
MODE="${MODE:-launch}"

if [ "$MODE" = "run" ]; then
  ollama run "$MODEL"
else
  ollama launch claude --model "$MODEL"
fi
