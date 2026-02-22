import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from core.routers.guards import circuit_breaker
from core.resource_arbitrator import get_resource_arbitrator

router = APIRouter()
DEFAULT_HTTP_TIMEOUT_S = 2.0
_DETECTIONS_REFRESH_LOCK = asyncio.Lock()
_DETECTIONS_REFRESH_MIN_INTERVAL_S = 0.8
_last_detections_refresh_ts = 0.0


@router.get("/vision/capture")
async def capture() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    if not hasattr(vision, "capture_once"):
        raise HTTPException(status_code=501, detail="capture not supported")
    image_path = await vision.capture_once()
    return {"path": image_path}


@router.post("/vision/describe")
@circuit_breaker("vision.describe")
async def vision_describe(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("vision_describe"):
        raise HTTPException(status_code=503, detail="arbitration_denied:vision_describe")
    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    config = orchestrator.config
    prompt = (
        (payload or {}).get("prompt")
        or config.get("vision.describe_prompt", "Décris l'image en français.")
    )
    model = config.get("vision.describe_model", "moondream:1.8b")
    num_predict = int(config.get("vision.describe_num_predict", 160))
    base_url = config.get("ollama.base_url", "http://localhost:11434")
    img_bytes = None
    if hasattr(vision, "get_latest_jpeg"):
        try:
            img_bytes = vision.get_latest_jpeg()
        except Exception:
            img_bytes = None
    if not img_bytes and hasattr(vision, "capture_once"):
        try:
            image_path = await vision.capture_once()
            img_bytes = api_module.Path(image_path).read_bytes()
        except Exception:
            img_bytes = None
    if not img_bytes:
        raise HTTPException(status_code=503, detail="capture unavailable")
    img_b64 = api_module.base64.b64encode(img_bytes).decode("ascii")
    payload_data: dict[str, Any] = {
        "model": model,
        "prompt": str(prompt),
        "stream": False,
        "images": [img_b64],
        "options": {"num_predict": num_predict, "temperature": 0.2},
    }
    keep_alive = config.get("ollama.keep_alive", None)
    if keep_alive:
        payload_data["keep_alive"] = keep_alive
    try:
        import httpx

        async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_S) as client:
            response = await client.post(f"{base_url}/api/generate", json=payload_data)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return {
        "response": str(data.get("response", "")).strip(),
        "model": model,
    }


@router.post("/vision/enroll")
async def vision_enroll(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision or not hasattr(vision, "enroll_owner"):
        raise HTTPException(status_code=503, detail="vision tentacle not ready")
    samples = int(payload.get("samples", 5)) if payload else 5
    result = await api_module.asyncio.to_thread(vision.enroll_owner, samples)
    return result


@router.get("/vision/owner")
async def vision_owner() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision or not hasattr(vision, "check_owner"):
        raise HTTPException(status_code=503, detail="vision tentacle not ready")
    result = await api_module.asyncio.to_thread(vision.check_owner)
    return result


@router.get("/vision/status")
async def vision_status() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    if not hasattr(vision, "get_status"):
        raise HTTPException(status_code=501, detail="vision status not supported")
    return vision.get_status()


@router.get("/vision/tags")
async def vision_tags() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    return {"tags": api_module._load_vision_tags()}


@router.post("/vision/tags")
async def vision_tags_update(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    if not payload:
        raise HTTPException(status_code=400, detail="payload required")
    tags = api_module._load_vision_tags()
    if "tags" in payload and isinstance(payload["tags"], dict):
        for key, value in payload["tags"].items():
            key = str(key)
            label = str(value).strip() if value is not None else ""
            if label:
                tags[key] = label
            elif key in tags:
                tags.pop(key, None)
    else:
        key = str(payload.get("key", "")).strip()
        label = str(payload.get("label", "")).strip()
        if not key:
            raise HTTPException(status_code=400, detail="key required")
        if label:
            tags[key] = label
        else:
            tags.pop(key, None)
    api_module._save_vision_tags(tags)
    return {"status": "ok", "count": len(tags)}


@router.get("/vision/zones")
async def vision_zones() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    width = orchestrator.config.get("vision.width", None)
    height = orchestrator.config.get("vision.height", None)
    zones = orchestrator.config.get("vision.zones", [])
    return {
        "zones": api_module._normalize_zones(zones, width, height),
        "width": width,
        "height": height,
    }


@router.post("/vision/detect")
@circuit_breaker("vision.detect")
async def vision_detect() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("npu_inference"):
        raise HTTPException(status_code=503, detail="arbitration_denied:npu_inference")
    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    if not hasattr(vision, "detect_once"):
        raise HTTPException(status_code=501, detail="vision detect not supported")
    try:
        return await asyncio.wait_for(vision.detect_once(), timeout=2.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="vision_detect_timeout")


@router.get("/vision/detections")
async def vision_detections() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    if not hasattr(vision, "get_latest_detections"):
        raise HTTPException(status_code=501, detail="vision detections not supported")
    data = vision.get_latest_detections()
    if not isinstance(data, dict):
        return {"detections": [], "frame": {"width": None, "height": None}, "ts": 0.0}

    # Passive mode: if background detection is disabled/stale, refresh at low frequency.
    last_ts = float(data.get("ts", 0.0) or 0.0)
    now = api_module.time.time()
    refresh_max_age_s = max(
        0.5,
        float(orchestrator.config.get("vision.on_demand_refresh_max_age_seconds", 1.5)),
    )
    background_detect_enabled = bool(orchestrator.config.get("vision.background_detect", True))
    detections = data.get("detections") if isinstance(data.get("detections"), list) else []
    needs_refresh = (now - last_ts) > refresh_max_age_s
    if not background_detect_enabled and len(detections) == 0:
        needs_refresh = True
    if needs_refresh and hasattr(vision, "detect_once"):
        global _last_detections_refresh_ts
        if (
            not _DETECTIONS_REFRESH_LOCK.locked()
            and (now - _last_detections_refresh_ts) >= _DETECTIONS_REFRESH_MIN_INTERVAL_S
        ):
            async with _DETECTIONS_REFRESH_LOCK:
                refresh_now = api_module.time.time()
                if (refresh_now - _last_detections_refresh_ts) >= _DETECTIONS_REFRESH_MIN_INTERVAL_S:
                    _last_detections_refresh_ts = refresh_now
                    arbitrator = get_resource_arbitrator()
                    if arbitrator.request_resource("npu_inference"):
                        try:
                            await asyncio.wait_for(vision.detect_once(), timeout=2.0)
                            refreshed = vision.get_latest_detections()
                            if isinstance(refreshed, dict):
                                refreshed["source"] = "on_demand_refresh"
                                return refreshed
                        except Exception:
                            pass
    return data


@router.get("/vision/detections-secondary")
async def vision_detections_secondary() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("secondary_stream"):
        raise HTTPException(status_code=503, detail="arbitration_denied:secondary_stream")
    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    if not hasattr(vision, "detect_secondary_frame"):
        raise HTTPException(status_code=501, detail="secondary detections not supported")
    cfg = orchestrator.config.get("vision.remote_stream", {}) or {}
    if not cfg.get("enabled", True):
        raise HTTPException(status_code=404, detail="secondary stream disabled")
    input_url = cfg.get("input_url", "udp://0.0.0.0:1234")
    fps = int(cfg.get("fps", 15))
    if not input_url:
        raise HTTPException(status_code=400, detail="input_url required")
    stream = api_module._get_remote_stream(str(input_url), fps=fps)
    frame_bytes, ts = stream.get_last()
    if not frame_bytes:
        raise HTTPException(status_code=503, detail="secondary stream not ready")
    frame = await api_module.asyncio.to_thread(
        api_module.cv2.imdecode,
        api_module.np.frombuffer(frame_bytes, api_module.np.uint8),
        api_module.cv2.IMREAD_COLOR,
    )
    if frame is None:
        raise HTTPException(status_code=503, detail="secondary frame decode failed")
    data = await api_module.asyncio.to_thread(vision.detect_secondary_frame, frame)
    data["stream_ts"] = ts
    return data


@router.get("/vision/status-secondary")
async def vision_status_secondary() -> dict[str, Any]:
    """
    Route ultra-légère pour la pastille d'état (CPU < 1%).
    Vérifie juste si des paquets UDP arrivent sans décoder d'image.
    """
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    cfg = orchestrator.config.get("vision.remote_stream", {}) or {}
    input_url = cfg.get("input_url", "udp://0.0.0.0:1234")

    # Endpoint passif: ne démarre pas ffmpeg, lit seulement l'état du stream déjà actif.
    with api_module._REMOTE_STREAM_LOCK:
        stream = api_module._REMOTE_STREAM
    if stream is None:
        return {
            "status": "offline",
            "age_s": None,
            "ts": 0.0,
        }
    _frame, ts = stream.get_last()

    # On calcule si le flux est récent (moins de 3 secondes)
    now = api_module.time.time()
    is_online = (ts > 0) and (now - ts < 3.0)

    return {
        "status": "online" if is_online else "offline",
        "age_s": round(now - ts, 1) if ts > 0 else None,
        "ts": ts,
    }


@router.get("/video/stream")
@circuit_breaker("vision.stream")
async def video_stream():
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    orchestrator = api_module._require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    live_enabled = bool(orchestrator.config.get("vision.enable_live", False))
    primary_fallback_secondary = bool(
        orchestrator.config.get("vision.primary_fallback_secondary", False)
    )
    if vision and live_enabled and hasattr(vision, "get_latest_jpeg"):
        primary_stream_stale = False
        if hasattr(vision, "get_status"):
            try:
                status = vision.get_status()
                last_frame_ts = float(status.get("last_frame_ts", 0.0) or 0.0)
                if last_frame_ts > 0.0:
                    age_s = max(0.0, api_module.time.time() - last_frame_ts)
                    stale_after_s = max(
                        1.0,
                        float(
                            orchestrator.config.get(
                                "vision.primary_stale_fallback_seconds", 2.5
                            )
                        ),
                    )
                    primary_stream_stale = age_s > stale_after_s
            except Exception:
                primary_stream_stale = False

        if primary_stream_stale and primary_fallback_secondary:
            cfg = orchestrator.config.get("vision.remote_stream", {}) or {}
            if cfg.get("enabled", True) and cfg.get("input_url"):
                fps = arbitrator.get_target_fps(default=int(cfg.get("fps", 15)))
                stream = api_module._get_remote_stream(str(cfg.get("input_url")), fps=fps)
                return api_module.StreamingResponse(
                    api_module._remote_mjpeg_generator(stream),
                    media_type="multipart/x-mixed-replace; boundary=frame",
                )
        return api_module.StreamingResponse(
            api_module._mjpeg_generator_from_vision(vision),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    def _secondary_stream_response():
        if not arbitrator.request_resource("secondary_stream"):
            return None
        cfg = orchestrator.config.get("vision.remote_stream", {}) or {}
        if not cfg.get("enabled", True):
            return None
        input_url = cfg.get("input_url", "udp://0.0.0.0:1234")
        fps = arbitrator.get_target_fps(default=int(cfg.get("fps", 15)))
        if not input_url:
            return None
        if api_module.shutil.which("ffmpeg") is None:
            return None
        stream = api_module._get_remote_stream(str(input_url), fps=fps)
        return api_module.StreamingResponse(
            api_module._remote_mjpeg_generator(stream),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    # Primary stream should target PS3 by default (no implicit fallback to Surface).
    # If needed, fallback can be explicitly re-enabled via config.
    api_local_capture_enabled = bool(
        orchestrator.config.get("vision.api_local_capture_enabled", True)
    )
    if not api_local_capture_enabled:
        if primary_fallback_secondary:
            fallback = _secondary_stream_response()
            if fallback is not None:
                return fallback
        raise HTTPException(
            status_code=423,
            detail="Primary PS3 stream disabled (vision.api_local_capture_enabled=false)",
        )
    camera_index = int(orchestrator.config.get("vision.camera_index", 0))
    camera_device = orchestrator.config.get("vision.camera_device", None)
    width = orchestrator.config.get("vision.width", None)
    height = orchestrator.config.get("vision.height", None)
    configured_fps = orchestrator.config.get("vision.fps", None)
    fps = arbitrator.get_target_fps(default=int(configured_fps or 20))
    fourcc = orchestrator.config.get("vision.fourcc", None)
    kill_on_open = bool(orchestrator.config.get("vision.kill_on_open", False))
    if api_module._VIDEO_LOCK.locked():
        raise HTTPException(status_code=409, detail="Camera busy")
    try:
        api_module._open_camera(
            camera_device, camera_index, width, height, fps, fourcc, kill_on_open
        ).release()
    except Exception:
        if primary_fallback_secondary:
            fallback = _secondary_stream_response()
            if fallback is not None:
                return fallback
        raise HTTPException(status_code=503, detail="Camera not available")
    return api_module.StreamingResponse(
        api_module._mjpeg_generator(
            camera_device, camera_index, width, height, fps, fourcc, kill_on_open
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/video/stream-secondary")
@circuit_breaker("vision.stream_secondary")
async def video_stream_secondary():
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("secondary_stream"):
        raise HTTPException(status_code=503, detail="arbitration_denied:secondary_stream")
    orchestrator = api_module._require_orchestrator()
    cfg = orchestrator.config.get("vision.remote_stream", {}) or {}
    if not cfg.get("enabled", True):
        raise HTTPException(status_code=404, detail="secondary stream disabled")
    input_url = cfg.get("input_url", "udp://0.0.0.0:1234")
    fps = arbitrator.get_target_fps(default=int(cfg.get("fps", 15)))
    if not input_url:
        raise HTTPException(status_code=400, detail="input_url required")
    if api_module.shutil.which("ffmpeg") is None:
        raise HTTPException(status_code=503, detail="ffmpeg not installed")
    stream = api_module._get_remote_stream(str(input_url), fps=fps)
    return api_module.StreamingResponse(
        api_module._remote_mjpeg_generator(stream),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
