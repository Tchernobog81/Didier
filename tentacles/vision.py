import argparse
import asyncio
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import sys
from pathlib import Path
from typing import Any, List

import cv2
import numpy as np

from core.config_access import npu_settings
from tentacles.base import BaseTentacle
from core.config import DidierConfig
from core.hardware_gatekeeper import HardwareLease, get_hardware_gatekeeper
from core.vision_npu_policy import vision_npu_status

DEFAULT_SUBPROCESS_TIMEOUT_S = 2.0


class HailoDetector:
    name = "hailo"

    def __init__(
        self,
        model_path: Path,
        logger: logging.Logger,
        *,
        score_threshold: float = 0.35,
        nms_threshold: float = 0.45,
        max_detections: int = 64,
    ) -> None:
        self._logger = logger
        self._model_path = model_path
        self._ready = False
        self._hef = None
        self._device = None
        self._network_group = None
        self._network_group_params = None
        self._infer_pipeline = None
        self._infer_vstreams_cls = None
        self._input_info = None
        self._output_infos = []
        self._input_shape = None
        self._input_name = None
        self._output_shapes_logged = False
        self._last_npu_load = None
        self._score_threshold = max(0.05, min(float(score_threshold), 0.95))
        self._nms_threshold = max(0.1, min(float(nms_threshold), 0.95))
        self._max_detections = max(1, int(max_detections))
        self._model_key = str(self._model_path.name).strip().lower()
        self._e2e_nms_free = "yolo26" in self._model_key
        self._init_detector()

    def _ensure_hailo_pythonpath(self) -> None:
        """Allow venv runtime to load distro-provided hailo_platform."""
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

    @property
    def ready(self) -> bool:
        return self._ready

    def _init_detector(self) -> None:
        if not self._model_path.exists():
            self._logger.warning("Hailo model not found: %s", self._model_path)
            return
        try:
            os.environ.setdefault("HAILO_MONITOR", "1")
            try:
                from hailo_platform import (  # type: ignore
                    HEF,
                    VDevice,
                    HailoStreamInterface,
                    ConfigureParams,
                    InputVStreamParams,
                    OutputVStreamParams,
                    InferVStreams,
                    FormatType,
                    HailoSchedulingAlgorithm,
                )
            except ModuleNotFoundError:
                self._ensure_hailo_pythonpath()
                from hailo_platform import (  # type: ignore
                    HEF,
                    VDevice,
                    HailoStreamInterface,
                    ConfigureParams,
                    InputVStreamParams,
                    OutputVStreamParams,
                    InferVStreams,
                    FormatType,
                    HailoSchedulingAlgorithm,
                )

            self._hef = HEF(str(self._model_path))
            params = VDevice.create_params()
            params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
            self._device = VDevice(params)
            configure_params = ConfigureParams.create_from_hef(
                self._hef, interface=HailoStreamInterface.PCIe
            )
            network_groups = self._device.configure(self._hef, configure_params)
            if not network_groups:
                self._logger.error("No Hailo network group created.")
                return
            self._network_group = network_groups[0]
            self._network_group_params = self._network_group.create_params()
            self._input_info = self._hef.get_input_vstream_infos()[0]
            self._output_infos = self._hef.get_output_vstream_infos()
            self._input_shape = self._extract_input_shape(self._input_info)
            self._input_name = getattr(self._input_info, "name", None)
            self._input_vstreams_params = InputVStreamParams.make_from_network_group(
                self._network_group, quantized=False, format_type=FormatType.UINT8
            )
            self._output_vstreams_params = OutputVStreamParams.make_from_network_group(
                self._network_group, quantized=False, format_type=FormatType.FLOAT32
            )
            self._infer_vstreams_cls = InferVStreams
            self._infer_pipeline = None
            self._ready = True
            self._logger.info(
                "Hailo detector initialized (input=%s, shape=%s).",
                self._input_name,
                self._input_shape,
            )
        except Exception:
            self._logger.exception("Failed to initialize Hailo detector.")

    def detect(self, frame: Any) -> List[dict]:
        if not self._ready:
            return []
        if (
            self._network_group is None
            or self._input_vstreams_params is None
            or self._output_vstreams_params is None
            or self._infer_vstreams_cls is None
        ):
            return []
        try:
            input_tensor = self._preprocess(frame)
            if input_tensor is None:
                return []
            inputs = {self._input_name: input_tensor} if self._input_name else input_tensor
            infer_pipeline = self._infer_vstreams_cls(
                self._network_group, self._input_vstreams_params, self._output_vstreams_params
            )
            # With scheduler mode enabled, explicit network_group.activate() is deprecated.
            with infer_pipeline as infer:
                outputs = infer.infer(inputs)
            if not self._output_shapes_logged:
                self._log_output_shapes(outputs)
                self._output_shapes_logged = True
            frame_shape = frame.shape[:2] if hasattr(frame, "shape") else None
            return self._postprocess(outputs, frame_shape)
        except Exception:
            self._logger.exception("Hailo inference failed.")
            return []

    def read_npu_load(self) -> int | None:
        if shutil.which("hailortcli") is None:
            return None
        try:
            result = subprocess.run(
                ["hailortcli", "monitor"],
                capture_output=True,
                text=True,
                timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
                env=os.environ.copy(),
                check=False,
            )
            output = (result.stdout or "") + (result.stderr or "")
            match = re.search(r"(\\d{1,3})\\s*%", output)
            if match:
                self._last_npu_load = int(match.group(1))
            return self._last_npu_load
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

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

    def _preprocess(self, frame: Any) -> np.ndarray | None:
        if self._input_shape is None:
            return None
        h, w, _ = self._input_shape
        resized = cv2.resize(frame, (w, h))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        tensor = np.expand_dims(rgb, axis=0).astype(np.uint8)
        order = self._infer_format_order()
        if order == "NCHW":
            tensor = np.transpose(tensor, (0, 3, 1, 2))
        return tensor

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

    def _log_output_shapes(self, outputs: Any) -> None:
        try:
            shapes = {}
            if isinstance(outputs, dict):
                for key, value in outputs.items():
                    try:
                        shapes[str(key)] = list(value.shape)
                    except Exception:
                        shapes[str(key)] = "unknown"
            self._logger.info("Hailo outputs: %s", shapes)
        except Exception:
            return

    def _postprocess(
        self, outputs: Any, frame_shape: tuple[int, int] | None
    ) -> List[dict]:
        detections: List[dict] = []
        if not isinstance(outputs, dict):
            return detections
        frame_h, frame_w = (frame_shape if frame_shape else (None, None))
        hailo_nms_handled = False
        for _, tensor in outputs.items():
            nms_detections = self._parse_hailo_nms_by_class(tensor, frame_w, frame_h)
            if nms_detections is not None:
                hailo_nms_handled = True
                detections.extend(nms_detections)
                continue
            if not hasattr(tensor, "shape"):
                continue
            rows = self._flatten_rows(np.asarray(tensor))
            for row in rows:
                det = self._row_to_detection(row, frame_w, frame_h)
                if det is not None:
                    detections.append(det)
        if hailo_nms_handled:
            detections.sort(key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
            return detections[: self._max_detections]
        if not self._e2e_nms_free:
            detections = self._apply_nms(detections)
        detections.sort(key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
        return detections[: self._max_detections]

    def _parse_hailo_nms_by_class(
        self,
        tensor: Any,
        frame_w: int | None,
        frame_h: int | None,
    ) -> List[dict] | None:
        classes_block: Any | None = None
        if isinstance(tensor, (list, tuple)):
            if len(tensor) == 0:
                return []
            first = tensor[0]
            if self._looks_like_hailo_classes_block(first):
                classes_block = first
            elif self._looks_like_hailo_classes_block(tensor):
                classes_block = tensor
        elif isinstance(tensor, np.ndarray):
            if tensor.ndim == 3 and int(tensor.shape[-1]) >= 5:
                classes_block = [tensor[idx] for idx in range(int(tensor.shape[0]))]
            else:
                return None
        else:
            return None

        if classes_block is None:
            return None

        detections: List[dict] = []
        for class_id, raw_rows in enumerate(classes_block):
            rows = self._extract_nms_rows(raw_rows)
            if not rows:
                continue
            for row in rows:
                det = self._nms_row_to_detection(row, class_id, frame_w, frame_h)
                if det is not None:
                    detections.append(det)
        return detections

    def _looks_like_hailo_classes_block(self, value: Any) -> bool:
        if isinstance(value, np.ndarray):
            return value.ndim == 3 and int(value.shape[-1]) >= 5
        if not isinstance(value, (list, tuple)):
            return False
        if len(value) < 2:
            return False
        sample = None
        for item in value:
            if isinstance(item, np.ndarray):
                if item.ndim == 0:
                    continue
                if item.size == 0 and item.ndim >= 2 and int(item.shape[-1]) >= 5:
                    continue
                sample = item
                break
            if isinstance(item, (list, tuple)) and len(item) > 0:
                sample = item
                break
        if sample is None:
            # Accept all-empty class arrays.
            return all(isinstance(item, np.ndarray) for item in value)
        if isinstance(sample, np.ndarray):
            return sample.ndim >= 2 and int(sample.shape[-1]) >= 5
        if isinstance(sample, (list, tuple)):
            first = sample[0]
            if isinstance(first, (list, tuple, np.ndarray)):
                arr = np.asarray(first)
                return arr.ndim >= 1 and arr.size >= 5
        return False

    def _extract_nms_rows(self, raw_rows: Any) -> List[np.ndarray]:
        rows: List[np.ndarray] = []
        if isinstance(raw_rows, np.ndarray):
            if raw_rows.size == 0:
                return rows
            if raw_rows.ndim == 1:
                row = np.asarray(raw_rows).reshape(-1)
                if row.size >= 5:
                    rows.append(row)
                return rows
            arr = raw_rows.reshape(-1, int(raw_rows.shape[-1]))
            for row in arr:
                flat = np.asarray(row).reshape(-1)
                if flat.size >= 5:
                    rows.append(flat)
            return rows
        if isinstance(raw_rows, (list, tuple)):
            for item in raw_rows:
                arr = np.asarray(item)
                if arr.size == 0:
                    continue
                flat = arr.reshape(-1)
                if flat.size >= 5:
                    rows.append(flat)
        return rows

    def _nms_row_to_detection(
        self,
        row: np.ndarray,
        class_id: int,
        frame_w: int | None,
        frame_h: int | None,
    ) -> dict | None:
        values = np.asarray(row).reshape(-1)
        if values.size < 5:
            return None
        try:
            y0 = float(values[0])
            x0 = float(values[1])
            y1 = float(values[2])
            x1 = float(values[3])
            score = float(values[4])
        except Exception:
            return None
        if score < self._score_threshold:
            return None

        # HAILO NMS BY CLASS exports boxes as [ymin, xmin, ymax, xmax, score].
        if frame_w and frame_h and max(abs(x0), abs(y0), abs(x1), abs(y1)) <= 2.0:
            x0 *= float(frame_w)
            x1 *= float(frame_w)
            y0 *= float(frame_h)
            y1 *= float(frame_h)

        left = min(x0, x1)
        right = max(x0, x1)
        top = min(y0, y1)
        bottom = max(y0, y1)

        if frame_w:
            left = max(0.0, min(left, float(frame_w - 1)))
            right = max(0.0, min(right, float(frame_w)))
        if frame_h:
            top = max(0.0, min(top, float(frame_h - 1)))
            bottom = max(0.0, min(bottom, float(frame_h)))

        width = max(1, int(round(right - left)))
        height = max(1, int(round(bottom - top)))
        return {
            "label": f"class_{int(class_id)}",
            "confidence": float(score),
            "bbox": [int(round(left)), int(round(top)), width, height],
            "class_id": int(class_id),
        }

    def _flatten_rows(self, tensor: np.ndarray) -> List[np.ndarray]:
        if tensor.size == 0:
            return []
        arr = np.asarray(tensor)

        def _to_rows(candidate: np.ndarray | None) -> np.ndarray | None:
            if candidate is None or candidate.ndim < 1:
                return None
            last_dim = int(candidate.shape[-1])
            if last_dim < 5:
                return None
            try:
                return candidate.reshape(-1, last_dim)
            except Exception:
                return None

        if arr.ndim == 1:
            return [arr] if arr.size >= 5 else []

        direct = _to_rows(arr)
        swapped = _to_rows(np.swapaxes(arr, -1, -2)) if arr.ndim >= 2 else None

        def _score(rows: np.ndarray | None) -> tuple[int, int]:
            if rows is None:
                return (-1, 10_000)
            dim = int(rows.shape[1])
            if 5 <= dim <= 512:
                return (2, dim)
            if dim > 512:
                return (0, dim)
            return (-1, dim)

        score_direct = _score(direct)
        score_swapped = _score(swapped)
        if score_swapped > score_direct:
            return list(swapped) if swapped is not None else []
        if direct is not None:
            return list(direct)
        if swapped is not None:
            return list(swapped)
        return []

    def _row_to_detection(
        self,
        row: np.ndarray,
        frame_w: int | None,
        frame_h: int | None,
    ) -> dict | None:
        if row is None:
            return None
        values = np.asarray(row).reshape(-1)
        if values.size < 5:
            return None
        try:
            x = float(values[0])
            y = float(values[1])
            w = float(values[2])
            h = float(values[3])
        except Exception:
            return None

        class_id = -1
        score = 0.0
        if self._e2e_nms_free and values.size >= 6 and self._looks_like_end_to_end_row(values):
            score = float(values[4])
            try:
                class_id = int(round(float(values[5])))
            except Exception:
                class_id = -1
        elif values.size > 6:
            objectness = float(values[4])
            class_scores = values[5:]
            if (
                0.0 <= objectness <= 1.0
                and class_scores.size > 0
                and float(np.max(class_scores)) <= 1.0
            ):
                class_idx = int(np.argmax(class_scores))
                class_prob = float(class_scores[class_idx])
                score = objectness * class_prob
                class_id = class_idx
            else:
                raw_scores = values[4:]
                if raw_scores.size > 0:
                    class_idx = int(np.argmax(raw_scores))
                    class_prob = float(raw_scores[class_idx])
                    if class_prob > 1.0 or float(np.min(raw_scores)) < 0.0:
                        class_prob = float(
                            1.0 / (1.0 + np.exp(-np.clip(class_prob, -30.0, 30.0)))
                        )
                    score = class_prob
                    class_id = class_idx
                else:
                    score = max(0.0, objectness)
        else:
            score = float(values[4])
            if values.size >= 6:
                try:
                    class_id = int(values[5])
                except Exception:
                    class_id = -1

        if score < self._score_threshold:
            return None
        bbox = self._decode_bbox(x, y, w, h, frame_w, frame_h)
        if not bbox:
            return None
        bw = int(bbox[2])
        bh = int(bbox[3])
        if bw <= 1 or bh <= 1:
            return None
        return {
            "label": f"class_{class_id}" if class_id >= 0 else "objet",
            "confidence": float(score),
            "bbox": bbox,
            "class_id": class_id if class_id >= 0 else None,
        }

    def _looks_like_end_to_end_row(self, values: np.ndarray) -> bool:
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

    def _apply_nms(self, detections: List[dict]) -> List[dict]:
        if len(detections) <= 1:
            return detections
        boxes: list[list[int]] = []
        scores: list[float] = []
        valid_positions: list[int] = []
        for pos, det in enumerate(detections):
            bbox = det.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            try:
                x, y, w, h = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
                score = float(det.get("confidence", 0.0))
            except Exception:
                continue
            if w <= 0 or h <= 0:
                continue
            boxes.append([x, y, w, h])
            scores.append(score)
            valid_positions.append(pos)
        if not boxes:
            return detections
        try:
            selected = cv2.dnn.NMSBoxes(
                boxes,
                scores,
                self._score_threshold,
                self._nms_threshold,
            )
        except Exception:
            return detections
        if selected is None:
            return detections
        keep_boxes_idx: set[int] = set()
        for item in selected:
            if isinstance(item, (list, tuple, np.ndarray)):
                if len(item) > 0:
                    keep_boxes_idx.add(int(item[0]))
            else:
                keep_boxes_idx.add(int(item))
        if not keep_boxes_idx:
            return detections
        keep_positions = {
            valid_positions[idx]
            for idx in keep_boxes_idx
            if 0 <= idx < len(valid_positions)
        }
        filtered = [det for pos, det in enumerate(detections) if pos in keep_positions]
        return filtered or detections

    def _decode_bbox(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        frame_w: int | None,
        frame_h: int | None,
    ) -> list[int] | None:
        if not frame_w or not frame_h:
            return None
        # Normalized outputs: accept either xyxy or xywh-center variants.
        if 0 <= x <= 1 and 0 <= y <= 1 and 0 <= w <= 1 and 0 <= h <= 1:
            if w > x and h > y and ((x + w) > 1.05 or (y + h) > 1.05):
                x0 = int(x * frame_w)
                y0 = int(y * frame_h)
                x1 = int(w * frame_w)
                y1 = int(h * frame_h)
                return [max(0, x0), max(0, y0), max(1, x1 - x0), max(1, y1 - y0)]
            cx = x * frame_w
            cy = y * frame_h
            bw = w * frame_w
            bh = h * frame_h
            x0 = int(cx - bw / 2)
            y0 = int(cy - bh / 2)
            return [max(0, x0), max(0, y0), max(1, int(bw)), max(1, int(bh))]
        # Heuristic: x,y,w,h absolute.
        if w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= frame_w and y + h <= frame_h:
            return [int(x), int(y), max(1, int(w)), max(1, int(h))]
        # Heuristic: x,y,x2,y2 absolute.
        if x >= 0 and y >= 0 and w > x and h > y and w <= frame_w and h <= frame_h:
            return [int(x), int(y), max(1, int(w - x)), max(1, int(h - y))]
        # Fallback: mixed ordering.
        x0 = int(min(x, w))
        y0 = int(min(y, h))
        x1 = int(max(x, w))
        y1 = int(max(y, h))
        return [max(0, x0), max(0, y0), max(1, x1 - x0), max(1, y1 - y0)]


class OpenCVFaceDetector:
    name = "opencv-haar"

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._ready = False
        self._cascade_path = None
        self._cascade = None
        self._init_detector()

    @property
    def ready(self) -> bool:
        return self._ready

    def _init_detector(self) -> None:
        try:
            cascade_dir = Path(cv2.data.haarcascades)
            cascade_path = cascade_dir / "haarcascade_frontalface_default.xml"
            if not cascade_path.exists():
                self._logger.warning("OpenCV cascade not found: %s", cascade_path)
                return
            cascade = cv2.CascadeClassifier(str(cascade_path))
            if cascade.empty():
                self._logger.warning("OpenCV cascade failed to load: %s", cascade_path)
                return
            self._cascade = cascade
            self._cascade_path = cascade_path
            self._ready = True
            self._logger.info("OpenCV face detector initialized.")
        except Exception:
            self._logger.exception("Failed to initialize OpenCV detector.")

    def detect(self, frame: Any) -> List[dict]:
        if not self._ready or self._cascade is None:
            return []
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            results = []
            for (x, y, w, h) in faces:
                results.append(
                    {
                        "label": "face",
                        "confidence": None,
                        "bbox": [int(x), int(y), int(w), int(h)],
                        "class_id": None,
                    }
                )
            return results
        except Exception:
            self._logger.exception("OpenCV detection failed.")
            return []


class OpenCVShapeDetector:
    name = "opencv-shape"

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._ready = True

    @property
    def ready(self) -> bool:
        return self._ready

    def detect(self, frame: Any) -> List[dict]:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame_h, frame_w = gray.shape[:2]
            min_area = max(140, int(frame_h * frame_w * 0.001))
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edged = cv2.Canny(blurred, 35, 120)
            thresh = cv2.adaptiveThreshold(
                blurred,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                11,
                2,
            )
            kernel = np.ones((3, 3), np.uint8)
            closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)
            contours_a, _ = cv2.findContours(
                edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            contours_b, _ = cv2.findContours(
                closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            contours = sorted(
                list(contours_a) + list(contours_b),
                key=cv2.contourArea,
                reverse=True,
            )
            results = []
            seen_boxes: list[tuple[int, int, int, int]] = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < min_area:
                    continue
                peri = cv2.arcLength(cnt, True)
                if peri <= 1.0:
                    continue
                approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
                x, y, w, h = cv2.boundingRect(approx)
                if w <= 0 or h <= 0:
                    continue
                # Skip near-duplicates generated by merged contour sources.
                duplicate = False
                for (sx, sy, sw, sh) in seen_boxes:
                    inter_w = max(0, min(x + w, sx + sw) - max(x, sx))
                    inter_h = max(0, min(y + h, sy + sh) - max(y, sy))
                    inter = inter_w * inter_h
                    if inter <= 0:
                        continue
                    union = (w * h) + (sw * sh) - inter
                    if union > 0 and (inter / union) > 0.7:
                        duplicate = True
                        break
                if duplicate:
                    continue
                shape = "forme"
                sides = len(approx)
                if sides == 3:
                    shape = "triangle"
                elif sides == 4:
                    ratio = w / float(h)
                    shape = "carré" if 0.9 <= ratio <= 1.1 else "rectangle"
                elif sides == 5:
                    shape = "pentagone"
                elif sides > 5:
                    shape = "cercle"
                results.append(
                    {
                        "label": shape,
                        "confidence": None,
                        "bbox": [int(x), int(y), int(w), int(h)],
                        "poly": [
                            [int(pt[0][0]), int(pt[0][1])]
                            for pt in approx
                            if pt is not None and len(pt) > 0
                        ],
                        "class_id": None,
                    }
                )
                seen_boxes.append((x, y, w, h))
                if len(results) >= 12:
                    break
            return results
        except Exception:
            self._logger.exception("OpenCV shape detection failed.")
            return []


class DisabledDetector:
    def __init__(self, name: str, reason: str) -> None:
        self.name = str(name or "disabled")
        self.ready = False
        self.reason = str(reason or "disabled")

    def detect(self, frame: Any) -> List[dict]:
        _ = frame
        return []

    def read_npu_load(self) -> None:
        return None


class Tentacle(BaseTentacle):
    name = "vision"

    def __init__(self, config, orchestrator: object) -> None:
        super().__init__(config, orchestrator)
        self._logger = logging.getLogger(f"Tentacle.{self.name}")
        self._camera_index = int(self.config.get("vision.camera_index", 0))
        self._npu_required_for_vision = bool(npu_settings(self.config).required_for_vision)
        self._camera_device = self.config.get("vision.camera_device", None)
        self._capture_backend = str(self.config.get("vision.capture_backend", "auto")).lower()
        self._width = self.config.get("vision.width", None)
        self._height = self.config.get("vision.height", None)
        self._fps = self.config.get("vision.fps", None)
        self._fourcc = self.config.get("vision.fourcc", None)
        self._loop_sleep_s = max(
            0.02, float(self.config.get("vision.loop_sleep_seconds", 0.08))
        )
        self._reopen_fail_threshold = max(
            4, int(self.config.get("vision.reopen_fail_threshold", 8))
        )
        self._reopen_cooldown_s = max(
            0.5, float(self.config.get("vision.reopen_cooldown_seconds", 2.0))
        )
        self._fallback_min_sleep_s = max(
            self._loop_sleep_s,
            float(self.config.get("vision.fallback_min_sleep_seconds", 0.25)),
        )
        self._fallback_max_sleep_s = max(
            self._fallback_min_sleep_s,
            float(self.config.get("vision.fallback_max_sleep_seconds", 1.5)),
        )
        self._fallback_backoff_s = self._fallback_min_sleep_s
        self._last_reopen_ts = 0.0
        self._background_detect = bool(
            self.config.get("vision.background_detect", True)
        )
        self._model_path = self._resolve_model_path(
            self.config.get("vision.model_path", "config/hailo_model.hef")
        )
        self._detector_mode = self.config.get("vision.detector", "auto")
        self._model_name = self.config.get("vision.model_name", None)
        self._npu_score_threshold = float(
            self.config.get("vision.npu_score_threshold", 0.35)
        )
        self._npu_nms_threshold = float(
            self.config.get("vision.npu_nms_threshold", 0.45)
        )
        self._npu_max_detections = int(
            self.config.get("vision.npu_max_detections", 64)
        )
        self._safe_hailo_detect = bool(
            self.config.get("vision.safe_hailo_detect", True)
        )
        try:
            self._safe_hailo_empty_streak = max(
                1, min(int(self.config.get("vision.safe_hailo_empty_streak", 4)), 30)
            )
        except Exception:
            self._safe_hailo_empty_streak = 4
        self._empty_hailo_streak = 0
        self._secondary_empty_hailo_streak = 0
        self._detect_timeout_s = max(
            0.4, float(self.config.get("vision.detect_timeout_seconds", 2.0))
        )
        self._shape_fallback_detector = OpenCVShapeDetector(self._logger)
        self._detector = self._build_detector()
        self._last_detections: List[dict] = []
        self._last_secondary_detections: List[dict] = []
        self._last_ts = 0.0
        self._last_secondary_ts = 0.0
        self._last_error: str | None = None
        self._last_npu_load: int | None = None
        self._last_monitor_ts = 0.0
        self._last_primary_infer_ts = 0.0
        self._last_secondary_infer_ts = 0.0
        self._primary_infer_fps = 0.0
        self._secondary_infer_fps = 0.0
        self._jpeg_lock = threading.Lock()
        self._last_jpeg: bytes | None = None
        self._frame_lock = threading.Lock()
        self._last_frame: Any | None = None
        self._last_frame_ts = 0.0
        self._last_frame_shape: tuple[int, int] | None = None
        self._last_secondary_frame_shape: tuple[int, int] | None = None
        self._frame_cache_max_age_s = max(
            0.05, float(self.config.get("vision.frame_cache_max_age_seconds", 0.7))
        )
        try:
            jpeg_fps_default = float(self._fps) if self._fps else 10.0
        except Exception:
            jpeg_fps_default = 10.0
        try:
            self._jpeg_target_fps = max(
                1.0,
                float(self.config.get("vision.stream_jpeg_fps", jpeg_fps_default)),
            )
        except Exception:
            self._jpeg_target_fps = max(1.0, jpeg_fps_default)
        self._jpeg_interval_s = 1.0 / self._jpeg_target_fps
        self._last_jpeg_encode_ts = 0.0
        self._stream_running = False
        self._interaction_zone = self.config.get("vision.interaction_zone", "zone-centre")
        self._require_person_roi = bool(self.config.get("vision.require_person_roi", False))
        person_ids = self.config.get("vision.person_class_ids", [0])
        try:
            self._person_class_ids = {int(x) for x in person_ids}
        except Exception:
            self._person_class_ids = {0}
        self._labels_path = Path(
            self.config.get("vision.labels_path", "models/vision/coco.names")
        )
        self._class_labels = self._load_class_labels()
        self._polygon_refine = bool(self.config.get("vision.polygon_refine", False))
        self._polygon_refine_max = int(self.config.get("vision.polygon_refine_max", 3))
        self._polygon_refine_epsilon = float(
            self.config.get("vision.polygon_refine_epsilon", 0.02)
        )
        self._polygon_refine_min_area = int(
            self.config.get("vision.polygon_refine_min_area", 120)
        )
        self._owner_mode = str(self.config.get("vision.owner_mode", "lbph")).lower()
        self._owner_profile_path = Path(
            self.config.get("vision.owner_profile_path", "data/vision/owner_face.npy")
        )
        self._owner_model_path = Path(
            self.config.get("vision.owner_model_path", "data/vision/owner_lbph.xml")
        )
        self._owner_embedding_path = Path(
            self.config.get("vision.owner_embedding_path", "data/vision/owner_embedding.npy")
        )
        self._owner_embedding_model = Path(
            self.config.get("vision.owner_embedding_model", "models/vision/arcface_mobilenet_v1.onnx")
        )
        owner_threshold = self.config.get("vision.owner_threshold", None)
        if owner_threshold is None:
            if self._owner_mode == "embedding":
                owner_threshold = 0.35
            elif self._owner_mode == "hist":
                owner_threshold = 0.6
            else:
                owner_threshold = 60.0
        self._owner_threshold = float(owner_threshold)
        self._owner_profile = self._load_owner_profile()
        self._owner_embedding = self._load_owner_embedding()
        self._owner_embedder = self._load_owner_embedder()
        self._owner_recognizer = self._load_owner_recognizer()
        self._owner_last_score: float | None = None
        self._face_cascade = None
        self._v4l2_lock = threading.Lock()
        self._detect_lock = threading.Lock()
        self._camera_io_lock = threading.Lock()
        self._gatekeeper = get_hardware_gatekeeper()
        self._camera_lease: HardwareLease | None = None

    def _resolve_model_path(self, raw_model_path: Any) -> Path:
        raw = str(raw_model_path or "").strip()
        if not raw:
            return Path("config/hailo_model.hef")
        candidate = Path(raw)

        repo_root = Path(__file__).resolve().parents[1]
        host_root = repo_root.parent.parent
        search_roots = [
            repo_root,
            host_root,
            Path("/mnt/didier_ssd/didier"),
        ]
        candidates: list[Path] = []
        if candidate.suffix.lower() == ".hef":
            for root in search_roots:
                candidates.append((root / "models" / "hailo" / "yolo26n.hef").resolve())
        if candidate.is_absolute():
            candidates.append(candidate)
        else:
            for root in search_roots:
                candidates.append((root / candidate).resolve())
            if candidate.suffix.lower() == ".hef":
                for root in search_roots:
                    candidates.extend(
                        sorted((root / "models" / "hailo").glob("*.hef"))
                    )
        for path in candidates:
            try:
                if path.exists():
                    if str(path) != raw:
                        self._logger.info("Resolved Hailo model path: %s", path)
                    return path
            except Exception:
                continue
        return candidate

    def _build_detector(self):
        mode = str(self._detector_mode or "auto").lower()
        def _hailo() -> HailoDetector:
            return HailoDetector(
                self._model_path,
                self._logger,
                score_threshold=self._npu_score_threshold,
                nms_threshold=self._npu_nms_threshold,
                max_detections=self._npu_max_detections,
            )
        if mode == "hailo":
            detector = _hailo()
            if detector.ready:
                return detector
            self._logger.warning(
                "Hailo detector requested but unavailable (model=%s). Fallback to OpenCV shape detector.",
                self._model_path,
            )
            if self._npu_required_for_vision:
                reason = "hailo_requested_but_unavailable"
                self._logger.error("Vision requires NPU; disabling CPU fallback (%s).", reason)
                return DisabledDetector("hailo-required", reason)
            return OpenCVShapeDetector(self._logger)
        if mode in {"opencv", "opencv_haar", "haar", "face"}:
            return OpenCVFaceDetector(self._logger)
        if mode in {"shape", "opencv-shape", "contour"}:
            return OpenCVShapeDetector(self._logger)
        detector = _hailo()
        if detector.ready:
            return detector
        if self._npu_required_for_vision:
            reason = "hailo_auto_unavailable"
            self._logger.error("Vision requires NPU; disabling CPU fallback (%s).", reason)
            return DisabledDetector("hailo-required", reason)
        return OpenCVShapeDetector(self._logger)

    def _load_class_labels(self) -> list[str]:
        try:
            if not self._labels_path.exists():
                return []
            lines = self._labels_path.read_text(encoding="utf-8").splitlines()
            return [line.strip() for line in lines if line.strip()]
        except Exception:
            return []

    def _load_owner_profile(self) -> np.ndarray | None:
        try:
            if self._owner_profile_path.exists():
                return np.load(self._owner_profile_path)
        except Exception:
            return None
        return None

    def _load_owner_embedding(self) -> np.ndarray | None:
        try:
            if self._owner_embedding_path.exists():
                return np.load(self._owner_embedding_path)
        except Exception:
            return None
        return None

    def _load_owner_embedder(self):
        if not self._owner_embedding_model.exists():
            return None
        try:
            import onnxruntime as ort  # type: ignore
        except Exception:
            return None
        try:
            return ort.InferenceSession(
                str(self._owner_embedding_model), providers=["CPUExecutionProvider"]
            )
        except Exception:
            return None

    def _can_use_lbph(self) -> bool:
        return bool(getattr(cv2, "face", None) and hasattr(cv2.face, "LBPHFaceRecognizer_create"))

    def _load_owner_recognizer(self):
        if not self._can_use_lbph():
            return None
        if not self._owner_model_path.exists():
            return None
        try:
            recognizer = cv2.face.LBPHFaceRecognizer_create()
            recognizer.read(str(self._owner_model_path))
            return recognizer
        except Exception:
            return None

    def _get_face_cascade(self):
        if self._face_cascade is not None:
            return self._face_cascade
        try:
            cascade_dir = Path(cv2.data.haarcascades)
            cascade_path = cascade_dir / "haarcascade_frontalface_default.xml"
            if not cascade_path.exists():
                return None
            cascade = cv2.CascadeClassifier(str(cascade_path))
            if cascade.empty():
                return None
            self._face_cascade = cascade
            return cascade
        except Exception:
            return None

    def _extract_face_roi(self, frame: Any) -> np.ndarray | None:
        cascade = self._get_face_cascade()
        if cascade is None:
            return None
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
            )
            if len(faces) == 0:
                return None
            # Pick the largest face
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            return frame[y : y + h, x : x + w]
        except Exception:
            return None

    def _compute_face_signature(self, frame: Any) -> np.ndarray | None:
        roi = self._extract_face_roi(frame)
        if roi is None:
            return None
        try:
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
            cv2.normalize(hist, hist)
            return hist.flatten()
        except Exception:
            return None

    def _extract_face_gray(self, frame: Any, size: int = 160) -> np.ndarray | None:
        roi = self._extract_face_roi(frame)
        if roi is None:
            return None
        try:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            gray = cv2.resize(gray, (size, size))
            return gray
        except Exception:
            return None

    def _extract_face_rgb(self, frame: Any, size: int = 112) -> np.ndarray | None:
        roi = self._extract_face_roi(frame)
        if roi is None:
            return None
        try:
            rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            rgb = cv2.resize(rgb, (size, size))
            return rgb
        except Exception:
            return None

    def _compute_face_embedding(self, frame: Any) -> np.ndarray | None:
        if self._owner_embedder is None:
            return None
        rgb = self._extract_face_rgb(frame)
        if rgb is None:
            return None
        try:
            img = rgb.astype(np.float32)
            img = (img - 127.5) / 128.0
            img = np.transpose(img, (2, 0, 1))[None, :, :, :]
            input_name = self._owner_embedder.get_inputs()[0].name
            output = self._owner_embedder.run(None, {input_name: img})
            embedding = np.asarray(output[0]).reshape(-1).astype(np.float32)
            norm = np.linalg.norm(embedding) + 1e-9
            return embedding / norm
        except Exception:
            return None

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))

    def _capture_frame_v4l2(self) -> np.ndarray | None:
        if not self._v4l2_lock.acquire(timeout=1.2):
            return None
        device = self._camera_device or f"/dev/video{self._camera_index}"
        width = int(self._width or 640)
        height = int(self._height or 480)
        fourcc = (self._fourcc or "YUYV").upper()
        expected = width * height * 2
        cmd = [
            "v4l2-ctl",
            "-d",
            str(device),
            f"--set-fmt-video=width={width},height={height},pixelformat={fourcc}",
            "--stream-mmap",
            "--stream-count=1",
            "--stream-to=-",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
                check=False,
            )
            data = result.stdout
            if not data or len(data) < expected:
                return None
            data = data[:expected]
            yuyv = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 2))
            frame = cv2.cvtColor(yuyv, cv2.COLOR_YUV2BGR_YUYV)
            return frame
        except Exception:
            return None
        finally:
            self._v4l2_lock.release()

    def enroll_owner(self, samples: int = 5) -> dict[str, Any]:
        cap = None
        use_fallback = self._capture_backend == "v4l2"
        if not use_fallback:
            cap = self._open_camera()
            if not cap.isOpened():
                cap.release()
                cap = None
                use_fallback = True
        use_embedding = self._owner_mode == "embedding" and self._owner_embedder is not None
        use_lbph = self._owner_mode != "hist" and self._can_use_lbph() and not use_embedding
        histograms: list[np.ndarray] = []
        faces_gray: list[np.ndarray] = []
        embeddings: list[np.ndarray] = []
        try:
            for _ in range(max(1, int(samples))):
                if use_fallback:
                    frame = self._capture_frame_v4l2()
                    if frame is None:
                        time.sleep(0.05)
                        continue
                else:
                    ret, frame = cap.read()
                    if not ret:
                        time.sleep(0.05)
                        continue
                if use_embedding:
                    emb = self._compute_face_embedding(frame)
                    if emb is not None:
                        embeddings.append(emb)
                elif use_lbph:
                    face = self._extract_face_gray(frame)
                    if face is not None:
                        faces_gray.append(face)
                else:
                    signature = self._compute_face_signature(frame)
                    if signature is not None:
                        histograms.append(signature)
                time.sleep(0.05)
        finally:
            if cap is not None:
                cap.release()
        if use_embedding:
            if not embeddings:
                return {"ok": False, "error": "No face detected"}
            try:
                avg = np.mean(embeddings, axis=0)
                avg = avg / (np.linalg.norm(avg) + 1e-9)
                self._owner_embedding_path.parent.mkdir(parents=True, exist_ok=True)
                np.save(self._owner_embedding_path, avg)
                self._owner_embedding = avg
                self._owner_profile = None
                self._owner_recognizer = None
            except Exception:
                return {"ok": False, "error": "Failed to save embedding"}
            return {
                "ok": True,
                "method": "embedding",
                "samples": len(embeddings),
                "path": str(self._owner_embedding_path),
            }
        if use_lbph:
            if not faces_gray:
                return {"ok": False, "error": "No face detected"}
            try:
                recognizer = cv2.face.LBPHFaceRecognizer_create()
                labels = np.zeros((len(faces_gray),), dtype=np.int32)
                recognizer.train(faces_gray, labels)
                self._owner_model_path.parent.mkdir(parents=True, exist_ok=True)
                recognizer.write(str(self._owner_model_path))
                self._owner_recognizer = recognizer
                self._owner_profile = None
            except Exception:
                return {"ok": False, "error": "Failed to save model"}
            return {
                "ok": True,
                "method": "lbph",
                "samples": len(faces_gray),
                "path": str(self._owner_model_path),
            }
        if not histograms:
            return {"ok": False, "error": "No face detected"}
        avg = np.mean(histograms, axis=0)
        try:
            self._owner_profile_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(self._owner_profile_path, avg)
        except Exception:
            return {"ok": False, "error": "Failed to save profile"}
        self._owner_profile = avg
        self._owner_recognizer = None
        self._owner_embedding = None
        return {
            "ok": True,
            "method": "hist",
            "samples": len(histograms),
            "path": str(self._owner_profile_path),
        }

    def check_owner(self) -> dict[str, Any]:
        if self._owner_recognizer is None and self._owner_profile is None and self._owner_embedding is None:
            return {"ok": False, "enrolled": False}
        cap = None
        use_fallback = self._capture_backend == "v4l2"
        if not use_fallback:
            cap = self._open_camera()
            if not cap.isOpened():
                cap.release()
                cap = None
                use_fallback = True
        try:
            if use_fallback:
                frame = self._capture_frame_v4l2()
                ret = frame is not None
            else:
                ret, frame = cap.read()
        finally:
            if cap is not None:
                cap.release()
        if not ret:
            return {"ok": False, "enrolled": True, "error": "Capture failed"}
        if self._owner_embedding is not None and self._owner_embedder is not None:
            emb = self._compute_face_embedding(frame)
            if emb is None:
                return {"ok": False, "enrolled": True, "match": False, "score": None}
            score = self._cosine_similarity(emb, self._owner_embedding)
            self._owner_last_score = score
            return {
                "ok": True,
                "method": "embedding",
                "enrolled": True,
                "match": score >= self._owner_threshold,
                "score": score,
                "threshold": self._owner_threshold,
            }
        if self._owner_recognizer is not None:
            face = self._extract_face_gray(frame)
            if face is None:
                return {"ok": False, "enrolled": True, "match": False, "score": None}
            try:
                label, confidence = self._owner_recognizer.predict(face)
                score = float(confidence)
            except Exception:
                score = None
            self._owner_last_score = score
            if score is None:
                return {"ok": False, "enrolled": True, "match": False, "score": None}
            return {
                "ok": True,
                "method": "lbph",
                "enrolled": True,
                "match": score <= self._owner_threshold,
                "score": score,
                "threshold": self._owner_threshold,
            }
        signature = self._compute_face_signature(frame)
        if signature is None or self._owner_profile is None:
            return {"ok": False, "enrolled": True, "match": False, "score": None}
        try:
            score = float(
                cv2.compareHist(signature.astype("float32"), self._owner_profile.astype("float32"), cv2.HISTCMP_CORREL)
            )
        except Exception:
            score = None
        self._owner_last_score = score
        if score is None:
            return {"ok": False, "enrolled": True, "match": False, "score": None}
        return {
            "ok": True,
            "method": "hist",
            "enrolled": True,
            "match": score >= self._owner_threshold,
            "score": score,
            "threshold": self._owner_threshold,
        }

    def _store_detections(self, detections: List[dict]) -> None:
        self._last_detections = detections
        self._last_ts = time.time()

    def _store_secondary_detections(self, detections: List[dict]) -> None:
        self._last_secondary_detections = detections
        self._last_secondary_ts = time.time()

    def _tag_detections(self, detections: List[dict], frame: Any | None = None) -> List[dict]:
        tagged: List[dict] = []
        refined = 0
        for det in detections:
            try:
                class_id = det.get("class_id")
                label = det.get("label")
                if class_id is not None and self._class_labels:
                    idx = int(class_id)
                    if 0 <= idx < len(self._class_labels):
                        label = self._class_labels[idx]
                if class_id is not None and class_id in self._person_class_ids:
                    label = "personne"
                if not label:
                    label = "objet"
                det["label"] = label
            except Exception:
                pass
            if (
                frame is not None
                and self._polygon_refine
                and refined < self._polygon_refine_max
            ):
                if self._refine_polygon(frame, det):
                    refined += 1
            self._ensure_polygon(det)
            tagged.append(det)
        return tagged

    def _detect_with_lock(self, frame: Any) -> List[dict]:
        if not self._detect_lock.acquire(timeout=0.4):
            self._last_error = "detect_lock_timeout"
            return []
        npu_lease: HardwareLease | None = None
        if getattr(self._detector, "name", "") == "hailo":
            npu_lease = self._gatekeeper.acquire("npu", timeout_s=0.3, blocking=False)
            if npu_lease is None:
                self._detect_lock.release()
                self._last_error = "npu_gate_locked"
                return []
        try:
            return self._detector.detect(frame)
        finally:
            if npu_lease is not None:
                npu_lease.release()
            self._detect_lock.release()

    def _is_hailo_detector(self) -> bool:
        return getattr(self._detector, "name", "") == "hailo"

    def _update_infer_fps(self, *, secondary: bool) -> None:
        now = time.time()
        if secondary:
            last_ts = self._last_secondary_infer_ts
            prev_fps = self._secondary_infer_fps
        else:
            last_ts = self._last_primary_infer_ts
            prev_fps = self._primary_infer_fps
        if last_ts > 0.0:
            delta = max(0.001, now - last_ts)
            instant = 1.0 / delta
            ema = instant if prev_fps <= 0.0 else ((0.35 * instant) + (0.65 * prev_fps))
        else:
            ema = prev_fps
        if secondary:
            self._last_secondary_infer_ts = now
            if ema > 0.0:
                self._secondary_infer_fps = ema
        else:
            self._last_primary_infer_ts = now
            if ema > 0.0:
                self._primary_infer_fps = ema

    async def _detect_frame(self, frame: Any) -> List[dict]:
        timeout_s = max(0.4, float(self._detect_timeout_s))
        is_hailo = self._is_hailo_detector()
        try:
            try:
                detections = await asyncio.wait_for(
                    asyncio.to_thread(self._detect_with_lock, frame),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                self._last_error = f"detect_timeout:{timeout_s:.1f}s"
                if self._safe_hailo_detect and is_hailo:
                    self._empty_hailo_streak = 0
                    self._logger.warning(
                        "Hailo detect timeout after %.1fs, fallback to shape detector.",
                        timeout_s,
                    )
                    return await asyncio.to_thread(self._shape_fallback_detector.detect, frame)
                return []

            if detections:
                self._last_error = None
                self._empty_hailo_streak = 0
                return detections

            if not (self._safe_hailo_detect and is_hailo):
                self._empty_hailo_streak = 0
                return detections

            if self._last_error in {"npu_gate_locked", "detect_lock_timeout"}:
                self._empty_hailo_streak = 0
                return await asyncio.to_thread(self._shape_fallback_detector.detect, frame)

            self._empty_hailo_streak += 1
            if self._empty_hailo_streak >= self._safe_hailo_empty_streak:
                self._empty_hailo_streak = 0
                fallback = await asyncio.to_thread(self._shape_fallback_detector.detect, frame)
                if fallback:
                    return fallback
            return detections
        finally:
            self._update_infer_fps(secondary=False)

    def _ensure_polygon(self, det: dict) -> None:
        if det.get("poly"):
            return
        bbox = det.get("bbox")
        if not bbox or len(bbox) < 4:
            return
        try:
            x, y, w, h = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        except Exception:
            return
        det["poly"] = [
            [x, y],
            [x + w, y],
            [x + w, y + h],
            [x, y + h],
        ]

    def _refine_polygon(self, frame: Any, det: dict) -> bool:
        bbox = det.get("bbox")
        if not bbox or len(bbox) < 4:
            return False
        try:
            x, y, w, h = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        except Exception:
            return False
        if w <= 0 or h <= 0:
            return False
        if w * h < self._polygon_refine_min_area:
            return False
        frame_h, frame_w = frame.shape[:2]
        x0 = max(0, min(frame_w - 1, x))
        y0 = max(0, min(frame_h - 1, y))
        x1 = max(0, min(frame_w, x + w))
        y1 = max(0, min(frame_h, y + h))
        if x1 <= x0 or y1 <= y0:
            return False
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0:
            return False
        try:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (3, 3), 0)
            edges = cv2.Canny(blurred, 50, 150)
            contours, _ = cv2.findContours(
                edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if not contours:
                return False
            contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(contour) < self._polygon_refine_min_area:
                return False
            epsilon = self._polygon_refine_epsilon * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            if approx is None or len(approx) < 3:
                return False
            poly = [
                [int(x0 + pt[0][0]), int(y0 + pt[0][1])]
                for pt in approx
                if pt is not None and len(pt) > 0
            ]
            if len(poly) < 3:
                return False
            det["poly"] = poly
            return True
        except Exception:
            return False

    def _update_stream_frame(self, frame: Any) -> None:
        now = time.time()
        try:
            frame_copy = frame.copy()
        except Exception:
            frame_copy = frame
        with self._frame_lock:
            self._last_frame = frame_copy
        self._last_frame_ts = now

        # Avoid JPEG encoding every raw frame; over-encoding increases capture latency.
        if (now - self._last_jpeg_encode_ts) < self._jpeg_interval_s:
            return
        try:
            ok, buffer = cv2.imencode(".jpg", frame)
            if not ok:
                return
            with self._jpeg_lock:
                self._last_jpeg = buffer.tobytes()
            self._last_jpeg_encode_ts = now
        except Exception:
            return

    def get_latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._last_jpeg

    def _get_recent_frame(self, max_age_s: float | None = None) -> Any | None:
        limit = self._frame_cache_max_age_s if max_age_s is None else max(0.01, float(max_age_s))
        now = time.time()
        with self._frame_lock:
            frame = self._last_frame
        if frame is None:
            return None
        if self._last_frame_ts <= 0 or (now - self._last_frame_ts) > limit:
            return None
        try:
            return frame.copy()
        except Exception:
            return frame

    def _ensure_bgr_frame(self, frame: Any) -> Any:
        if frame is None or not hasattr(frame, "shape"):
            return frame
        try:
            if len(frame.shape) == 2:
                try:
                    return cv2.cvtColor(frame, cv2.COLOR_BayerGR2BGR)
                except Exception:
                    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            if len(frame.shape) == 3 and int(frame.shape[2]) == 1:
                return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        except Exception:
            return frame
        return frame

    def _capture_single_frame(self) -> Any | None:
        lease = self._gatekeeper.acquire("camera", timeout_s=0.4, blocking=False)
        if lease is None:
            self._last_error = "camera_gate_locked"
            return None
        try:
            with self._camera_io_lock:
                cap = None
                use_fallback = self._capture_backend == "v4l2"
                if not use_fallback:
                    cap = self._open_camera()
                    if not cap.isOpened():
                        cap.release()
                        cap = None
                        use_fallback = True
                try:
                    if use_fallback:
                        return self._capture_frame_v4l2()
                    ret, frame = cap.read()
                    if not ret:
                        return None
                    return self._ensure_bgr_frame(frame)
                finally:
                    if cap is not None:
                        cap.release()
        finally:
            lease.release()

    def _build_gstreamer_pipeline(self) -> str | None:
        if not self._camera_device and self._camera_index is None:
            return None
        device = self._camera_device or f"/dev/video{self._camera_index}"
        width = int(self._width or 640)
        height = int(self._height or 480)
        fps = int(self._fps or 30)
        fourcc = (self._fourcc or "YUYV").upper()
        if fourcc == "YUYV":
            fourcc = "YUY2"
        return (
            f"v4l2src device={device} "
            f"! video/x-raw,format={fourcc},width={width},height={height},framerate={fps}/1 "
            "! videoconvert ! appsink"
        )

    def _open_camera(self) -> cv2.VideoCapture:
        source = self._camera_device if self._camera_device else self._camera_index
        gst = self._build_gstreamer_pipeline()

        def _apply_settings(cap: cv2.VideoCapture) -> None:
            if self._fourcc:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self._fourcc))
            if self._width:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            if self._height:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            if self._fps:
                cap.set(cv2.CAP_PROP_FPS, self._fps)
            # Keep camera buffer short to avoid stale frames and PS3 backlog.
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

        open_attempts: list[tuple[str, Any, int | None]] = []
        if self._capture_backend == "gstreamer" and gst:
            open_attempts.append(("gstreamer", gst, cv2.CAP_GSTREAMER))
        open_attempts.append(("v4l2", source, cv2.CAP_V4L2))
        open_attempts.append(("opencv", source, None))
        if self._camera_device:
            open_attempts.append(("index-v4l2", self._camera_index, cv2.CAP_V4L2))
            open_attempts.append(("index-opencv", self._camera_index, None))
        if gst and self._capture_backend != "gstreamer":
            open_attempts.append(("gstreamer", gst, cv2.CAP_GSTREAMER))

        for backend_name, src, api_pref in open_attempts:
            cap = (
                cv2.VideoCapture(src, api_pref)
                if api_pref is not None
                else cv2.VideoCapture(src)
            )
            if not cap.isOpened():
                cap.release()
                continue
            _apply_settings(cap)
            # Drop startup garbage frames from USB PS3 devices.
            for _ in range(2):
                try:
                    cap.grab()
                except Exception:
                    break
            return cap
        fallback = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if fallback.isOpened():
            _apply_settings(fallback)
        return fallback

    def get_status(self) -> dict[str, Any]:
        detector_name = getattr(self._detector, "name", "unknown")
        detector_ready = bool(getattr(self._detector, "ready", False))
        npu_status = vision_npu_status(
            detector_name=detector_name,
            detector_ready=detector_ready,
            required_for_vision=self._npu_required_for_vision,
        )
        if self._model_name:
            model_name = self._model_name
        elif detector_name == "opencv-haar":
            model_name = "haarcascade_frontalface_default.xml"
        elif detector_name == "opencv-shape":
            model_name = "contours"
        else:
            model_name = self._model_path.name if self._model_path else "unknown"
        return {
            "detector": detector_name,
            "model": model_name,
            "ready": detector_ready,
            "npu_required": npu_status["required"],
            "npu_active": npu_status["active"],
            "execution_target": npu_status["execution_target"],
            "npu_reason": npu_status["reason"],
            "last_ts": self._last_ts,
            "last_frame_ts": self._last_frame_ts,
            "last_count": len(self._last_detections),
            "infer_fps": round(float(self._primary_infer_fps), 2),
            "secondary_infer_fps": round(float(self._secondary_infer_fps), 2),
            "last_error": self._last_error,
            "npu_load": self._last_npu_load,
        }

    async def run(self) -> None:
        if not self.config.get("vision.enable_live", False):
            self._logger.info("Vision tentacle idle (enable_live=false).")
            await self.stop_event.wait()
            return
        self._logger.info("Vision tentacle starting (camera=%s).", self._camera_index)
        while not self.stop_event.is_set():
            lease = await asyncio.to_thread(
                self._gatekeeper.acquire,
                "camera",
                timeout_s=0.5,
                blocking=False,
            )
            if lease is not None:
                self._camera_lease = lease
                break
            self._last_error = "camera_gate_locked"
            await asyncio.sleep(0.3)
        if self._camera_lease is None:
            return
        self._stream_running = True
        cap = None
        use_fallback = self._capture_backend == "v4l2"
        if not use_fallback:
            cap = self._open_camera()
            if not cap.isOpened():
                self._logger.warning("OpenCV camera failed; fallback v4l2-ctl.")
                cap.release()
                cap = None
                use_fallback = True

        try:
            failures = 0
            fallback_failures = 0
            while not self.stop_event.is_set():
                if use_fallback:
                    frame = await asyncio.to_thread(self._capture_frame_v4l2)
                    if frame is None:
                        fallback_failures += 1
                        now = time.monotonic()
                        if (
                            fallback_failures >= self._reopen_fail_threshold
                            and now - self._last_reopen_ts >= self._reopen_cooldown_s
                        ):
                            self._last_reopen_ts = now
                            fallback_failures = 0
                            self._logger.warning(
                                "v4l2 capture failing; trying to reopen camera."
                            )
                            try:
                                cap = self._open_camera()
                                if cap.isOpened():
                                    use_fallback = False
                                    self._fallback_backoff_s = self._fallback_min_sleep_s
                                else:
                                    self._fallback_backoff_s = min(
                                        self._fallback_max_sleep_s,
                                        max(
                                            self._fallback_min_sleep_s,
                                            self._fallback_backoff_s * 1.5,
                                        ),
                                    )
                            except Exception:
                                cap = None
                                self._fallback_backoff_s = min(
                                    self._fallback_max_sleep_s,
                                    max(
                                        self._fallback_min_sleep_s,
                                        self._fallback_backoff_s * 1.5,
                                    ),
                                )
                        await asyncio.sleep(self._fallback_backoff_s)
                        continue
                    frame = self._ensure_bgr_frame(frame)
                    fallback_failures = 0
                    self._fallback_backoff_s = self._fallback_min_sleep_s
                else:
                    ret, frame = await asyncio.to_thread(cap.read)
                    if not ret:
                        failures += 1
                        now = time.monotonic()
                        if (
                            failures >= self._reopen_fail_threshold
                            and now - self._last_reopen_ts >= self._reopen_cooldown_s
                        ):
                            self._last_reopen_ts = now
                            self._logger.warning("Camera read failed; reopening stream.")
                            failures = 0
                            try:
                                cap.release()
                            except Exception:
                                pass
                            cap = self._open_camera()
                            if not cap.isOpened():
                                self._logger.warning(
                                    "OpenCV reopen failed; switching to v4l2."
                                )
                                cap.release()
                                cap = None
                                use_fallback = True
                        await asyncio.sleep(0.05)
                        continue
                    frame = self._ensure_bgr_frame(frame)
                    failures = 0
                self._last_frame_shape = frame.shape[:2]
                await asyncio.to_thread(self._update_stream_frame, frame)
                if self._background_detect:
                    detections = await self._detect_frame(frame)
                    detections = self._tag_detections(detections, frame)
                    self._store_detections(detections)
                else:
                    now = time.time()
                    self._last_ts = now
                    self._last_error = None
                now = time.time()
                if (
                    hasattr(self._detector, "read_npu_load")
                    and now - self._last_monitor_ts > 5
                ):
                    self._last_monitor_ts = now
                    try:
                        load = self._detector.read_npu_load()
                        if load is not None:
                            self._last_npu_load = load
                            self._logger.info("NPU load: %s%%", load)
                    except Exception:
                        pass
                if use_fallback:
                    await asyncio.sleep(max(0.05, self._loop_sleep_s))
                else:
                    # cap.read() already blocks on frame cadence; only yield cooperatively.
                    await asyncio.sleep(min(max(self._loop_sleep_s, 0.0), 0.01))
        finally:
            self._stream_running = False
            if cap is not None:
                cap.release()
            if self._camera_lease is not None:
                self._camera_lease.release()
                self._camera_lease = None

    async def detect_once(self) -> dict[str, Any]:
        frame = self._get_recent_frame(max_age_s=1.0)
        if frame is None and self._stream_running:
            for _ in range(8):
                await asyncio.sleep(0.06)
                frame = self._get_recent_frame(max_age_s=1.2)
                if frame is not None:
                    break
        if frame is None:
            frame = await asyncio.to_thread(self._capture_single_frame)
        if frame is None:
            raise RuntimeError("Failed to capture frame")
        frame = self._ensure_bgr_frame(frame)
        self._last_frame_shape = frame.shape[:2]
        await asyncio.to_thread(self._update_stream_frame, frame)
        detections = await self._detect_frame(frame)
        detections = self._tag_detections(detections, frame)
        self._store_detections(detections)
        return {
            "detections": detections,
            "status": self.get_status(),
        }

    async def capture_once(self) -> str:
        image_path = Path(self.config.get("vision.capture_path", "data/capture.jpg"))
        frame = self._get_recent_frame(max_age_s=1.0)
        if frame is None and self._stream_running:
            for _ in range(8):
                await asyncio.sleep(0.06)
                frame = self._get_recent_frame(max_age_s=1.2)
                if frame is not None:
                    break
        if frame is None:
            frame = await asyncio.to_thread(self._capture_single_frame)
        if frame is None:
            raise RuntimeError("Failed to capture frame")
        frame = self._ensure_bgr_frame(frame)
        self._last_frame_shape = frame.shape[:2]
        await asyncio.to_thread(self._update_stream_frame, frame)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(cv2.imwrite, str(image_path), frame)
        return str(image_path)

    def get_latest_detections(self) -> dict[str, Any]:
        width = None
        height = None
        if self._last_frame_shape:
            height, width = self._last_frame_shape
        elif self._width and self._height:
            width, height = int(self._width), int(self._height)
        return {
            "detections": list(self._last_detections),
            "frame": {"width": width, "height": height},
            "ts": self._last_ts,
            "status": self.get_status(),
        }

    def _detect_secondary_with_fallback(self, frame: Any) -> List[dict]:
        detections = self._detect_with_lock(frame)
        if detections:
            self._secondary_empty_hailo_streak = 0
            return detections
        is_hailo = self._is_hailo_detector()
        # Secondary stream should tolerate brief lock contention from primary loop.
        if self._last_error in {"npu_gate_locked", "detect_lock_timeout"}:
            self._secondary_empty_hailo_streak = 0
            time.sleep(0.06)
            detections = self._detect_with_lock(frame)
            if detections:
                return detections
            try:
                fallback = self._shape_fallback_detector.detect(frame)
                if fallback:
                    return fallback
            except Exception:
                pass
            return detections

        if self._safe_hailo_detect and is_hailo:
            self._secondary_empty_hailo_streak += 1
            if self._secondary_empty_hailo_streak >= 2:
                self._secondary_empty_hailo_streak = 0
                try:
                    fallback = self._shape_fallback_detector.detect(frame)
                    if fallback:
                        return fallback
                except Exception:
                    pass
        else:
            self._secondary_empty_hailo_streak = 0
        return detections

    def detect_secondary_frame(self, frame: Any) -> dict[str, Any]:
        if frame is None or not hasattr(frame, "shape"):
            raise RuntimeError("Invalid frame")
        try:
            self._last_secondary_frame_shape = frame.shape[:2]
            detections = self._detect_secondary_with_fallback(frame)
            detections = self._tag_detections(detections, frame)
            self._store_secondary_detections(detections)
            height, width = self._last_secondary_frame_shape
            return {
                "detections": detections,
                "frame": {"width": width, "height": height},
                "ts": self._last_secondary_ts,
                "status": self.get_status(),
            }
        finally:
            self._update_infer_fps(secondary=True)

    def get_latest_secondary_detections(self) -> dict[str, Any]:
        width = None
        height = None
        if self._last_secondary_frame_shape:
            height, width = self._last_secondary_frame_shape
        return {
            "detections": list(self._last_secondary_detections),
            "frame": {"width": width, "height": height},
            "ts": self._last_secondary_ts,
            "status": self.get_status(),
        }

    def person_in_roi(self) -> bool:
        if not self._last_detections:
            return False
        zone = self._resolve_interaction_zone()
        if zone is None:
            return self._any_person_detected()
        width, height = self._frame_size()
        if not width or not height:
            return False
        zx, zy, zw, zh = self._normalize_zone(zone, width, height)
        for det in self._last_detections:
            if not self._is_person_detection(det):
                continue
            bbox = det.get("bbox")
            if not bbox:
                continue
            x, y, w, h = bbox
            cx = x + w / 2
            cy = y + h / 2
            if zx <= cx <= zx + zw and zy <= cy <= zy + zh:
                return True
        return False

    def _any_person_detected(self) -> bool:
        for det in self._last_detections:
            if self._is_person_detection(det):
                return True
        return False

    def _is_person_detection(self, det: dict) -> bool:
        label = str(det.get("label", "")).lower()
        if label in {"person", "face"}:
            return True
        class_id = det.get("class_id", None)
        try:
            if class_id is not None and int(class_id) in self._person_class_ids:
                return True
        except Exception:
            return False
        return False

    def _resolve_interaction_zone(self) -> dict[str, Any] | None:
        zones = self.config.get("vision.zones", []) or []
        if not zones:
            return None
        for zone in zones:
            if isinstance(zone, dict) and zone.get("name") == self._interaction_zone:
                return zone
        first = zones[0]
        if isinstance(first, dict):
            return first
        if isinstance(first, (list, tuple)) and len(first) >= 4:
            return {"x": first[0], "y": first[1], "w": first[2], "h": first[3]}
        return None

    def _frame_size(self) -> tuple[int | None, int | None]:
        if self._last_frame_shape:
            return self._last_frame_shape[1], self._last_frame_shape[0]
        if self._width and self._height:
            return int(self._width), int(self._height)
        return None, None

    def _normalize_zone(self, zone: dict[str, Any], width: int, height: int) -> tuple[float, float, float, float]:
        x = float(zone.get("x", 0))
        y = float(zone.get("y", 0))
        w = float(zone.get("w", 0))
        h = float(zone.get("h", 0))
        if max(x, y, w, h) <= 1.0:
            return x * width, y * height, w * width, h * height
        return x, y, w, h


def _draw_debug_zones(frame: Any, zones: list[dict[str, Any]]) -> None:
    if frame is None:
        return
    height, width = frame.shape[:2]
    for zone in zones:
        x = zone.get("x")
        y = zone.get("y")
        w = zone.get("w")
        h = zone.get("h")
        if x is None or y is None or w is None or h is None:
            continue
        try:
            x = float(x)
            y = float(y)
            w = float(w)
            h = float(h)
        except Exception:
            continue
        if max(x, y, w, h) <= 1.0:
            x = int(x * width)
            y = int(y * height)
            w = int(w * width)
            h = int(h * height)
        else:
            x = int(x)
            y = int(y)
            w = int(w)
            h = int(h)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
        name = zone.get("name")
        if name:
            cv2.putText(
                frame,
                str(name),
                (x + 6, max(20, y + 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 255),
                2,
            )


def _capture_debug_frame(config_path: str | Path) -> int:
    config = DidierConfig.load(config_path)
    camera_index = int(config.get("vision.camera_index", 0))
    camera_device = config.get("vision.camera_device", None)
    width = config.get("vision.width", None)
    height = config.get("vision.height", None)
    fps = config.get("vision.fps", None)
    fourcc = config.get("vision.fourcc", None)
    zones = config.get("vision.zones", []) or []

    source = camera_device if camera_device else camera_index
    cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
    if not cap.isOpened() and camera_device:
        cap.release()
        cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    if width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps:
        cap.set(cv2.CAP_PROP_FPS, fps)
    if not cap.isOpened():
        print("Camera unavailable.")
        return 1

    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        print("Failed to capture frame.")
        return 1

    zones_list: list[dict[str, Any]] = []
    for zone in zones:
        if isinstance(zone, dict):
            zones_list.append(zone)
        elif isinstance(zone, (list, tuple)) and len(zone) >= 4:
            zones_list.append(
                {"x": zone[0], "y": zone[1], "w": zone[2], "h": zone[3]}
            )
    _draw_debug_zones(frame, zones_list)

    ssd_mount = config.get("storage.ssd_mount", "/mnt/didier_ssd")
    debug_path = Path(ssd_mount) / "didier" / "logs" / "debug.jpg"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_path), frame)
    print(f"Saved debug image: {debug_path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Didier vision tools")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Capture a debug frame with the interaction zone overlay.",
    )
    parser.add_argument(
        "--config", default="config/config.json", help="Path to config file."
    )
    args = parser.parse_args()
    if args.debug:
        sys.exit(_capture_debug_frame(args.config))
    parser.print_help()
