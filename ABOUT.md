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

## Mission v3.0 : "Speedy Didier" 🚀

**Objectif Principal** : Migrer l'architecture d'un monolithe conteneurisé vers une exécution "Native-Native" (sans Docker) sur Raspberry Pi 5, optimisée pour la haute performance Edge AI.

### ÉTAPE 1 : Audit & Découpage
*   **Analyse de la Dette Technique** : Éliminer les appels bloquants (synchrones) et les boucles inefficaces (ex: `arecord`, `cv2.imdecode`, scans Docker) qui consomment du CPU au repos.
*   **Validation du Découpage Modulaire** : Assurer l'étanchéité des nouveaux services pour le système (`router_system.py`), la vision (`router_vision.py`), et l'IA (`router_ai.py`).
*   **Audit Hardware** : Garantir que les accès matériels critiques (PCIe pour Hailo, I/O pour SSD) ne sont jamais verrouillés.

### ÉTAPE 2 : Doctrine de Performance "Speedy"
*   **Zéro Framework Inutile** : Privilégier Python pur pour les tâches simples pour minimiser la surcharge.
*   **AOT (Ahead-Of-Time)** : Pré-compiler tous les modèles pour le NPU Hailo-8L afin d'éliminer les temps de chauffe (`warmup`).
*   **Monitoring Asynchrone** : Calculer les métriques en arrière-plan à basse fréquence (ex: 2Hz) et les stocker dans un état partagé pour une lecture instantanée.

### ÉTAPE 3 : Plan d'Implémentation
*   **Phase A (Dé-Dockerisation)** : Remplacer les conteneurs Docker par des services `systemd`. Mettre en place un `venv` optimisé avec les bindings matériels (Hailo, LiteRT).
*   **Phase B (Routes Légères)** : Créer des endpoints de statut non bloquants (ex: `/vision/status-secondary`) et limiter la fréquence des appels depuis le frontend.
*   **Phase C (Cerveau Réflexe)** : Intégrer un micro-modèle (type microGPT) pour analyser les flux de données en temps réel et ne solliciter le LLM principal (Ollama) que sur détection d'anomalies pertinentes.

## État de la Migration (2026-02-12) 🚧

**Statut :** Migration V3/V4 en cours (Étape 2 : Migration Asynchrone).

**Points de contrôle (Checklist) :**
1.  [x] Optimisation `RemoteMjpegStream` (Thread + Queue).
2.  [x] Ajout utilitaire `_run_cmd_async_text` et migration `_read_version`.
3.  [ ] **CRITIQUE** : Finaliser la migration des commandes système (`pactl`, `fuser`, `v4l2-ctl`) vers `asyncio` dans `core/api_impl.py`.
4.  [ ] Activer le monitoring système asynchrone (2Hz).
5.  [ ] Valider la stabilité du flux vidéo UDP sur `/video/stream-secondary`.

---

Si tu veux, je peux :
- proposer un exemple de PR qui ajoute un client d'inférence alternatif (ex: ONNX runtime) ; ou
- créer une issue template / CONTRIBUTING.md pour formaliser les attentes.

Merci — dis-moi quelle action prioritaire tu préfères. 👇