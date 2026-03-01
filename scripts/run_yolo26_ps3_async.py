#!/usr/bin/env python3
"""Low-latency PS3 Eye + Hailo-8L YOLO26 pipeline with MJPEG streaming.

This script is intentionally standalone:
- dedicated capture thread (PS3 Eye via V4L2)
- dedicated inference thread (Hailo blocking calls isolated from capture)
- YOLO26 6-head raw decode (3 box heads + 3 class heads)
- MJPEG HTTP stream for a remote Surface/VLC viewer

Example:
    ./venv/bin/python scripts/run_yolo26_ps3_async.py \
        --hef /mnt/didier_ssd/didier/models/hailo/yolo26n.hef \
        --device /dev/video0 \
        --http-port 8090

Then open:
    http://<pi-ip>:8090/stream.mjpg
    http://<pi-ip>:8090/health
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import cv2
import numpy as np


LOGGER = logging.getLogger("yolo26.ps3.async")


def _ensure_hailo_pythonpath() -> None:
    candidates = [
        "/usr/lib/python3/dist-packages",
        f"/usr/lib/python{sys.version_info.major}.{sys.version_info.minor}/dist-packages",
        "/usr/local/lib/python3/dist-packages",
        f"/usr/local/lib/python{sys.version_info.major}.{sys.version_info.minor}/dist-packages",
    ]
    for raw in candidates:
        try:
            path = Path(raw)
            if not path.exists():
                continue
            resolved = str(path.resolve())
            if resolved not in sys.path:
                sys.path.append(resolved)
        except Exception:
            continue


try:
    from hailo_platform import ConfigureParams  # type: ignore
    from hailo_platform import FormatType  # type: ignore
    from hailo_platform import HailoSchedulingAlgorithm  # type: ignore
    from hailo_platform import HailoStreamInterface  # type: ignore
    from hailo_platform import HEF  # type: ignore
    from hailo_platform import InferVStreams  # type: ignore
    from hailo_platform import InputVStreamParams  # type: ignore
    from hailo_platform import OutputVStreamParams  # type: ignore
    from hailo_platform import VDevice  # type: ignore
except ModuleNotFoundError:
    _ensure_hailo_pythonpath()
    from hailo_platform import ConfigureParams  # type: ignore
    from hailo_platform import FormatType  # type: ignore
    from hailo_platform import HailoSchedulingAlgorithm  # type: ignore
    from hailo_platform import HailoStreamInterface  # type: ignore
    from hailo_platform import HEF  # type: ignore
    from hailo_platform import InferVStreams  # type: ignore
    from hailo_platform import InputVStreamParams  # type: ignore
    from hailo_platform import OutputVStreamParams  # type: ignore
    from hailo_platform import VDevice  # type: ignore


COCO_COLORS: list[tuple[int, int, int]] = [
    (255, 99, 71),
    (46, 204, 113),
    (52, 152, 219),
    (241, 196, 15),
    (230, 126, 34),
    (231, 76, 60),
    (26, 188, 156),
    (155, 89, 182),
]


@dataclass(frozen=True)
class LetterboxMeta:
    scale: float
    pad_x: int
    pad_y: int
    net_w: int
    net_h: int
    src_w: int
    src_h: int


@dataclass(frozen=True)
class Detection:
    class_id: int
    label: str
    score: float
    bbox: tuple[int, int, int, int]


class LatestFrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_id = 0
        self._ts = 0.0

    def publish(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame.copy()
            self._frame_id += 1
            self._ts = time.time()

    def snapshot(self) -> tuple[np.ndarray | None, int, float]:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
            return frame, self._frame_id, self._ts


class SharedState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._overlay: np.ndarray | None = None
        self._metrics: dict[str, Any] = {
            "capture_fps": 0.0,
            "inference_fps": 0.0,
            "capture_ts": 0.0,
            "inference_ts": 0.0,
            "detections": [],
            "frame_size": {"width": 0, "height": 0},
            "camera_connected": False,
            "camera_error": "",
            "decode_debug": {},
            "output_shapes": {},
        }

    def update_metrics(self, **values: Any) -> None:
        with self._lock:
            self._metrics.update(values)

    def publish_overlay(self, frame: np.ndarray, *, jpeg_quality: int) -> None:
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
        )
        if not ok:
            return
        payload = encoded.tobytes()
        with self._lock:
            self._overlay = frame.copy()
            self._jpeg = payload
            self._metrics["inference_ts"] = time.time()

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            metrics = dict(self._metrics)
            if isinstance(metrics.get("frame_size"), dict):
                metrics["frame_size"] = dict(metrics["frame_size"])
            if isinstance(metrics.get("decode_debug"), dict):
                metrics["decode_debug"] = json.loads(json.dumps(metrics["decode_debug"]))
            if isinstance(metrics.get("output_shapes"), dict):
                metrics["output_shapes"] = json.loads(json.dumps(metrics["output_shapes"]))
            metrics["stream_ready"] = self._jpeg is not None
            return metrics


def load_labels(path: Path) -> list[str]:
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    return [line.strip() for line in lines if line.strip()]


def letterbox_bgr(frame: np.ndarray, net_w: int, net_h: int) -> tuple[np.ndarray, LetterboxMeta]:
    src_h, src_w = frame.shape[:2]
    scale = min(float(net_w) / float(max(1, src_w)), float(net_h) / float(max(1, src_h)))
    resized_w = max(1, int(round(src_w * scale)))
    resized_h = max(1, int(round(src_h * scale)))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((net_h, net_w, 3), dtype=np.uint8)
    pad_x = max(0, (net_w - resized_w) // 2)
    pad_y = max(0, (net_h - resized_h) // 2)
    canvas[pad_y : pad_y + resized_h, pad_x : pad_x + resized_w] = resized
    return canvas, LetterboxMeta(
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
        net_w=net_w,
        net_h=net_h,
        src_w=src_w,
        src_h=src_h,
    )


def clip_box(x1: float, y1: float, x2: float, y2: float, width: int, height: int) -> tuple[int, int, int, int] | None:
    left = max(0, min(int(round(x1)), width - 1))
    top = max(0, min(int(round(y1)), height - 1))
    right = max(0, min(int(round(x2)), width))
    bottom = max(0, min(int(round(y2)), height))
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def map_box_to_source(box: tuple[float, float, float, float], meta: LetterboxMeta) -> tuple[int, int, int, int] | None:
    x1, y1, x2, y2 = box
    x1 = (x1 - float(meta.pad_x)) / max(meta.scale, 1e-6)
    y1 = (y1 - float(meta.pad_y)) / max(meta.scale, 1e-6)
    x2 = (x2 - float(meta.pad_x)) / max(meta.scale, 1e-6)
    y2 = (y2 - float(meta.pad_y)) / max(meta.scale, 1e-6)
    return clip_box(x1, y1, x2, y2, meta.src_w, meta.src_h)


class Yolo26Decoder:
    def __init__(
        self,
        *,
        score_threshold: float,
        nms_threshold: float,
        max_detections: int,
        labels: list[str],
    ) -> None:
        self.score_threshold = max(0.01, min(float(score_threshold), 0.99))
        self.nms_threshold = max(0.05, min(float(nms_threshold), 0.99))
        self.max_detections = max(1, int(max_detections))
        self.labels = list(labels)
        self.last_debug: dict[str, Any] = {}

    def _sigmoid(self, values: np.ndarray) -> np.ndarray:
        clipped = np.clip(values, -30.0, 30.0)
        return 1.0 / (1.0 + np.exp(-clipped))

    def _normalize_spatial_head(self, tensor: Any) -> np.ndarray | None:
        try:
            arr = np.asarray(tensor)
        except Exception:
            return None
        while arr.ndim > 3 and int(arr.shape[0]) == 1:
            arr = arr[0]
        if arr.ndim != 3:
            return None
        if int(arr.shape[-1]) in {4, 80}:
            return np.asarray(arr, dtype=np.float32)
        if int(arr.shape[0]) in {4, 80}:
            return np.asarray(np.moveaxis(arr, 0, -1), dtype=np.float32)
        return None

    def _apply_class_aware_nms(self, detections: list[Detection]) -> list[Detection]:
        grouped: dict[int, list[Detection]] = {}
        for det in detections:
            grouped.setdefault(det.class_id, []).append(det)
        filtered: list[Detection] = []
        for group in grouped.values():
            if len(group) <= 1:
                filtered.extend(group)
                continue
            boxes = [list(det.bbox) for det in group]
            scores = [float(det.score) for det in group]
            try:
                keep = cv2.dnn.NMSBoxes(
                    boxes,
                    scores,
                    float(self.score_threshold),
                    float(self.nms_threshold),
                )
            except Exception:
                filtered.extend(group)
                continue
            if keep is None:
                continue
            kept_ids: set[int] = set()
            for item in keep:
                if isinstance(item, (list, tuple, np.ndarray)):
                    if len(item) > 0:
                        kept_ids.add(int(item[0]))
                else:
                    kept_ids.add(int(item))
            for idx, det in enumerate(group):
                if idx in kept_ids:
                    filtered.append(det)
        filtered.sort(key=lambda item: item.score, reverse=True)
        return filtered[: self.max_detections]

    def decode(
        self,
        outputs: dict[str, Any],
        *,
        meta: LetterboxMeta,
        model_w: int,
        model_h: int,
    ) -> list[Detection]:
        heads: dict[tuple[int, int], dict[str, tuple[str, np.ndarray]]] = {}
        output_shapes: dict[str, Any] = {}
        for key, tensor in outputs.items():
            try:
                output_shapes[str(key)] = list(np.asarray(tensor).shape)
            except Exception:
                output_shapes[str(key)] = "unknown"
            arr = self._normalize_spatial_head(tensor)
            if arr is None:
                continue
            grid_h, grid_w, channels = (int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2]))
            slot = heads.setdefault((grid_h, grid_w), {})
            if channels == 4 and "box" not in slot:
                slot["box"] = (str(key), arr)
            elif channels >= 80 and "cls" not in slot:
                slot["cls"] = (str(key), arr)

        detections: list[Detection] = []
        head_debug: list[dict[str, Any]] = []
        for (grid_h, grid_w), slot in sorted(heads.items(), key=lambda item: item[0][0], reverse=True):
            if "box" not in slot or "cls" not in slot:
                continue
            box_name, box_arr = slot["box"]
            cls_name, cls_arr = slot["cls"]
            boxes = np.asarray(box_arr, dtype=np.float32).reshape(-1, 4)
            logits = np.asarray(cls_arr, dtype=np.float32).reshape(-1, int(cls_arr.shape[-1]))
            class_ids = np.argmax(logits, axis=1).astype(np.int32)
            raw_scores = logits[np.arange(int(logits.shape[0])), class_ids]
            if float(np.min(logits)) < 0.0 or float(np.max(logits)) > 1.0:
                scores = self._sigmoid(raw_scores)
                score_mode = "sigmoid_logits"
            else:
                scores = np.clip(raw_scores, 0.0, 1.0)
                score_mode = "probabilities"

            preview: list[dict[str, Any]] = []
            preview_count = min(3, int(scores.size))
            if preview_count > 0:
                preview_start = max(0, int(scores.size) - preview_count)
                preview_idx = np.argpartition(scores, preview_start)[preview_start:]
                preview_idx = preview_idx[np.argsort(scores[preview_idx])[::-1]]
                for idx in preview_idx:
                    preview.append(
                        {
                            "grid_xy": [int(idx % max(1, grid_w)), int(idx // max(1, grid_w))],
                            "class_id": int(class_ids[idx]),
                            "score": round(float(scores[idx]), 4),
                            "box_raw": [round(float(v), 4) for v in boxes[idx][:4]],
                        }
                    )

            keep_idx = np.flatnonzero(scores >= self.score_threshold)
            stride_x = float(model_w) / float(max(1, grid_w))
            stride_y = float(model_h) / float(max(1, grid_h))
            head_debug.append(
                {
                    "grid": [grid_w, grid_h],
                    "stride": [round(stride_x, 3), round(stride_y, 3)],
                    "box_head": box_name,
                    "cls_head": cls_name,
                    "score_mode": score_mode,
                    "candidates": int(logits.shape[0]),
                    "above_threshold": int(keep_idx.size),
                    "score_range": [
                        round(float(np.min(scores)), 4),
                        round(float(np.max(scores)), 4),
                    ],
                    "box_range": [
                        round(float(np.min(boxes)), 4),
                        round(float(np.max(boxes)), 4),
                    ],
                    "top_candidates": preview,
                }
            )
            if keep_idx.size == 0:
                continue

            grid_y = (keep_idx // max(1, grid_w)).astype(np.float32)
            grid_x = (keep_idx % max(1, grid_w)).astype(np.float32)
            ltrb = np.maximum(boxes[keep_idx], 0.0)
            anchor_x = grid_x + 0.5
            anchor_y = grid_y + 0.5
            x1 = (anchor_x - ltrb[:, 0]) * stride_x
            y1 = (anchor_y - ltrb[:, 1]) * stride_y
            x2 = (anchor_x + ltrb[:, 2]) * stride_x
            y2 = (anchor_y + ltrb[:, 3]) * stride_y
            x1 = np.clip(x1, 0.0, float(model_w - 1))
            y1 = np.clip(y1, 0.0, float(model_h - 1))
            x2 = np.clip(x2, 0.0, float(model_w))
            y2 = np.clip(y2, 0.0, float(model_h))

            for pos, idx in enumerate(keep_idx):
                mapped = map_box_to_source(
                    (float(x1[pos]), float(y1[pos]), float(x2[pos]), float(y2[pos])),
                    meta,
                )
                if mapped is None:
                    continue
                class_id = int(class_ids[idx])
                label = self.labels[class_id] if 0 <= class_id < len(self.labels) else f"class_{class_id}"
                detections.append(
                    Detection(
                        class_id=class_id,
                        label=label,
                        score=float(scores[idx]),
                        bbox=mapped,
                    )
                )

        filtered = self._apply_class_aware_nms(detections)
        self.last_debug = {
            "decode_path": "yolo26_raw_head_pairs",
            "score_threshold": round(float(self.score_threshold), 4),
            "raw_detections": int(len(detections)),
            "nms_kept": int(len(filtered)),
            "head_pairs": head_debug,
            "output_shapes": output_shapes,
        }
        return filtered


class HailoAsyncDetector:
    def __init__(
        self,
        *,
        hef_path: Path,
        labels_path: Path,
        score_threshold: float,
        nms_threshold: float,
        max_detections: int,
    ) -> None:
        if not hef_path.exists():
            raise FileNotFoundError(f"HEF not found: {hef_path}")
        self.hef_path = hef_path
        self._hef = HEF(str(hef_path))
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
        self._device = VDevice(params)
        configure_params = ConfigureParams.create_from_hef(
            self._hef,
            interface=HailoStreamInterface.PCIe,
        )
        network_groups = self._device.configure(self._hef, configure_params)
        if not network_groups:
            raise RuntimeError("No Hailo network group created")
        self._network_group = network_groups[0]
        self._input_info = self._hef.get_input_vstream_infos()[0]
        self._output_infos = self._hef.get_output_vstream_infos()
        self._input_name = getattr(self._input_info, "name", None)
        self._input_shape = self._extract_input_shape(self._input_info)
        if self._input_shape is None:
            raise RuntimeError("Unable to resolve model input shape")
        self._input_params = InputVStreamParams.make_from_network_group(
            self._network_group,
            quantized=False,
            format_type=FormatType.UINT8,
        )
        self._output_params = OutputVStreamParams.make_from_network_group(
            self._network_group,
            quantized=False,
            format_type=FormatType.FLOAT32,
        )
        labels = load_labels(labels_path)
        self._decoder = Yolo26Decoder(
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            max_detections=max_detections,
            labels=labels,
        )
        self._output_shapes_logged = False

    @property
    def model_size(self) -> tuple[int, int]:
        h, w, _ = self._input_shape
        return int(w), int(h)

    def _extract_input_shape(self, info: Any) -> tuple[int, int, int] | None:
        shape = getattr(info, "shape", None)
        if shape is None and hasattr(info, "get_shape"):
            shape = info.get_shape()
        if not shape:
            return None
        shape = tuple(int(x) for x in shape)
        if len(shape) == 4:
            _, h, w, c = shape
        elif len(shape) == 3:
            h, w, c = shape
        else:
            return None
        return (h, w, c)

    def _infer_format_order(self) -> str | None:
        fmt = getattr(self._input_info, "format", None)
        if fmt is None:
            return None
        order = getattr(fmt, "order", None)
        if order is None:
            order = getattr(fmt, "format_order", None)
        if order is None:
            return None
        order_str = str(order).upper()
        if "NCHW" in order_str:
            return "NCHW"
        if "NHWC" in order_str:
            return "NHWC"
        return None

    def prepare_input(self, frame: np.ndarray) -> tuple[dict[str, np.ndarray] | np.ndarray, LetterboxMeta]:
        model_w, model_h = self.model_size
        letterboxed, meta = letterbox_bgr(frame, model_w, model_h)
        rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
        tensor = np.expand_dims(rgb, axis=0).astype(np.uint8)
        if self._infer_format_order() == "NCHW":
            tensor = np.transpose(tensor, (0, 3, 1, 2))
        payload: dict[str, np.ndarray] | np.ndarray
        if self._input_name:
            payload = {self._input_name: tensor}
        else:
            payload = tensor
        return payload, meta

    def infer_loop(
        self,
        *,
        stop_event: threading.Event,
        frames: LatestFrameStore,
        state: SharedState,
        jpeg_quality: int,
        overlay_enabled: bool,
        idle_sleep_s: float,
    ) -> None:
        last_frame_id = 0
        last_infer_started = 0.0
        infer_fps = 0.0
        with InferVStreams(self._network_group, self._input_params, self._output_params) as infer:
            while not stop_event.is_set():
                frame, frame_id, frame_ts = frames.snapshot()
                if frame is None or frame_id == 0:
                    time.sleep(idle_sleep_s)
                    continue
                if frame_id == last_frame_id:
                    time.sleep(idle_sleep_s)
                    continue
                last_frame_id = frame_id
                started = time.perf_counter()
                try:
                    inputs, meta = self.prepare_input(frame)
                    outputs = infer.infer(inputs)
                    detections = self._decoder.decode(
                        outputs if isinstance(outputs, dict) else {},
                        meta=meta,
                        model_w=self.model_size[0],
                        model_h=self.model_size[1],
                    )
                    overlay = draw_overlay(frame, detections) if overlay_enabled else frame
                    state.publish_overlay(overlay, jpeg_quality=jpeg_quality)
                    state.update_metrics(
                        detections=[d.__dict__ for d in detections],
                        frame_size={"width": int(frame.shape[1]), "height": int(frame.shape[0])},
                        decode_debug=self._decoder.last_debug,
                        output_shapes=self._decoder.last_debug.get("output_shapes", {}),
                    )
                except Exception as exc:
                    LOGGER.exception("Inference failed")
                    state.update_metrics(camera_error=f"inference_error:{exc}")
                    time.sleep(0.05)
                    continue
                elapsed = max(1e-6, time.perf_counter() - started)
                if last_infer_started > 0.0:
                    interval = max(1e-6, started - last_infer_started)
                    current_fps = 1.0 / interval
                    infer_fps = current_fps if infer_fps <= 0.0 else (infer_fps * 0.85) + (current_fps * 0.15)
                last_infer_started = started
                state.update_metrics(
                    inference_latency_ms=round(elapsed * 1000.0, 2),
                    inference_fps=round(infer_fps, 2),
                    capture_ts=frame_ts,
                )


def draw_overlay(frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
    canvas = frame.copy()
    for det in detections:
        x, y, w, h = det.bbox
        color = COCO_COLORS[det.class_id % len(COCO_COLORS)]
        cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 2)
        label = f"{det.label} {det.score:.2f}"
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        top = max(0, y - th - baseline - 6)
        right = min(canvas.shape[1], x + tw + 8)
        cv2.rectangle(canvas, (x, top), (right, y), color, -1)
        cv2.putText(
            canvas,
            label,
            (x + 4, max(th + 2, y - baseline - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (12, 12, 12),
            2,
            cv2.LINE_AA,
        )
    return canvas


class CaptureWorker:
    def __init__(
        self,
        *,
        device: str,
        width: int,
        height: int,
        fps: int,
        store: LatestFrameStore,
        state: SharedState,
        stop_event: threading.Event,
    ) -> None:
        self.device = device
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.store = store
        self.state = state
        self.stop_event = stop_event
        self._thread = threading.Thread(target=self._run, daemon=True, name="capture")

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def _open_camera(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        cap.set(cv2.CAP_PROP_FPS, float(self.fps))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
        try:
            cap.set(cv2.CAP_PROP_FOURCC, float(cv2.VideoWriter_fourcc(*"MJPG")))
        except Exception:
            pass
        return cap

    def _run(self) -> None:
        cap: cv2.VideoCapture | None = None
        frame_counter = 0
        window_started = time.time()
        while not self.stop_event.is_set():
            if cap is None or not cap.isOpened():
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                cap = self._open_camera()
                if not cap.isOpened():
                    self.state.update_metrics(
                        camera_connected=False,
                        camera_error=f"camera_open_failed:{self.device}",
                    )
                    time.sleep(0.5)
                    continue
                LOGGER.info(
                    "Camera connected: %s (%sx%s @ %sfps target)",
                    self.device,
                    self.width,
                    self.height,
                    self.fps,
                )
                self.state.update_metrics(
                    camera_connected=True,
                    camera_error="",
                )

            ok, frame = cap.read()
            if not ok or frame is None:
                self.state.update_metrics(
                    camera_connected=False,
                    camera_error="camera_read_failed",
                )
                try:
                    cap.release()
                except Exception:
                    pass
                cap = None
                time.sleep(0.2)
                continue

            self.store.publish(frame)
            frame_counter += 1
            now = time.time()
            elapsed = now - window_started
            if elapsed >= 1.0:
                capture_fps = float(frame_counter) / max(elapsed, 1e-6)
                self.state.update_metrics(
                    capture_fps=round(capture_fps, 2),
                    camera_connected=True,
                    camera_error="",
                )
                frame_counter = 0
                window_started = now

        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


class StreamHandler(BaseHTTPRequestHandler):
    server: "StreamServer"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        LOGGER.debug("http %s - %s", self.client_address[0], format % args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/index.html"}:
            self._serve_index()
            return
        if self.path == "/health":
            self._serve_json(self.server.state.snapshot())
            return
        if self.path == "/frame.jpg":
            jpeg = self.server.state.latest_jpeg()
            if not jpeg:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "frame not ready")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)
            return
        if self.path == "/stream.mjpg":
            self._serve_stream()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def _serve_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_index(self) -> None:
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>YOLO26 PS3 Stream</title></head><body>"
            "<h1>YOLO26 PS3 Stream</h1>"
            "<p><a href='/stream.mjpg'>MJPEG stream</a></p>"
            "<p><a href='/health'>Health</a></p>"
            "<img src='/stream.mjpg' style='max-width:100%;height:auto' />"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_stream(self) -> None:
        boundary = b"--frame"
        self.send_response(HTTPStatus.OK)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        last_payload: bytes | None = None
        try:
            while not self.server.stop_event.is_set():
                jpeg = self.server.state.latest_jpeg()
                if jpeg is None:
                    time.sleep(0.03)
                    continue
                if jpeg == last_payload:
                    time.sleep(0.01)
                    continue
                last_payload = jpeg
                self.wfile.write(boundary + b"\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            return


class StreamServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], state: SharedState, stop_event: threading.Event):
        super().__init__(addr, StreamHandler)
        self.state = state
        self.stop_event = stop_event


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PS3 Eye + Hailo-8L YOLO26 async MJPEG pipeline")
    parser.add_argument(
        "--hef",
        default="/mnt/didier_ssd/didier/models/hailo/yolo26n.hef",
        help="Path to the compiled HEF",
    )
    parser.add_argument(
        "--device",
        default="/dev/video0",
        help="V4L2 camera device path",
    )
    parser.add_argument(
        "--labels",
        default="models/vision/coco.names",
        help="COCO labels path",
    )
    parser.add_argument("--width", type=int, default=640, help="Capture width")
    parser.add_argument("--height", type=int, default=480, help="Capture height")
    parser.add_argument("--fps", type=int, default=60, help="Capture target FPS")
    parser.add_argument("--score-threshold", type=float, default=0.45, help="Confidence threshold")
    parser.add_argument("--nms-threshold", type=float, default=0.45, help="NMS IoU threshold")
    parser.add_argument("--max-detections", type=int, default=64, help="Maximum output detections")
    parser.add_argument("--http-host", default="0.0.0.0", help="MJPEG HTTP bind host")
    parser.add_argument("--http-port", type=int, default=8090, help="MJPEG HTTP bind port")
    parser.add_argument("--jpeg-quality", type=int, default=80, help="JPEG quality for MJPEG")
    parser.add_argument(
        "--no-overlay",
        action="store_true",
        help="Stream raw frames without drawing detections",
    )
    parser.add_argument(
        "--idle-sleep-ms",
        type=float,
        default=2.0,
        help="Sleep used while waiting for a new frame",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging level",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stop_event = threading.Event()
    frames = LatestFrameStore()
    state = SharedState()
    server_holder: dict[str, StreamServer] = {}

    def _request_stop(signum: int, _frame: Any) -> None:
        LOGGER.info("Signal %s received, shutting down", signum)
        stop_event.set()
        server = server_holder.get("server")
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True, name="http-shutdown").start()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    detector = HailoAsyncDetector(
        hef_path=Path(args.hef),
        labels_path=Path(args.labels),
        score_threshold=float(args.score_threshold),
        nms_threshold=float(args.nms_threshold),
        max_detections=int(args.max_detections),
    )
    capture = CaptureWorker(
        device=str(args.device),
        width=int(args.width),
        height=int(args.height),
        fps=int(args.fps),
        store=frames,
        state=state,
        stop_event=stop_event,
    )
    capture.start()

    infer_thread = threading.Thread(
        target=detector.infer_loop,
        kwargs={
            "stop_event": stop_event,
            "frames": frames,
            "state": state,
            "jpeg_quality": int(args.jpeg_quality),
            "overlay_enabled": not bool(args.no_overlay),
            "idle_sleep_s": max(0.0005, float(args.idle_sleep_ms) / 1000.0),
        },
        daemon=True,
        name="inference",
    )
    infer_thread.start()

    server = StreamServer((str(args.http_host), int(args.http_port)), state, stop_event)
    server_holder["server"] = server
    server_thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.2},
        daemon=True,
        name="http-server",
    )
    server_thread.start()
    LOGGER.info(
        "MJPEG stream ready on http://%s:%s/stream.mjpg",
        args.http_host,
        args.http_port,
    )
    try:
        while not stop_event.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)
        capture.join(timeout=2.0)
        infer_thread.join(timeout=2.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
