# Plan d'Unification : Flask vers FastAPI

Ce document détaille les étapes pour fusionner l'interface matérielle (`didier_orchestrator.py`) avec le cerveau cognitif (`main.py`).

## Phase 1 : Modularisation du Matériel (Hardware Layer)
Objectif : Extraire la logique matérielle du script Flask vers des modules réutilisables dans `orchestrator/`.

- [ ] **Créer `orchestrator/audio.py` (AudioManager)**
  - Intégrer `Kokoro` (TTS) : Chargement du modèle ONNX et génération audio.
  - Intégrer `paplay` : Lecture audio via subprocess (compatible PulseAudio).
  - Gestion des erreurs (si `paplay` ou modèle absent).

- [ ] **Créer `orchestrator/vision.py` (VisionManager)**
  - Intégrer `cv2` (OpenCV) : Capture d'image depuis `/dev/video0`.
  - Gestion de la sauvegarde fichiers (`data/capture.jpg`).
  - Préparer l'intégration future des détections Hailo.

## Phase 2 : Intégration dans l'Orchestrateur (Core Layer)
Objectif : Rendre ces capacités accessibles à l'application principale.

- [ ] **Mise à jour de `orchestrator/core.py`**
  - Initialiser `AudioManager` et `VisionManager` au démarrage.
  - Passer la configuration (`config.json`) à ces modules.

- [ ] **Mise à jour de `DidierAgent`**
  - Permettre à l'agent de déclencher la parole (TTS) automatiquement après une réponse LLM.
  - Permettre à l'agent de "voir" (appeler VisionManager) si le prompt le demande.

## Phase 3 : Migration des Interfaces (API Layer)
Objectif : Remplacer les routes Flask par des routes FastAPI asynchrones dans `main.py`.

- [ ] **Route `/api/speak`** : Endpoint direct pour le TTS.
- [ ] **Route `/api/see`** : Endpoint pour capture + retour JSON (chemin fichier).
- [ ] **Route `/chat` (Améliorée)** :
  - Pipeline complet : User Text -> LLM (Ollama) -> TTS (Audio).

## Phase 4 : Nettoyage et Bascule
Objectif : Supprimer la dette technique.

- [ ] **Mise à jour `docker-compose.dev.yml`** : Changer la commande de démarrage pour `uvicorn main:app`.
- [ ] **Suppression** de `didier_orchestrator.py`.
- [ ] **Validation** : Test complet Voix + Vision + Chat.
