# Architecture Technique de DIDIER

Ce document décrit l'architecture technique du projet Didier (v4.0) tel qu'analysé, pour servir de référence aux développeurs et aux agents IA.

## 1. Vue d'ensemble (Edge-Native)
Didier est un orchestrateur conçu pour le **Raspberry Pi 5**, tirant parti de l'accélération matérielle locale (NPU Hailo, GPU/CPU) pour minimiser la latence et la dépendance au cloud.

### Stack Infrastructure
- **Runtime** : Docker & Docker Compose.
- **OS Hôte** : Linux (accès privilégié requis pour le matériel).
- **Réseau** : `network_mode: "host"` (crucial pour mDNS, Bluetooth, PulseAudio).

## 2. Topologie des Services (Docker)

| Service | Rôle | Accès Matériel | Persistance |
| :--- | :--- | :--- | :--- |
| **`didier-brain`** | Cœur applicatif (Python). Orchestre la vision, la voix et la logique. | ✅ `/dev/hailo0` (NPU)<br>✅ `/dev/video0` (Cam)<br>✅ `/dev/snd` (Audio) | `/app/data`<br>`/app/config` |
| **`ollama`** | Serveur d'inférence LLM local. Expose une API HTTP sur le port 11435. | ❌ (Utilise CPU/RAM hôte) | `/root/.ollama` (Modèles) |
| **`didier-vscode`** | Environnement de dev distant (Code Server). | ❌ | Workspace partagé |
| **`reverse-proxy`** | Nginx pour sécuriser/router les accès externes. | ❌ | Certificats SSL |

## 3. Architecture Logicielle (État Actuel)
Le projet présente actuellement une dualité qu'il faudra unifier :

### A. L'Interface Matérielle (`didier_orchestrator.py` - Flask)
- **Rôle** : Gère les E/S physiques immédiates.
- **Endpoints** :
  - `/ask` : Bridge vers Ollama + TTS.
  - `/see` : Capture OpenCV + Sauvegarde.
- **Points forts** : Fonctionnel, accès direct au hardware.

### B. Le Cerveau Cognitif (`main.py` / `orchestrator/` - FastAPI)
- **Rôle** : Gestion de l'état, mémoire, et logique complexe.
- **Composants** :
  - `DidierAgent` : Gestion de la persona et du flux de chat.
  - `Memory` : Stockage SQLite des conversations.
  - `ModelManager` : Abstraction pour le téléchargement/chargement de modèles.
- **Points forts** : Structuré, extensible, asynchrone.

## 4. Flux de Données (Data Flow)

### Pipeline Vocal (Interaction)
1.  **Input** : Micro (ALSA) -> `whisper.cpp` (ASR) -> Texte.
2.  **Cognition** : Texte -> `didier-brain` -> API Ollama (`llama3.2`) -> Réponse Texte.
3.  **Output** : Réponse Texte -> `kokoro-onnx` (TTS) -> WAV -> `paplay` (PulseAudio) -> Bluetooth Sink.

### Pipeline Visuel
1.  **Input** : Caméra (PS3 Eye) -> OpenCV (`/dev/video0`).
2.  **Traitement** :
    - Détection : Hailo-8L (YOLO/SSD via `hailo_model.hef`).
    - Description : VLM (`moondream`).
3.  **Output** : Fichiers JPG dans `data/` ou flux JSON.

## 5. Gestion des Données (Persistence)

- **Configuration** : `config/config.json` (Source de vérité statique).
- **État Domotique** : `config/actuators.json`.
- **Mémoire Court Terme** : `data/memory.json`.
- **Mémoire Long Terme** : `data/didier.db` (SQLite).
- **Modèles** : Stockés sur SSD (`/mnt/didier_ssd`) pour éviter la saturation SD.

## 6. Points d'Attention (Dette Technique)
1.  **Unification** : Fusionner la logique Flask (`didier_orchestrator.py`) dans l'architecture FastAPI (`main.py`).
2.  **Mémoire** : Consolider les multiples formats de mémoire (JSON, MD, SQL) en une interface unique.
3.  **Sécurité** : L'exécution de commandes shell (`/terminal`) et l'accès `privileged` nécessitent une sécurisation accrue.
