#!/bin/bash

# --- COULEURS ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${RED}☢️  PROTOCOLE DE RÉANIMATION BLUETOOTH (DEEP CLEAN) ☢️${NC}"
echo "Ce script va arrêter les services, purger le cache corrompu et recharger les pilotes."

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ Erreur : Ce script doit être lancé avec sudo.${NC}"
  exit 1
fi

# 1. Arrêt brutal
echo -e "\n${BLUE}[1/6] Arrêt des services Bluetooth...${NC}"
systemctl stop bluetooth
pkill -9 bluetoothd
echo "Services arrêtés."

# 2. Nettoyage Cache
echo -e "\n${BLUE}[2/6] Purge du cache de pairage (/var/lib/bluetooth)...${NC}"
# On sauvegarde au cas où, mais on vide le dossier pour forcer une redécouverte propre
if [ -d "/var/lib/bluetooth" ]; then
    mv /var/lib/bluetooth /var/lib/bluetooth.bak.$(date +%s)
    mkdir /var/lib/bluetooth
    echo "✅ Cache déplacé en backup et dossier recréé à neuf."
else
    echo "Pas de cache trouvé."
fi

# 3. Modules Noyau
echo -e "\n${BLUE}[3/6] Rechargement des pilotes (Kernel Modules)...${NC}"
# Liste des modules potentiels sur Pi
MODULES=("btusb" "bnep" "hci_uart" "btbcm" "bluetooth")

for mod in "${MODULES[@]}"; do
    if lsmod | grep -q "$mod"; then
        echo "Déchargement de $mod..."
        modprobe -r "$mod" 2>/dev/null || echo "  (Impossible de décharger $mod, peut-être utilisé)"
    fi
done

sleep 2
echo "Rechargement des modules..."
modprobe bluetooth
modprobe hci_uart
modprobe btbcm
modprobe btusb 2>/dev/null # Pas toujours présent si pas de dongle USB

# 4. Vérification Firmware/Config
echo -e "\n${BLUE}[4/6] Vérification configuration Boot...${NC}"
CONFIG="/boot/firmware/config.txt"
[ ! -f "$CONFIG" ] && CONFIG="/boot/config.txt"

if [ -f "$CONFIG" ]; then
    if grep -q "dtoverlay=disable-bt" "$CONFIG"; then
        echo -e "${RED}⚠️  ALERTE : Le Bluetooth est désactivé dans $CONFIG !${NC}"
        echo "Veuillez supprimer ou commenter la ligne 'dtoverlay=disable-bt'."
    else
        echo -e "${GREEN}Config OK (pas de disable-bt détecté).${NC}"
    fi
else
    echo "Fichier config.txt introuvable."
fi

# 5. Redémarrage
echo -e "\n${BLUE}[5/6] Redémarrage des services...${NC}"
systemctl start bluetooth
sleep 2
rfkill unblock bluetooth
echo "Services relancés."

echo -e "\n${YELLOW}✅ NETTOYAGE TERMINÉ.${NC}"
echo "Le système est propre. Un redémarrage complet est nécessaire pour appliquer les changements matériels."