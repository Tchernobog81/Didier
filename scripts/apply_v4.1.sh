#!/bin/bash

echo "🚀 DÉPLOIEMENT DIDIER v4.1 & AUTOTESTS"
echo "======================================"

# 1. Installation des dépendances manquantes (LiteRT) dans le conteneur
echo "[1/4] Installation dépendances (tflite-runtime)..."
if docker ps | grep -q didier-brain; then
    docker exec didier-brain pip install tflite-runtime --index-url https://google-coral.github.io/py-repo/
else
    echo "⚠️  Le conteneur n'est pas lancé, impossible d'installer pip packages maintenant."
fi

# 2. Exécution du diagnostic AVANT redémarrage (pour voir l'état actuel)
echo -e "\n[2/4] Diagnostic Pré-Redémarrage..."
if docker ps | grep -q didier-brain; then
    docker exec didier-brain python3 /app/scripts/diagnose.py
fi

# 3. Redémarrage Systématique
echo -e "\n[3/4] 🔄 REDÉMARRAGE DU CERVEAU (didier-brain)..."
docker compose restart didier-brain

# 4. Attente et Diagnostic Post-Redémarrage
echo -e "\n[4/4] Attente initialisation (5s)..."
sleep 5
echo "Diagnostic Post-Redémarrage :"
docker exec didier-brain python3 /app/scripts/diagnose.py

echo -e "\n✅ Opération terminée. Vérifiez http://localhost:5000 ou index.html"
echo "Si 'PulseAudio' est KO, vérifiez que votre utilisateur hôte a bien accès au son."
echo "Si le Sink est introuvable, mettez à jour config.json avec un sink listé ci-dessus."