#!/bin/bash

echo "🏷️  Marquage de la version : v4.1-LiteRT"

# Création du tag Git si possible
if command -v git &> /dev/null && [ -d .git ]; then
    git tag -f "v4.1-LiteRT"
    echo "✅ Tag Git 'v4.1-LiteRT' posé."
else
    echo "ℹ️  Git non détecté ou pas de dépôt, création du fichier VERSION uniquement."
fi

# Création/Mise à jour du fichier VERSION à la racine
echo "v4.1-LiteRT" > VERSION
echo "✅ Fichier VERSION créé."

echo "🛑 Arrêt propre des services Didier..."
sudo systemctl stop didier-asr.service didier-audio.service didier-brain.service didier-vision.service didier-api.service || true
echo "✅ Services arrêtés."

echo "💤 Extinction du Raspberry Pi..."
echo "À demain Didier."
sudo shutdown -h now
