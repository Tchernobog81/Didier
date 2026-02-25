#!/bin/bash

# Adresse MAC de la Soundboks (depuis config.json)
MAC="00:07:80:E0:3F:F0"

echo "--- TENTATIVE DE CONNEXION FORCEE SOUNDBOKS ---"
echo "Cible : $MAC"
echo "Assurez-vous que l'enceinte est en mode APPAIRAGE (LED bleue clignotante)."

# On s'assure que le Bluetooth est allumé
bluetoothctl power on
sleep 1

# On supprime les vieux restes au cas où (c'est souvent ça qui bloque)
echo "[*] Oubli de l'appareil..."
bluetoothctl remove $MAC > /dev/null 2>&1

echo "[*] Recherche de l'enceinte (Scan 15s)..."
# On lance le scan en arrière-plan
bluetoothctl scan on &
SCAN_PID=$!
sleep 15
kill $SCAN_PID > /dev/null 2>&1

# Tentative de pairage
echo "[*] Tentative de pairage..."
bluetoothctl pair $MAC
sleep 2

# Finalisation de la connexion
echo "[*] Confiance et Connexion..."
bluetoothctl trust $MAC
bluetoothctl connect $MAC

if bluetoothctl info $MAC | grep -q "Connected: yes"; then
    echo "🎉 DIDIER EST CONNECTÉ À LA SOUNDBOKS !"
else
    echo "❌ Échec. Vérifiez que l'enceinte clignote toujours en bleu."
fi