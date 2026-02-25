# Fondation Didier (Version Exportable)

Date de reference: 2026-02-25
Statut global: ARCHIVE HISTORIQUE (document OpenClaw legacy, non actif)
- Release UI historique: `V3r2`
- Document runtime actif a utiliser: `fondation_didier.md`
- Note: depuis le 2026-02-25, OpenClaw est purge (code + services + configs + dossier `openclaw/`).

## 1) Architecture active

- Point d'entree unique API: `didier-api.service` sur `0.0.0.0:5010`
- Workers edge:
  - `didier-vision.service` (socket Unix `/tmp/didier_vision.sock`)
  - `didier-brain.service` (socket Unix `/tmp/didier_brain.sock`)
  - `didier-audio.service` (socket Unix `/tmp/didier_audio.sock`)
  - `didier-asr.service` (service ASR dedie, health HTTP `127.0.0.1:5014`)
- OpenClaw natif:
  - `openclaw.service` (Node gateway local)
  - `didier-openclaw-bridge.service` (socket Unix `/tmp/didier_openclaw.sock`)
- IPC interne: priorite Unix sockets via `shared/ipc.py`, fallback HTTP local si necessaire
- Deploiement production: 100% systemd natif
- Docker: uniquement dev (`docker-compose.dev.yml`)

## 2) Etat des migrations OpenClaw (plan 6 etapes)

- Etape 1: Preparation + installation native + Ollama local -> VALIDEE
- Etape 2: Service systemd natif OpenClaw -> VALIDEE
- Etape 3: Bridge IPC natif OpenClaw <-> Didier -> VALIDEE
- Etape 4: Synchronisation memoire OpenClaw vers SharedState -> VALIDEE
- Etape 5: Heartbeat/co-orchestration 2 Hz natif -> VALIDEE
- Etape 6: Tests finaux + rollback wrapper documente -> VALIDEE

## 3) Contrats runtime en place

### OpenClaw metrics

- Endpoint API: `GET /agent/metrics` (via `:5010`)
- Retour natif actuel:
  - `ok=true`
  - `native=true`
  - `source=openclaw_native_bridge`
  - `shared_state.runtime.scheduler_hz=2.0`
  - `shared_state.runtime.wrapper_heartbeat_enabled=false`
  - `shared_state.runtime.didier_state_sync_enabled=true`
  - `shared_state.didier_state` rempli (cpu/memory/npu/asr/workers)

### Memoire OpenClaw partagee

- Sources suivies:
  - `data/openclaw_memory/SOUL.md`
  - `data/openclaw_memory/MEMORY.md`
  - `openclaw/AGENTS.md`
- Endpoints:
  - `GET /agent/memory`
  - `POST /agent/memory`

## 4) Services systemd critiques

- `didier-api.service`
- `didier-vision.service`
- `didier-brain.service`
- `didier-audio.service`
- `didier-asr.service`
- `openclaw.service`
- `didier-openclaw-bridge.service`
- `didier-soundboks.service`

## 5) Resultats de recette (dernieres validations)

### OK

- API unifiee accessible sur `5010`
- SharedState centralise actif (`source=shared_state_v1`)
- OpenClaw natif visible dans `/agent/metrics`
- Synchronisation `didier_state` vers OpenClaw bridge active
- Memoire OpenClaw lisible/ecrivable via API
- Plus d'erreur de schema OpenClaw (`Unrecognized key`) depuis correction

### Points encore ouverts

- `POST /agent/react` retourne encore `405 Method Not Allowed` sur `http://127.0.0.1:3800/hooks/agent`
- Wake test ASR valide le flux audio mais ne matche pas toujours le wake word sur echantillon court
- Critere load idle strict `<0.3` non atteint sur la derniere mesure (load > 1)

## 6) Rollback officiel

- Procedure complete: `docs/ROLLBACK.md`
- Section specifique OpenClaw:
  - `Rollback OpenClaw natif -> wrapper (sans couper l'API 5010)`
- Principe wrapper:
  - `openclaw.service` OFF
  - `didier-openclaw-bridge.service` en `DIDIER_OPENCLAW_NATIVE_ONLY=0`
  - API `5010` conservee

## 7) Commandes de verification rapide

```bash
systemctl is-active didier-api.service didier-vision.service didier-brain.service didier-audio.service didier-asr.service openclaw.service didier-openclaw-bridge.service
curl -sS http://127.0.0.1:5010/health
curl -sS http://127.0.0.1:5010/metrics
curl -sS "http://127.0.0.1:5010/agent/metrics?timeout_s=2"
curl -sS http://127.0.0.1:5010/agent/memory
```

## 8) Fichiers de reference

- `fondation_didier.md` (ce document)
- `README.md`
- `docs/ROLLBACK.md`
- `config/config.json`
- `config/openclaw.runtime.json`
- `services/openclaw.service`
- `services/didier-openclaw-bridge.service`
- `orchestrator/openclaw_bridge.py`
- `core/shared_state.py`

## 9) Avancement "Didier vivant" (2026-02-19)

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
