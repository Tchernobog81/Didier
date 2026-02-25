# Fondation Didier

Etat de reference documente le 2026-02-18 (heure locale machine).
Statut: ARCHIVE LEGACY (ne pas utiliser pour l'etat runtime courant; voir `fondation_didier.md`).

## 1) Snapshot operationnel reel (au moment de la redaction)

- Version fichier: `didier-v4.0-optimized-2026-02-12` (`VERSION`)
- Revision git remontee par API: `4eee67b` (`/device-status`)
- Service principal actif: `run_didier.service` = `active`
- Services workers actifs:
- `didier-api.service` = `active`
- `didier-vision.service` = `active`
- `didier-brain.service` = `active`
- `didier-audio.service` = `active`
- `didier.service` = `inactive`
- Ports ecoutes observes:
- `0.0.0.0:5003` (process `uvicorn`, API legacy complete)
- `127.0.0.1:5010` (worker API)
- `127.0.0.1:5011` (worker vision)
- `127.0.0.1:5012` (worker brain)
- `127.0.0.1:5013` (worker audio)
- `0.0.0.0:8080` (code-server / VSCode)
- `127.0.0.1:11434` (Ollama local)

Etat health observe:
- `GET /ping` (5003): `{"status":"ok","name":"Didier"}`
- `GET /health` (5003): `{"status":"ok","name":"Didier"}`
- Workers 5010/5011/5012/5013: `status=ok` (detail selon worker)

## 2) Architecture actuelle (hybride)

Didier tourne en pratique avec deux plans:

1. Plan principal legacy (actif):
- Service: `run_didier.service`
- Commande: `uvicorn core.api:app --host 0.0.0.0 --port 5003`
- API complete + UI + tentacules + routes historiques

2. Plan workers edge (actif en parallele):
- `didier-api` sur `5010`
- `didier-vision` sur `5011`
- `didier-brain` sur `5012`
- `didier-audio` sur `5013`
- IPC unique en HTTP local `127.0.0.1`

## 3) Point d entree principal utilise en production

### 3.1 `core.api` (FastAPI sur 5003)

`core/api.py`:
- monte les fichiers statiques depuis `web/` sous `/static`
- expose `/` (retourne `web/index.html`) et `/ping`
- inclut les routeurs:
- `core/routers/system.py`
- `core/routers/vision.py`
- `core/routers/ai.py`
- `core/routers/actuators.py`
- demarrage (`startup`):
- `setup_logging()`
- creation `Orchestrator()`
- `await orchestrator.start()` (chargement tentacules)
- start watchdog camera (`_camera_watchdog`)
- warmup Ollama non bloquant (`_warmup_ollama`)

### 3.2 Orchestrator dynamique des tentacules

`core/orchestrator.py`:
- charge `config/config.json` via `DidierConfig`
- discover des modules `tentacles/*.py` (hors `_` et `base.py`)
- instancie `Tentacle(config, orchestrator=self)`
- lance `tentacle.start()` avec timeout (defaut 12s)
- indexe les tentacules par nom (`get_tentacle(name)`)

Tentacules disponibles dans le repo:
- `hearing`
- `vocal`
- `brain`
- `vision`
- `actuators`
- `music`

## 4) Chaine vocale actuelle (wake word -> reponse -> ecoute commande)

### 4.1 Hearing (ASR)

`tentacles/hearing.py`:
- capture audio micro via `arecord` (device ALSA `asr.alsa_device`, config actuelle `hw:2,0`)
- chunks WAV temporaires dans `/tmp/didier_mic_*.wav`
- downmix mono en prenant le canal le plus energique (PS3 Eye 4 canaux)
- transcription via binaire whisper.cpp (`asr.whisper_cpp_bin`) et modele config
- passage wake model puis passage command model

Detection wake:
- wake principal: `Yo! Didier`
- aliases configures (ex: `Yo Didier`, `Yadii`, etc.)
- matching tolerant aux erreurs ASR (normalisation + heuristiques + similarite)

Quand wake detecte:
- log `Wake word detected.`
- etat `LISTENING` ecrit dans `data/asr_status.json`
- tentacule `vocal` dit la phrase wake de config si active:
- texte actuel: `Salut Tcherno, qu'est-ce que je peux faire pour toi ?`
- fenetre d ecoute commande (`wake_timeout_seconds`)

Quand commande entendue:
- `_handle_transcript()`
- appelle `brain.generate(text)`
- pousse la reponse vers `vocal.speak(response)`
- met a jour `last_prompt` / `last_response` dans `data/asr_status.json`

### 4.2 Vocal (TTS)

`tentacles/vocal.py`:
- file async interne (queue)
- synthese Kokoro ONNX
- sortie WAV: `data/didier_speaks.wav`
- lecture via `paplay` vers sink bluetooth Soundboks
- fallback: tentative reconnect bluetooth si echec paplay

### 4.3 Brain (LLM)

`tentacles/brain.py`:
- appelle Ollama (`ollama.base_url`)
- compose prompt avec:
- memoire persistante (`core.memory.MemoryStore`)
- system prompt personality
- update des statuts `THINKING` / `IDLE`
- autotune LLM optionnel (bench, selection modele, persistence config)

## 5) API 5003: routes actives (catalogue)

### 5.1 System

- `GET /health`
- `GET /version`
- `GET /metrics`
- `GET /device-status`
- `GET /docker/diagram`
- `GET /files/search`
- `POST /terminal/exec`
- `GET /camera/holders`
- `POST /camera/reconnect`
- `POST /camera/force-format`

### 5.2 Vision

- `GET /vision/capture`
- `POST /vision/describe`
- `POST /vision/enroll`
- `GET /vision/owner`
- `GET /vision/status`
- `GET /vision/tags`
- `POST /vision/tags`
- `GET /vision/zones`
- `POST /vision/detect`
- `GET /vision/detections`
- `GET /vision/detections-secondary`
- `GET /vision/status-secondary`
- `GET /video/stream`
- `GET /video/stream-secondary`

### 5.3 IA / Audio

- `POST /speak`
- `POST /music/play`
- `POST /audio/test`
- `POST /ask`
- `POST /ask-and-speak`
- `POST /coding`
- `GET /ollama/models`
- `GET /asr/status`
- `POST /asr/wake-test`
- `POST /agent/react`
- `GET /agent/metrics`

### 5.4 Actionneurs

- `GET /actuators`
- `GET /actuators/{id}/status`
- `POST /actuators/{id}/command`

## 6) Comportement important des routes cle

### 6.1 `POST /ask`

- resolut modele ask (profil + fallback)
- prompt compact francais pour latence courte
- support experts (`@jardinage`, `code:`, etc.)
- peut passer par filtre OpenClaw react
- timeout borne
- fallback erreur: HTTP 503 `Ollama unavailable: ...`

### 6.2 `POST /ask-and-speak`

Pipeline prioritaire:
1. normalise prompt
2. regle rapide \"parle en francais\"
3. detection actionneur ON/OFF par langage naturel
4. detection musique
5. sinon LLM (Ollama)
6. envoi vocal de la reponse via `vocal`

Comportement anti-reponse vide:
- fallback texte court (`Je suis pret...`)
- remplace les reponses type `je t ecoute` par une reponse actionnable

### 6.3 `POST /asr/wake-test`

- test de bout en bout wake
- options: injection TTS wake, fallback loopback TTS->ASR, reply_on_wake
- sort:
- `status=ok` si wake matche
- `status=audio_only` si audio detecte sans wake
- `status=timeout` sinon
- retourne transcript entendu, delai, flags debug

### 6.4 `GET /metrics`

Expose:
- CPU (global + per-core)
- RAM
- disque root + SSD
- etat NPU
- etat audio/listening
- etat shared OpenClaw (`openclaw.shared_state_snapshot()`)

## 7) Vision actuelle

`tentacles/vision.py`:
- capture live primaire camera PS3 (`/dev/video0`) via OpenCV V4L2, fallback GStreamer puis fallback `v4l2-ctl`
- stream MJPEG principal via `/video/stream`
- stream secondaire remote UDP (ffmpeg image2pipe) via `/video/stream-secondary`
- detection:
- Hailo (`HailoDetector`) si init OK
- sinon fallback OpenCV shape
- support owner enrollment/check (embedding/LBPH/hist)
- expose ROI interaction (`person_in_roi`) pour gating vocal optionnel

## 8) Actionneurs (Yeelight)

`tentacles/actuators.py`:
- registre persistant: `config/actuators.json`
- transport: TCP JSON-RPC vers port Yeelight `55443`
- actions supportees:
- `on`, `off`, `toggle`
- `bright`/`brightness` (1..100)
- `color`/`rgb` (hex ou int)
- `validate` (peut aussi renommer)
- retries sur erreurs transitoires (`refused`, timeout, no response)
- status retourne `reachable`, etat courant lampe, derniere commande

Etat des lampes enregistrees actuellement:
- Entree (`192.168.1.12`)
- Chiottes (`192.168.1.18`)
- Cuisine (`192.168.1.19`)
- Dancefloor (`192.168.1.22`)
- Salle a manger (`192.168.1.23`)
- Canape (`192.168.1.24`)

## 9) Workers edge 5010-5013 (services natifs)

### 9.1 `didier-api` (5010)
- health + metrics de supervision workers
- proxy `/speak` vers audio worker
- `AUDIO_PROXY_TIMEOUT_S` bornable (defaut 1.5s)
- `POST /speak` retourne rapidement avec etat de queue audio

### 9.2 `didier-vision` (5011)
- process worker separe (multiprocessing spawn)
- health/metrics normalises (`status/service/uptime_s/ts/detail`)
- endpoint passif `/vision/status-secondary`
- mode `hailo_mode` ou `cpu_mode`

### 9.3 `didier-brain` (5012)
- bridge local vers Ollama (TCP ou Unix socket si present)
- micro-cerveau `MicroGPTLite` actif si configure
- `POST /generate`:
- reponse micro immediate pour prompts simples
- fallback `stub` si Ollama indisponible

### 9.4 `didier-audio` (5013)
- queue async interne
- `POST /speak` renvoie `{\"status\":\"queued\"}`
- `POST /beep` de test
- health/metrics normalises

## 10) OpenClaw integration actuelle

Active dans `config/config.json`:
- `openclaw.enabled = true`
- bridge runtime: `orchestrator/openclaw_bridge.py`
- wrapper process: `openclaw_wrapper.py`

Fonctions effectives:
- scheduler heartbeat interne a 2 Hz
- restart wrapper si down
- refresh memoire markdown partagee
- relais prompt via `/agent/react`
- metriques via `/agent/metrics`
- etat partage injecte dans `/metrics` (5003)

## 11) UI web actuelle (onglets et comportement)

Page: `web/index.html`, script: `web/app.js`.

Onglets:
- `Didier` (dashboard)
- `VSCode`
- `Terminal`
- `Workers Edge`
- `Actionneurs`

Elements majeurs:
- pastille statut `EN LIGNE` en haut droite
- test wake button (`/asr/wake-test`)
- chat Didier (`/ask-and-speak`)
- stream video primaire + secondaire
- terminal web local (`/terminal/exec`)
- panneau actionneurs ON/OFF + rename + intensite + couleurs
- iframe VSCode pointe sur `/vscode/?folder=/home/coder/project`

Polling UI principal:
- `/metrics` toutes 2s
- `/device-status` toutes 2s
- `/asr/status` toutes 2s
- `/vision/status-secondary` toutes 3s
- `/docker/diagram` toutes 5s

## 12) Configuration courante critique (`config/config.json`)

- Ollama:
- base URL: `http://localhost:11434`
- modele default: `llama3.2:1b`
- profile ask: `deepseek-r1:1.5b`
- profile coding: `deepseek-coder:1.3b`
- ASR:
- wake word: `Yo! Didier`
- wake reply: `Salut Tcherno, qu'est-ce que je peux faire pour toi ?`
- whisper bin: `/mnt/didier_ssd/didier/code/bin/whisper.cpp`
- TTS:
- modele Kokoro ONNX + voices bin
- Vision:
- camera principale `/dev/video0`
- stream secondaire UDP `udp://0.0.0.0:1234?...`
- Actionneurs:
- backend Yeelight LAN

## 13) Fichiers de persistance et etat

- etat ASR runtime: `data/asr_status.json`
- memoire conversation: `data/memory.json`
- tags vision: `data/vision/tags.json`
- owner vision: `data/vision/*`
- registre lampes: `config/actuators.json`
- logs rotates:
- `logs/didier.log`
- `logs/didier-audio.log`
- `logs/didier-vision.log`

## 14) Exploitation / outillage

- check one-command edge: `scripts/check_edge.sh`
- ports, health, bench latence, process cpu/ram, resultat pass/fail
- install services idempotent: `scripts/install_systemd.sh`
- rollback documente: `docs/ROLLBACK.md`

## 15) Coexistence et points de vigilance (structure actuelle)

1. Deux entrees applicatives coexistent:
- `run_didier.service` -> `core.api` (actif, complet)
- `didier_orchestrator.py` -> `orchestrator/flask_runtime.py` (autre chemin, plus minimal)

2. `docker-compose.yml` coexiste avec systemd natif:
- peut demarrer un chemin parallelle (`didier-brain`, `vscode`, `ollama`, `reverse-proxy`)

3. `nginx/nginx.conf` (compose) route `/` vers `127.0.0.1:5000` alors que le service legacy natif est sur `5003`.
- ce point est important si utilisation reverse-proxy compose en frontal.

4. Snapshot device courant a la redaction:
- micro/camera/npu/tts OK
- `sound.available=false` sur `/device-status` (sink SB pas actif a cet instant)

---

Ce document decrit l etat courant du code et des services actifs, sans projection future.
