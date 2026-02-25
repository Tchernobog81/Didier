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
echo -e "${YELLOW}🔍 DIAGNOSTIC BLUETOOTH & AUDIO POUR DIDIER...${NC}"

# 1. Service Bluetooth
header "1. État du service Bluetooth"
if systemctl is-active --quiet bluetooth; then
    echo -e "${GREEN}✅ Le service Bluetooth est ACTIF et en cours d'exécution.${NC}"
else
    echo -e "${RED}❌ Le service Bluetooth n'est PAS ACTIF !${NC}"
    echo -e "Astuce : Essayez 'sudo systemctl start bluetooth'"
    exit 1
fi

# 2. Contrôleur Bluetooth du Pi
header "2. État du contrôleur Bluetooth interne"
if bluetoothctl show | grep -q "Powered: yes"; then
    echo -e "${GREEN}✅ Le contrôleur est allumé (Powered: yes).${NC}"
else
    echo -e "${RED}❌ Le contrôleur est éteint (Powered: no).${NC}"
    echo -e "Astuce : Le script va tenter de l'allumer avec 'bluetoothctl power on'..."
    bluetoothctl power on
    sleep 1
fi
bluetoothctl show

# 3. Scan des appareils à proximité
header "3. Scan des appareils Bluetooth à proximité (10 secondes)"
echo "Veuillez patienter..."
timeout 10s bluetoothctl scan on > /dev/null
echo -e "${GREEN}Scan terminé.${NC} Voici les appareils détectés :"
bluetoothctl devices

# 4. État de PulseAudio
header "4. État du serveur de son (PulseAudio)"
if pulseaudio --check; then
    echo -e "${GREEN}✅ Le service PulseAudio est en cours d'exécution.${NC}"
else
    echo -e "${YELLOW}⚠️ Le service PulseAudio ne semble pas tourner. Tentative de démarrage...${NC}"
    pulseaudio --start
    sleep 2
fi

if pactl list modules short | grep -q "module-bluetooth-discover"; then
    echo -e "${GREEN}✅ Le module de découverte Bluetooth pour PulseAudio est chargé.${NC}"
else
    echo -e "${RED}❌ Le module Bluetooth pour PulseAudio n'est pas chargé !${NC}"
    echo -e "Astuce : Installez-le avec 'sudo apt-get install pulseaudio-module-bluetooth' puis redémarrez ('reboot')."
fi

# 5. Liste des sorties et entrées audio
header "5. Périphériques audio reconnus par le système"
echo -e "${YELLOW}--- SORTIES AUDIO (Sinks) ---${NC}"
pactl list short sinks

echo -e "\n${YELLOW}✅ DIAGNOSTIC TERMINÉ.${NC}"
echo -e "Vérifiez dans la section 3 si votre 'Soundboks' apparaît. Si oui, tentez de la connecter manuellement et relancez ce script pour voir si une sortie 'bluez_sink' apparaît dans la section 5."