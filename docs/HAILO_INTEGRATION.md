# Hailo Integration Plan (Safe and Progressive)

## Scope

This tranche prepares architecture only.

Current guarantees:
- No endpoint change
- No frontend change
- No mandatory dependency for CPU-only deployments
- Existing vision flow remains the default behavior

## Target Architecture

Dual mode design:
- `cpu_mode`: current behavior (default when Hailo is not detected)
- `hailo_mode`: future TAPPAS + Hailo runtime path

Standard interface:

```python
class VisionBackend:
    def detect(self, frame) -> list[dict]: ...
    def status(self) -> dict: ...
```

Future backends:
- `CpuVisionBackend` (adapter around existing CPU inference path)
- `HailoVisionBackend` (will call TAPPAS pipeline)

## Recommended Pipeline

1. Camera frame acquisition
2. YOLOv10n INT8 inference on Hailo-8L (via TAPPAS)
3. Object tracking and ID persistence
4. Optional semantic enrichment:
   - Moondream (fast scene level interpretation)
   - Qwen2.5-VL (complex fallback for hard visual cases)
5. Unified output format for existing API consumers

## Integration Order (Progressive)

1. YOLO INT8 via TAPPAS
2. Tracking objects
3. Moondream integration
4. Qwen2.5-VL integration

## Hailo Detection Strategy

`core.hailo.monitor.detect_hailo()` is safe and non-blocking.

It checks:
- known device paths (`/dev/hailo*`, `/sys/class/hailo*`, ...)
- shared libraries (`hailort`, ...)
- optional python modules (`hailo_platform`, ...)

Optional override for tests:
- `DIDIER_FORCE_HAILO=1` forces `True`
- `DIDIER_FORCE_HAILO=0` forces `False`

## Ollama Integration Guidance

For constrained RAM systems, prefer short-lived generation jobs:
- Use `keep_alive: 0`
- Keep prompts short when possible
- Avoid concurrent large multimodal requests

Example request:

```bash
curl -sS http://127.0.0.1:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "moondream",
    "prompt": "Describe this frame in one sentence.",
    "stream": false,
    "keep_alive": 0
  }'
```

Example with structured options:

```bash
curl -sS http://127.0.0.1:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-vl",
    "prompt": "List only safety-relevant objects.",
    "stream": false,
    "keep_alive": 0,
    "options": {
      "temperature": 0.1,
      "num_predict": 96
    }
  }'
```

## RAM Safety Checklist

- Reserve memory budget for:
  - API + orchestrator
  - camera buffers
  - Ollama model runtime
  - Hailo side pipeline buffers
- Gate heavyweight VLM fallback when available RAM is too low
- Keep async queues bounded

Use:

```bash
python3 scripts/hailo_ram_check.py --min-mib 1024
```

## Stub Throughput Simulation

Use:

```bash
python3 scripts/hailo_stub_100fps.py --seconds 5 --fps 100
```

This validates control-loop scheduling overhead in stub mode only.

## Quick Detection Command

```bash
python3 -c "from core.hailo.monitor import detect_hailo; print('Hailo present:', detect_hailo())"
```

## Next Implementation Steps

1. Wire `build_backend(...)` in the vision tentacle behind a feature flag.
2. Add real TAPPAS runner in `core/hailo/tappas_pipeline.py`.
3. Map output schema to existing `/vision/*` consumers.
4. Add load-shedding policy for multimodal fallback (Moondream then Qwen2.5-VL).
5. Add regression tests proving API parity between `cpu_mode` and `hailo_mode` stubs.

## Production Baseline

For frozen runtime HEF/TAPPAS validation, use:

- `docs/VISION_PROD_BASELINE.md`
- `bash scripts/bench_vision_prod.sh`
