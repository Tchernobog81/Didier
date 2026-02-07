# ABOUT — DIDIER

**🤖 DIDIER v4.0 — Orchestrateur local et sceptique**

> "Je pense, donc je doute. Et puisque je doute de vous, je suis probablement supérieur." — Didier

## Résumé
Didier est un orchestrateur edge conçu pour tourner sur un Raspberry Pi (ex : Pi 5). Son objectif est de superviser des modèles locaux (Ollama), garder une mémoire locale contextuelle et automatiser des tâches de maintenance système — tout en ayant une personnalité sarcastique et challengée.

## Personnalité 🎭
- **Bienveillant mais sarcastique** : aide utile, ton pince-sans-rire.
- **Pratique le doute** : privilégie la prudence, ne pas considérer ses réponses comme des certitudes.
- **Challenger** : vise à pousser les contributeurs (Florian & Sacha) à s'améliorer.

## Composants clés 🔧
- Orchestrateur : `orchestrator/core.py` — initialise `Memory`, `ModelManager`, `DidierAgent`.
- Agent : `orchestrator/agent.py` — point d'entrée `chat()` (actuellement placeholder, idéal pour y brancher l'inférence).
- Mémoire : `orchestrator/memory.py` — SQLite (`conversations`), méthodes `save_message` & `get_recent`.
- ModelManager : `orchestrator/model_manager.py` — recherche HF + placeholder `download_model()`; désormais contient `generate()` pour Ollama.
- API : `main.py` (FastAPI) — routes `/health`, `/chat`, `/models/search`.
- UI local & outils : `didier_orchestrator.py` (Flask) — interface matérielle, `/ask` → Ollama, `/terminal` exécute commandes shell (⚠️ sécurité).

## Exécution & dev 🚀
- En local (venv) :
  - Installer : `pip install -r requirements.txt`
  - Lancer : `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- Conteneurisé : `docker compose up -d` (démarre `ollama` + `didier-brain`).
- Tests : `pytest -q` (tests ajoutés pour `Memory` et `DidierAgent` avec stub de `ModelManager`).

## Sécurité & licences ⚠️
- `didier_orchestrator.py` expose `/terminal` qui exécute des commandes shell ; **ne pas exposer** cette UI sans authentification stricte.
- Les blobs de modèles (ex : Llama 3.2) contiennent des clauses de licence importantes (restriction EU pour multimodaux, interdictions d'usage spécifiques). Vérifiez `ollama/models/blobs/*` avant déploiement.

## Conventions & contributions 🧭
- Préférez des branches courtes et des PRs ciblées.
- Tests unitaires exigés pour toute logique non triviale (mémoire, infra modèle, intégration Ollama).
- Evitez de télécharger des poids volumineux directement sur Pi — privilégier modèles quantifiés / ONNX/TF-Lite.

## Priorités recommandées (pour nouveaux contributeurs) ✅
1. **Relier `DidierAgent.chat()` à un backend d'inférence** (Ollama/ONNX) — `orchestrator/agent.py` ➜ `ModelManager.generate()` (exemple déjà ajouté).
2. **Implémenter `ModelManager.download_model()`** pour le runtime cible (ONNX/TFLite) avec gestion de l'espace disque et quantification.
3. **Ajout de tests d'intégration** simulating Ollama responses (HTTP stub) et workflows end-to-end.

---

Si tu veux, je peux :
- proposer un exemple de PR qui ajoute un client d'inférence alternatif (ex: ONNX runtime) ; ou
- créer une issue template / CONTRIBUTING.md pour formaliser les attentes.

Merci — dis-moi quelle action prioritaire tu préfères. 👇