"""Compatibility shim for legacy imports + optional Hailo dashboard overlay.

The active API lives in ``core.api`` and is imported here as ``app``.
This module keeps backward-compatibility for historical code paths while adding
an optional non-blocking Hailo detection loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from fastapi import Request
from fastapi.responses import HTMLResponse, Response

from audio_service import AudioService
from core.api import app
from core.hailo.monitor import detect_hailo

LOGGER = logging.getLogger("Didier.Hailo")

STATE_LOCK = threading.Lock()
STATE: dict[str, Any] = {
    "detections": [],
    "visible_objects": [],
    "npu_fps": 0.0,
    "consecutive_person_frames": 0,
    "backend": "disabled",
    "vision_enabled": False,
    "vision_reason": "not_started",
    "last_update": 0.0,
}


def _state_snapshot() -> dict[str, Any]:
    with STATE_LOCK:
        return {
            "detections": list(STATE.get("detections", [])),
            "visible_objects": list(STATE.get("visible_objects", [])),
            "npu_fps": float(STATE.get("npu_fps", 0.0) or 0.0),
            "consecutive_person_frames": int(
                STATE.get("consecutive_person_frames", 0) or 0
            ),
            "backend": str(STATE.get("backend", "disabled")),
            "vision_enabled": bool(STATE.get("vision_enabled", False)),
            "vision_reason": str(STATE.get("vision_reason", "")),
            "last_update": float(STATE.get("last_update", 0.0) or 0.0),
        }


def _state_update(**values: Any) -> None:
    with STATE_LOCK:
        STATE.update(values)


def _looks_like_person(label: str, class_id: Any) -> bool:
    normalized = str(label or "").strip().lower()
    if normalized in {"person", "personne", "human", "humain"}:
        return True
    try:
        return int(class_id) == 0
    except Exception:
        return False


class HailoDetector:
    """Passive threaded detector that publishes state to STATE.

    Notes:
    - No event-loop work in the detection loop.
    - If Hailo or model is missing, detector stays disabled and API remains up.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        confidence_threshold: float = 0.6,
        target_fps: float = 15.0,
    ) -> None:
        self._threshold = max(0.0, min(float(confidence_threshold), 1.0))
        self._target_fps = max(1.0, float(target_fps))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._infer: Callable[[Any], Any] | None = None
        self._backend = "disabled"
        self._model_path = self._resolve_model_path(model_path)
        self._fps_ema = 0.0
        self._person_streak = 0
        self._alert_emitted = False
        self._polygon_refine = os.getenv("DIDIER_VISION_POLYGON_REFINE", "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            self._polygon_refine_max = max(
                0,
                min(int(os.getenv("DIDIER_VISION_POLYGON_REFINE_MAX", "3")), 12),
            )
        except Exception:
            self._polygon_refine_max = 3
        try:
            self._polygon_refine_epsilon = max(
                0.005,
                min(float(os.getenv("DIDIER_VISION_POLYGON_REFINE_EPSILON", "0.02")), 0.2),
            )
        except Exception:
            self._polygon_refine_epsilon = 0.02
        try:
            self._polygon_refine_min_area = max(
                80,
                min(int(os.getenv("DIDIER_VISION_POLYGON_REFINE_MIN_AREA", "120")), 50000),
            )
        except Exception:
            self._polygon_refine_min_area = 120
        try:
            self._model_input_width = max(
                32,
                min(int(os.getenv("DIDIER_HAILO_INPUT_WIDTH", "640")), 4096),
            )
        except Exception:
            self._model_input_width = 640
        try:
            self._model_input_height = max(
                32,
                min(int(os.getenv("DIDIER_HAILO_INPUT_HEIGHT", "640")), 4096),
            )
        except Exception:
            self._model_input_height = 640
        self._init_backend()

    @property
    def enabled(self) -> bool:
        return self._infer is not None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _resolve_model_path(self, model_path: str | Path | None) -> Path | None:
        candidates = []
        if model_path:
            candidates.append(Path(model_path))
        candidates.extend(
            [
                Path("models/hailo/yolo26n.hef"),
                Path("/mnt/didier_ssd/didier/models/hailo/yolo26n.hef"),
                Path("models/hailo/yolov8s_hailo8l.hef"),
                Path("/mnt/didier_ssd/didier/models/hailo/yolov8s_hailo8l.hef"),
                Path("models/hailo/hailo_model.hef"),
                Path("/mnt/didier_ssd/didier/models/hailo/hailo_model.hef"),
            ]
        )
        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate.resolve()
            except Exception:
                continue
        return None

    def _init_backend(self) -> None:
        if not detect_hailo():
            reason = "hailo_not_detected"
            _state_update(
                vision_enabled=False,
                vision_reason=reason,
                backend="disabled",
                detections=[],
                visible_objects=[],
                npu_fps=0.0,
                consecutive_person_frames=0,
                last_update=time.time(),
            )
            LOGGER.warning("Hailo unavailable at startup, vision disabled.")
            return

        if self._model_path is None:
            reason = "hef_not_found(yolo26n.hef)"
            _state_update(
                vision_enabled=False,
                vision_reason=reason,
                backend="disabled",
                detections=[],
                visible_objects=[],
                npu_fps=0.0,
                consecutive_person_frames=0,
                last_update=time.time(),
            )
            LOGGER.warning("Hailo model missing, vision disabled.")
            return

        # .hef load section:
        # We first try hailo_python_api (requested integration path), then fallback
        # to the existing project detector for stability if API signatures differ.
        infer_fn, backend_name = self._try_hailo_python_api(self._model_path)
        if infer_fn is None:
            infer_fn, backend_name = self._try_legacy_hailo_backend(self._model_path)

        if infer_fn is None:
            reason = "hailo_backend_init_failed"
            _state_update(
                vision_enabled=False,
                vision_reason=reason,
                backend="disabled",
                detections=[],
                visible_objects=[],
                npu_fps=0.0,
                consecutive_person_frames=0,
                last_update=time.time(),
            )
            LOGGER.warning("No usable Hailo backend, vision disabled.")
            return

        self._infer = infer_fn
        self._backend = backend_name
        _state_update(
            vision_enabled=True,
            vision_reason="ok",
            backend=backend_name,
            last_update=time.time(),
        )
        LOGGER.info("Hailo detector ready (%s, model=%s).", backend_name, self._model_path)

    def _try_hailo_python_api(
        self, model_path: Path
    ) -> tuple[Callable[[Any], Any] | None, str]:
        try:
            import hailo_python_api as hapi  # type: ignore
        except Exception as exc:
            LOGGER.info("hailo_python_api unavailable: %s", exc)
            return None, "disabled"

        candidates = [
            "HailoDetector",
            "Detector",
            "InferenceRunner",
            "InferenceModel",
        ]
        for name in candidates:
            cls = getattr(hapi, name, None)
            if cls is None:
                continue
            try:
                instance = cls(str(model_path))
            except TypeError:
                try:
                    instance = cls(model=str(model_path))
                except Exception:
                    continue
            except Exception:
                continue

            infer = getattr(instance, "infer", None) or getattr(instance, "predict", None)
            if callable(infer):
                return infer, "hailo_python_api"
        LOGGER.warning("hailo_python_api imported but no supported inference class found.")
        return None, "disabled"

    def _try_legacy_hailo_backend(
        self, model_path: Path
    ) -> tuple[Callable[[Any], Any] | None, str]:
        try:
            from tentacles.vision import HailoDetector as LegacyHailoDetector

            detector = LegacyHailoDetector(
                model_path=model_path,
                logger=LOGGER,
                score_threshold=self._threshold,
            )
            if not bool(getattr(detector, "ready", False)):
                return None, "disabled"
            return detector.detect, "hailo_platform_legacy"
        except Exception:
            LOGGER.exception("Legacy Hailo backend init failed.")
            return None, "disabled"

    def _run_loop(self) -> None:
        interval = 1.0 / self._target_fps
        while not self._stop_event.is_set():
            started = time.monotonic()
            if self._infer is None:
                self._sleep_remaining(started, interval)
                continue
            frame = self._read_latest_frame()
            if frame is None:
                self._sleep_remaining(started, interval)
                continue

            try:
                raw = self._infer(frame)
            except Exception:
                LOGGER.exception("Hailo inference error.")
                self._sleep_remaining(started, interval)
                continue

            detections = self._normalize_and_filter(raw, frame)
            self._update_person_streak(detections)
            self._update_fps(started)
            visible = sorted(
                {
                    str(item.get("label", "")).strip()
                    for item in detections
                    if str(item.get("label", "")).strip()
                }
            )
            _state_update(
                detections=detections,
                visible_objects=visible,
                npu_fps=round(self._fps_ema, 2),
                consecutive_person_frames=self._person_streak,
                backend=self._backend,
                vision_enabled=True,
                vision_reason="ok",
                last_update=time.time(),
            )
            self._sleep_remaining(started, interval)

    def _sleep_remaining(self, started_monotonic: float, interval: float) -> None:
        elapsed = max(0.0, time.monotonic() - started_monotonic)
        remaining = max(0.01, interval - elapsed)
        self._stop_event.wait(remaining)

    def _update_fps(self, started_monotonic: float) -> None:
        elapsed = max(1e-6, time.monotonic() - started_monotonic)
        instant = 1.0 / elapsed
        if self._fps_ema <= 0.0:
            self._fps_ema = instant
            return
        self._fps_ema = (0.85 * self._fps_ema) + (0.15 * instant)

    def _read_latest_frame(self) -> Any | None:
        try:
            from core import api as api_runtime

            orchestrator = getattr(api_runtime, "_orchestrator", None)
            ready = bool(getattr(api_runtime, "_orchestrator_ready", False))
            if not ready or orchestrator is None:
                return None
            vision = orchestrator.get_tentacle("vision")
            if not vision or not hasattr(vision, "get_latest_jpeg"):
                return None
            jpeg_bytes = vision.get_latest_jpeg()
            if not jpeg_bytes:
                return None
            frame = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
            return frame
        except Exception:
            return None

    def _normalize_and_filter(self, raw: Any, frame: Any | None = None) -> list[dict[str, Any]]:
        direct = self._decode_yolo26_outputs(raw, frame)
        if direct is not None:
            return direct

        items: list[Any]
        if isinstance(raw, dict):
            maybe = raw.get("detections")
            items = maybe if isinstance(maybe, list) else []
        elif isinstance(raw, list):
            items = raw
        elif isinstance(raw, tuple):
            items = list(raw)
        else:
            items = []

        filtered: list[dict[str, Any]] = []
        refined = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            label = (
                item.get("label")
                or item.get("class_name")
                or item.get("name")
                or item.get("category")
                or "object"
            )
            score_raw = item.get("score", item.get("confidence", item.get("probability", 0.0)))
            try:
                score = float(score_raw)
            except Exception:
                score = 0.0
            if score <= self._threshold:
                continue
            det: dict[str, Any] = {
                "label": str(label),
                "score": round(score, 4),
                "confidence": round(score, 4),
                "bbox": item.get("bbox"),
                "class_id": item.get("class_id"),
            }
            raw_poly = item.get("poly")
            if isinstance(raw_poly, list) and len(raw_poly) >= 3:
                poly = self._normalize_polygon(raw_poly)
                if poly:
                    det["poly"] = poly
            if "poly" not in det and frame is not None and self._polygon_refine and refined < self._polygon_refine_max:
                if self._refine_polygon(frame, det):
                    refined += 1
            self._ensure_polygon(det)
            if isinstance(det.get("poly"), list) and len(det.get("poly", [])) >= 3:
                det["shape"] = self._shape_from_polygon(det["poly"])
            if not det.get("bbox") and not det.get("poly"):
                continue
            filtered.append(det)
        return filtered

    def _decode_yolo26_outputs(
        self,
        raw: Any,
        frame: Any | None,
    ) -> list[dict[str, Any]] | None:
        if frame is None:
            return None
        if isinstance(raw, dict) and isinstance(raw.get("detections"), list):
            return None
        if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], dict):
            return None

        structured = self._decode_yolo26_structured(raw, frame)
        if structured is not None:
            return structured

        rows = self._coerce_yolo26_rows(raw)
        if rows is None:
            return None
        return self._yolo26_rows_to_detections(rows, frame)

    def _decode_yolo26_structured(
        self,
        raw: Any,
        frame: Any,
    ) -> list[dict[str, Any]] | None:
        if not isinstance(raw, dict):
            return None

        boxes = raw.get("boxes")
        if boxes is None:
            boxes = raw.get("bboxes")
        if boxes is None:
            boxes = raw.get("bbox")
        scores = raw.get("scores")
        if scores is None:
            scores = raw.get("confidences")
        if scores is None:
            scores = raw.get("confidence")
        classes = raw.get("classes")
        if classes is None:
            classes = raw.get("class_ids")
        labels = raw.get("labels")

        if boxes is None or scores is None:
            return None

        try:
            boxes_arr = np.asarray(boxes)
            scores_arr = np.asarray(scores).reshape(-1)
            classes_arr = None if classes is None else np.asarray(classes).reshape(-1)
            labels_arr = None if labels is None else np.asarray(labels).reshape(-1)
        except Exception:
            return None

        while boxes_arr.ndim > 2 and boxes_arr.shape[0] == 1:
            boxes_arr = boxes_arr[0]
        if boxes_arr.ndim != 2 or boxes_arr.shape[1] < 4:
            return None

        count = min(int(boxes_arr.shape[0]), int(scores_arr.size))
        if classes_arr is not None:
            count = min(count, int(classes_arr.size))
        if labels_arr is not None:
            count = min(count, int(labels_arr.size))
        if count <= 0:
            return []

        filtered: list[dict[str, Any]] = []
        refined = 0
        for idx in range(count):
            try:
                score = float(scores_arr[idx])
            except Exception:
                continue
            if score <= self._threshold:
                continue

            bbox = self._decode_yolo26_bbox(boxes_arr[idx], frame)
            if bbox is None:
                continue

            class_id = None
            if classes_arr is not None:
                try:
                    class_id = int(round(float(classes_arr[idx])))
                except Exception:
                    class_id = None

            label = None
            if labels_arr is not None:
                label = str(labels_arr[idx]).strip() or None

            det = self._build_detection_entry(
                label=label,
                class_id=class_id,
                score=score,
                bbox=bbox,
                frame=frame,
                refined_count=refined,
            )
            if det is None:
                continue
            if bool(det.pop("_refined_poly", False)):
                refined += 1
            filtered.append(det)
        return filtered

    def _coerce_yolo26_rows(self, raw: Any) -> np.ndarray | None:
        candidate: Any = None
        if isinstance(raw, np.ndarray):
            candidate = raw
        elif isinstance(raw, dict):
            for value in raw.values():
                if isinstance(value, np.ndarray):
                    candidate = value
                    break
        elif isinstance(raw, (list, tuple)):
            for value in raw:
                if isinstance(value, np.ndarray):
                    candidate = value
                    break
            if candidate is None and raw and all(
                isinstance(value, (list, tuple, float, int, np.floating, np.integer))
                for value in raw
            ):
                candidate = np.asarray(raw)

        if candidate is None:
            return None

        try:
            rows = np.asarray(candidate)
        except Exception:
            return None

        while rows.ndim > 2 and rows.shape[0] == 1:
            rows = rows[0]
        if rows.ndim == 1 and rows.size >= 5:
            rows = rows.reshape(1, -1)
        if rows.ndim != 2:
            return None
        if rows.shape[0] in (5, 6, 7, 8) and rows.shape[1] > rows.shape[0]:
            rows = rows.T
        if rows.shape[1] < 5:
            return None
        return rows

    def _yolo26_rows_to_detections(self, rows: np.ndarray, frame: Any) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        refined = 0
        for row in rows:
            try:
                values = np.asarray(row, dtype=np.float32).reshape(-1)
            except Exception:
                continue
            if values.size < 5:
                continue

            class_id: int | None = None
            score = 0.0
            if values.size >= 6 and self._looks_like_direct_yolo26_row(values):
                score = float(values[4])
                try:
                    class_id = int(round(float(values[5])))
                except Exception:
                    class_id = None
            else:
                class_scores = values[4:]
                if class_scores.size <= 0:
                    continue
                class_id = int(np.argmax(class_scores))
                score = float(class_scores[class_id])

            if score <= self._threshold:
                continue

            bbox = self._decode_yolo26_bbox(values[:4], frame)
            if bbox is None:
                continue

            det = self._build_detection_entry(
                label=None,
                class_id=class_id,
                score=score,
                bbox=bbox,
                frame=frame,
                refined_count=refined,
            )
            if det is None:
                continue
            if bool(det.pop("_refined_poly", False)):
                refined += 1
            filtered.append(det)
        return filtered

    def _looks_like_direct_yolo26_row(self, values: np.ndarray) -> bool:
        if values.size < 6:
            return False
        try:
            score = float(values[4])
            class_token = float(values[5])
        except Exception:
            return False
        if not np.isfinite(score) or not (0.0 <= score <= 1.0):
            return False
        if not np.isfinite(class_token) or class_token < 0.0:
            return False
        return abs(class_token - round(class_token)) <= 1e-3

    def _decode_yolo26_bbox(self, values: Any, frame: Any) -> list[int] | None:
        try:
            coords = [float(values[idx]) for idx in range(4)]
        except Exception:
            return None
        if not all(np.isfinite(coord) for coord in coords):
            return None

        frame_h, frame_w = frame.shape[:2]
        if frame_w <= 0 or frame_h <= 0:
            return None

        x1_raw, y1_raw, x2_raw, y2_raw = coords
        if x2_raw > x1_raw and y2_raw > y1_raw:
            x1, y1, x2, y2 = x1_raw, y1_raw, x2_raw, y2_raw
        else:
            cx, cy, w_raw, h_raw = coords
            if w_raw <= 0.0 or h_raw <= 0.0:
                return None
            x1 = cx - (w_raw / 2.0)
            y1 = cy - (h_raw / 2.0)
            x2 = cx + (w_raw / 2.0)
            y2 = cy + (h_raw / 2.0)

        scale_x = 1.0
        scale_y = 1.0
        coord_max = max(abs(x1), abs(y1), abs(x2), abs(y2))
        if coord_max <= 1.5:
            scale_x = float(frame_w)
            scale_y = float(frame_h)
        elif (
            max(abs(x1), abs(x2)) <= float(self._model_input_width) + 1.0
            and max(abs(y1), abs(y2)) <= float(self._model_input_height) + 1.0
        ):
            scale_x = float(frame_w) / float(max(1, self._model_input_width))
            scale_y = float(frame_h) / float(max(1, self._model_input_height))

        x1_i = int(round(max(0.0, min(float(frame_w), x1 * scale_x))))
        y1_i = int(round(max(0.0, min(float(frame_h), y1 * scale_y))))
        x2_i = int(round(max(0.0, min(float(frame_w), x2 * scale_x))))
        y2_i = int(round(max(0.0, min(float(frame_h), y2 * scale_y))))
        if x2_i <= x1_i or y2_i <= y1_i:
            return None
        return [x1_i, y1_i, x2_i - x1_i, y2_i - y1_i]

    def _build_detection_entry(
        self,
        *,
        label: str | None,
        class_id: int | None,
        score: float,
        bbox: list[int],
        frame: Any | None,
        refined_count: int,
    ) -> dict[str, Any] | None:
        det: dict[str, Any] = {
            "label": str(label or (f"class_{class_id}" if class_id is not None else "object")),
            "score": round(float(score), 4),
            "confidence": round(float(score), 4),
            "bbox": list(bbox),
            "class_id": class_id,
        }
        refined = False
        if (
            frame is not None
            and self._polygon_refine
            and refined_count < self._polygon_refine_max
        ):
            refined = bool(self._refine_polygon(frame, det))
        self._ensure_polygon(det)
        if isinstance(det.get("poly"), list) and len(det.get("poly", [])) >= 3:
            det["shape"] = self._shape_from_polygon(det["poly"])
        if refined:
            det["_refined_poly"] = True
        if not det.get("bbox") and not det.get("poly"):
            return None
        return det

    def _normalize_polygon(self, poly: list[Any]) -> list[list[int]]:
        normalized: list[list[int]] = []
        for point in poly:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                x = int(round(float(point[0])))
                y = int(round(float(point[1])))
            except Exception:
                continue
            normalized.append([x, y])
        if len(normalized) < 3:
            return []
        return normalized

    def _ensure_polygon(self, det: dict[str, Any]) -> None:
        if isinstance(det.get("poly"), list) and len(det.get("poly", [])) >= 3:
            return
        bbox = det.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            return
        try:
            x, y, w, h = (
                int(round(float(bbox[0]))),
                int(round(float(bbox[1]))),
                int(round(float(bbox[2]))),
                int(round(float(bbox[3]))),
            )
        except Exception:
            return
        if w <= 0 or h <= 0:
            return
        det["poly"] = [
            [x, y],
            [x + w, y],
            [x + w, y + h],
            [x, y + h],
        ]

    def _shape_from_polygon(self, poly: list[list[int]]) -> str:
        count = len(poly)
        if count <= 2:
            return "segment"
        if count == 3:
            return "triangle"
        if count == 4:
            return "quadrilatere"
        if count <= 7:
            return "polygone"
        return "arrondi"

    def _refine_polygon(self, frame: Any, det: dict[str, Any]) -> bool:
        bbox = det.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            return False
        try:
            x, y, w, h = (
                int(round(float(bbox[0]))),
                int(round(float(bbox[1]))),
                int(round(float(bbox[2]))),
                int(round(float(bbox[3]))),
            )
        except Exception:
            return False
        if w <= 0 or h <= 0:
            return False
        if (w * h) < self._polygon_refine_min_area:
            return False
        if not hasattr(frame, "shape"):
            return False
        frame_h, frame_w = frame.shape[:2]
        x0 = max(0, min(frame_w - 1, x))
        y0 = max(0, min(frame_h - 1, y))
        x1 = max(0, min(frame_w, x + w))
        y1 = max(0, min(frame_h, y + h))
        if x1 <= x0 or y1 <= y0:
            return False
        roi = frame[y0:y1, x0:x1]
        if roi is None or getattr(roi, "size", 0) <= 0:
            return False
        try:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (3, 3), 0)
            edges = cv2.Canny(blurred, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return False
            contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(contour) < self._polygon_refine_min_area:
                return False
            epsilon = self._polygon_refine_epsilon * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            if approx is None or len(approx) < 3:
                return False
            poly = []
            for point in approx:
                if point is None or len(point) <= 0:
                    continue
                px = int(x0 + int(point[0][0]))
                py = int(y0 + int(point[0][1]))
                poly.append([px, py])
            if len(poly) < 3:
                return False
            det["poly"] = poly
            return True
        except Exception:
            return False

    def _update_person_streak(self, detections: list[dict[str, Any]]) -> None:
        person_detected = any(
            _looks_like_person(item.get("label", ""), item.get("class_id"))
            for item in detections
        )
        if person_detected:
            self._person_streak += 1
            if self._person_streak > 3 and not self._alert_emitted:
                logging.info("DIDIER_ALERT: Human detected")
                self._alert_emitted = True
            return
        self._person_streak = 0
        self._alert_emitted = False


_HAILO_DETECTOR: HailoDetector | None = None
_MIDDLEWARE_INSTALLED = False


def _audit_report_from_state(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    visible = snapshot.get("visible_objects") or []
    fps = float(snapshot.get("npu_fps", 0.0) or 0.0)
    backend = str(snapshot.get("backend", "disabled"))
    enabled = bool(snapshot.get("vision_enabled", False))
    reason = str(snapshot.get("vision_reason", ""))
    details = ", ".join(str(item) for item in visible[:10]) if visible else "none"
    return [
        {
            "component": "Vision NPU",
            "status": "OK" if enabled else "DISABLED",
            "details": backend if enabled else reason,
        },
        {
            "component": "Visible Objects",
            "status": "OK" if visible else "IDLE",
            "details": details,
        },
        {
            "component": "NPU FPS",
            "status": "OK" if fps > 0.1 else "IDLE",
            "details": f"{fps:.2f}",
        },
    ]


async def _read_response_body(response: Response) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk)
        else:
            chunks.append(str(chunk).encode("utf-8"))
    return b"".join(chunks)


def _clone_headers_without_length(response: Response) -> dict[str, str]:
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return headers


def _patch_metrics_payload(payload: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    npu = result.get("npu")
    if not isinstance(npu, dict):
        npu = {}
    npu["real_fps"] = round(float(snapshot.get("npu_fps", 0.0) or 0.0), 2)
    npu["backend"] = snapshot.get("backend")
    npu["vision_enabled"] = bool(snapshot.get("vision_enabled", False))
    result["npu"] = npu
    result["detections"] = list(snapshot.get("detections", []))
    result["visible_objects"] = list(snapshot.get("visible_objects", []))
    return result


def _inject_audit_report_html(html: str, snapshot: dict[str, Any]) -> str:
    report = _audit_report_from_state(snapshot)
    script = (
        "<script id=\"didier-audit-report\">"
        f"window.__DIDIER_AUDIT_REPORT__ = {json.dumps(report, ensure_ascii=False)};"
        f"window.__DIDIER_VISIBLE_OBJECTS__ = {json.dumps(snapshot.get('visible_objects', []), ensure_ascii=False)};"
        "</script>"
    )
    if "id=\"didier-audit-report\"" in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", script + "</body>", 1)
    return html + script


def _install_middleware_once() -> None:
    global _MIDDLEWARE_INSTALLED
    if _MIDDLEWARE_INSTALLED:
        return

    @app.middleware("http")
    async def _hailo_overlay_middleware(request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        path = request.url.path
        if path not in {"/", "/metrics"}:
            return response
        if response.status_code >= 400:
            return response

        body = await _read_response_body(response)
        headers = _clone_headers_without_length(response)
        snapshot = _state_snapshot()

        if path == "/metrics":
            content_type = headers.get("content-type", "")
            if "application/json" not in content_type:
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=headers,
                    media_type=response.media_type,
                )
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            patched = _patch_metrics_payload(payload, snapshot)
            return Response(
                content=json.dumps(patched, ensure_ascii=False).encode("utf-8"),
                status_code=response.status_code,
                headers=headers,
                media_type="application/json",
            )

        content_type = headers.get("content-type", "")
        if "text/html" not in content_type:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
            )
        try:
            html = body.decode("utf-8", errors="replace")
            patched_html = _inject_audit_report_html(html, snapshot)
        except Exception:
            patched_html = body.decode("utf-8", errors="replace")
        return HTMLResponse(
            content=patched_html,
            status_code=response.status_code,
            headers=headers,
        )

    _MIDDLEWARE_INSTALLED = True


_install_middleware_once()


@app.on_event("startup")
async def _startup_hailo_overlay() -> None:
    global _HAILO_DETECTOR
    if _HAILO_DETECTOR is None:
        _HAILO_DETECTOR = HailoDetector()
    _HAILO_DETECTOR.start()


@app.on_event("shutdown")
async def _shutdown_hailo_overlay() -> None:
    global _HAILO_DETECTOR
    if _HAILO_DETECTOR is None:
        return
    _HAILO_DETECTOR.stop()
    _HAILO_DETECTOR = None


class AsyncAudioService:
    """Async wrapper around the singleton audio service used by legacy Flask runtime."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._service = AudioService.get_instance(config or {})
        self.queue = self._service.queue

    async def speak(self, text: str) -> None:
        await asyncio.to_thread(self._service.speak, str(text))

    async def beep(self) -> None:
        await asyncio.to_thread(self._service.beep)

    async def clear(self) -> None:
        await asyncio.to_thread(self._service.clear)


__all__ = ["app", "AsyncAudioService", "HailoDetector", "STATE"]
