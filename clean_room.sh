#!/bin/bash
echo "[DIDIER] Début du protocole de nettoyage..."
# Nettoyage Docker
docker image prune -f
# Nettoyage des logs (auditabilité préservée sur 24h)
sudo journalctl --vacuum-time=1d
# Nettoyage cache système
sudo apt-get clean
echo "[DIDIER] Nettoyage terminé. La chambre est propre, Florian."
