# 1. On crée le fichier
cat << 'EOF' > ~/workspace/Didier/diag.sh
#!/bin/bash

# --- COULEURS POUR Y VOIR CLAIR ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

LOG_FILE="didier_diag_$(date +%H%M%S).txt"

# Fonction d'affichage (Ecran + Fichier)
log() {
    echo -e "$1"
    echo -e "$1" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE"
}

header() {
    log ""
    log "${BLUE}========================================================${NC}"
    log "${BLUE}   $1${NC}"
    log "${BLUE}========================================================${NC}"
}

# --- DEBUT DU DIAGNOSTIC ---
clear
log "${YELLOW}🔍 LANCEMENT DU DIAGNOSTIC COMPLET DE DIDIER...${NC}"
log "Rapport sauvegardé dans : $LOG_FILE"

# 1. IDENTITÉ & SYSTÈME
header "1. SYSTÈME & SANTÉ"
MODEL=$(cat /proc/device-tree/model 2>/dev/null || echo "Raspberry Pi")
log "Modèle      : $MODEL"
log "OS          : $(grep PRETTY_NAME /etc/os-release | cut -d'"' -f2)"
log "Kernel      : $(uname -r)"
log "Uptime      : $(uptime -p)"

# Température & Throttling
TEMP=$(vcgencmd measure_temp)
THROTTLED=$(vcgencmd get_throttled)
log "Température : ${TEMP}"

if [ "$THROTTLED" == "throttled=0x0" ]; then
    log "Throttling  : ${GREEN}OK (Pas de surchauffe)${NC}"
else
    log "Throttling  : ${RED}ATTENTION (Code: $THROTTLED)${NC}"
fi

# 2. LE MATÉRIEL (HAT, USB, PCIe)
header "2. HARDWARE (HATs & Périphériques)"

log "${YELLOW}--- Bus PCI (Hailo / NVMe) ---${NC}"
if lspci | grep -q "."; then
    lspci | while read line; do log "  > $line"; done
else
    log "${RED}Aucun périphérique PCI détecté (Hailo mal branché ?)${NC}"
fi

log ""
log "${YELLOW}--- Bus USB (Micros / Clés) ---${NC}"
lsusb | while read line; do log "  > $line"; done

log ""
log "${YELLOW}--- Audio (Oreilles & Bouche) ---${NC}"
# Check Micro
log "MICROPHONES (Capture) :"
arecord -l | grep "card" || log "${RED}Aucun micro détecté !${NC}"
# Check Enceintes
log "ENCEINTES (Playback) :"
aplay -l | grep "card" || log "${RED}Aucune sortie audio détectée !${NC}"

# 3. RÉSEAU
header "3. RÉSEAU & CONNECTIVITÉ"
IP_LOCAL=$(hostname -I | cut -d' ' -f1)
log "IP Locale   : ${GREEN}$IP_LOCAL${NC}"

if ping -c 1 8.8.8.8 &> /dev/null; then
    log "Internet    : ${GREEN}CONNECTÉ${NC}"
else
    log "Internet    : ${RED}DÉCONNECTÉ${NC}"
fi

# 4. CERVEAU & CONTAINERS
header "4. DOCKER & OLLAMA"

if ! command -v docker &> /dev/null; then
    log "${RED}CRITIQUE : Docker n'est pas installé !${NC}"
else
    # Liste des conteneurs qui tournent
    log "${YELLOW}--- Conteneurs Actifs ---${NC}"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | while read line; do log "$line"; done
    
    log ""
    log "${YELLOW}--- Test API Ollama (Port 11434) ---${NC}"
    if curl -s --max-time 2 http://localhost:11434 > /dev/null; then
        log "${GREEN}SUCCÈS : Ollama répond.${NC}"
        # Essai de lister le modèle
        MODELS=$(curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
        log "Modèles chargés : $MODELS"
    else
        log "${RED}ECHEC : Ollama ne répond pas sur le port 11434.${NC}"
        log "Astuce : Vérifie 'docker logs loom_brain'"
    fi
fi

# 5. STOCKAGE
header "5. STOCKAGE"
df -h / | awk 'NR==2 {print "Disque Principal : Utilise " $5 " (" $4 " libres)"}'

log ""
log "${YELLOW}✅ DIAGNOSTIC TERMINÉ.${NC}"
EOF

# 2. On rend exécutable
chmod +x ~/workspace/Didier/diag.sh

# 3. On lance !
~/workspace/Didier/diag.sh
