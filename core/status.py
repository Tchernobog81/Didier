import json
import threading
import time
from pathlib import Path
from typing import Any

STATUS_PATH = Path("data/asr_status.json")
_LOCK = threading.Lock()


def _read_raw() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_status() -> dict[str, Any]:
    with _LOCK:
        return _read_raw()


def update_status(**fields: Any) -> dict[str, Any]:
    with _LOCK:
        if "state" in fields and fields["state"] is not None:
            fields["state"] = str(fields["state"]).upper()
        data = _read_raw()
        data.update({k: v for k, v in fields.items() if v is not None})
        data["updated_at"] = time.time()
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(data), encoding="utf-8")
        return data
