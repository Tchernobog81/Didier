#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${MODELS_DIR:-$ROOT_DIR/models}"
VOICES_DIR="${VOICES_DIR:-$ROOT_DIR/voices}"

mkdir -p "$MODELS_DIR" "$VOICES_DIR"

echo "== Install Edge Models =="

echo "[ASR] Installing whisper.cpp + small model"
"$ROOT_DIR/scripts/install_whisper_cpp.sh"

echo "[VAD] Downloading silero VAD ONNX"
if [ ! -f "$MODELS_DIR/silero_vad.onnx" ]; then
  curl -L -o "$MODELS_DIR/silero_vad.onnx" \
    "https://github.com/snakers4/silero-vad/files/7603706/silero_vad.onnx"
else
  echo "VAD model already present."
fi

echo "[TTS] Downloading Kokoro models (if missing)"
if [ ! -f "$VOICES_DIR/kokoro-v1.0.onnx" ]; then
  curl -L -o "$VOICES_DIR/kokoro-v1.0.onnx" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
fi
if [ ! -f "$VOICES_DIR/voices-v1.0.bin" ]; then
  curl -L -o "$VOICES_DIR/voices-v1.0.bin" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
fi

echo "[MUSIC] Optional MusicGen-small ONNX (quantized)"
if [ "${INSTALL_MUSICGEN:-0}" = "1" ]; then
  MUSIC_DIR="$MODELS_DIR/musicgen-small-onnx"
  mkdir -p "$MUSIC_DIR/onnx"
  echo "Downloading MusicGen-small ONNX q4f16 (may be large)..."
  curl -L -o "$MUSIC_DIR/config.json" \
    "https://huggingface.co/harisnaeem/musicgen-small-ONNX/resolve/main/config.json"
  curl -L -o "$MUSIC_DIR/generation_config.json" \
    "https://huggingface.co/harisnaeem/musicgen-small-ONNX/resolve/main/generation_config.json"
  for file in build_delay_pattern_mask_q4f16.onnx decoder_model_q4f16.onnx decoder_with_past_model_q4f16.onnx encodec_decode_q4f16.onnx text_encoder_q4f16.onnx; do
    curl -L -o "$MUSIC_DIR/onnx/$file" \
      "https://huggingface.co/harisnaeem/musicgen-small-ONNX/resolve/main/onnx/$file"
  done
  echo "MusicGen-small ONNX downloaded in: $MUSIC_DIR"
else
  echo "Set INSTALL_MUSICGEN=1 to download the MusicGen-small ONNX model."
fi

echo "[VISION] Hugging Face Edge models"
HF_VISION_DIR="$MODELS_DIR/vision/huggingface"
mkdir -p "$HF_VISION_DIR"
download_hf() {
  local dest="$1"
  local url="$2"
  if [ -f "$dest" ]; then
    echo "Already present: $dest"
    return
  fi
  echo "Downloading $url -> $dest"
  curl -L -o "$dest" "$url"
}

# YOLOv8n FP16 ONNX (object detection)
download_hf "$HF_VISION_DIR/yolov8n_fp16.onnx" \
  "https://huggingface.co/webnn/yolov8n/resolve/main/onnx/yolov8n_fp16.onnx"

# YOLOv8n-seg ONNX (instance segmentation)
download_hf "$HF_VISION_DIR/yolov8n-seg.onnx" \
  "https://huggingface.co/Kalray/yolov8n-seg/resolve/main/yolov8n-seg.optimized.onnx"

cat <<EOF

[VISION] Hailo model zoo:
Pick a Hailo-8L optimized model (e.g. yolov5n/yolov8n) and place the .hef in:
  $ROOT_DIR/config/hailo_model.hef

EOF
