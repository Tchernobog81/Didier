# Fondation Didier (Version Exportable)

Date de reference: 2026-03-01
Statut global: VISION YOLO26 HAILO ACTIVE + FLUX SURFACE CADENCE CORRIGEE + PARITE DE DETECTION PS3/SURFACE + INDICES COCO VISIBLES VALIDES
- Release UI: `didier-v4r37-coco-hints-visible-2026-03-01`
- Tag de reference: `didier_alive`

## Mise a jour 2026-03-01 (V4r37 - Vision YOLO26 / Surface / COCO)

- Release validee: `didier-v4r37-coco-hints-visible-2026-03-01`
- Vision Hailo:
  - `yolo26n.hef` est l'artefact runtime actif
  - le post-processing manuel des 6 sorties YOLO26 (branches boxes + classes) est actif dans le runtime
  - la detection semantique est validee sur les deux flux pendant la meme fenetre de controle (`personne` sur PS3 et `personne` sur Surface)
  - les payloads de detection exposent maintenant `semantic_hints`, ce qui rend visibles les meilleures classes COCO meme quand aucune detection n'est encore confirmee
- Flux Surface:
  - la cause des saccades etait backend: le generateur MJPEG HTTP suivait encore le `target_fps` de l'arbitre (`10 fps` en `TENDU`) au lieu du `15 fps` configure pour le flux distant
  - le correctif v4r36 (toujours actif dans v4r37) force maintenant la reemission, le watchdog de stall et le backoff de restart a respecter le `fps` configure du flux Surface
  - validation backend: `/vision/status-secondary` remonte `diagnostic=healthy`, `fps=15`, `frame_gap_s~0.04`
- UI diagnostic objet:
  - quand un frame reste sous seuil, l'UI peut maintenant afficher des `indices COCO` plutot qu'un vide semantique ou seulement des formes brutes
  - cela permet de voir des classes comme `personne`, `camion`, `parapluie`, `television` meme en dessous du seuil de confirmation
- Telemetrie NPU:
  - `/metrics` publie maintenant un `utilization` estime si Hailo est actif mais que le driver ne fournit pas de pourcentage exploitable
  - retour valide en temps reel: `active=true`, `real_fps~15`, `hailo0` visible comme actif
- Source canonique de cet etat runtime:
  - `memory/technical/next-session.md`
  - `memory/technical/registry.json`

## Mise a jour 2026-02-25 (Hard Purge OpenClaw)

- Purge physique terminee:
  - dossier `openclaw/` supprime du depot.
  - fichiers legacy OpenClaw supprimes (services, bridge, wrapper, runtime config).
- Runtime aligne Picobot uniquement:
  - `core/api.py` n'integre plus de loop OpenClaw.
  - `core/shared_state.py` ne publie plus de bloc `openclaw`.
  - `shared/ipc.py` route `picobot` (plus de cible `openclaw`).
- Services:
  - `didier-brain.service`: `DIDIER_BRAIN_TASK_ROUTE_TARGET=picobot`.
  - `didier-api.service`: variables `DIDIER_OPENCLAW_*` retirees.
- Note de tracabilite:
  - toute mention OpenClaw restante dans ce document est archive historique, non active en production.

## Mise a jour 2026-02-24 (V4r2)

- UI:
  - Onglet `Sens & Actionneurs` supprime du dashboard web.
  - Onglet `Actionneurs` conserve.
- Orientation architecture:
  - demarrage du chantier "Didier Edge AI vivant" base sur `llmfit` (hardware-aware routing).
- Version UI runtime:
  - `V4r2 · 2026-02-24`
  - assets: `styles.css?v=20260224-v4r2-llmfit-step1`, `app.js?v=20260224-v4r2-llmfit-step1`

## Mise a jour 2026-02-25 (Etape 7)

- Validation scenarios hardware-aware:
  - Pixel present (`192.168.1.50`) -> route chat `preferred_backend=pixel_tpu`, `execution_backend=pixel_ollama`.
  - Pixel absent -> fallback `local_ollama`.
  - Vision sans NPU -> fallback local confirme.
- Stabilisation runtime:
  - ajout d'un ciblage Ollama (`core/ollama_targeting.py`) avec probe `2.0s` + fallback automatique vers local.
  - `POST /ask` ne retourne plus d'erreur 503 en boucle si backend LLM indisponible; retour degrade controle.
- Detection Pixel:
  - `config/config.json` aligne `hardware.discovery.pixel_ip_hints=["192.168.1.50"]`.
  - `hardware_profile.tpu.pixel_detected=true` verifie dans `/hardware/llmfit`.
- Blocage externe constate sur le Pixel:
  - `GET /api/tags` OK.
  - `POST /api/generate` KO avec erreur runtime: `error starting runner: exec: "serve": executable file not found in $PATH`.
  - consequence: fallback local active tant que l'installation Ollama Pixel n'est pas corrigee.
- Integration Picobot -> Pixel Brain (propre):
  - `picobot_data/config.json` aligne sur provider `openai` avec endpoint `http://192.168.1.50:8080/v1`.
  - modele cible: `qwen-2.5-3b` (resolved par le serveur Pixel vers `qwen-2.5-3b.gguf`).
  - tool principal configure: `get_system_status` -> `GET http://192.168.1.47:5010/health`.
  - `config/config.json` section `picobot` synchronisee (`llm_provider`, `llm_endpoint`, `llm_model`, `system_prompt`).

## Programme llmfit (trace projet communautaire)

Objectif: rendre Didier auto-adaptatif selon hardware detecte et selectionner automatiquement le meilleur backend/model par type de tache.

Statut par etape:
- Etape 1 (INTEGREE): module independent + API `get_best_model(task_type, context)`.
- Etape 2 (INTEGREE): detection hardware dynamique + `hardware_profile` partage sur changement.
- Etape 3 (INTEGREE): routing intelligent dans brain/API via `choose_backend(prompt, task_type)`.
- Etape 4 (INTEGREE): integration Picobot bridge vers llmfit (`/agent/route` + delegation bridge par contrat).
- Etape 5 (INTEGREE): UI monitoring "Hardware & Models" + endpoint `GET /hardware/llmfit`.
- Etape 6 (INTEGREE): durcissement open-source (config de routage, abstractions generiques, docs communautaires, tests).
- Etape 7 (VALIDEE AVEC RESERVES): scenarios de routage valides, reserve runtime Pixel Ollama + reserve idle strict.

Artefacts Etape 1:
- `core/hardware_aware.py`
- `core/llmfit/__init__.py`
- `core/llmfit/README.md`
- `requirements-llmfit.txt`
- `config/config.json` section `llmfit`
- `tests/test_hardware_aware.py`

Artefacts Etape 2:
- `core/network_discovery.py`
- `core/shared_state.py` (`hardware_profile` + update on-change)
- `core/api.py` (integration loop shared state)
- `config/config.json` section `hardware.discovery`

Artefacts Etape 3:
- `core/backend_routing.py`
- `core/routers/ai.py` (`/ask`, `/ask-and-speak`, `/agent/react` routes avec contrat de routage)
- `scripts/run_brain.py` (worker brain avec `choose_backend` + metriques de routage)

Artefacts Etape 4:
- `scripts/run_picobot_bridge.py` (`/agent/route`, `/route`, delegation par `routing.preferred_backend`)
- `core/routers/ai.py` (`POST /agent/route` proxy + fallback local)

Artefacts Etape 5:
- `core/routers/system.py` (`GET /hardware/llmfit`, cache TTL, rapport complet recommandations)
- `web/index.html` (section "Hardware & Models" dans l'onglet Picobot)
- `web/app.js` (render live cartes + tableau llmfit)
- `web/styles.css` (styles score Perfect/Good/Marginal/Fallback)

Artefacts Etape 6:
- `config/config.json` section `routing` (alias, seuils prompt, devices supportes, priorites backend)
- `core/backend_routing.py` (policy configurable + gate devices supportes)
- `core/contracts.py` (abstractions `TentacleContract`, `ActuatorContract`, `PeripheralContract`)
- `tentacles/base.py` (base tentacles branchee sur contrat commun)
- `tests/test_backend_routing.py` (tests seuils/alias/device-gating)
- `CONTRIBUTING.md` + `README.md` (guides communautaires)

Artefacts Etape 7:
- `core/ollama_targeting.py` (resolution endpoint Pixel + probe health `2.0s`)
- `core/routers/ai.py` (selection backend Ollama dynamique + fallback local si Pixel KO)
- `scripts/run_brain.py` (execution backend aware + fallback local/stub stable)
- `tests/test_ollama_targeting.py`

## 1) Architecture active

- Point d'entree unique API: `didier-api.service` sur `0.0.0.0:5010`
- Workers edge:
  - `didier-vision.service` (socket Unix `/tmp/didier_vision.sock`)
  - `didier-brain.service` (socket Unix `/tmp/didier_brain.sock`)
  - `didier-audio.service` (socket Unix `/tmp/didier_audio.sock`)
  - `didier-asr.service` (service ASR dedie, health HTTP `127.0.0.1:5014`)
- Agent externe:
  - `didier-picobot.service` (service agent Go)
  - bridge HTTP `scripts/run_picobot_bridge.py` via `POST /agent/route`
- IPC interne: priorite Unix sockets via `shared/ipc.py`, fallback HTTP local si necessaire
- Deploiement production: 100% systemd natif
- Docker: uniquement dev (`docker-compose.dev.yml`)

## 2) Etat migration Picobot (doctrine Speedy)

- Eradication OpenClaw runtime + code + services + configs -> VALIDEE
- Service systemd Picobot + persistance `picobot_data/` -> VALIDEE
- Bridge `/agent/*` vers Picobot avec fallback local -> VALIDEE
- Monitoring integration (`/system/integrations`) -> VALIDE

## 3) Contrats runtime en place

### Picobot metrics

- Endpoint API: `GET /agent/metrics` (via `:5010`)
- Retour attendu:
  - `ok=true`
  - `source=picobot_bridge`
  - etat bridge `connected/degraded`
  - score routage llmfit expose via `GET /hardware/llmfit`

### Memoire agent partagee

- Sources suivies:
  - `picobot_data/config.json`
  - `config/config.json` (`picobot`, `llmfit`, `routing`)
- Endpoints:
  - `GET /agent/memory`
  - `POST /agent/memory`

## 4) Services systemd critiques

- `didier-api.service`
- `didier-vision.service`
- `didier-brain.service`
- `didier-audio.service`
- `didier-asr.service`
- `didier-picobot.service`
- `didier-soundboks.service`

## 5) Resultats de recette (dernieres validations)

### OK

- API unifiee accessible sur `5010`
- SharedState centralise actif (`source=shared_state_v1`)
- Picobot visible dans `/agent/metrics` et `/system/integrations`
- Delegation `/agent/route` pilotee par `choose_backend`
- Monitoring hardware/model disponible via `/hardware/llmfit`
- Memoire agent lisible/ecrivable via API

### Points encore ouverts

- Critere load idle strict `<0.3` non atteint en charge de validation (reserve acceptee)

### Optimisations fluidite (2026-02-20, etapes 3-5 validees)

- Brain worker:
  - filtre `MicroGPTLite` renforce pour court-circuiter plus de prompts courts
  - nouvelles metriques: `requests_total`, `micro_shortcuts`, `micro_bypass_ratio`
- SharedState loops:
  - intervals de publication parametrables par env (`DIDIER_*_SHARED_STATE_INTERVAL_S`, valeur courante `1.0`)
  - `core/api.py` utilise `psutil.cpu_percent(interval=None)` (non bloquant) au lieu de sondage bloquant
  - boucle de sync agent intervallee par variables `DIDIER_*_INTERVAL_S`
- Systemd CPU scheduling:
  - ajout `CPUQuota` + `Nice` sur `didier-api`, `didier-brain`, `didier-vision`, `didier-audio`, `didier-asr`, `didier-picobot`, `didier-soundboks`
- Etape 4 (bonus fluidite UI):
  - nouveau flux WebSocket `GET ws://<host>:5010/ws/metrics` (router system)
  - payload live: `metrics` + `asr`
  - `web/app.js` bascule auto en mode WS et coupe les polls `fetchMetrics`/`fetchAsrStatus` tant que le socket est connecte
  - fallback automatique au polling HTTP si WS coupe, puis reconnexion
- Etape 5 (validation globale, 2026-02-20):
  - `POST /agent/react`: OK (`status_code=202`)
  - wake test ASR (`/asr/wake-test` text probes): OK
  - chaine `/ask-and-speak`: OK (reponse + audio queue)
  - script unique mis a jour: `scripts/check_edge.sh` (ports, health, bench, react, wake, ask-and-speak, idle gate)
  - point restant: idle strict `<0.3` non atteint sur la machine de validation (load1 observe > 9), principalement pendant activite inference (`ollama runner`, `whisper.cpp`) et outillage dev actif

## 6) Rollback officiel

- Procedure complete: `docs/ROLLBACK.md`
- Principe fallback actuel:
  - `didier-picobot.service` OFF
  - API `5010` conservee (routes agent avec fallback local)
  - llmfit continue en mode profile fallback

## 7) Commandes de verification rapide

```bash
systemctl is-active didier-api.service didier-vision.service didier-brain.service didier-audio.service didier-asr.service didier-picobot.service
curl -sS http://127.0.0.1:5010/health
curl -sS http://127.0.0.1:5010/metrics
curl -sS "http://127.0.0.1:5010/agent/metrics?timeout_s=2"
curl -sS http://127.0.0.1:5010/hardware/llmfit
```

## 8) Fichiers de reference

- `fondation_didier.md` (ce document)
- `README.md`
- `docs/ROLLBACK.md`
- `config/config.json`
- `picobot_data/config.json`
- `services/didier-picobot.service`
- `scripts/run_picobot_bridge.py`
- `core/shared_state.py`

## 9) Archive historique (legacy pre-Picobot)

Les sections suivantes documentent les etapes historiques avant la bascule vers Picobot/llmfit.  
Elles sont conservees pour tracabilite uniquement.
Les chemins/fichiers OpenClaw cites ci-dessous ont ete retires du runtime courant et ne doivent plus etre utilises.

### Etape 1 (en place)

- Tag git pose: `openclaw_aware`
- Routage intelligent ajoute dans `core/routers/ai.py`:
  - nouvelle fonction `process_input(text, is_voice=False, image_bytes=None)`
  - detection legere tache vs conversation
  - tache -> delegation OpenClaw (`relay_react` via socket bridge)
  - conversation -> chemin Ollama classique
- Endpoint `POST /ask` branche sur `process_input`
- Endpoint `POST /ask-and-speak`:
  - en mode voix, les demandes detectees comme taches passent d'abord par OpenClaw
  - reponse vocale conservee si tentacule vocal present
- `services/didier-brain.service` complete avec variables de routage:
  - `DIDIER_BRAIN_TASK_ROUTING=1`
  - `DIDIER_BRAIN_TASK_ROUTE_TARGET=openclaw`

### Etape 2 (en place)

- Worker vision enrichi avec `GET /vision/see_user` (`scripts/run_vision.py`)
  - check de fraicheur frame (`last_frame_age_s`)
  - option owner-check via API locale (`/vision/owner`) avec timeout court
  - retour compact: `seen`, `location`, `summary`, `owner_check`
- Brain/API (`core/routers/ai.py`) integre un "coup d'oeil" a chaque interaction:
  - appel IPC vers worker vision (`/vision/see_user`)
  - injection d'un prefixe contextuel dans la reponse (`Je te vois ...`) quand disponible
  - payload reponse expose aussi `vision`
- Service vision complete avec variables de tuning:
  - `DIDIER_VISION_SEE_MAX_AGE_S`
  - `DIDIER_VISION_SEE_OWNER_CHECK`
  - `DIDIER_VISION_SEE_OWNER_TIMEOUT_S`
  - `DIDIER_VISION_ROOM_HINT`

### Etape 3 (en place)

- Reponse duale standardisee dans `core/routers/ai.py` (`POST /ask-and-speak`):
  - texte toujours renvoye au client (chat UI)
  - tentative TTS via worker audio (`didier-audio`) sur socket interne
  - verification Soundboks avant queue TTS
  - fallback explicite si enceinte absente/non connectee (mode ecrit seul)
- UI chat (`web/app.js`) enrichie:
  - affichage de la reponse texte comme avant
  - affichage d'une ligne `[Audio] ...` quand fallback audio

### Etape 4 (en place)

- UI:
  - nouvel onglet `Tâches OpenClaw` dans `web/index.html`
  - panneau dedie avec:
    - bandeau KPI (runtime, latence bridge, taches actives, erreurs, scheduler, etat endpoint)
    - liste de cartes taches "En cours"
    - timeline verticale des evenements recents
  - version UI incrementee: `V3r2 · 2026-02-19`
- JS (`web/app.js`):
  - polling live sur `/agent/metrics?timeout_s=2` et `/agent/tasks` (4s)
  - normalisation robuste des payloads taches
  - fallback visuel si `/agent/tasks` absent (prevu a l'etape 5)
  - bouton `Rafraichir` pour forcer la synchro
- CSS (`web/styles.css`):
  - theme OpenClaw (cartes + timeline + KPI), responsive mobile

## 10) Incident micro-coupure (2026-02-21)

- Cause confirmee: micro-coupure electrique (intemperies), pas un crash applicatif pur.
- Verification post-redemarrage:
  - `didier-api` `didier-asr` `didier-brain` `didier-audio` `didier-vision` actifs
  - endpoints critiques OK: `/health`, `/peripherals`, `POST /agent/react`
  - IPC sockets workers presentes
- Point d'attention non bloquant:
  - `NetworkManager-wait-online.service` et `logrotate.service` en failed dans `systemctl --failed`

## 11) UI Peripheriques (etape 4 du protocole UI) - 2026-02-21

- Onglet `Sens & Actionneurs` cable complet:
  - boutons `Activer`/`Desactiver` branches sur `POST /peripherals/toggle`
  - feedback utilisateur clair (progression, succes, erreur)
  - rafraichissement automatique de l'etat apres action
- Validation fonctionnelle:
  - toggle reel `video: stop -> inactive`
  - toggle reel `video: start -> active`

## 12) Correctifs systeme et thermique (2026-02-21)

- Correctif `logrotate.service`:
  - cause: rotation Didier sur dossier groupe-writable sans `su`
  - fix: regle `/etc/logrotate.d/didier` avec `su tchernobog tchernobog`
  - etat apres fix: `logrotate.service` passe en succes
- Correctif `NetworkManager-wait-online.service`:
  - cause: timeout trop court pendant reprise reseau post-coupure
  - fix: override systemd `ExecStart=/usr/bin/nm-online -s -q -t 120`
  - etat apres fix: service `active (exited)`
- Persistance:
  - template logrotate versionne: `config/logrotate.d/didier`
  - override NM wait-online versionne: `services/NetworkManager-wait-online.override.conf`
  - installation idempotente mise a jour: `scripts/install_systemd.sh`
- Tuning charge/thermique ASR:
  - `DIDIER_ASR_MODEL_PATH` -> `ggml-base.bin`
  - `DIDIER_ASR_WAKE_MODEL_PATH` -> `ggml-tiny.bin`
  - `DIDIER_ASR_WAKE_EVERY_N_CHUNKS=3`
  - wake VAD renforce (`min_speech_ratio=0.22`, `abs_min=0.015`)
  - cgroup ASR ajuste: `CPUQuota=70%`, `Nice=7`
  - effet observe: plus de process `whisper.cpp` runaway, temperature stabilisee ~49C en mesure post-fix
- Tuning anti-boucle vision (API legacy tentacle):
  - `tentacles/vision.py`: ajout `reopen_cooldown_seconds`, `reopen_fail_threshold`, backoff progressif fallback (`fallback_min/max_sleep_seconds`)
  - effet observe: cadence des warnings camera reduite (boucle rapide eliminee, retries espaces)
- Hygiene unité vision:
  - `services/didier-vision.service`: variable `DIDIER_VISION_ROOM_HINT` correctement quotee (suppression des warnings systemd "Invalid environment assignment")
- Profil NPU vision "forme/flux stabilise":
  - `services/didier-vision.service`: `DIDIER_VISION_FPS=30`, `HAILO_MONITOR=1`, pipeline Hailo 30 FPS avec fallback `videotestsrc` stable
  - `scripts/run_vision.py`: auto-relance TAPPAS si sortie (`DIDIER_VISION_TAPPAS_RESTART_INTERVAL_S`, default 6s)
  - `core/routers/vision.py`: `/video/stream` garde le flux primaire PS3 par defaut (capture locale active) et n'utilise plus implicitement `stream-secondary` (anti-doublon Surface)
  - fallback primaire vers secondaire uniquement si `vision.primary_fallback_secondary=true`
  - `config/config.json`: `vision.api_local_capture_enabled=true` et `vision.primary_fallback_secondary=false`
  - correction caps GStreamer: format `YUY2` (au lieu de `YUYV`) pour la negotiation reelle avec `v4l2src`
  - verification lock camera: pendant `/video/stream`, seul `gst-launch` (worker vision) tient `/dev/video0`
  - script de bench dedie: `scripts/bench_vision_tpu.sh`
  - resultat bench valide: mode `hailo_mode`, backend `tappas_native`, ~30 FPS stables (jitter ~0.04), utilisation Hailo observee ~48%
- UI Workers Edge (coherence workers/liaisons):
  - deduplication des workers entre `/docker/diagram` et `/metrics` via normalisation canonique (`didier-*`)
  - suppression de l'ajout des workers metrics inconnus (plus de gonflement artificiel du compte)
  - enrichissement des liaisons sync/async exposees (`core/routers/system.py`: worker<->worker + worker<->infra: camera, NPU, audio, TTS, LLM)
  - garantie d'au moins une liaison API->worker cote rendu (`web/app.js`) pour eviter les noeuds orphelins

### Etape 5 (en place)

- Bridge OpenClaw natif:
  - nouvel endpoint `GET /tasks` dans `scripts/run_openclaw_bridge.py`
  - suivi des taches ReAct ajoute dans `orchestrator/openclaw_bridge.py`:
    - creation a l'entree de `relay_prompt`
    - finalisation en `done|error` avec `duration_s`, `result`, `error`
    - snapshot stable via `bridge.tasks()`
- API Didier 5010:
  - nouvel endpoint `GET /agent/tasks` dans `core/routers/ai.py`
  - proxy socket prioritaire vers OpenClaw (`orchestrator/openclaw_bridge_native.py::fetch_tasks`)
  - fallback degrade lisant `core/shared_state.py` si bridge indisponible (endpoint reste present)
- SharedState central:
  - bloc `openclaw.tasks` ajoute dans `core/shared_state.py`
  - fonction `update_openclaw_tasks(...)` pour publier les taches normalisees (items limites et tries)

### Etape 6 (validation experience complete)

- Script unique de recette ajoute: `scripts/check_didier_alive.sh`
  - scenarios simules:
    - task vocalisee -> route OpenClaw (`/ask-and-speak`, `force_task=true`)
    - vision glance -> presence `vision` dans la reponse
    - chat task -> creation visible dans `/agent/tasks`
  - verifications:
    - `/agent/tasks`
    - `/agent/metrics`
    - load average instantanee
- Robustesse API:
  - `GET /agent/metrics` en mode degrade (200 + payload + `degraded=true`) si OpenClaw runtime indisponible
  - evite le blocage UI quand OpenClaw est temporairement non pret
- Resultat dernier run:
  - `PASS=8 FAIL=1`
  - KO restant: critere strict `load1 < 0.30` (mesure observee > 8)
  - chaine fonctionnelle cote API/UI, OpenClaw actuellement en mode degrade (runtime non pret)
