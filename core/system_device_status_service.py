"""Device status aggregation and cache orchestration for system routes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Awaitable
from typing import Callable


def _camera_from_vision_status(
    *,
    vision: Any,
    now: float,
    camera_index: int,
    camera_device: Any,
) -> dict[str, Any] | None:
    if not vision or not callable(getattr(vision, "get_status", None)):
        return None
    try:
        status = vision.get_status()
        last_frame_ts = status.get("last_frame_ts")
        age = float(now) - float(last_frame_ts) if last_frame_ts else None
        ok = age is not None and age < 3.5
        return {
            "device": camera_device or f"index:{int(camera_index)}",
            "opened": bool(ok),
            "frame": bool(ok),
            "last_frame_ts": last_frame_ts,
            "last_frame_age_s": round(age, 2) if age is not None else None,
            "source": "vision",
        }
    except Exception:
        return None


def _camera_secondary_payload(
    *,
    enabled: bool,
    stream: Any,
    now: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": bool(enabled),
        "opened": False,
        "frame": False,
        "last_frame_ts": None,
        "last_frame_age_s": None,
        "source": "remote_stream",
    }
    if not enabled or stream is None:
        return payload
    try:
        frame, last_frame_ts = stream.get_last()
        age = float(now) - float(last_frame_ts) if last_frame_ts else None
        payload.update(
            {
                "opened": True,
                "frame": bool(frame),
                "last_frame_ts": last_frame_ts,
                "last_frame_age_s": round(age, 2) if age is not None else None,
            }
        )
    except Exception:
        pass
    return payload


@dataclass(frozen=True)
class DeviceStatusDeps:
    get_orchestrator: Callable[[], Any]
    now: Callable[[], float]
    get_remote_stream: Callable[[], Any]
    check_camera: Callable[[int, Any], Awaitable[dict[str, Any]]]
    check_camera_usb: Callable[[Any, Any], Awaitable[dict[str, Any]]]
    check_camera_mic: Callable[[], Awaitable[dict[str, Any]]]
    check_soundboks_sink: Callable[[str], Awaitable[dict[str, Any]]]
    check_npu: Callable[[str, str], Awaitable[dict[str, Any]]]
    check_tts: Callable[[Any, Any, Any], Awaitable[dict[str, Any]]]
    read_version: Callable[[], Awaitable[dict[str, Any]]]


@dataclass
class DeviceStatusCollector:
    cache_ttl_s: float
    _cache: dict[str, Any] | None = None
    _cache_ts: float = 0.0
    _lock: Any = field(default_factory=asyncio.Lock)

    def invalidate(self) -> None:
        self._cache = None
        self._cache_ts = 0.0

    async def collect(self, *, deps: DeviceStatusDeps) -> dict[str, Any]:
        now = float(deps.now())
        if self._cache is not None and (now - self._cache_ts) <= self.cache_ttl_s:
            return dict(self._cache)
        if self._lock.locked() and self._cache is not None:
            return dict(self._cache)

        async with self._lock:
            now = float(deps.now())
            if self._cache is not None and (now - self._cache_ts) <= self.cache_ttl_s:
                return dict(self._cache)

            orchestrator = deps.get_orchestrator()
            camera_index = int(orchestrator.config.get("vision.camera_index", 0))
            camera_device = orchestrator.config.get("vision.camera_device", None)
            vendor = orchestrator.config.get("vision.usb_id_vendor", None)
            product = orchestrator.config.get("vision.usb_id_product", None)
            sink = str(orchestrator.config.get("bluetooth.sink_name", "") or "")
            tts_model = orchestrator.config.get("tts.model_path", None)
            tts_config = orchestrator.config.get("tts.config_path", None)
            tts_voices = orchestrator.config.get("tts.voices_path", None)
            npu_device = str(orchestrator.config.get("npu.device", "/dev/hailo0") or "/dev/hailo0")
            npu_pcie = str(
                orchestrator.config.get("npu.pcie_address", "0001:01:00.0") or "0001:01:00.0"
            )
            didier_model = (
                orchestrator.config.get("ollama.model_profiles.ask", None)
                or orchestrator.config.get("ollama.ask_model", None)
                or orchestrator.config.get("ollama.model", None)
            )
            secondary_cfg = orchestrator.config.get("vision.remote_stream", {}) or {}
            secondary_enabled = bool(secondary_cfg.get("enabled", True))

            vision = orchestrator.get_tentacle("vision")
            camera = _camera_from_vision_status(
                vision=vision,
                now=now,
                camera_index=camera_index,
                camera_device=camera_device,
            )
            if camera is None:
                camera = await deps.check_camera(camera_index, camera_device)

            camera_secondary = _camera_secondary_payload(
                enabled=secondary_enabled,
                stream=deps.get_remote_stream(),
                now=deps.now(),
            )
            camera_usb, mic, sound, npu, tts, version = await asyncio.gather(
                deps.check_camera_usb(vendor, product),
                deps.check_camera_mic(),
                deps.check_soundboks_sink(sink),
                deps.check_npu(npu_device, npu_pcie),
                deps.check_tts(tts_model, tts_config, tts_voices),
                deps.read_version(),
            )

            payload = {
                "camera": camera,
                "camera_secondary": camera_secondary,
                "camera_usb": camera_usb,
                "mic": mic,
                "sound": sound,
                "npu": npu,
                "tts": tts,
                "version": version,
                "models": {
                    "didier": didier_model,
                    "clawbot": didier_model,
                    "ask": orchestrator.config.get("ollama.model_profiles.ask", None),
                    "coding": orchestrator.config.get("ollama.model_profiles.coding", None),
                },
            }
            self._cache = dict(payload)
            self._cache_ts = float(deps.now())
            return payload
