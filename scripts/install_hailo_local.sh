#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="${MODEL_DIR:-$ROOT_DIR/config}"
MODEL_FILE="${MODEL_FILE:-$MODEL_DIR/hailo_model.hef}"
MODEL_URL="${MODEL_URL:-https://github.com/hailo-ai/hailo-rpi5-examples/raw/main/resources/yolov8s_h8l.hef}"

echo "== Installation Hailo (local) =="

if [ ! -f "$MODEL_FILE" ]; then
  echo "📥 Téléchargement du modèle YOLOv8s pour Hailo-8L..."
  mkdir -p "$MODEL_DIR"
  if command -v wget >/dev/null 2>&1; then
    wget -q --show-progress -O "$MODEL_FILE" "$MODEL_URL"
  elif command -v curl >/dev/null 2>&1; then
    curl -L --progress-bar -o "$MODEL_FILE" "$MODEL_URL"
  else
    echo "❌ wget/curl introuvable. Installe wget ou curl."
    exit 1
  fi
  size_bytes=$(stat -c%s "$MODEL_FILE" || echo 0)
  if [ "$size_bytes" -lt 1000 ]; then
    echo "⚠️  Téléchargement invalide ($size_bytes bytes). Suppression."
    rm -f "$MODEL_FILE"
    exit 1
  fi
  echo "✅ Modèle Hailo installé : $MODEL_FILE (${size_bytes} bytes)"
else
  echo "ℹ️ Modèle Hailo déjà présent : $MODEL_FILE"
fi

if ! command -v hailortcli >/dev/null 2>&1; then
  echo "🔧 Installation du runtime Hailo sur l'hôte..."
  echo "⚠️  Cette étape nécessite sudo."
  sudo apt update
  sudo apt install -y hailo-all
else
  echo "ℹ️ Runtime Hailo déjà installé."
fi
