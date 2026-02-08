#!/usr/bin/env bash
set -euo pipefail

MODELS=(
  "llama3.2:1b"
  "llama3.2:3b"
  "gemma2:2b"
  "qwen2.5:1.5b"
  "qwen2.5:3b"
  "qwen2.5-coder:1.5b"
  "phi3.5:3.8b"
  "moondream:1.8b"
)

echo "Téléchargement du pack de modèles Ollama (peut être long)..."
for model in "${MODELS[@]}"; do
  echo "-> $model"
  docker compose exec ollama ollama pull "$model"
done

echo "Terminé."
