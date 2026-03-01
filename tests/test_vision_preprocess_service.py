import unittest

import numpy as np

from core.vision_preprocess_service import letterbox_frame
from core.vision_preprocess_service import map_model_box_to_frame
from core.vision_preprocess_service import prepare_model_input


class VisionPreprocessServiceTests(unittest.TestCase):
    def test_letterbox_frame_keeps_ps3_aspect_ratio(self) -> None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        prepared, meta = letterbox_frame(frame, net_w=640, net_h=640)

        self.assertEqual(prepared.shape, (640, 640, 3))
        self.assertEqual(meta["mode"], "letterbox")
        self.assertEqual(meta["pad_x"], 0)
        self.assertEqual(meta["pad_y"], 80)

    def test_prepare_model_input_supports_nchw(self) -> None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        tensor, meta = prepare_model_input(
            frame,
            (640, 640, 3),
            use_letterbox=True,
            format_order="NCHW",
        )

        assert tensor is not None
        assert meta is not None
        self.assertEqual(tuple(tensor.shape), (1, 3, 640, 640))
        self.assertEqual(meta["mode"], "letterbox")

    def test_map_model_box_to_frame_unpads_letterbox(self) -> None:
        bbox = map_model_box_to_frame(
            x1=100.0,
            y1=120.0,
            x2=300.0,
            y2=280.0,
            frame_w=640,
            frame_h=480,
            preprocess_meta={
                "mode": "letterbox",
                "scale": 1.0,
                "pad_x": 0,
                "pad_y": 80,
            },
            input_shape=(640, 640, 3),
        )

        self.assertEqual(bbox, [100, 40, 200, 160])


if __name__ == "__main__":
    unittest.main()
