import unittest

import numpy as np

from tentacles.vision import HailoDetector


class TentaclesHailoDetectorTests(unittest.TestCase):
    def _build_detector(self, *, e2e: bool) -> HailoDetector:
        detector = object.__new__(HailoDetector)
        detector._e2e_nms_free = bool(e2e)
        detector._score_threshold = 0.6
        detector._nms_threshold = 0.45
        detector._max_detections = 64
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


if __name__ == "__main__":
    unittest.main()
