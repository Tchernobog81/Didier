#!/bin/bash

# Configuration
PIPER_PATH="/home/tchernobog/workspace/Didier/voices/piper/piper"
MODEL_PATH="/home/tchernobog/workspace/Didier/voices/fr_FR-siwis-low.onnx"
OUTPUT_WAV="/tmp/test_audio.wav"

echo "--- TEST AUDIO DIDIER ---"

# 1. Vérification PulseAudio
echo "[1/4] Vérification PulseAudio..."
if ! pulseaudio --check; then
    echo "❌ PulseAudio n'est pas lancé."
    echo "👉 Tentative de démarrage..."
    pulseaudio --start
    sleep 2
else
    echo "✅ PulseAudio est actif."
fi

# 2. Vérification Sink (Sortie audio)
echo "[2/4] Vérification de la sortie audio..."
if command -v pactl &> /dev/null; then
    DEFAULT_SINK=$(pactl get-default-sink 2>/dev/null || pactl info | grep "Default Sink" | cut -d: -f2)
    echo "ℹ️  Sortie actuelle : $DEFAULT_SINK"

    if [[ "$DEFAULT_SINK" == *"bluez"* ]]; then
        echo "✅ Une enceinte Bluetooth est sélectionnée."
    else
        echo "⚠️  Attention : La sortie n'est pas une enceinte Bluetooth."
        echo "    Liste des sorties disponibles :"
        pactl list short sinks
    fi
else
    echo "❌ Commande 'pactl' introuvable."
fi

# 3. Test Piper (Génération)
echo "[3/4] Test de génération vocale (Piper)..."
if [ ! -f "$PIPER_PATH" ] || [ ! -f "$MODEL_PATH" ]; then
    echo "❌ Piper ou le modèle vocal est introuvable."
    echo "   Piper: $PIPER_PATH"
    echo "   Model: $MODEL_PATH"
    exit 1
else
    echo "Ceci est un test audio pour Didier. Si vous m'entendez, tout fonctionne." | "$PIPER_PATH" --model "$MODEL_PATH" --output_file "$OUTPUT_WAV"
    echo "✅ Fichier audio généré."
fi

# 4. Test Lecture (Playback)
echo "[4/4] Lecture du son..."
echo "🔊 Lecture en cours via 'paplay'..."
if paplay "$OUTPUT_WAV"; then
    echo "✅ Lecture terminée (code retour 0)."
else
    echo "❌ Erreur lors de la lecture."
fi
echo "--- FIN DU TEST ---"