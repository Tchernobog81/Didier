import unittest

import numpy as np

from core.vision_yolo26_service import build_object_hints
from core.vision_yolo26_service import decode_yolo26_head_pairs
from core.vision_yolo26_service import decorate_debug_snapshot


class VisionYolo26ServiceTests(unittest.TestCase):
    def test_decode_yolo26_head_pairs_decodes_vectorized_heads(self) -> None:
        boxes = np.zeros((1, 80, 80, 4), dtype=np.float32)
        logits = np.full((1, 80, 80, 80), -8.0, dtype=np.float32)
        boxes[0, 10, 20] = np.asarray([2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        logits[0, 10, 20, 0] = 8.0

        detections, debug = decode_yolo26_head_pairs(
            {
                "model/conv61": boxes,
                "model/conv64": logits,
            },
            frame_w=640,
            frame_h=640,
            input_shape=(640, 640, 3),
            preprocess_meta={"mode": "resize"},
            score_threshold=0.6,
            max_detections=64,
            apply_nms=lambda items: list(items),
            map_box_to_frame=lambda **kwargs: [148, 60, 48, 64],
        )

        assert detections is not None
        assert debug is not None
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0]["class_id"], 0)
        self.assertEqual(debug["nms_kept"], 1)
        self.assertEqual(debug["decode_path"], "yolo26_raw_head_pairs")

    def test_decorate_and_build_object_hints_keep_semantic_candidates(self) -> None:
        snapshot = decorate_debug_snapshot(
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
            },
            class_name_for_id=lambda class_id: {0: "personne", 2: "voiture"}.get(class_id),
        )

        hints = build_object_hints(
            snapshot,
            class_name_for_id=lambda class_id: {0: "personne", 2: "voiture"}.get(class_id),
        )

        assert snapshot is not None
        assert hints is not None
        candidates = snapshot["head_pairs"][0]["top_candidates"]
        self.assertEqual(candidates[0]["class_name"], "voiture")
        self.assertEqual(hints["best_label"], "personne")
        self.assertFalse(hints["under_threshold"])


if __name__ == "__main__":
    unittest.main()
