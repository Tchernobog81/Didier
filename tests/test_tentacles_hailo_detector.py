import unittest
import tempfile
from pathlib import Path

import numpy as np

from tentacles.vision import HailoDetector
from tentacles.vision import Tentacle


class TentaclesHailoDetectorTests(unittest.TestCase):
    def _build_detector(self, *, e2e: bool) -> HailoDetector:
        detector = object.__new__(HailoDetector)
        detector._e2e_nms_free = bool(e2e)
        detector._score_threshold = 0.6
        detector._nms_threshold = 0.45
        detector._max_detections = 64
        detector._input_shape = (640, 640, 3)
        detector._input_info = None
        detector._last_output_shapes = {}
        detector._last_decode_debug = {}
        detector._last_preprocess_meta = None
        return detector

    def test_postprocess_keeps_overlapping_rows_in_yolo26_mode(self) -> None:
        detector = self._build_detector(e2e=True)
        outputs = {
            "out": np.asarray(
                [
                    [0.20, 0.20, 0.90, 0.90, 0.95, 0],
                    [0.22, 0.22, 0.88, 0.88, 0.91, 0],
                ],
                dtype=np.float32,
            )
        }

        detections = detector._postprocess(outputs, (480, 640))

        self.assertEqual(len(detections), 2)
        self.assertEqual(detections[0]["class_id"], 0)
        self.assertGreaterEqual(float(detections[0]["confidence"]), 0.91)

    def test_row_to_detection_reads_direct_score_and_class_id_for_yolo26(self) -> None:
        detector = self._build_detector(e2e=True)
        row = np.asarray([0.20, 0.20, 0.90, 0.90, 0.87, 3, 99.0], dtype=np.float32)

        detection = detector._row_to_detection(row, 640, 480)

        self.assertIsNotNone(detection)
        assert detection is not None
        self.assertEqual(detection["class_id"], 3)
        self.assertEqual(detection["label"], "class_3")
        self.assertAlmostEqual(float(detection["confidence"]), 0.87, places=3)

    def test_postprocess_decodes_paired_yolo26_raw_heads(self) -> None:
        detector = self._build_detector(e2e=True)
        boxes = np.zeros((1, 80, 80, 4), dtype=np.float32)
        logits = np.full((1, 80, 80, 80), -8.0, dtype=np.float32)
        boxes[0, 10, 20] = np.asarray([2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        logits[0, 10, 20, 0] = 8.0

        detections = detector._postprocess(
            {
                "model/conv61": boxes,
                "model/conv64": logits,
            },
            (640, 640),
        )

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0]["class_id"], 0)
        self.assertEqual(detections[0]["bbox"], [148, 60, 48, 64])
        debug = detector.debug_snapshot()
        self.assertEqual(debug.get("decode_path"), "yolo26_raw_head_pairs")
        self.assertEqual(debug.get("nms_kept"), 1)

    def test_preprocess_uses_letterbox_for_yolo26(self) -> None:
        detector = self._build_detector(e2e=True)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        tensor = detector._preprocess(frame)

        self.assertIsNotNone(tensor)
        assert tensor is not None
        self.assertEqual(tuple(tensor.shape), (1, 640, 640, 3))
        meta = detector.debug_snapshot().get("preprocess", {})
        self.assertEqual(meta.get("mode"), "letterbox")
        self.assertEqual(meta.get("pad_x"), 0)
        self.assertEqual(meta.get("pad_y"), 80)

    def test_map_model_box_to_frame_unpads_letterbox(self) -> None:
        detector = self._build_detector(e2e=True)
        detector._last_preprocess_meta = {
            "mode": "letterbox",
            "scale": 1.0,
            "pad_x": 0,
            "pad_y": 80,
            "src_w": 640,
            "src_h": 480,
            "net_w": 640,
            "net_h": 640,
        }

        bbox = detector._map_model_box_to_frame(
            x1=100.0,
            y1=120.0,
            x2=300.0,
            y2=280.0,
            frame_w=640,
            frame_h=480,
        )

        self.assertEqual(bbox, [100, 40, 200, 160])


class TentaclesVisionTentacleTests(unittest.TestCase):
    def test_load_class_labels_translates_coco_names_to_french(self) -> None:
        tentacle = object.__new__(Tentacle)
        with tempfile.TemporaryDirectory() as tmpdir:
            labels_path = Path(tmpdir) / "coco.names"
            labels_path.write_text("person\ncar\nbackpack\n", encoding="utf-8")
            tentacle._labels_path = labels_path

            labels = tentacle._load_class_labels()

        self.assertEqual(labels, ["personne", "voiture", "sac a dos"])

    def test_load_class_labels_accepts_json_label_files(self) -> None:
        tentacle = object.__new__(Tentacle)
        with tempfile.TemporaryDirectory() as tmpdir:
            labels_path = Path(tmpdir) / "coco.json"
            labels_path.write_text('{"labels":["person","truck","remote"]}', encoding="utf-8")
            tentacle._labels_path = labels_path

            labels = tentacle._load_class_labels()

        self.assertEqual(labels, ["personne", "camion", "telecommande"])

    def test_decorate_debug_snapshot_adds_translated_class_name(self) -> None:
        tentacle = object.__new__(Tentacle)
        tentacle._class_labels = ["personne", "velo", "voiture"]
        tentacle._person_class_ids = {0}

        payload = tentacle._decorate_debug_snapshot(
            {
                "head_pairs": [
                    {
                        "top_candidates": [
                            {"class_id": 2, "score": 0.4},
                            {"class_id": 99, "score": 0.1},
                        ]
                    }
                ]
            }
        )

        assert payload is not None
        candidates = payload["head_pairs"][0]["top_candidates"]
        self.assertEqual(candidates[0]["class_name"], "voiture")
        self.assertNotIn("class_name", candidates[1])

    def test_object_hints_from_debug_summarizes_best_candidates(self) -> None:
        tentacle = object.__new__(Tentacle)
        tentacle._class_labels = ["personne", "velo", "voiture"]
        tentacle._person_class_ids = {0}

        hints = tentacle._object_hints_from_debug(
            {
                "score_threshold": 0.15,
                "head_pairs": [
                    {
                        "grid": [20, 20],
                        "top_candidates": [
                            {"class_id": 2, "score": 0.09},
                            {"class_id": 0, "score": 0.22},
                        ],
                    }
                ],
            }
        )

        assert hints is not None
        self.assertEqual(hints["best_label"], "personne")
        self.assertAlmostEqual(hints["best_score"], 0.22, places=3)
        self.assertFalse(hints["under_threshold"])
        self.assertEqual(hints["top_labels"][0]["label"], "personne")
        self.assertEqual(hints["top_labels"][1]["label"], "voiture")

    def test_semantic_hints_from_status_payload_uses_stream_specific_hints(self) -> None:
        tentacle = object.__new__(Tentacle)

        hints = tentacle._semantic_hints_from_status_payload(
            {
                "object_hints": {
                    "top_labels": [{"label": "voiture", "score": 0.09}],
                },
                "secondary_object_hints": {
                    "top_labels": [{"label": "personne", "score": 0.22}],
                },
            },
            secondary=True,
        )

        self.assertEqual(hints, [{"label": "personne", "score": 0.22}])

    def test_get_latest_detections_exposes_semantic_hints(self) -> None:
        tentacle = object.__new__(Tentacle)
        tentacle._last_frame_shape = (480, 640)
        tentacle._width = 640
        tentacle._height = 480
        tentacle._last_detections = []
        tentacle._last_ts = 123.0
        tentacle.get_status = lambda: {
            "primary_object_hints": {
                "top_labels": [
                    {"label": "personne", "score": 0.12},
                    {"label": "canape", "score": 0.03},
                ]
            }
        }
        tentacle._semantic_hints_from_status_payload = Tentacle._semantic_hints_from_status_payload.__get__(
            tentacle, Tentacle
        )

        payload = tentacle.get_latest_detections()

        self.assertEqual(
            payload["semantic_hints"],
            [
                {"label": "personne", "score": 0.12},
                {"label": "canape", "score": 0.03},
            ],
        )

    def test_detect_with_lock_uses_secondary_threshold_without_mutating_primary_threshold(self) -> None:
        class _DummyLock:
            def acquire(self, timeout: float = 0.0) -> bool:
                return True

            def release(self) -> None:
                return None

        class _DummyLease:
            def release(self) -> None:
                return None

        class _DummyGatekeeper:
            def acquire(self, *args, **kwargs):
                return _DummyLease()

        class _DummyDetector:
            name = "hailo"

            def __init__(self) -> None:
                self._score_threshold = 0.15
                self.seen_thresholds: list[float] = []

            def detect(self, frame):
                self.seen_thresholds.append(float(self._score_threshold))
                return []

        tentacle = object.__new__(Tentacle)
        tentacle._detect_lock = _DummyLock()
        tentacle._gatekeeper = _DummyGatekeeper()
        tentacle._detector = _DummyDetector()
        tentacle._secondary_npu_score_threshold = 0.12
        tentacle._last_error = None
        tentacle._capture_detector_debug = lambda secondary=False: None

        tentacle._detect_with_lock(frame=np.zeros((4, 4, 3), dtype=np.uint8), secondary=True)

        self.assertEqual(tentacle._detector.seen_thresholds, [0.12])
        self.assertAlmostEqual(tentacle._detector._score_threshold, 0.15, places=4)

    def test_detect_secondary_frame_discards_shape_only_fallback_when_hailo_is_active(self) -> None:
        tentacle = object.__new__(Tentacle)
        tentacle._safe_hailo_detect = True
        tentacle._last_secondary_ts = 0.0
        tentacle._detect_secondary_with_fallback = (
            lambda frame: [{"label": "forme", "class_id": None, "confidence": None}]
        )
        tentacle._tag_detections = lambda detections, frame: list(detections)
        stored: dict[str, list[dict]] = {}
        tentacle._store_secondary_detections = (
            lambda detections: stored.setdefault("detections", list(detections))
        )
        tentacle._is_hailo_detector = lambda: True
        tentacle.get_status = lambda: {"ready": True}
        tentacle._update_infer_fps = lambda secondary=True: None

        result = tentacle.detect_secondary_frame(np.zeros((10, 10, 3), dtype=np.uint8))

        self.assertEqual(result["detections"], [])
        self.assertEqual(stored["detections"], [])


if __name__ == "__main__":
    unittest.main()
