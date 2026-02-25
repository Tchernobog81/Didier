#!/usr/bin/env bash
set -euo pipefail

SSD_MOUNT="/mnt/didier_ssd"
SSD_ROOT="$SSD_MOUNT/didier"
SSD_CODE="$SSD_ROOT/code"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="$ROOT_DIR"

if ! mountpoint -q "$SSD_MOUNT"; then
  echo "SSD non monté sur $SSD_MOUNT"
  exit 1
fi

mkdir -p "$SSD_CODE"
if [ "$ROOT_DIR" != "$SSD_CODE" ]; then
  echo "Synchronisation du code vers $SSD_CODE..."
  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude ".git" \
      --exclude "venv" \
      --exclude "__pycache__" \
      --exclude "logs" \
      --exclude "models" \
      --exclude "ollama" \
      "$ROOT_DIR"/ "$SSD_CODE"/
  else
    cp -a "$ROOT_DIR"/. "$SSD_CODE"/
  fi
  CODE_DIR="$SSD_CODE"
fi

cd "$CODE_DIR"

mkdir -p core tentacles config voices logs data

# --- Swap SSD (4G) ---
SWAPFILE="$SSD_MOUNT/swapfile"
if [ ! -f "$SWAPFILE" ]; then
  echo "Création du swapfile sur SSD..."
  sudo fallocate -l 4G "$SWAPFILE"
  sudo chmod 600 "$SWAPFILE"
  sudo mkswap "$SWAPFILE"
fi

if ! swapon --show=NAME | grep -qx "$SWAPFILE"; then
  echo "Activation du swapfile..."
  sudo swapon "$SWAPFILE"
fi

SWAPPINESS_CONF="/etc/sysctl.d/99-didier.conf"
CURRENT_SWAPPINESS="$(sysctl -n vm.swappiness 2>/dev/null || echo "")"
if [ "$CURRENT_SWAPPINESS" != "10" ]; then
  sudo sysctl -w vm.swappiness=10
fi
if [ -f "$SWAPPINESS_CONF" ]; then
  if ! grep -q '^vm\.swappiness=10$' "$SWAPPINESS_CONF"; then
    echo "vm.swappiness=10" | sudo tee -a "$SWAPPINESS_CONF" >/dev/null
  fi
else
  echo "vm.swappiness=10" | sudo tee "$SWAPPINESS_CONF" >/dev/null
fi

mkdir -p \
  "$SSD_ROOT/models/hailo" \
  "$SSD_ROOT/models/tts" \
  "$SSD_ROOT/ollama" \
  "$SSD_ROOT/logs"

# --- Optimisations perf & latence ---
SSD_DEVICE="$(findmnt -no SOURCE --target "$SSD_MOUNT" 2>/dev/null || true)"
if [ -n "${SSD_DEVICE:-}" ] && [ -b "$SSD_DEVICE" ]; then
  SSD_PARENT="$(lsblk -no PKNAME "$SSD_DEVICE" 2>/dev/null || true)"
  if [ -z "${SSD_PARENT:-}" ]; then
    SSD_PARENT="$(basename "$SSD_DEVICE")"
  fi
  if [ -n "${SSD_PARENT:-}" ] && [ -e "/sys/block/$SSD_PARENT/queue/scheduler" ]; then
    SCHED_PATH="/sys/block/$SSD_PARENT/queue/scheduler"
    SCHED_AVAILABLE="$(cat "$SCHED_PATH")"
    if echo "$SCHED_AVAILABLE" | grep -qw none; then
      echo "none" | sudo tee "$SCHED_PATH" >/dev/null
    elif echo "$SCHED_AVAILABLE" | grep -qw mq-deadline; then
      echo "mq-deadline" | sudo tee "$SCHED_PATH" >/dev/null
    elif echo "$SCHED_AVAILABLE" | grep -qw deadline; then
      echo "deadline" | sudo tee "$SCHED_PATH" >/dev/null
    fi
  fi
fi

if compgen -G "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor" >/dev/null; then
  echo "performance" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor >/dev/null
fi

DOCKER_DAEMON_JSON="/etc/docker/daemon.json"
if [ -f "$DOCKER_DAEMON_JSON" ]; then
  if command -v python3 >/dev/null 2>&1; then
    sudo python3 - <<'PY'
import json

path = "/etc/docker/daemon.json"
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    data = {}

data.setdefault("storage-driver", "overlay2")
data.setdefault("log-driver", "json-file")
opts = data.get("log-opts", {})
if not isinstance(opts, dict):
    opts = {}
opts.setdefault("max-size", "50m")
opts.setdefault("max-file", "5")
data["log-opts"] = opts

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
PY
  else
    echo "python3 indisponible; configuration Docker inchangée."
  fi
else
  sudo tee "$DOCKER_DAEMON_JSON" >/dev/null <<'JSON'
{
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
JSON
fi

LOGROTATE_FILE="/etc/logrotate.d/didier"
sudo tee "$LOGROTATE_FILE" >/dev/null <<'EOF'
/mnt/didier_ssd/didier/logs/* {
  daily
  rotate 7
  compress
  delaycompress
  missingok
  notifempty
  copytruncate
}
EOF

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart docker
fi

HAILO_PCI_DEVICES=()
if [ -d /sys/bus/pci/drivers ]; then
  while IFS= read -r dev; do
    [ -n "$dev" ] && HAILO_PCI_DEVICES+=("$dev")
  done < <(find /sys/bus/pci/drivers -maxdepth 2 -type l -name "0000:*" -path "*/hailo*" -printf "%f\n" 2>/dev/null || true)
fi

if [ ${#HAILO_PCI_DEVICES[@]} -eq 0 ] && command -v lspci >/dev/null 2>&1; then
  while IFS= read -r dev; do
    [ -n "$dev" ] && HAILO_PCI_DEVICES+=("$dev")
  done < <(lspci -D 2>/dev/null | awk 'tolower($0) ~ /hailo/ {print $1}' || true)
fi

if [ ${#HAILO_PCI_DEVICES[@]} -eq 0 ]; then
  while IFS= read -r path; do
    dev="$(basename "$(dirname "$path")")"
    [ -n "$dev" ] && HAILO_PCI_DEVICES+=("$dev")
  done < <(grep -l "0x1e60" /sys/bus/pci/devices/*/vendor 2>/dev/null || true)
fi

for dev in "${HAILO_PCI_DEVICES[@]}"; do
  POWER_CONTROL="/sys/bus/pci/devices/$dev/power/control"
  if [ -w "$POWER_CONTROL" ]; then
    echo "on" | sudo tee "$POWER_CONTROL" >/dev/null
  fi
  AUTOSUSPEND="/sys/bus/pci/devices/$dev/power/autosuspend_delay_ms"
  if [ -w "$AUTOSUSPEND" ]; then
    echo "-1" | sudo tee "$AUTOSUSPEND" >/dev/null
  fi
done

KOKORO_MODEL_URL="${KOKORO_MODEL_URL:-https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0.19.onnx}"
KOKORO_CONFIG_URL="${KOKORO_CONFIG_URL:-https://raw.githubusercontent.com/thewh1teagle/kokoro-onnx/main/kokoro_onnx/config.json}"
KOKORO_VOICES_URL="${KOKORO_VOICES_URL:-https://raw.githubusercontent.com/thewh1teagle/kokoro-onnx/main/kokoro_onnx/voices.json}"
HAILO_MODEL_URL="${HAILO_MODEL_URL:-https://github.com/hailo-ai/hailo-rpi5-examples/raw/main/resources/yolov8s_h8l.hef}"

KOKORO_MODEL_PATH="${KOKORO_MODEL_PATH:-$SSD_ROOT/models/tts/kokoro-v0.19.onnx}"
KOKORO_CONFIG_PATH="${KOKORO_CONFIG_PATH:-$SSD_ROOT/models/tts/kokoro-v0.19.json}"
KOKORO_VOICES_PATH="${KOKORO_VOICES_PATH:-$SSD_ROOT/models/tts/voices.json}"
HAILO_MODEL_PATH="${HAILO_MODEL_PATH:-$SSD_ROOT/models/hailo/hailo_model.hef}"

if [ -f "$HAILO_MODEL_PATH" ]; then
  if [ "$(stat -c%s "$HAILO_MODEL_PATH")" -lt 1000 ]; then
    rm -f "$HAILO_MODEL_PATH"
  fi
fi

if [ ! -f "$HAILO_MODEL_PATH" ]; then
  echo "Downloading Hailo model..."
  curl -L "$HAILO_MODEL_URL" -o "$HAILO_MODEL_PATH"
  if [ "$(stat -c%s "$HAILO_MODEL_PATH")" -lt 1000 ]; then
    rm -f "$HAILO_MODEL_PATH"
    echo "Hailo model download invalid."
    exit 1
  fi
fi

if [ ! -f "$KOKORO_MODEL_PATH" ]; then
  echo "Downloading Kokoro model..."
  curl -L "$KOKORO_MODEL_URL" -o "$KOKORO_MODEL_PATH"
fi

if [ ! -f "$KOKORO_CONFIG_PATH" ]; then
  echo "Downloading Kokoro config..."
  curl -L "$KOKORO_CONFIG_URL" -o "$KOKORO_CONFIG_PATH"
fi

if [ ! -f "$KOKORO_VOICES_PATH" ]; then
  echo "Downloading Kokoro voices..."
  curl -L "$KOKORO_VOICES_URL" -o "$KOKORO_VOICES_PATH"
fi

if ! command -v hailortcli >/dev/null 2>&1; then
  echo "Installing Hailo runtime..."
  sudo apt update
  sudo apt install -y hailo-all
fi

echo "Starting Docker deployment..."
docker compose up --build
