import unittest

from core.vision_remote_status_service import RemoteStreamSnapshot
from core.vision_remote_status_service import evaluate_remote_stream_status
from core.vision_remote_status_service import snapshot_remote_stream


class _Stream:
    def __init__(self, ts: float) -> None:
        self._ts = ts

    def get_last(self) -> tuple[bytes, float]:
        return b"", self._ts


class _DebugStream(_Stream):
    def debug_snapshot(self) -> dict[str, object]:
        return {
            "fps": 15,
            "frame_gap_s": 4.7,
            "last_error": "ffmpeg stream stalled",
            "alive": True,
            "started_at": 10.0,
            "spawn_count": 2,
            "restart_count": 1,
            "input_url": "udp://0.0.0.0:1234",
        }


class _WaitingStream(_Stream):
    def debug_snapshot(self) -> dict[str, object]:
        return {
            "fps": 15,
            "last_error": "waiting for source frames",
            "alive": True,
            "started_at": 20.0,
            "waiting_s": 5.2,
            "spawn_count": 1,
            "restart_count": 0,
            "input_url": "udp://0.0.0.0:1234",
        }


class VisionRemoteStatusServiceTests(unittest.TestCase):
    def test_snapshot_remote_stream_marks_missing_stream_offline(self) -> None:
        snapshot = snapshot_remote_stream(None)
        status = evaluate_remote_stream_status(snapshot, now=10.0)

        self.assertFalse(snapshot.present)
        self.assertEqual(snapshot.ts, 0.0)
        self.assertEqual(status["diagnostic"], "stream_not_started")
        self.assertFalse(status["started"])

    def test_evaluate_remote_stream_status_marks_recent_stream_online(self) -> None:
        status = evaluate_remote_stream_status(
            RemoteStreamSnapshot(present=True, ts=10.0, started=True, alive=True),
            now=11.2,
        )

        self.assertEqual(status["status"], "online")
        self.assertEqual(status["age_s"], 1.2)
        self.assertEqual(status["ts"], 10.0)
        self.assertEqual(status["diagnostic"], "healthy")

    def test_snapshot_and_evaluate_mark_stale_stream_offline(self) -> None:
        snapshot = snapshot_remote_stream(_WaitingStream(0.0))
        status = evaluate_remote_stream_status(snapshot, now=9.2)

        self.assertEqual(status["status"], "offline")
        self.assertIsNone(status["age_s"])
        self.assertEqual(status["ts"], 0.0)
        self.assertEqual(status["diagnostic"], "source_waiting")
        self.assertEqual(status["waiting_s"], 5.2)

    def test_snapshot_preserves_remote_stream_debug_details(self) -> None:
        snapshot = snapshot_remote_stream(_DebugStream(12.0))
        status = evaluate_remote_stream_status(snapshot, now=15.5)

        self.assertEqual(snapshot.fps, 15)
        self.assertEqual(snapshot.frame_gap_s, 4.7)
        self.assertEqual(snapshot.last_error, "ffmpeg stream stalled")
        self.assertTrue(snapshot.alive)
        self.assertTrue(snapshot.started)
        self.assertEqual(snapshot.spawn_count, 2)
        self.assertEqual(snapshot.restart_count, 1)
        self.assertTrue(status["stalled"])
        self.assertEqual(status["fps"], 15)
        self.assertEqual(status["frame_gap_s"], 4.7)
        self.assertEqual(status["last_error"], "ffmpeg stream stalled")
        self.assertEqual(status["diagnostic"], "source_stalled")
        self.assertEqual(status["restart_count"], 1)


if __name__ == "__main__":
    unittest.main()
