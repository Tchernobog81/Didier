# Routes Map

Date: 2026-02-28
Scope: current FastAPI surface in `core/routers/`
Status: inventory for rationalization; not yet contract-locked

## Purpose
This document maps Didier's route surface by domain, dependency type, and regression risk.

The goal is to identify which route families should remain thin and which currently contain too much orchestration logic.

## Domain Inventory
### AI Routes
File: [`core/routers/ai.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/ai.py)

Main endpoints:

- `/speak`
- `/music/play`
- `/audio/test`
- `/ask`
- `/ask-and-speak`
- `/coding`
- `/ollama/models`
- `/asr/status`
- `/asr/wake-test`
- `/agent/react`
- `/agent/route`
- `/agent/metrics`
- `/agent/tasks`
- `/agent/memory`

Primary dependencies:

- config (`ollama`, `tts`, `routing`, `picobot`, `asr`, `bluetooth`)
- shared state
- IPC (`audio`, `brain`, `vision`, `picobot`)
- backend routing logic
- HTTP calls to Ollama and remote model endpoints

Risk classification: `critical`

Reason:
- largest concentration of orchestration logic
- most defaults
- most fallback branches
- direct impact on user-perceived latency and regressions

### Vision Routes
File: [`core/routers/vision.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/vision.py)

Main endpoints:

- `/vision/capture`
- `/vision/describe`
- `/vision/enroll`
- `/vision/owner`
- `/vision/status`
- `/vision/status-secondary`
- `/vision/tags`
- `/vision/zones`
- `/vision/detect`
- `/vision/detections`
- `/vision/detections-secondary`
- `/video/stream`
- `/video/stream-secondary`

Primary dependencies:

- config (`vision.*`)
- runtime bridge / OpenCV / ffmpeg
- arbitrator state
- remote secondary stream

Risk classification: `high`

Reason:
- stream routing and fallback policy are sensitive
- mixed concerns: streaming, detection, status, UI support

### System Routes
File: [`core/routers/system.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/system.py)

Main endpoints:

- `/health`
- `/version`
- `/metrics`
- `/system/arbitration`
- `/system/integrations`
- `/hardware/llmfit`
- `/hardware/models/current`
- `/hardware/models/select`
- `/ws/metrics`
- `/device-status`
- `/peripherals`
- `/peripherals/toggle`
- `/docker/diagram`
- `/files/search`
- `/terminal/exec`
- `/camera/holders`
- `/camera/reconnect`
- `/camera/force-format`

Primary dependencies:

- config (`vision`, `bluetooth`, `npu`, `ollama`, `picobot`)
- shared state
- subprocess/system inspection
- websocket metrics streaming

Risk classification: `high`

Reason:
- broad operational scope
- easy to accumulate ad hoc diagnostics
- prone to endpoint creep

### Actuators Routes
File: [`core/routers/actuators.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/actuators.py)

Main endpoints:

- `GET /`
- `GET /{id}/status`
- `POST /{id}/command`

Primary dependencies:

- actuator tentacle only

Risk classification: `medium`

Reason:
- narrower scope
- relatively low branching

## Structural Findings
### Route Logic Density
- AI routes currently blend:
  - request validation
  - backend selection
  - LLM prompting
  - response shaping
  - TTS delivery
  - metrics
  - fallback policy

- Vision routes currently blend:
  - stream selection
  - camera availability
  - fallback policy
  - detection cadence
  - UI-oriented convenience payloads

This is the main reason routes regress when unrelated behavior changes.

### Recommended Future Split
Each route family should move toward:

- `routers`: HTTP and contract only
- `services`: orchestration and use cases
- `adapters`: IPC, filesystem, subprocess, model endpoints
- `domain`: pure rules (routing, compaction, policy)

## Extraction Priority
### Priority 1
- `core/routers/ai.py`

Target:
- `core/services/chat_service.py`
- `core/services/audio_delivery_service.py`
- `core/services/agent_bridge_service.py`
- `core/domain/response_policy.py`

### Priority 2
- `core/routers/vision.py`

Target:
- `core/services/vision_stream_service.py`
- `core/services/vision_detection_service.py`
- `core/domain/vision_policy.py`

### Priority 3
- `core/routers/system.py`

Target:
- `core/services/system_status_service.py`
- `core/services/device_diagnostics_service.py`

## Contract Stabilization Candidates
The following routes should receive stable response contracts before deeper refactors:

- `/ask-and-speak`
- `/vision/status`
- `/vision/status-secondary`
- `/video/stream`
- `/device-status`
- `/metrics`

These are the highest-value anti-regression anchors.
