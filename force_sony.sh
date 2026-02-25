#!/bin/bash
MAC="6C:47:60:E8:31:B4"

echo "--- TENTATIVE DE CONNEXION FORCEE SONY ---"
echo "Assurez-vous que l'enceinte clignote VITE."

# On s'assure que le Bluetooth est allumé
bluetoothctl power on
sleep 1

# On supprime les vieux restes au cas où
bluetoothctl remove $MAC > /dev/null 2>&1

echo "[*] Recherche de l'enceinte (60 secondes max)..."
# On lance le scan en arrière-plan
bluetoothctl scan on &
SCAN_PID=$!

# Boucle de 60 secondes pour essayer de pairer
for i in {1..60}; do
    echo -n "."
    # On essaie de pairer. Si ça réussit, on sort de la boucle.
    if bluetoothctl pair $MAC | grep -q "Pairing successful"; then
        echo -e "\n✅ PAIRING OK!"
        break
    fi
    sleep 1
done

# On arrête le scan
kill $SCAN_PID > /dev/null 2>&1
bluetoothctl scan off > /dev/null 2>&1

# Finalisation de la connexion
echo "[*] Confiance et Connexion..."
bluetoothctl trust $MAC
bluetoothctl connect $MAC

if bluetoothctl info $MAC | grep -q "Connected: yes"; then
    echo "🎉 DIDIER EST CONNECTÉ À L'ENCEINTE !"
else
    echo "❌ Échec. Rapprochez l'enceinte ou vérifiez le mode appairage."
fi
