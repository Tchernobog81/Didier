#!/usr/bin/env python3
import os
import sys
import subprocess
import requests

def check_step(name, status, details=""):
    icon = "✅" if status else "❌"
    print(f"{icon} [{name}] {details}")
    return status

print("--- 🔍 DIDIER v4.1 AUTOTESTS ---")

# 1. Test NPU (Hailo)
hailo_dev = os.path.exists("/dev/hailo0")
check_step("NPU Device", hailo_dev, "/dev/hailo0 trouvé" if hailo_dev else "NON TROUVÉ")

try:
    import tflite_runtime.interpreter as tflite
    check_step("LiteRT Lib", True, f"Version: {tflite.__version__ if hasattr(tflite, '__version__') else 'Installed'}")
except ImportError:
    check_step("LiteRT Lib", False, "Module 'tflite_runtime' manquant")

# 2. Test Audio (PulseAudio)
try:
    # On liste les sinks disponibles
    result = subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True, text=True)
    sinks = result.stdout.strip()
    if result.returncode == 0:
        check_step("PulseAudio", True, "Serveur accessible")
        print(f"    Sinks détectés :\n{sinks}")
    else:
        check_step("PulseAudio", False, f"Erreur pactl: {result.stderr}")
except FileNotFoundError:
    check_step("PulseAudio", False, "Commande 'pactl' introuvable")

# 3. Test Ollama
try:
    r = requests.get("http://localhost:11435/api/tags", timeout=2)
    if r.status_code == 200:
        models = [m['name'] for m in r.json().get('models', [])]
        check_step("Ollama API", True, f"Connecté (Port 11435). Modèles: {len(models)}")
        if "qwen2.5:0.5b" in models:
            print("    ✅ Modèle qwen2.5:0.5b présent")
        else:
            print("    ❌ Modèle qwen2.5:0.5b MANQUANT")
    else:
        check_step("Ollama API", False, f"Status {r.status_code}")
except Exception as e:
    check_step("Ollama API", False, f"Erreur connexion: {e}")

# 4. Test Config
import json
try:
    with open("/app/config/config.json", "r") as f:
        conf = json.load(f)
        model = conf.get("ollama", {}).get("model")
        sink = conf.get("bluetooth", {}).get("sink_name")
        print(f"--- CONFIG ACTUELLE ---")
        print(f"Modèle cible : {model}")
        print(f"Sink cible   : {sink}")
        
        # Vérif si le sink cible est dans la liste pactl
        if 'sinks' in locals() and sink not in sinks:
            print(f"⚠️  ATTENTION: Le sink configuré n'est PAS dans la liste des sinks audio !")
            
except Exception as e:
    check_step("Config JSON", False, str(e))

print("------------------------------")