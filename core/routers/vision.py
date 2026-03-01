import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from core.routers.guards import circuit_breaker
from core.resource_arbitrator import get_resource_arbitrator
from core.vision_describe_service import VisionDescribeDeps
from core.vision_describe_service import VisionDescribeServiceError
from core.vision_describe_service import describe_latest_frame
from core.vision_primary_service import PrimaryDetectionsState
from core.vision_remote_status_service import evaluate_remote_stream_status
from core.vision_remote_status_service import snapshot_remote_stream
from core.vision_route_support import VisionRouteGuardError
from core.vision_route_support import enforce_npu_requirement
from core.vision_route_support import get_vision_tentacle
from core.vision_route_support import require_vision_capability
from core.vision_route_support import require_vision_tentacle
from core.vision_secondary_detection_service import VisionSecondaryDetectionDeps
from core.vision_secondary_detection_service import collect_secondary_detections
from core.vision_secondary_service import SecondaryDetectionsState
from core.vision_stream_service import PrimaryStreamConfig
from core.vision_stream_service import SecondaryStreamConfig
from core.vision_stream_service import build_primary_camera_plan
from core.vision_stream_service import build_secondary_stream_plan
from core.vision_stream_service import evaluate_primary_stream

router = APIRouter()
DEFAULT_HTTP_TIMEOUT_S = 2.0
_DETECTIONS_REFRESH_LOCK = asyncio.Lock()
_PRIMARY_STATE = PrimaryDetectionsState(cache_ttl_s=0.7)
_SECONDARY_DETECTIONS_LOCK = asyncio.Lock()
_SECONDARY_STATE = SecondaryDetectionsState(non_empty_hold_ttl_s=4.0)


async def _post_vision_describe_generate(
    base_url: str,
    payload_data: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=float(timeout_s)) as client:
            response = await client.post(f"{str(base_url).rstrip('/')}/api/generate", json=payload_data)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise VisionDescribeServiceError(f"Ollama unavailable: {exc}")
    return data if isinstance(data, dict) else {}


def _raise_guard_error(exc: VisionRouteGuardError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/vision/capture")
async def capture() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    try:
        vision = require_vision_capability(
            orchestrator,
            "capture_once",
            unsupported_detail="capture not supported",
        )
    except VisionRouteGuardError as exc:
        _raise_guard_error(exc)
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
    try:
        vision = require_vision_tentacle(orchestrator)
    except VisionRouteGuardError as exc:
        _raise_guard_error(exc)
    config = orchestrator.config
    deps = VisionDescribeDeps(
        get_latest_jpeg=(vision.get_latest_jpeg if hasattr(vision, "get_latest_jpeg") else None),
        capture_once=(vision.capture_once if hasattr(vision, "capture_once") else None),
        read_bytes=lambda path: api_module.Path(path).read_bytes(),
        post_generate=_post_vision_describe_generate,
    )
    try:
        return await describe_latest_frame(
            prompt=(
                (payload or {}).get("prompt")
                or config.get("vision.describe_prompt", "Décris l'image en français.")
            ),
            model=config.get("vision.describe_model", "moondream:1.8b"),
            num_predict=int(config.get("vision.describe_num_predict", 160)),
            base_url=config.get("ollama.base_url", "http://localhost:11434"),
            keep_alive=config.get("ollama.keep_alive", None),
            timeout_s=DEFAULT_HTTP_TIMEOUT_S,
            deps=deps,
        )
    except VisionDescribeServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/vision/enroll")
async def vision_enroll(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    try:
        vision = require_vision_capability(
            orchestrator,
            "enroll_owner",
            missing_detail="vision tentacle not ready",
            unsupported_detail="vision tentacle not ready",
            unsupported_status_code=503,
        )
    except VisionRouteGuardError as exc:
        _raise_guard_error(exc)
    samples = int(payload.get("samples", 5)) if payload else 5
    result = await api_module.asyncio.to_thread(vision.enroll_owner, samples)
    return result


@router.get("/vision/owner")
async def vision_owner() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    try:
        vision = require_vision_capability(
            orchestrator,
            "check_owner",
            missing_detail="vision tentacle not ready",
            unsupported_detail="vision tentacle not ready",
            unsupported_status_code=503,
        )
    except VisionRouteGuardError as exc:
        _raise_guard_error(exc)
    result = await api_module.asyncio.to_thread(vision.check_owner)
    return result


@router.get("/vision/status")
async def vision_status() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    try:
        vision = require_vision_capability(
            orchestrator,
            "get_status",
            unsupported_detail="vision status not supported",
        )
    except VisionRouteGuardError as exc:
        _raise_guard_error(exc)
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
    try:
        vision = require_vision_capability(
            orchestrator,
            "detect_once",
            unsupported_detail="vision detect not supported",
        )
        enforce_npu_requirement(orchestrator, vision)
    except VisionRouteGuardError as exc:
        _raise_guard_error(exc)
    try:
        return await asyncio.wait_for(vision.detect_once(), timeout=2.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="vision_detect_timeout")


@router.get("/vision/detections")
async def vision_detections() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    now = api_module.time.time()
    cached = _PRIMARY_STATE.fresh_cached_payload(now, source="primary_cache")
    if cached is not None:
        return cached

    orchestrator = api_module._require_orchestrator()
    try:
        vision = require_vision_capability(
            orchestrator,
            "get_latest_detections",
            unsupported_detail="vision detections not supported",
        )
    except VisionRouteGuardError as exc:
        _raise_guard_error(exc)
    if _DETECTIONS_REFRESH_LOCK.locked():
        cached = _PRIMARY_STATE.cached_payload(source="primary_cache_locked")
        if cached is not None:
            return cached
        return _PRIMARY_STATE.empty_payload(source="primary_cache_locked_empty")

    async with _DETECTIONS_REFRESH_LOCK:
        now = api_module.time.time()
        cached = _PRIMARY_STATE.fresh_cached_payload(now, source="primary_cache")
        if cached is not None:
            return cached
        try:
            data = await asyncio.wait_for(
                api_module.asyncio.to_thread(vision.get_latest_detections),
                timeout=0.15,
            )
        except asyncio.TimeoutError:
            cached = _PRIMARY_STATE.cached_payload(source="primary_timeout_cache")
            if cached is not None:
                return cached
            return _PRIMARY_STATE.empty_payload(source="primary_timeout")
        except Exception:
            cached = _PRIMARY_STATE.cached_payload(source="primary_error_cache")
            if cached is not None:
                return cached
            return _PRIMARY_STATE.empty_payload(source="primary_error")
        return _PRIMARY_STATE.finalize_fresh_payload(
            data,
            refreshed_at=api_module.time.time(),
        )


@router.get("/vision/detections-secondary")
async def vision_detections_secondary() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    orchestrator = api_module._require_orchestrator()
    secondary_cfg = SecondaryStreamConfig.from_mapping(
        orchestrator.config.get("vision.remote_stream", {}) or {}
    )
    vision = get_vision_tentacle(orchestrator)
    deps = VisionSecondaryDetectionDeps(
        now=api_module.time.time,
        request_secondary_stream=lambda: arbitrator.request_resource("secondary_stream"),
        get_stream=lambda input_url, fps: api_module._get_remote_stream(input_url, fps=fps),
        decode_frame=lambda frame_bytes: api_module.asyncio.to_thread(
            api_module.cv2.imdecode,
            api_module.np.frombuffer(frame_bytes, api_module.np.uint8),
            api_module.cv2.IMREAD_COLOR,
        ),
        detect_secondary_frame=lambda target_vision, frame: api_module.asyncio.to_thread(
            target_vision.detect_secondary_frame,
            frame,
        ),
    )
    return await collect_secondary_detections(
        arbitrator=arbitrator,
        state=_SECONDARY_STATE,
        refresh_lock=_SECONDARY_DETECTIONS_LOCK,
        stream_config=secondary_cfg,
        vision=vision,
        deps=deps,
    )


@router.get("/vision/status-secondary")
async def vision_status_secondary() -> dict[str, Any]:
    """
    Route ultra-légère pour la pastille d'état (CPU < 1%).
    Vérifie juste si des paquets UDP arrivent sans décoder d'image.
    """
    from core import runtime_bridge as api_module

    # Endpoint passif: ne démarre pas ffmpeg, lit seulement l'état du stream déjà actif.
    with api_module._REMOTE_STREAM_LOCK:
        stream = api_module._REMOTE_STREAM
    snapshot = snapshot_remote_stream(stream)
    return evaluate_remote_stream_status(snapshot, now=api_module.time.time())


@router.get("/video/stream")
@circuit_breaker("vision.stream")
async def video_stream():
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    orchestrator = api_module._require_orchestrator()
    vision_cfg = PrimaryStreamConfig.from_mapping(orchestrator.config.get("vision", {}) or {})
    secondary_cfg = SecondaryStreamConfig.from_mapping(
        orchestrator.config.get("vision.remote_stream", {}) or {}
    )
    vision = orchestrator.get_tentacle("vision")
    ffmpeg_available = api_module.shutil.which("ffmpeg") is not None

    def _secondary_stream_response():
        if not arbitrator.request_resource("secondary_stream"):
            return None
        plan, _error = build_secondary_stream_plan(
            config=secondary_cfg,
            target_fps=arbitrator.get_target_fps(default=secondary_cfg.fps),
            ffmpeg_available=ffmpeg_available,
        )
        if plan is None:
            return None
        stream = api_module._get_remote_stream(plan.input_url, fps=plan.fps)
        return api_module.StreamingResponse(
            api_module._remote_mjpeg_generator(stream),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    if vision and hasattr(vision, "get_latest_jpeg"):
        cached_jpeg = None
        try:
            cached_jpeg = vision.get_latest_jpeg()
        except Exception:
            cached_jpeg = None
        last_frame_ts = 0.0
        if hasattr(vision, "get_status"):
            try:
                status = vision.get_status()
                last_frame_ts = float(status.get("last_frame_ts", 0.0) or 0.0)
            except Exception:
                last_frame_ts = 0.0
        decision = evaluate_primary_stream(
            config=vision_cfg,
            has_vision=True,
            has_live_jpeg=True,
            cached_jpeg=cached_jpeg,
            last_frame_ts=last_frame_ts,
            now=api_module.time.time(),
        )
        if decision.use_live_stream:
            return api_module.StreamingResponse(
                api_module._mjpeg_generator_from_vision(vision),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )
        if decision.should_try_secondary_fallback:
            fallback = _secondary_stream_response()
            if fallback is not None:
                return fallback

    # Primary stream should target PS3 by default (no implicit fallback to Surface).
    # If needed, fallback can be explicitly re-enabled via config.
    camera_plan = build_primary_camera_plan(
        config=vision_cfg,
        target_fps=arbitrator.get_target_fps(default=vision_cfg.fps),
    )
    if not camera_plan.api_local_capture_enabled:
        if vision_cfg.primary_fallback_secondary:
            fallback = _secondary_stream_response()
            if fallback is not None:
                return fallback
        raise HTTPException(
            status_code=423,
            detail="Primary PS3 stream disabled (vision.api_local_capture_enabled=false)",
        )
    if api_module._VIDEO_LOCK.locked():
        raise HTTPException(status_code=409, detail="Camera busy")
    try:
        api_module._open_camera(
            camera_plan.camera_device,
            camera_plan.camera_index,
            camera_plan.width,
            camera_plan.height,
            camera_plan.fps,
            camera_plan.fourcc,
            camera_plan.kill_on_open,
        ).release()
    except Exception:
        if vision_cfg.primary_fallback_secondary:
            fallback = _secondary_stream_response()
            if fallback is not None:
                return fallback
        raise HTTPException(status_code=503, detail="Camera not available")
    return api_module.StreamingResponse(
        api_module._mjpeg_generator(
            camera_plan.camera_device,
            camera_plan.camera_index,
            camera_plan.width,
            camera_plan.height,
            camera_plan.fps,
            camera_plan.fourcc,
            camera_plan.kill_on_open,
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
    secondary_cfg = SecondaryStreamConfig.from_mapping(
        orchestrator.config.get("vision.remote_stream", {}) or {}
    )
    plan, error = build_secondary_stream_plan(
        config=secondary_cfg,
        target_fps=arbitrator.get_target_fps(default=secondary_cfg.fps),
        ffmpeg_available=(api_module.shutil.which("ffmpeg") is not None),
    )
    if plan is None:
        if error == "secondary stream disabled":
            raise HTTPException(status_code=404, detail=error)
        if error == "input_url required":
            raise HTTPException(status_code=400, detail=error)
        raise HTTPException(status_code=503, detail=error or "secondary stream unavailable")
    stream = api_module._get_remote_stream(plan.input_url, fps=plan.fps)
    return api_module.StreamingResponse(
        api_module._remote_mjpeg_generator(stream),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
