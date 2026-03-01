import unittest

from core.vision_remote_status_service import RemoteStreamSnapshot
from core.vision_remote_status_service import evaluate_remote_stream_status
from core.vision_remote_status_service import snapshot_remote_stream


class _Stream:
    def __init__(self, ts: float) -> None:
        self._ts = ts

    def get_last(self) -> tuple[bytes, float]:
        return b"", self._ts


class VisionRemoteStatusServiceTests(unittest.TestCase):
    def test_snapshot_remote_stream_marks_missing_stream_offline(self) -> None:
        snapshot = snapshot_remote_stream(None)

        self.assertFalse(snapshot.present)
        self.assertEqual(snapshot.ts, 0.0)

    def test_evaluate_remote_stream_status_marks_recent_stream_online(self) -> None:
        status = evaluate_remote_stream_status(
            RemoteStreamSnapshot(present=True, ts=10.0),
            now=11.2,
        )

        self.assertEqual(status["status"], "online")
        self.assertEqual(status["age_s"], 1.2)
        self.assertEqual(status["ts"], 10.0)

    def test_snapshot_and_evaluate_mark_stale_stream_offline(self) -> None:
        snapshot = snapshot_remote_stream(_Stream(5.0))
        status = evaluate_remote_stream_status(snapshot, now=9.2)

        self.assertEqual(status["status"], "offline")
        self.assertEqual(status["age_s"], 4.2)
        self.assertEqual(status["ts"], 5.0)


if __name__ == "__main__":
    unittest.main()
