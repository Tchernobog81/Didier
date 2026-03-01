"""Pure preprocessing helpers for camera frames and NPU inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class LetterboxMeta:
    scale: float
    pad_x: int
    pad_y: int
    src_w: int
    src_h: int
    net_w: int
    net_h: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": "letterbox",
            "scale": round(float(self.scale), 6),
            "pad_x": int(self.pad_x),
            "pad_y": int(self.pad_y),
            "src_w": int(self.src_w),
            "src_h": int(self.src_h),
            "net_w": int(self.net_w),
            "net_h": int(self.net_h),
        }


def letterbox_frame(
    frame: np.ndarray,
    *,
    net_w: int,
    net_h: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    src_h, src_w = frame.shape[:2]
    scale = min(float(net_w) / float(max(1, src_w)), float(net_h) / float(max(1, src_h)))
    resized_w = max(1, int(round(float(src_w) * scale)))
    resized_h = max(1, int(round(float(src_h) * scale)))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((net_h, net_w, 3), dtype=np.uint8)
    pad_x = max(0, (net_w - resized_w) // 2)
    pad_y = max(0, (net_h - resized_h) // 2)
    canvas[pad_y : pad_y + resized_h, pad_x : pad_x + resized_w] = resized
    meta = LetterboxMeta(
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
        src_w=src_w,
        src_h=src_h,
        net_w=net_w,
        net_h=net_h,
    )
    return canvas, meta.as_dict()


def resize_frame(
    frame: np.ndarray,
    *,
    net_w: int,
    net_h: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    src_h, src_w = frame.shape[:2]
    resized = cv2.resize(frame, (net_w, net_h), interpolation=cv2.INTER_LINEAR)
    meta = {
        "mode": "resize",
        "scale_x": round(float(net_w) / float(max(1, src_w)), 6),
        "scale_y": round(float(net_h) / float(max(1, src_h)), 6),
        "src_w": int(src_w),
        "src_h": int(src_h),
        "net_w": int(net_w),
        "net_h": int(net_h),
    }
    return resized, meta


def prepare_model_input(
    frame: Any,
    input_shape: tuple[int, int, int] | None,
    *,
    use_letterbox: bool,
    format_order: str | None,
) -> tuple[np.ndarray | None, dict[str, Any] | None]:
    if input_shape is None:
        return None, None
    net_h, net_w, _channels = (int(input_shape[0]), int(input_shape[1]), int(input_shape[2]))
    if not hasattr(frame, "shape"):
        return None, None
    if use_letterbox:
        prepared, meta = letterbox_frame(frame, net_w=net_w, net_h=net_h)
    else:
        prepared, meta = resize_frame(frame, net_w=net_w, net_h=net_h)
    rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB)
    tensor = np.expand_dims(rgb, axis=0).astype(np.uint8)
    if str(format_order or "").upper() == "NCHW":
        tensor = np.transpose(tensor, (0, 3, 1, 2))
    return tensor, meta


def map_model_box_to_frame(
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    frame_w: int,
    frame_h: int,
    preprocess_meta: dict[str, Any] | None,
    input_shape: tuple[int, int, int] | None,
) -> list[int] | None:
    if frame_w <= 0 or frame_h <= 0:
        return None
    meta = dict(preprocess_meta or {})
    mode = str(meta.get("mode", "")).strip().lower()
    if mode == "letterbox":
        try:
            pad_x = float(meta.get("pad_x", 0))
            pad_y = float(meta.get("pad_y", 0))
            scale = float(meta.get("scale", 0.0))
        except Exception:
            pad_x = 0.0
            pad_y = 0.0
            scale = 0.0
        if scale > 0.0:
            x1 = (x1 - pad_x) / scale
            y1 = (y1 - pad_y) / scale
            x2 = (x2 - pad_x) / scale
            y2 = (y2 - pad_y) / scale
    else:
        model_h = int((input_shape or (frame_h, frame_w, 3))[0] or frame_h)
        model_w = int((input_shape or (frame_h, frame_w, 3))[1] or frame_w)
        x1 *= float(frame_w) / float(max(1, model_w))
        x2 *= float(frame_w) / float(max(1, model_w))
        y1 *= float(frame_h) / float(max(1, model_h))
        y2 *= float(frame_h) / float(max(1, model_h))

    left = max(0, min(int(round(x1)), frame_w - 1))
    top = max(0, min(int(round(y1)), frame_h - 1))
    right = max(0, min(int(round(x2)), frame_w))
    bottom = max(0, min(int(round(y2)), frame_h))
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]
