# Fondation Didier (Référence Vivante)

Dernière mise à jour: 2026-02-18  
Mode de suivi: mise à jour incrémentale "au fil de l'eau"

## Statut global

- Architecture cible: workers edge unifiés, point d'entrée unique.
- Etape en cours du plan: **Etape 5** (implémentée, en attente de validation utilisateur).

## Journal de validation

### Etape 1 - Unification du point d'entrée (VALIDEE)

Objectif validé:
- sortie du dual-run legacy/worker côté entrée HTTP;
- point d'entrée unique opérationnel visé: `didier-api.service` sur `5010`.

Changements appliqués:
- `services/didier-api.service`
  - `ExecStart` aligné sur `uvicorn core.api:app --host 0.0.0.0 --port 5010`
  - conflit explicite avec services legacy (`run_didier.service`, `didier.service`)
- `run_didier.service`
  - archivé en service inactif (`RefuseManualStart=yes`, `ExecStart=/bin/false`)
- `services/didier.service`
  - archivé en service inactif (`RefuseManualStart=yes`, `ExecStart=/bin/false`)
- `scripts/install_systemd.sh`
  - installation/disable cohérents pour ne plus activer legacy en prod
- `nginx/nginx.conf`
  - proxy principal aligné vers `127.0.0.1:5010`
- `scripts/check_edge.sh`
  - checks orientés `5010` et vérification que `5003` n'est plus le point d'entrée
- `docs/ROLLBACK.md`
  - rollback documenté avec scénario de retour legacy si incident
- `README.md`
  - documentation d'entrée mise à jour
- `scripts/bench_actuators.py`
  - base URL par défaut alignée sur `5010`

Autotests exécutés:
- `bash -n scripts/check_edge.sh`
- `bash -n scripts/install_systemd.sh`
- `python3 -m py_compile scripts/bench_actuators.py`

Résultat:
- validation technique de l'Etape 1 acquise.

## Notes de continuité

- L'ancien fichier `fondation_dider.md` (typo) est conservé comme archive de contexte.
- Le suivi courant est désormais centralisé dans `fondation_didier.md`.

## Prochaine étape

- **Etape 3** après validation Etape 2.

## Etape 2 - IPC Unix sockets (IMPLÉMENTÉE / À VALIDER)

Objectif:
- remplacer les appels inter-workers HTTP `127.0.0.1:501x` par Unix sockets avec fallback contrôlé.

Changements appliqués:
- `shared/ipc.py` (nouveau)
  - helper async IPC: Unix socket prioritaire, fallback HTTP local
  - API: `request(...)`, `health(...)`, résolution des sockets workers
- `shared/__init__.py` (nouveau)
- `scripts/run_api.py`
  - appels vers workers vision/brain/audio migrés via `shared.ipc`
- `scripts/run_brain.py`
  - sondes workers migrées via `shared.ipc`
  - service brain configuré pour écouter en Unix socket (avec cleanup socket stale)
- `core/routers/system.py`
  - `/docker/diagram` probe health workers via IPC Unix socket + fallback
  - suppression du `urlopen` synchrone pour un appel async homogène
- `scripts/run_vision.py`
  - écoute worker vision via Unix socket (avec cleanup socket stale)
- `scripts/run_audio.py`
  - écoute worker audio via Unix socket (avec cleanup socket stale)
- `services/didier-vision.service`
  - `DIDIER_VISION_SOCK` + `ExecStartPre` cleanup socket
- `services/didier-brain.service`
  - `DIDIER_BRAIN_SOCK` + `ExecStartPre` cleanup socket
- `services/didier-audio.service`
  - `DIDIER_AUDIO_SOCK` + `ExecStartPre` cleanup socket
- `services/didier-api.service`
  - env IPC sockets workers pour la résolution côté API
- `scripts/check_edge.sh`
  - checks workers basculés sur sockets (`curl --unix-socket`) avec maintien du check d'entrée `5010`

Autotests exécutés:
- `python3 -m py_compile shared/ipc.py scripts/run_api.py scripts/run_brain.py scripts/run_vision.py scripts/run_audio.py core/routers/system.py`
- `bash -n scripts/check_edge.sh`
- `bash -n scripts/install_systemd.sh`
- `scripts/install_systemd.sh` (reload + restart services)
- `scripts/check_edge.sh` => `result=PASS`, `failures=0`
- `ss -ltnp | grep -E ':(5010|5011|5012|5013)\b'`
  - écoute confirmée: `5010` uniquement (5011/5012/5013 fermés, IPC via `.sock`)

## Etape 3 - ASR asynchrone worker (IMPLÉMENTÉE / À VALIDER)

Objectif:
- sortir la capture/transcription wake du process API;
- supprimer l'usage bloquant `subprocess.run(arecord)` côté orchestration;
- garder la chaîne wake -> réponse -> commande.

Changements appliqués:
- `scripts/run_asr.py` (nouveau)
  - worker ASR dédié sur `127.0.0.1:5014`
  - capture micro via `asyncio.create_subprocess_exec` (`arecord`)
  - transcription whisper.cpp via subprocess async
  - queue `asyncio.Queue` pour pipeline capture -> transcription
  - publication `data/asr_status.json` via `core.status.update_status`
  - endpoint worker `/wake-test` pour test non bloquant
- `services/didier-asr.service` (nouveau)
  - service systemd hardené pour worker ASR
- `core/orchestrator.py`
  - skip automatique du tentacule `hearing` en mode worker ASR (`DIDIER_ASR_WORKER_MODE=1`)
- `core/routers/ai.py`
  - `/asr/wake-test` proxifié vers worker ASR si mode worker activé
- `core/routers/system.py`
  - ajout worker `didier-asr` dans `/docker/diagram`
- `services/didier-api.service`
  - activation mode worker ASR + URL worker (`DIDIER_ASR_WORKER_MODE`, `DIDIER_ASR_WORKER_URL`)
- `scripts/install_systemd.sh`
  - gestion idempotente du nouveau service `didier-asr`
- `scripts/check_edge.sh`
  - contrôle port/health `5014` + process `run_asr.py`

Autotests exécutés:
- `python3 -m py_compile scripts/run_asr.py core/orchestrator.py core/routers/ai.py core/routers/system.py shared/ipc.py`
- `bash -n scripts/install_systemd.sh`
- `bash -n scripts/check_edge.sh`
- `scripts/install_systemd.sh`
- `curl -sS -X POST http://127.0.0.1:5010/asr/wake-test` (timeout test, proxy worker ok)
- `scripts/check_edge.sh` => `result=PASS`, `failures=0`
- `journalctl -u didier-api.service ...`:
  - confirmation `Skipping tentacle hearing (ASR worker mode enabled).`
- `ps -eo pid,cmd | grep arecord`:
  - `arecord` porté par `scripts/run_asr.py` (plus par le process API)

## Etape 4 - Dé-Dockerisation (IMPLÉMENTÉE / À VALIDER)

Objectif:
- basculer explicitement en déploiement natif systemd;
- conserver compose uniquement pour usage dev;
- retirer la dépendance Docker runtime dans le code/UI actif.

Changements appliqués:
- renommage fichier compose:
  - `docker-compose.yml` -> `docker-compose.dev.yml`
- `README.md`
  - wording déploiement production en systemd natif
  - ajout note compose dev
- `core/api.py`
  - suppression dépendance runtime Docker (`_read_docker_containers()` retourne désormais `[]`)
- `core/api_impl.py`
  - alignement compatibilité (même suppression dépendance Docker runtime)
- `web/app.js`
  - suppression libellés Docker en UI (`Runtime Dev` / `services dev`)
- `scripts/tag_and_shutdown.sh`
  - arrêt services systemd à la place de `docker compose down`
- `scripts/check_edge.sh`
  - label benchmark `/docker/diagram` renommé en `workers-diagram` (endpoint conservé)
- `docs/ROLLBACK.md`
  - baseline 100% native + inclusion `didier-asr.service`
- `.github/copilot-instructions.md`
  - références compose ajustées vers `docker-compose.dev.yml`
- `PLAN_UNIFICATION.md`
  - référence compose mise à jour vers `docker-compose.dev.yml`

## Etape 5 - SharedState centralisé (IMPLÉMENTÉE / À VALIDER)

Objectif:
- centraliser les métriques runtime dans un état partagé;
- publication workers à 2 Hz;
- `/metrics` lit uniquement cet état partagé (sans IPC HTTP interne).

Changements appliqués:
- `core/shared_state.py` (nouveau)
  - store JSON locké (`data/shared_state.json`) avec:
    - `metrics`
    - `workers`
    - `updated_at`
  - API: `update_metrics`, `update_worker_metrics`, `metrics_snapshot`
- `core/api.py`
  - nouvelle boucle `_shared_state_loop` à 2 Hz
  - calcule CPU/RAM/disque/NPU + ASR status + OpenClaw snapshot
  - écrit dans `shared_state` et publie worker `api`
- `core/routers/system.py`
  - `/metrics` lit uniquement `metrics_snapshot()` (plus de calcul direct)
- `scripts/run_vision.py`
  - publication worker `vision` à 2 Hz vers shared state
- `scripts/run_brain.py`
  - publication worker `brain` à 2 Hz vers shared state
- `scripts/run_audio.py`
  - publication worker `audio` à 2 Hz vers shared state
- `scripts/run_asr.py`
  - publication worker `asr` à 2 Hz vers shared state
- `web/app.js`
  - panneau Workers Edge: fallback workers depuis `/metrics` (state unique)

Autotests exécutés:
- `python3 -m py_compile core/shared_state.py core/api.py core/routers/system.py scripts/run_vision.py scripts/run_brain.py scripts/run_audio.py scripts/run_asr.py`
- `node --check web/app.js`
- `bash -n scripts/check_edge.sh`
- `bash -n scripts/install_systemd.sh`
- `systemctl is-active didier-api.service didier-vision.service didier-brain.service didier-audio.service didier-asr.service` -> tous `active`
- `curl -sS http://127.0.0.1:5010/metrics` -> payload `source=shared_state_v1` + `workers`
- validation fichier `data/shared_state.json`:
  - `workers=['api','asr','audio','brain','vision']`
- `scripts/check_edge.sh` -> `result=PASS`, `failures=0`

## Correctif immédiat CPU / Thermique (2026-02-18)

Objectif:
- réduire les pointes CPU prolongées en veille;
- limiter la chauffe >70C sans casser la chaîne wake/command.

Changements appliqués:
- `services/didier-asr.service`
  - wake model allégé: `DIDIER_ASR_WAKE_MODEL_PATH=.../ggml-tiny.bin`
  - threads limités: `DIDIER_ASR_THREADS=2`, `DIDIER_ASR_WAKE_THREADS=1`
  - wake capture plus léger: `DIDIER_ASR_CHUNK_SECONDS=2`
  - stride idle anti-chauffe: `DIDIER_ASR_WAKE_EVERY_N_CHUNKS=2`
  - garde-fous systemd: `CPUQuota=150%`, `Nice=5`, `IOSchedulingClass/priority`
- `scripts/run_asr.py`
  - séparation threads wake/command
  - stride en mode wake (`1 chunk transcrit sur N`) pour casser les transcriptions continues en bruit ambiant
  - métriques exposées: `idle_chunk_count`
- `scripts/check_edge.sh`
  - résumé enrichi avec `runtime_load_*` et `runtime_temp_c`

## Correctif immédiat Soundboks erratique (2026-02-18)

Objectif:
- éliminer les bascules "associé mais non connecté";
- maintenir la sortie audio Bluetooth SB en sink par défaut.

Changements appliqués:
- `scripts/soundboks_watchdog.sh` (nouveau)
  - watchdog léger (intervalle 8s) avec auto-heal:
    - vérifie `bluetoothctl info` (`Connected: yes`)
    - force profil `a2dp-sink`
    - restaure `bluez_output.*` en default sink
    - déplace les flux actifs vers la SB
    - fallback sur `connect_soundboks.sh` si reconnexion directe échoue
- `services/didier-soundboks.service` (nouveau)
  - service systemd natif, restart automatique
  - dépendances `bluetooth.service` + `didier-audio.service`
- `scripts/install_systemd.sh`
  - installation/idempotence étendues au nouveau service

Validation exécutée:
- déconnexion forcée: `bluetoothctl disconnect 00:07:80:E0:3F:F0`
- reconnexion auto validée en journal:
  - `soundboks-watchdog: heal start ...`
  - `soundboks-watchdog: heal ok (sink=bluez_output.00_07_80_E0_3F_F0.1)`
- checks runtime:
  - `bluetoothctl info ...` => `Connected: yes`
  - `pactl info` => `Default Sink: bluez_output.00_07_80_E0_3F_F0.1`
  - `POST /audio/test` => `status=played`
  - `scripts/check_edge.sh` => `result=PASS`
