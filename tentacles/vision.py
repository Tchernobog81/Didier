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

from tentacles.base import BaseTentacle
from core.config import DidierConfig


class HailoDetector:
    name = "hailo"

    def __init__(self, model_path: Path, logger: logging.Logger) -> None:
        self._logger = logger
        self._model_path = model_path
        self._ready = False
        self._hef = None
        self._device = None
        self._network_group = None
        self._network_group_params = None
        self._infer_pipeline = None
        self._input_info = None
        self._output_infos = []
        self._input_shape = None
        self._input_name = None
        self._output_shapes_logged = False
        self._last_npu_load = None
        self._init_detector()

    @property
    def ready(self) -> bool:
        return self._ready

    def _init_detector(self) -> None:
        if not self._model_path.exists():
            self._logger.warning("Hailo model not found: %s", self._model_path)
            return
        try:
            os.environ.setdefault("HAILO_MONITOR", "1")
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
            self._infer_pipeline = InferVStreams(
                self._network_group, self._input_vstreams_params, self._output_vstreams_params
            )
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
        if self._infer_pipeline is None or self._network_group is None:
            return []
        try:
            input_tensor = self._preprocess(frame)
            if input_tensor is None:
                return []
            inputs = {self._input_name: input_tensor} if self._input_name else input_tensor
            with self._network_group.activate(self._network_group_params):
                outputs = self._infer_pipeline.infer(inputs)
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
                timeout=1.2,
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
        threshold = 0.25
        frame_h, frame_w = (frame_shape if frame_shape else (None, None))
        for _, tensor in outputs.items():
            if not hasattr(tensor, "shape"):
                continue
            shape = tensor.shape
            if len(shape) < 2:
                continue
            last_dim = shape[-1]
            if last_dim not in (6, 7):
                continue
            flat = tensor.reshape(-1, last_dim)
            for row in flat:
                score = float(row[4])
                if score < threshold:
                    continue
                class_id = int(row[5]) if last_dim >= 6 else -1
                bbox = None
                try:
                    x, y, w, h = (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
                    bbox = self._decode_bbox(x, y, w, h, frame_w, frame_h)
                except Exception:
                    bbox = None
                detections.append(
                    {
                        "label": f"class_{class_id}",
                        "confidence": score,
                        "bbox": bbox,
                        "class_id": class_id,
                    }
                )
        return detections

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
        if 0 <= x <= 1 and 0 <= y <= 1 and 0 <= w <= 1 and 0 <= h <= 1:
            cx = x * frame_w
            cy = y * frame_h
            bw = w * frame_w
            bh = h * frame_h
            x0 = int(cx - bw / 2)
            y0 = int(cy - bh / 2)
            return [max(0, x0), max(0, y0), int(bw), int(bh)]
        # Heuristic: if w/h are positive and fit, assume x,y,w,h absolute
        if w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= frame_w and y + h <= frame_h:
            return [int(x), int(y), int(w), int(h)]
        # Fallback: treat w/h as x2/y2
        x0 = int(min(x, w))
        y0 = int(min(y, h))
        x1 = int(max(x, w))
        y1 = int(max(y, h))
        return [max(0, x0), max(0, y0), max(0, x1 - x0), max(0, y1 - y0)]


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
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edged = cv2.Canny(blurred, 50, 150)
            contours, _ = cv2.findContours(
                edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            results = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < 600:
                    continue
                peri = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
                x, y, w, h = cv2.boundingRect(approx)
                if w <= 0 or h <= 0:
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
                        "class_id": None,
                    }
                )
            return results
        except Exception:
            self._logger.exception("OpenCV shape detection failed.")
            return []


class Tentacle(BaseTentacle):
    name = "vision"

    def __init__(self, config, orchestrator: object) -> None:
        super().__init__(config, orchestrator)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._camera_index = int(self.config.get("vision.camera_index", 0))
        self._camera_device = self.config.get("vision.camera_device", None)
        self._capture_backend = str(self.config.get("vision.capture_backend", "auto")).lower()
        self._width = self.config.get("vision.width", None)
        self._height = self.config.get("vision.height", None)
        self._fps = self.config.get("vision.fps", None)
        self._fourcc = self.config.get("vision.fourcc", None)
        self._model_path = Path(
            self.config.get("vision.model_path", "config/hailo_model.hef")
        )
        self._detector_mode = self.config.get("vision.detector", "auto")
        self._model_name = self.config.get("vision.model_name", None)
        self._detector = self._build_detector()
        self._last_detections: List[dict] = []
        self._last_ts = 0.0
        self._last_error: str | None = None
        self._last_npu_load: int | None = None
        self._last_monitor_ts = 0.0
        self._jpeg_lock = threading.Lock()
        self._last_jpeg: bytes | None = None
        self._last_frame_ts = 0.0
        self._last_frame_shape: tuple[int, int] | None = None
        self._interaction_zone = self.config.get("vision.interaction_zone", "zone-centre")
        self._require_person_roi = bool(self.config.get("vision.require_person_roi", False))
        person_ids = self.config.get("vision.person_class_ids", [0])
        try:
            self._person_class_ids = {int(x) for x in person_ids}
        except Exception:
            self._person_class_ids = {0}
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

    def _build_detector(self):
        mode = str(self._detector_mode or "auto").lower()
        if mode == "hailo":
            return HailoDetector(self._model_path, self._logger)
        if mode in {"opencv", "opencv_haar", "haar", "face"}:
            return OpenCVFaceDetector(self._logger)
        if mode in {"shape", "opencv-shape", "contour"}:
            return OpenCVShapeDetector(self._logger)
        detector = HailoDetector(self._model_path, self._logger)
        if detector.ready:
            return detector
        return OpenCVShapeDetector(self._logger)

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
        expected = width * height * 2
        cmd = [
            "v4l2-ctl",
            "-d",
            str(device),
            "--stream-mmap",
            "--stream-count=1",
            "--stream-to=-",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=1.5,
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

    def _update_stream_frame(self, frame: Any) -> None:
        try:
            ok, buffer = cv2.imencode(".jpg", frame)
            if not ok:
                return
            with self._jpeg_lock:
                self._last_jpeg = buffer.tobytes()
                self._last_frame_ts = time.time()
        except Exception:
            return

    def get_latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._last_jpeg

    def _open_camera(self) -> cv2.VideoCapture:
        source = self._camera_device if self._camera_device else self._camera_index
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if not cap.isOpened() and self._camera_device:
            cap.release()
            cap = cv2.VideoCapture(self._camera_index, cv2.CAP_V4L2)
        if self._fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self._fourcc))
        if self._width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        if self._height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if self._fps:
            cap.set(cv2.CAP_PROP_FPS, self._fps)
        return cap

    def get_status(self) -> dict[str, Any]:
        detector_name = getattr(self._detector, "name", "unknown")
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
            "ready": bool(getattr(self._detector, "ready", False)),
            "last_ts": self._last_ts,
            "last_count": len(self._last_detections),
            "last_error": self._last_error,
            "npu_load": self._last_npu_load,
        }

    async def run(self) -> None:
        if not self.config.get("vision.enable_live", False):
            self._logger.info("Vision tentacle idle (enable_live=false).")
            await self.stop_event.wait()
            return
        self._logger.info("Vision tentacle starting (camera=%s).", self._camera_index)
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
            while not self.stop_event.is_set():
                if use_fallback:
                    frame = await asyncio.to_thread(self._capture_frame_v4l2)
                    if frame is None:
                        await asyncio.sleep(0.05)
                        continue
                else:
                    ret, frame = await asyncio.to_thread(cap.read)
                    if not ret:
                        await asyncio.sleep(0.05)
                        continue
                self._last_frame_shape = frame.shape[:2]
                await asyncio.to_thread(self._update_stream_frame, frame)
                detections = await asyncio.to_thread(self._detector.detect, frame)
                self._store_detections(detections)
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
                    await asyncio.sleep(0.05)
                else:
                    await asyncio.sleep(0)
        finally:
            if cap is not None:
                cap.release()

    async def detect_once(self) -> dict[str, Any]:
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
                frame = await asyncio.to_thread(self._capture_frame_v4l2)
                if frame is None:
                    raise RuntimeError("Failed to capture frame")
            else:
                ret, frame = await asyncio.to_thread(cap.read)
                if not ret:
                    raise RuntimeError("Failed to capture frame")
            self._last_frame_shape = frame.shape[:2]
            detections = await asyncio.to_thread(self._detector.detect, frame)
            self._store_detections(detections)
            return {
                "detections": detections,
                "status": self.get_status(),
            }
        finally:
            if cap is not None:
                cap.release()

    async def capture_once(self) -> str:
        image_path = Path(self.config.get("vision.capture_path", "data/capture.jpg"))
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
                frame = await asyncio.to_thread(self._capture_frame_v4l2)
                if frame is None:
                    raise RuntimeError("Failed to capture frame")
            else:
                ret, frame = await asyncio.to_thread(cap.read)
                if not ret:
                    raise RuntimeError("Failed to capture frame")
            self._last_frame_shape = frame.shape[:2]
            image_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(cv2.imwrite, str(image_path), frame)
        finally:
            if cap is not None:
                cap.release()
        return str(image_path)

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
