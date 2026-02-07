#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_BIN="${TARGET_BIN:-$ROOT_DIR/bin/whisper.cpp}"
TARGET_MODELS="${TARGET_MODELS:-$ROOT_DIR/models}"
REPO_DIR="${REPO_DIR:-$ROOT_DIR/.deps/whisper.cpp}"
MODEL_NAME="${MODEL_NAME:-ggml-small.bin}"

mkdir -p "$ROOT_DIR/bin" "$TARGET_MODELS" "$(dirname "$REPO_DIR")"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required" >&2
  exit 1
fi

if [ ! -d "$REPO_DIR" ]; then
  echo "Cloning whisper.cpp..."
  git clone --depth 1 https://github.com/ggerganov/whisper.cpp "$REPO_DIR"
fi

echo "Building whisper.cpp..."
make -C "$REPO_DIR" -j"$(nproc)"

if [ ! -f "$REPO_DIR/main" ]; then
  echo "Build failed: main not found" >&2
  exit 1
fi

cp "$REPO_DIR/main" "$TARGET_BIN"
chmod +x "$TARGET_BIN"
echo "Binary installed at $TARGET_BIN"

MODEL_PATH="$TARGET_MODELS/$MODEL_NAME"
if [ ! -f "$MODEL_PATH" ]; then
  echo "Downloading model $MODEL_NAME..."
  "$REPO_DIR"/models/download-ggml-model.sh small
  if [ -f "$REPO_DIR/models/$MODEL_NAME" ]; then
    cp "$REPO_DIR/models/$MODEL_NAME" "$MODEL_PATH"
  else
    echo "Model download failed" >&2
    exit 1
  fi
fi

echo "Model available at $MODEL_PATH"
