#!/bin/bash

# --- COULEURS ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

header() {
    echo -e ""
    echo -e "${BLUE}========================================================${NC}"
    echo -e "${BLUE}   $1${NC}"
    echo -e "${BLUE}========================================================${NC}"
}

clear
echo -e "${YELLOW}🔍 DIAGNOSTIC BLUETOOTH PROFOND POUR DIDIER...${NC}"
echo "Ce script va analyser en profondeur l'état du Bluetooth."

# --- Vérification des outils nécessaires ---
if ! command -v hciconfig &> /dev/null; then
    echo -e "${RED}Outil 'hciconfig' manquant. Installation de 'bluez'...${NC}"
    sudo apt-get update && sudo apt-get install -y bluez
fi

# 1. État des services
header "1. État détaillé du service Bluetooth"
# Using systemctl status for more verbosity
systemctl status bluetooth --no-pager -l
if ! systemctl is-active --quiet bluetooth; then
    echo -e "${RED}❌ Le service Bluetooth n'est PAS ACTIF. Le diagnostic ne peut continuer.${NC}"
    exit 1
fi

# 2. Blocages logiciels ou matériels
header "2. Vérification des blocages (rfkill)"
if command -v rfkill &> /dev/null; then
    rfkill list bluetooth
    if rfkill list bluetooth | grep -q "Soft blocked: yes"; then
        echo -e "${YELLOW}⚠️ Un blocage logiciel (Soft block) est détecté. Tentative de déblocage...${NC}"
        sudo rfkill unblock bluetooth
        sleep 1
        rfkill list bluetooth
    fi
else
    echo -e "${YELLOW}⚠️ Commande 'rfkill' non trouvée. Impossible de vérifier les blocages.${NC}"
fi

# 3. Analyse bas-niveau (Kernel & Hardware)
header "3. Analyse bas-niveau (Kernel & Contrôleur)"
echo -e "${YELLOW}--- Messages du Kernel (dmesg) liés au Bluetooth ---${NC}"
dmesg | grep -i -E "blue|hci" | tail -n 20
echo ""
echo -e "${YELLOW}--- Configuration du contrôleur (hciconfig) ---${NC}"
# Tentative de réinitialisation du contrôleur, ce qui peut résoudre beaucoup de problèmes
echo "Réinitialisation de l'interface hci0..."
sudo hciconfig hci0 down
sleep 1
sudo hciconfig hci0 up
sleep 1
echo "Détails de l'interface hci0 après réinitialisation :"
hciconfig -a hci0

# 4. Scan interactif
header "4. Lancement du scan"
echo "Après les diagnostics et la réinitialisation, nous lançons un nouveau scan."
echo -e "Mettez votre enceinte en mode appairage ${GREEN}MAINTENANT${NC}."
echo "Le scan va démarrer dans 5 secondes..."
sleep 5
echo "----------------------------------------------------------------"
echo "Scan en cours... Appuyez sur [Ctrl+C] pour arrêter."
sudo bluetoothctl scan on

echo -e "\n${YELLOW}✅ DIAGNOSTIC TERMINÉ.${NC}"
echo "Si un appareil est apparu, notez son adresse MAC et utilisez 'connect_soundboks.sh' ou connectez-vous manuellement."
echo "Si rien n'apparaît, le problème est probablement matériel (antenne, alimentation) ou un bug de driver profond."