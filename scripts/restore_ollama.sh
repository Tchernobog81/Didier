#!/bin/bash

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}🔧 DIAGNOSTIC ET RESTAURATION OLLAMA POUR DIDIER${NC}"

# 1. Vérification et Démarrage du Conteneur
echo -e "\n${YELLOW}[1/3] Vérification du service Docker Ollama...${NC}"

if [ "$(docker ps -q -f name=ollama)" ]; then
    echo -e "${GREEN}✅ Le conteneur Ollama est déjà en cours d'exécution.${NC}"
else
    echo -e "${RED}❌ Le conteneur Ollama est arrêté. Tentative de démarrage...${NC}"
    docker compose up -d ollama
    
    echo "Attente de 5 secondes pour l'initialisation..."
    sleep 5
    
    if [ "$(docker ps -q -f name=ollama)" ]; then
        echo -e "${GREEN}✅ Ollama a démarré avec succès.${NC}"
    else
        echo -e "${RED}🔥 Échec critique : Impossible de démarrer Ollama. Vérifiez les logs (docker logs ollama).${NC}"
        exit 1
    fi
fi

# 2. Liste des modèles Edge (basée sur config.json)
MODELS=(
    "llama3.2:1b"        # Cerveau principal / Chat rapide
    "qwen2.5:0.5b"       # Ultra-léger (Réflexe)
    "llama3.2:3b"        # Alternative plus intelligente
    "qwen2.5:1.5b"       # Expert Jardinage / Cuisine
    "gemma2:2b"          # Expert Bricolage
    "qwen2.5-coder:1.5b" # Expert Code
    "phi3.5:3.8b"        # Expert Résumé
    "moondream:1.8b"     # Vision (Description d'image)
)

echo -e "\n${YELLOW}[2/3] Vérification et téléchargement des modèles...${NC}"

for model in "${MODELS[@]}"; do
    echo -e "👉 Vérification de ${YELLOW}$model${NC}..."
    # On utilise docker exec pour lancer le pull directement DANS le conteneur
    docker exec ollama ollama pull "$model"
done

echo -e "\n${YELLOW}[3/3] Test rapide...${NC}"
docker exec ollama ollama list

# Bonus : Vérification des dépendances Python pour LiteRT
echo -e "\n${YELLOW}[4/4] Vérification dépendances LiteRT...${NC}"
if ! docker exec didier-brain pip show tflite-runtime > /dev/null 2>&1; then
    echo -e "${RED}⚠️ tflite-runtime manquant. Installation...${NC}"
    docker exec didier-brain pip install tflite-runtime
fi

echo -e "\n${GREEN}✅ Opération terminée. Didier a retrouvé sa mémoire.${NC}"