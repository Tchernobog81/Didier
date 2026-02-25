import pytest
from orchestrator.memory import Memory


def test_memory_save_and_get_recent(tmp_path):
    db = tmp_path / "didier.db"
    mem = Memory(str(db))
    mem.connect()

    mem.save_message("user", "hello")
    mem.save_message("assistant", "hi")

    rows = mem.get_recent(2)
    assert len(rows) == 2

    # most recent first (ORDER BY id DESC)
    assert rows[0][0] == "assistant"
    assert rows[0][1] == "hi"

    assert rows[1][0] == "user"
    assert rows[1][1] == "hello"
