# Release Notes

## didier-v4r41-yeelight-mac-fallback-2026-03-01 - 2026-03-01 23:35:00 UTC
- Captured the two remaining missing lamp identities using stable MAC-backed fallback IDs because those bulbs still do not publish a Yeelight SSDP `id` reliably on this network.
- `tentacles/actuators.py` now derives a synthetic stable identity (`mac:..`) from `/proc/net/arp` for scan-only bulbs, so `Canapé` and `Salle à manger` can keep deterministic bindings even when SSDP stays incomplete.
- The actuator registry persistence path now preserves top-level metadata (including `reference_metrics`) instead of rewriting the file with `devices` only.
- Added unit coverage for ARP-based identity fallback and preservation of non-device registry keys.

## didier-v4r40-yeelight-binding-hardening-2026-03-01 - 2026-03-01 23:05:00 UTC
- Hardened the Yeelight binding repair path so scan-only bulbs with no hardware identifier no longer leak the string `"None"` into persisted `yeelight_id` fields; missing IDs now stay `null`.
- Heuristic rebinding is now gated behind a complete bulb inventory, which prevents partial discovery runs from corrupting the actuator registry by remapping several logical lamps during an incomplete scan.
- Added seed-IP based matching from logical device IDs (`yl_192_168_1_xx`) so duplicate/stale current IPs do not let one bulb "steal" another lamp slot during reconciliation.
- Broadened the nearby TCP scan with short repeated attempts and bounded multi-round accumulation, which made the live inventory converge on the real reachable bulbs without relying on SSDP alone.
- Added regression tests for `None`-like hardware IDs and incomplete-inventory protection.

## didier-v4r39-yeelight-auto-discovery-rebind-2026-03-01 - 2026-03-01 22:05:00 UTC
- Added Yeelight SSDP discovery and automatic IP rebind for Xiaomi/Yeelight bulbs, so Didier can recover from DHCP drift instead of treating moved bulbs as permanently offline.
- The actuators tentacle now persists `yeelight_id` hardware identifiers when it can see the bulbs, then uses those stable IDs to refresh stale IPs on later probes and commands.
- Live status now falls back to the discovery snapshot when direct control probing hits a transport error, which keeps ON/OFF and brightness/color indicators aligned with the real lamp state while the binding is being healed.
- Yeelight commands now retry once after an automatic rebind when the first attempt fails due to a transport-level error (`Connection refused`, timeout, reset, no response).
- Added unit coverage for stale-IP reconciliation, discovery-state fallback, and command retry after rebind.

## didier-v4r38-actuator-live-state-palette-2026-03-01 - 2026-03-01 21:05:00 UTC
- Fixed the actuator state regression in the web UI: ON/OFF no longer falls back to `last_command` when a live Yeelight/Xiaomi status probe fails. A lamp now shows its real probed state when reachable, and explicitly shows an unknown/offline state when it cannot be read.
- Added periodic live status refresh while the `Actionneurs` tab is open, so the lamp cards track external state changes instead of only refreshing on manual reload.
- Replaced the fixed 8-color preset strip with a real integrated color picker per lamp card: each card now exposes a direct native palette control (full color chooser) instead of preset-only swatches.
- Added unit coverage for the actuators tentacle live status/command flow.

## didier-v4r37-coco-hints-visible-2026-03-01 - 2026-03-01 20:45:00 UTC
- Detection payloads now expose `semantic_hints` explicitly on both primary and secondary paths, so clients can consume the best COCO candidates without having to dig through nested `status.*_object_hints`.
- The vision UI now surfaces COCO semantic hints when no object is confirmed yet: the object tag panel switches from raw shape-only chips to an object-first message (`indices COCO`), and the overlays can show a lightweight hint banner instead of looking semantically empty.
- This makes sub-threshold COCO activity (for example `personne`, `television`, `canape`) visible during borderline frames, which improves diagnosis without lowering the detector thresholds again.

## didier-v4r36-surface-stream-cadence-fix-2026-03-01 - 2026-03-01 20:10:00 UTC
- Fixed the actual Surface-display cadence bug: the remote MJPEG HTTP generator no longer re-applies the resource arbitrator target FPS once the backend reader already has a healthy stream, so a `15 fps` Surface stream is emitted at `15 fps` instead of being silently clamped down to `10 fps` in `TENDU`.
- The same fixed cadence is now used for remote-stream stall timing and restart backoff, which keeps the diagnostics aligned with the configured stream instead of the CPU throttle profile.
- Added a pure `stream_emit_interval()` helper and unit coverage so the distinction between "follow the arbitrator" and "honor the configured stream FPS" stays locked in tests.

## didier-v4r35-secondary-sync-live-npu-2026-03-01 - 2026-03-01 20:45:00 UTC
- Reduced the end-to-end latency of UI object overlays: primary and secondary detection polling now runs at 250 ms, and the API-side request throttles for `/vision/detections` and `/vision/detections-secondary` were tightened to match instead of forcing stale empty payloads.
- Lowered the UI overlay confidence gates to match the backend detector thresholds, so valid Hailo detections around `0.12-0.15` are no longer silently hidden on screen.
- Secondary Hailo detections now use a dedicated score threshold (`vision.secondary_npu_score_threshold`, set to `0.12`) under the same shared detector lock, which lets the Surface stream keep up with the PS3 on near-threshold `personne` detections without changing the primary threshold.
- Secondary display streaming now keeps its configured cadence stable (`vision.remote_stream.fps`) instead of inheriting arbitration target FPS, which removes avoidable 10/15/20 FPS oscillations in the Surface viewer.
- When the Hailo driver reports runtime activity but no reliable utilization percentage, Didier now publishes a live estimated NPU utilization derived from real inference FPS, so the NPU bar behaves more like the CPU telemetry instead of staying visually dead.

## didier-v4r34-modular-vision-pipeline-2026-03-01 - 2026-03-01 20:20:00 UTC
- Refactored the active vision pipeline into testable modules:
  - `core/vision_capture_service.py` plans capture sources and backend attempts,
  - `core/vision_preprocess_service.py` isolates letterboxing and model-input preparation,
  - `core/vision_yolo26_service.py` owns the vectorized YOLO26 6-head decode and semantic debug hints.
- The live tentacle now consumes those pure helpers, which keeps the PS3 path stable while making the Hailo pre/post-processing unit-testable without hardware.
- Added configuration-ready camera source planning (`vision.camera_source`) so the same capture engine can pivot between PS3 USB devices and network camera URLs without rewriting the core loop.
- Class labels now accept `.json` and simple `.yaml/.yml` files in addition to `.names`, so COCO-80 labels can be externalized in structured config files.

## didier-v4r33-remote-stream-lifecycle-object-hints-2026-03-01 - 2026-03-01 19:05:00 UTC
- The shared Surface stream reader now exposes richer lifecycle diagnostics (`started`, `alive`, `waiting_s`, `spawn_count`, `restart_count`, `input_url`) so `/vision/status-secondary` can distinguish "reader not started", "waiting for source packets", and "stalled source" instead of a generic offline state.
- The remote `ffmpeg` reader now starts with lower-latency probe settings, logs spawn/stall/restart events, and is explicitly stopped during API shutdown, which prevents orphaned reader processes from piling up and reduces service stop timeouts.
- The UI now stops forcing secondary MJPEG reconnects while the backend reader is already alive but waiting on packets; it only reopens `/video/stream-secondary` when the shared reader is missing or actually down.
- Vision status now publishes object-oriented hints (`object_hints`, `primary_object_hints`, `secondary_object_hints`) derived from the YOLO26 top candidates, so sub-threshold COCO classes remain visible as semantic clues instead of forcing shape-only interpretation.

## didier-v4r32-surface-watchdog-coco-debug-2026-03-01 - 2026-03-01 18:52:38 UTC
- Stopped the UI from force-reloading the Surface MJPEG stream on a blind timer while healthy; the secondary stream is now only reconnected on actual backend offline status.
- Added a stall watchdog in the shared remote MJPEG reader: if `ffmpeg` stays alive but stops yielding JPEG frames for too long, Didier now restarts that reader automatically instead of sitting on multi-second freezes.
- `/vision/status-secondary` now returns extra remote-stream diagnostics (`fps`, `frame_gap_s`, `last_error`, `stalled`) to distinguish a frozen source from a display-only issue.
- Vision debug snapshots now carry translated `class_name` values for top candidates, making sub-threshold COCO classes visible in diagnostics even when the final accepted detection remains `personne`.

## didier-v4r31-coco80-french-labels-2026-03-01 - 2026-03-01 18:40:53 UTC
- The active vision tentacle now normalizes COCO label names to French-oriented runtime labels when loading `models/vision/coco.names`.
- This makes the 80 YOLO/COCO classes directly usable in the UI and payloads (`voiture`, `sac a dos`, `telecommande`, etc.) instead of relying on raw English labels or generic `class_X` fallbacks.
- Added a unit test covering COCO label translation at load time.

## didier-v4r30-wire-label-object-diagnostics-2026-03-01 - 2026-03-01 18:32:57 UTC
- Added wire-label overlays on primary and secondary vision streams: labels are now offset from the object with a leader line instead of being stamped directly on the polygon.
- Detection text now prioritizes object-oriented diagnostics:
  - semantic detections show object label + confidence,
  - the secondary line shows an AI/class hint,
  - shape-only fallbacks are downgraded to a generic `cible visuelle` / `fallback contour` wording instead of raw shape names.
- Detection chips in the tagging panel now follow the same object-first wording, with semantic labels preferred over geometric fallback labels.

## didier-v4r29-npu-ui-hailo-activity-2026-03-01 - 2026-03-01 18:26:03 UTC
- Fixed the NPU UI so Hailo runtime activity is no longer flattened to `0%` when `/metrics` reports `active=true` but no reliable utilization percentage.
- `hailo0` now shows `ACTIF` in the per-core panel when `runtime_status` is `active/resuming`, with a visible minimum fill instead of a dead bar.
- The top NPU pill now prefers explicit active text (`act ...`) and real FPS when the device is running but utilization is not measurable, instead of showing misleading `0%`.

## didier-v4r28-vision-stream-smoothing-yolo26-2026-03-01 - 2026-03-01 17:35:26 UTC
- Added short primary detection hold (`1.2s`) so brief YOLO26 misses no longer blank the overlay immediately after a valid hit.
- Hardened remote Surface MJPEG ingestion:
  - `ffmpeg` stderr is now discarded to avoid pipe backpressure stalls,
  - the reader automatically restarts `ffmpeg` after transient input drops,
  - the HTTP MJPEG generator re-emits the last JPEG at target cadence to reduce visible freezes.
- Remote stream requests now keep the active `ffmpeg` session stable when only FPS guidance changes, avoiding visible cuts during load-mode swings while still updating stream cadence hints.
- Secondary vision now suppresses shape-only fallback payloads when Hailo is active, so the UI prefers a short hold of the last real object detection over noisy polygons.
- Added targeted unit tests for the new primary hold and secondary shape-fallback suppression behavior.

## didier-v4r23-chat-timeout-bounded-2026-02-25 - 2026-02-25 22:08:00 UTC
- Tightened `/ask-and-speak` latency budget to keep conversational responses bounded under fluctuating load.
- In `TENDU`, conversation path now avoids remote Pixel chat round-trip and prioritizes local fast-fail behavior.
- Added cancellation propagation fixes so timeout cancellation is not swallowed by broad exception handlers.
- Result: significantly lower worst-case response latency during contention, with explicit overload fallback text instead of long hangs.

## didier-v4r22-chat-audio-latency-guards-2026-02-25 - 2026-02-25 22:02:00 UTC
- Added load-aware chat QoS in `ai` router:
  - tighter LLM time budgets under `TENDU/SURVIE`,
  - bounded `/ask-and-speak` global budget via `asyncio.wait_for`,
  - forced local execution path in `TENDU` to avoid slow remote Pixel round-trips.
- Added cancellation-safe handling (`CancelledError`) in key async LLM calls to ensure timeout guards are effective.
- Added dynamic TTS shortening based on runtime pressure (arbitration mode + audio queue/speaking state).
- Added audio worker preemption controls:
  - `/speak` now supports `interrupt_current`,
  - playback process interruption + skip-current-output guard to prioritize freshest reply,
  - exposed `playback_interrupted` counters in audio health/metrics.

## didier-v4r21-surface-empty-fallback-guard-2026-02-25 - 2026-02-25 21:55:00 UTC
- Added secondary-stream empty-result guard: after consecutive empty Hailo results, trigger controlled shape fallback to reduce long “no detection” periods on Surface.
- Kept Hailo priority path unchanged; fallback only activates on repeated empty outputs or lock contention.

## didier-v4r20-arbitration-vision-fps-sync-2026-02-25 - 2026-02-25 21:51:00 UTC
- Added mode-aware secondary detection cadence (Nominal/Tendu/Survie) in `/vision/detections-secondary`.
- Added safer fallback behavior for secondary stream when arbitration denies access: short hold of last non-empty detections instead of immediate visual drop.
- Added primary and secondary inference FPS tracking in vision tentacle status (`infer_fps`, `secondary_infer_fps`).
- Enriched `/metrics.npu` with `real_fps` and `secondary_fps` when Hailo is active.
- Updated UI NPU display/pill to surface FPS activity even when kernel utilization metrics are unavailable.

## didier-v4r19-vision-surface-threshold-balance-2026-02-25 - 2026-02-25 21:44:00 UTC
- Added per-stream overlay confidence thresholds for better practical visibility:
  - Primary PS3: `0.40` (strict, cleaner overlay).
  - Secondary Surface: `0.25` (more permissive to avoid apparent dropouts).
- Keeps primary anti-rectangle behavior while preserving useful secondary feedback.

## didier-v4r18-vision-overlay-surface-stability-2026-02-25 - 2026-02-25 21:39:00 UTC
- Removed rectangle-style overlays on primary PS3 feed by suppressing bbox-equivalent polygons while keeping Surface fallback visibility.
- Added confidence guard (`>= 0.4`) on overlay rendering to reduce unstable low-confidence boxes.
- Stabilized secondary (Surface) detections with short hold of last non-empty result (`4s`) to avoid flicker/no-detection gaps.
- Added secondary detection retry + shape fallback when NPU/camera locks are briefly contended.
- Increased secondary detection polling cadence in UI (`3.5s -> 2.2s`) for faster visual updates.

## didier-v4r17-ui-cache-sync-poly-stable-2026-02-25 - 2026-02-25 21:24:00 UTC
- Removed hardcoded UI `V4r14` values by server-side injecting `__UI_VERSION__` from `VERSION`.
- Replaced static cache-busters with dynamic `__ASSET_TAG__` derived from current release version.
- Synced header version text with `/version` polling to keep UI version stable after reload.
- This prevents stale cached JS/CSS from hiding polygon overlays after normal browser reload.

## didier-v4r15-path-guard-release-2026-02-25 - 2026-02-25 20:56:00 UTC
- Added repository-root preflight guard scripts to eliminate wrong-path executions.
- Added mandatory release bump enforcement for code commits (VERSION + RELEASE_NOTES.md).
- Added versioned Git hook setup script and enabled hook path support.
## didier-v4r16-model-first-poly-latency-2026-02-25 - 2026-02-25 20:12:17 UTC
- Model-first tool planning, LLM circuit breaker for latency, polygon shape overlay.
- Added OpenAI-compatible planner contract (`intent/needs_tools/answer_mode`) with safe heuristic fallback.
- Added short LLM response cache and parallel tool execution in bridge for lower end-to-end latency.
- Enabled `vision.polygon_refine=true` and shape labeling in overlay rendering.

## didier-v4r24-picobot-gemini-boost-2026-02-25 - 2026-02-25 21:39:26 UTC
- Added a `Boost` toggle in the `Parler a Didier` chat box and persisted user preference in local storage.
- `/ask-and-speak` now receives `boost` and can route conversational generation through Gemini when enabled.
- Added bounded Gemini fallback path with strict timeout and transparent fallback to existing local/pixel routes.
- Added lightweight rolling memory for boosted exchanges (`data/gemini_boost_memory.jsonl`) so answers can improve over repeated usage.
- Added `picobot.gemini` configuration block for enablement, endpoint/model, timeout and memory controls.
## didier-v4r25-gemini-env-systemd-2026-02-25 - 2026-02-25 21:47:18 UTC
- Secured Gemini API key via systemd EnvironmentFile and updated Gemini model to gemini-2.0-flash.

## didier-v4r26-disable-gemini-boost-temp-2026-02-25 - 2026-02-25 21:48:52 UTC
- Disabled picobot.gemini boost path by default to avoid quota errors; fallback remains transparent via existing routes.

## didier-v4r27-checkpoint-rationalization-yolo26-prehef-2026-03-01 - 2026-03-01 01:59:03 UTC
- Checkpoint: architecture rationalization, E2E chat green on 5010, YOLO26 artifacts generated to ONNX and ready for external HEF build.
