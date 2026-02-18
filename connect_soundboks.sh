#!/bin/bash
# Script pour connecter l'enceinte Soundboks
# Usage: ./connect_soundboks.sh
 
CONFIG_FILE="didier.conf"
TARGET_NAME="Soundboks"
TARGET_MAC=""
 
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
    TARGET_MAC="${SOUNDBOKS_MAC}"
fi
 
echo "--- CONNEXION SOUNDBOKS ---"
echo "1. Assurez-vous que la Soundboks est allumée et en mode APPAIRAGE (LED bleue clignotante)."

if ! command -v pactl &> /dev/null; then
    echo "❌ pactl indisponible. PipeWire/PulseAudio requis."
    exit 1
fi

bluetoothctl power on
sleep 2

if [ -n "$TARGET_MAC" ]; then
    echo "ℹ️  Utilisation de l'adresse MAC configurée : $TARGET_MAC"
    MAC="$TARGET_MAC"
else
    # Scan rapide pour découvrir le device si pas déjà connu
    echo "[*] Scan en cours (15s)..."
    bluetoothctl scan on &
    SCAN_PID=$!
    sleep 15
    kill $SCAN_PID 2>/dev/null
    
    # Recherche de l'adresse MAC par nom
    MAC=$(bluetoothctl devices | grep -i "$TARGET_NAME" | head -n 1 | awk '{print $2}')
fi

if [ -z "$MAC" ]; then
    echo "❌ Appareil introuvable."
    echo "Vérifiez que l'enceinte est bien en mode appairage (LED bleue clignotante)."
    echo "Astuce : Vérifiez l'adresse MAC dans 'didier.conf' ou lancez un scan manuel avec 'bluetoothctl scan on'."
    exit 1
fi

echo "🎯 Cible identifiée : $MAC"

# Connexion
bluetoothctl trust $MAC
bluetoothctl pair $MAC
sleep 2
bluetoothctl connect $MAC

# Vérification
if bluetoothctl info $MAC | grep -q "Connected: yes"; then
    echo "✅ Connecté !"
    
    # Tentative de bascule audio (PipeWire/PulseAudio)
    if command -v pactl &> /dev/null; then
        # On attend que la carte/sink bluetooth apparaisse
        sleep 1
        MAC_STR=$(echo $MAC | tr ':' '_')
        CARD="bluez_card.$MAC_STR"
        for _ in $(seq 1 20); do
            if pactl list cards short 2>/dev/null | awk '{print $2}' | grep -q "^$CARD$"; then
                break
            fi
            sleep 0.5
        done
        # Force profil A2DP pour créer un sink de lecture
        pactl set-card-profile "$CARD" a2dp-sink 2>/dev/null || true
        sleep 0.5
        SINK=$(pactl list short sinks | awk '{print $2}' | grep "bluez_output.$MAC_STR" | head -n 1)
        
        if [ -n "$SINK" ]; then
            pactl set-default-sink "$SINK"
            echo "🔊 Sortie audio définie sur $SINK"
            # Déplace les flux déjà ouverts vers la SB
            while read -r input_id _; do
                [ -n "$input_id" ] && pactl move-sink-input "$input_id" "$SINK" 2>/dev/null || true
            done < <(pactl list short sink-inputs 2>/dev/null)
            # Notification vocale via Piper pour confirmer la connexion
            PIPER="/home/tchernobog/workspace/Didier/voices/piper/piper"
            MODEL="/home/tchernobog/workspace/Didier/voices/fr_FR-siwis-low.onnx"
            if [ -f "$PIPER" ]; then echo "Connexion établie." | "$PIPER" --model "$MODEL" --output_file /tmp/didier_ready.wav && paplay /tmp/didier_ready.wav; fi
        else
            echo "⚠️ Pas de sink audio détecté. Vérifiez 'pactl list cards' et 'pactl list sinks'."
        fi
    fi
else
    echo "❌ Échec connexion."
fi
