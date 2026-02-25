# Vision Prod Baseline (HEF)

Date baseline: 2026-02-14

## Reference config (frozen)

- HEF path: `/mnt/didier_ssd/didier/models/hailo/hailo_model.hef`
- Worker service: `services/didier-vision.service`
- Runtime endpoint: `http://127.0.0.1:5011/metrics`

Current production command (systemd env `DIDIER_TAPPAS_COMMAND`):
- camera path first (`v4l2src /dev/video0`)
- fallback to `videotestsrc` if camera is busy/unavailable

This keeps the worker alive while preserving a deterministic HEF path.

## One command benchmark

```bash
bash scripts/bench_vision_prod.sh
```

Optional tuning:

```bash
DIDIER_VISION_BENCH_DURATION=30 \
DIDIER_VISION_BENCH_INTERVAL=1 \
DIDIER_VISION_MIN_AVG_FPS=10 \
bash scripts/bench_vision_prod.sh
```

## Expected output

- `tappas_started_count > 0`
- `hef_command_match_count > 0`
- `mode_hailo_count > 0` on healthy Hailo setup
- `result=PASS` or `result=WARN:avg_fps_below_target`

`FAIL:*` means production baseline is broken and should block rollout.

## Quick triage

1. Check service:
```bash
systemctl --no-pager --full status didier-vision.service
```
2. Check live metrics:
```bash
curl -sS http://127.0.0.1:5011/metrics
```
3. Check logs:
```bash
journalctl -u didier-vision.service --since "10 min ago" --no-pager
```
