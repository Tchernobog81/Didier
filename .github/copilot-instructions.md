# Copilot Instructions for Didier 👇

## Purpose
Short, actionable guidance for AI agents to be immediately productive in this repo. Focus on where to change behavior, how things run, and gotchas (hardware, licensing, security).

## Big-picture architecture 🔧
- Core orchestrator: `orchestrator/` (see `core.py`) initializes three main pieces:
  - `Memory` (SQLite, `orchestrator/memory.py`) — stores conversations.
  - `ModelManager` (`orchestrator/model_manager.py`) — HF metadata + placeholder for model downloads.
  - `DidierAgent` (`orchestrator/agent.py`) — persona + `chat()` entrypoint (currently placeholder logic).
- Two runtime entrypoints:
  - API: `main.py` (FastAPI) exposes `/health`, `POST /chat` and `GET /models/search`.
  - Hardware UI / quick ops: `didier_orchestrator.py` (Flask) — small web UI, monitors hardware and calls Ollama.
- Local model hosting: `ollama` container (see `docker-compose.yml` and `ollama/` directory that contains model manifests/blobs).

## How to run / developer workflows ▶️
- Local dev (Python): create venv, install `requirements.txt` and run:
  - `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- Docker (recommended for full stack): `docker compose up -d` (uses `docker-compose.yml` to start `ollama` + `didier-brain`).
- The docker `didier-brain` container runs `didier_orchestrator.py` (Flask UI on port 5000) and maps devices (`/dev/hailo0`, camera, sound).
- System service: `run_didier.service` included — update `User` and paths before enabling.
- Useful checks: `scripts/init_repo.sh` initializes repo; `check_didier.sh` contains health tips (e.g., query Ollama tags on `http://localhost:11434/api/tags`).

## Key files & places to edit (concrete examples) ✏️
- Add model inference:
  - Replace placeholder in `orchestrator/agent.py::DidierAgent.chat()` with a call into ModelManager or an inference client (Ollama/Hugging Face/local engine).
  - Example: `didier_orchestrator.py` uses Ollama API: POST `http://ollama:11434/api/generate` — mimic or centralize this logic in `ModelManager`.
- Model management:
  - `orchestrator/model_manager.py::search_hf()` uses `huggingface_hub.HfApi()` (metadata only).
  - `download_model()` is intentionally NOT IMPLEMENTED — implement for target runtime (onnx/tflite) and be mindful of device constraints (Pi).
- Persistence & memory:
  - `orchestrator/memory.py` manages SQLite schema (`conversations` table). Use `get_recent()` and `save_message()` to build context for prompts.
  - Note: `didier_orchestrator.py` also uses a separate `memory.json` for UI audit — this is a repo-specific divergence to be aware of.
- Hardware and device mapping: `docker-compose.yml` mounts `/dev/hailo0` and other devices into `didier-brain`; code checks `/dev/hailo0` to detect NPU.

## Integration points & externals ⚙️
- Ollama: local model serving via `ollama/` + `ollama` container. The Flask UI calls Ollama at `ollama:11434` in Docker; in local dev use `localhost:11434`.
- Hugging Face: used for model discovery (`HfApi().list_models()`), public metadata only unless auth is configured.
- Watch license + model terms: `ollama/models/blobs/...` contains model license text (Llama 3.2) — pay attention to usage restrictions (e.g., EU limitation for multimodal Llama 3.2).

## Conventions & gotchas 🚨
- Two runtimes: FastAPI (API) and Flask (UI). Be intentional when you modify endpoints or unify behavior.
- Security: `didier_orchestrator.py` exposes a `/terminal` endpoint that executes shell commands (`subprocess.check_output`) — **do not** expose this UI publicly without auth or hardening.
- Missing/unclear scripts: README references `setup.sh` but it is not present; `scripts/init_repo.sh` exists instead. Validate README before relying on it.
- Requirements include `sqlalchemy`/`databases` but current code uses raw `sqlite3` — take care when refactoring.

## Testing / Observability
- There are no unit tests in the repo. Add focused tests for:
  - `Memory` (connect/save/get_recent)
  - `ModelManager.search_hf()` (mock HF responses)
  - `DidierAgent.chat()` after it is wired to a model backend
- Logs: use container logs for `didier-brain` and `ollama`; `check_didier.sh` shows helpful debugging commands.

## First tasks for an AI agent ✅
1. Wire `DidierAgent.chat()` to a real inference call (either `ModelManager` or call Ollama endpoint — see `didier_orchestrator.py`).
2. Implement `ModelManager.download_model()` for the chosen target format (document space and size constraints).
3. Add tests for memory and model search; add an integration test that hits `POST /chat` with a mocked model backend.

---
Please review these notes and tell me which areas you want expanded or where you'd like short example patches (e.g., a minimal `DidierAgent` that calls Ollama or an initial test for `Memory`).
