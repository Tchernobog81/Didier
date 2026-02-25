# Release Notes

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

