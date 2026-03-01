"""Vision description orchestration outside the route layer."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable


class VisionDescribeServiceError(RuntimeError):
    """Raised when a vision description request cannot complete."""


@dataclass(frozen=True)
class VisionDescribeDeps:
    get_latest_jpeg: Callable[[], bytes | None] | None
    capture_once: Callable[[], Awaitable[str]] | None
    read_bytes: Callable[[str], bytes]
    post_generate: Callable[[str, dict[str, Any], float], Awaitable[dict[str, Any]]]


async def describe_latest_frame(
    *,
    prompt: str,
    model: str,
    num_predict: int,
    base_url: str,
    keep_alive: Any,
    timeout_s: float,
    deps: VisionDescribeDeps,
) -> dict[str, str]:
    img_bytes = None
    if deps.get_latest_jpeg is not None:
        try:
            img_bytes = deps.get_latest_jpeg()
        except Exception:
            img_bytes = None
    if not img_bytes and deps.capture_once is not None:
        try:
            image_path = await deps.capture_once()
            img_bytes = deps.read_bytes(image_path)
        except Exception:
            img_bytes = None
    if not img_bytes:
        raise VisionDescribeServiceError("capture unavailable")

    img_b64 = base64.b64encode(img_bytes).decode("ascii")
    payload_data: dict[str, Any] = {
        "model": str(model),
        "prompt": str(prompt),
        "stream": False,
        "images": [img_b64],
        "options": {
            "num_predict": int(num_predict),
            "temperature": 0.2,
        },
    }
    if keep_alive:
        payload_data["keep_alive"] = keep_alive

    data = await deps.post_generate(str(base_url), payload_data, float(timeout_s))
    return {
        "response": str(data.get("response", "")).strip(),
        "model": str(model),
    }
