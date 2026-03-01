# Technical Invariants

Date: 2026-02-28
Status: initial baseline

## Source Ownership
- `config/config.json` is the only instance configuration file.
- `data/shared_state.json` is the only shared runtime state file.
- `memory/technical/` and `memory/operations/` are the only canonical non-conversational memory roots.

## Configuration
- New route logic must not introduce hidden defaults when a domain config already exists.
- Defaults belong in typed config schema modules, not in hot-path route handlers.
- AI-domain config access and text compaction helpers should live in pure modules (`core/ai_config.py`), not inside FastAPI routes.
- AI backend timeout/fallback/base-url policy should live in pure modules (`core/ai_backend_policy.py`), not inside FastAPI routes.
- Ask-and-speak orchestration should live in a dedicated service (`core/ai_ask_and_speak_service.py`), not inside FastAPI routes.
- Service modules should keep local fast paths split into focused helper functions; moving code out of a route must not simply recreate a second monolith.
- AI conversation orchestration should live in a dedicated service (`core/ai_conversation_service.py`), not inside FastAPI routes.
- AI input orchestration should live in a dedicated service (`core/ai_process_service.py`), not inside FastAPI routes.
- AI coding generation should live in a dedicated service (`core/ai_coding_service.py`) and use typed config, not direct `config.get(...)` calls inside FastAPI routes.
- When `npu.required_for_vision=true`, vision inference must fail closed if Hailo is inactive; silent CPU fallback is not acceptable for “real NPU” mode.
- Vision describe capture selection and Ollama request shaping should live in a dedicated service (`core/vision_describe_service.py`), not in the route module.
- Primary vision detection cache and fallback payload policy should live in a dedicated service (`core/vision_primary_service.py`), not in the route module.
- Secondary vision detection cache, hold-last, and empty-payload policy should live in a dedicated service (`core/vision_secondary_service.py`), not in the route module.
- Secondary vision detection arbitration, stream-read, decode, timeout, and refresh orchestration should live in a dedicated service (`core/vision_secondary_detection_service.py`), not in the route module.
- Primary/secondary video stream selection, stale detection, and camera-plan policy should live in a dedicated service (`core/vision_stream_service.py`), not in the route module.
- Passive remote stream health evaluation should live in a dedicated service (`core/vision_remote_status_service.py`), not inline in the route module.
- Vision tentacle lookup, capability validation, and NPU guard-to-error mapping should live in a shared support module (`core/vision_route_support.py`), not be duplicated across endpoints.
- Hardware model selection validation, config mutation, and current-model payload shaping should live in a dedicated service (`core/system_model_selection_service.py`), not inline in `core/routers/system.py`.
- Integration probes, rollup policy, and cached `/system/integrations` snapshot orchestration should live in a dedicated service (`core/system_integrations_service.py`), not inline in `core/routers/system.py`.
- Device-status cache and hardware aggregation should live in a dedicated service (`core/system_device_status_service.py`), not inline in `core/routers/system.py`.
- LLMFit report sampling, scoring rollup, and cache orchestration should live in a dedicated service (`core/system_llmfit_service.py`), not inline in `core/routers/system.py`.
- Camera utility config extraction and control payload shaping should live in a dedicated service (`core/system_camera_service.py`), not inline in `core/routers/system.py`.
- `systemctl` invocation and service-state normalization should live in a shared control module (`core/system_service_control.py`), not inline in `core/routers/system.py`.
- `core/routers/system.py` should keep only thin HTTP wrappers plus dependency builders; repeated lambda wiring should be factored into shared local builders.
- Peripheral inventory shaping and toggle orchestration should live in a dedicated service (`core/system_peripherals_service.py`), not inline in `core/routers/system.py`.
- Workers Edge health probing and `/docker/diagram` worker payload shaping should live in a dedicated service (`core/system_workers_service.py`), not inline in `core/routers/system.py`.
- Terminal command validation, timeout handling, and output truncation should live in a dedicated service (`core/system_terminal_service.py`), not inline in `core/routers/system.py`.
- The final written-question/thinking/written-response/audio validation should be exercised with `scripts/validate_chat_e2e.py` and tracked as an operational runbook.
- The `Workers Edge` UI should present summary, workers, and critical flows as separate readable surfaces; the graph is infrastructure context, not the only view.
- External Picobot HTTP calls should live in a dedicated adapter (`core/picobot_client.py`), not inside FastAPI routes.
- Brain worker IPC calls should live in a dedicated adapter (`core/brain_client.py`), not inside FastAPI routes.
- ASR worker health must not report a degraded status with a `ready` detail; health payloads must explicitly expose loop state (`capture_up`, `process_up`) and restart dead runtime tasks before publishing shared metrics.
- `core/api_impl.py` should prefer `models/hailo/yolo26n.hef` when present and decode NMS-free YOLO26 outputs directly from raw tensors (structured arrays or flat rows) without adding an OpenCV NMS pass in that overlay path.
- The active vision runtime in `tentacles/vision.py` should auto-prefer `models/hailo/yolo26n.hef` when it exists, but retain the current working HEF when the YOLO26 artifact is absent; support for a new model must not silently disable NPU vision.
- Audio queueing is an IPC enqueue path, not synthesis; `/ask-and-speak` must not use sub-second queue timeouts so aggressive that the UDS audio worker is marked unavailable while it is healthy.
- The canonical local API/UI runtime for Didier is `http://127.0.0.1:5010`; legacy `5003` assumptions should not be used for end-to-end validation.

## Runtime State
- Shared state is a runtime projection, not a substitute for static config.
- Shared state must remain writable by services and readable by diagnostics without becoming a second config system.

## Documentation
- Architecture, operations, and decisions must remain separated.
- Legacy documents may remain for context, but must not define active behavior.

## Change Discipline
- A structural change should update either technical memory, operational memory, or both.
- A regression without an operational trace is considered incomplete remediation.

## Planned Follow-Up
- After the current optimization pass, a dedicated refresh of the `Workers Edge` tab should be planned so the UI reflects the new worker/adapters structure cleanly.
- The final validation pass must include an end-to-end scenario: written question, visible thinking phase, written response, and audio response.
