#!/usr/bin/env python3
import json
import os
import re
import sys

# Chemin vers la config (relatif à la racine du workspace)
CONFIG_PATH = "config/config.json"

def get_audio_device():
    """Détecte l'index de la carte son USB (PS3 Eye ou autre)."""
    try:
        with open("/proc/asound/cards", "r") as f:
            content = f.read()
            print("--- Cartes Audio Détectées ---")
            print(content.strip())
            print("------------------------------")
    except FileNotFoundError:
        print("❌ /proc/asound/cards introuvable.")
        return None
    
    # Regex pour trouver une carte contenant "Camera", "USB", ou "OmniVision"
    # Ex: 2 [CameraB409241  ]: USB-Audio - USB Camera-B4.09.24.1
    match = re.search(r"^\s*(\d+)\s+\[.*(Camera|USB|OmniVision).*", content, re.MULTILINE | re.IGNORECASE)
    if match:
        card_index = match.group(1)
        return f"hw:{card_index},0"
    return None

def main():
    new_device = get_audio_device()
    
    if not new_device:
        print("⚠️ Aucun micro USB détecté. Vérifiez le branchement.")
        return

    print(f"✅ Micro trouvé sur : {new_device}")
    
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    config["asr"]["alsa_device"] = new_device
    
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print(f"💾 Configuration mise à jour ({CONFIG_PATH}). Redémarrez Didier.")

if __name__ == "__main__":
    main()