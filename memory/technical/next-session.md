# Next Session Handoff

Date: 2026-03-01
Status: yolo26 active, PS3 + Surface aligned on semantic Hailo detections, Surface cadence fix + live NPU activity + visible COCO hints validated, actuator bindings repaired and lamp color baseline calibrated

## Current Runtime State
- Canonical local API/UI runtime is `http://127.0.0.1:5010`.
- `didier-api` was restarted multiple times on `2026-03-01`; latest validated UI/runtime reload before this handoff served release `didier-v4r37-coco-hints-visible-2026-03-01`.
- Legacy LAN URL is restored and still valid: `http://192.168.1.47:5010` now answers again because `192.168.1.47/24` was re-added as a persistent secondary IP on `eth0`.
- Active vision runtime now resolves `/mnt/didier_ssd/didier/models/hailo/yolo26n.hef`.
- `/vision/status` now reports:
  - `model=yolo26n.hef`
  - `ready=true`
  - `npu_active=true`
  - `detector_debug.decode_path=yolo26_raw_head_pairs`
  - `preprocess.mode=letterbox`
  - `score_threshold=0.15`
  - non-empty raw Hailo detections again
- `/vision/detections` returns real Hailo-side object detections again (recent confirmed examples: `personne`, confidence between roughly `0.15` and `0.43` depending on scene).
- `/vision/detections-secondary` now returns real Hailo-side object detections again. Latest validated control aligned both streams on the same semantic class (`personne` on PS3 and `personne` on Surface).
- Primary and secondary detection payloads now also expose `semantic_hints` directly:
  - when a frame is below the confirmation threshold, the runtime still exposes the strongest COCO candidates (`personne`, `camion`, `parapluie`, `television`, etc.)
  - this gives an object-first diagnostic path even when `detections=[]`
- The recurring Surface "sauts" were traced to the HTTP MJPEG emitter, not the UDP source: the remote reader was already healthy at `15 fps`, but the HTTP generator still followed the resource arbitrator target FPS (`10 fps` in `TENDU`). That path now honors the configured remote stream FPS for emission cadence, stall timing, and restart backoff.
- `/vision/status-secondary` is now a reliable backend truth source for the Surface path. Latest validated check returned `diagnostic=healthy`, `fps=15`, `frame_gap_s~0.04`, `spawn_count=1`, `restart_count=0`.
- `/metrics` now publishes a usable live NPU signal even when the driver does not expose a trustworthy percentage:
  - `npu.active=true`
  - `npu.real_fps~15`
  - `npu.utilization` is estimated from inference cadence when needed
  - `cores[0].id=hailo0`
  - `runtime_status=active`
- The Xiaomi/Yeelight actuator path is no longer dependent on stale fixed IPs only:
  - `tentacles/actuators.py` now uses SSDP discovery plus a bounded nearby TCP scan to repair DHCP drift
  - missing hardware IDs no longer persist as the string `"None"`
  - heuristic rebinding is blocked when the discovered bulb inventory is incomplete, which prevents registry corruption during partial scans
  - logical IDs (`yl_192_168_1_xx`) are now used as seed IP anchors during reconciliation
- Current validated lamp bindings after the repair:
  - `yl_192_168_1_12` (Entrée) -> `192.168.1.13`
  - `yl_192_168_1_19` (Cuisine) -> `192.168.1.14`
  - `yl_192_168_1_18` (Chiottes) -> `192.168.1.18`
  - `yl_192_168_1_22` (Dancefloor) -> `192.168.1.20`
  - `yl_192_168_1_24` (Canapé) -> `192.168.1.21`
  - `yl_192_168_1_23` (Salle à manger) -> `192.168.1.23`
- Canonical actuator calibration baseline, captured on 2026-03-01 after manual lamp sync (`vert franc`):
  - `power_on=true`
  - `bright=80`
  - `color_mode=1`
  - `rgb=65283`
  - `hex=#00FF03`
  - `hue=121`
  - `sat=100`
  - persisted in `config/actuators.json` under `reference_metrics.lamp_sync_green_2026_03_01`

## Deployment Record
- External HEF source used for this deployment: `/home/tchernobog/yolo26n.hef`
- Deployed runtime copy: `/mnt/didier_ssd/didier/models/hailo/yolo26n.hef`
- `config/config.json` still points to `/mnt/didier_ssd/didier/models/hailo/hailo_model.hef`, but `tentacles/vision.py` now auto-prefers `yolo26n.hef` because that artifact exists.
- `hailo_model.hef` remains in place as the fallback artifact.

## YOLO26 Runtime Notes
- `tentacles/vision.py` no longer flattens each raw tensor as if it already contained final detections.
- The false detections seen earlier (tiny boxes and the thin orange “sinusoid” near the top-left) were a decoder artifact from treating the raw `4ch` and `80ch` heads as direct detection rows.
- The active decoder now pairs YOLO26 raw heads by stride (`boxes(4)` + `classes(80)`), decodes them as anchor-free grid heads, applies class-aware NMS, and exposes a compact `detector_debug` snapshot through `/vision/status`.
- The active pre-processing path now uses real letterboxing for YOLO26 (`640x480 -> 640x640` with padding), instead of stretching the frame vertically. This materially improved class confidence.
- `config/config.json` now explicitly sets `vision.npu_score_threshold=0.15` for this HEF. With the previous default (`0.35`), the model stayed below threshold even after the decoder fix.
- `models/vision/coco.names` is present and loaded by the vision tentacle; COCO labels are available at runtime, but only the current label policy/UI wording has been tuned so far (full COCO naming normalization/localization remains the next step).
- Startup logs confirm the model switch:
  - `Resolved Hailo model path: /mnt/didier_ssd/didier/models/hailo/yolo26n.hef`
  - `Hailo detector initialized (input=model/input_layer1, shape=(640, 640, 3))`
- Startup logs now expose the raw YOLO26 heads:
  - `model/conv61`
  - `model/conv64`
  - `model/conv77`
  - `model/conv80`
  - `model/conv91`
  - `model/conv94`
- Current diagnostics after letterboxing and threshold tuning show the model is now usable:
  - 80x80 head still remains low (around `0.03`)
  - 40x40 head now reaches roughly `0.22`
  - 20x20 head can reach `0.5`
- In practice, the model now yields at least one stable `person` detection on the active PS3 stream.
- The UI overlay is no longer a text-on-box style only:
  - primary and secondary overlays now use wire-label callouts (leader line + offset label box),
  - semantic detections show object + confidence,
  - secondary text line shows a compact AI/class hint,
  - non-semantic contour fallback is intentionally de-emphasized (`cible visuelle` / `fallback contour`).
- The UI now surfaces COCO semantic hints even on borderline frames:
  - when no object is confirmed yet, the object tag panel and overlays can show `indices COCO` instead of staying semantically empty,
  - this keeps sub-threshold COCO activity visible without lowering thresholds again.
- The NPU tile/pill no longer falsely looks dead when Hailo is active without measurable utilization:
  - `hailo0` now shows active state from `runtime_status`,
  - the pill favors activity/fps text over fake `0%`.
- With the current thresholds (`0.15` primary, `0.12` secondary), the validated runtime can now produce the same confirmed semantic class on both active streams during the same inspection window.

## Remaining Checks
1. Validate the current parity (`personne` / same-class behavior) and the new `semantic_hints` path on several real scenes and object types, not only on the latest pose that passed.
2. Continue the COCO rollout by improving semantic precision (for example: better confirmed classes beyond `personne`), not just hint visibility.
3. If the Surface stream still looks jerky in the browser after `v4r37`, compare `/video/stream-secondary` directly against the full dashboard to isolate any remaining frontend-only rendering issue.
4. If the `0.15` / `0.12` thresholds prove too noisy in wider scenes, tune incrementally rather than jumping back to `0.35`.
5. Only change `vision.model_path` later if you want the config to explicitly declare `yolo26n.hef`; runtime behavior is already correct without that change.
6. Two lamps (`Canapé`, `Salle à manger`) still have no stable `yeelight_id`; if you want future rebinds to be fully deterministic even under drift, capture and persist their hardware IDs during a full six-bulb discovery window.
