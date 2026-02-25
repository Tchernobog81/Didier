#!/usr/bin/env python3
"""Thin Didier entrypoint.

Step 4.3: keep entrypoint small (<50 lines) and delegate runtime details.
"""

from orchestrator.flask_runtime import app
from core.resource_arbitrator import get_resource_arbitrator
import os


def main() -> int:
    arbitrator = get_resource_arbitrator()
    arbitrator.start()
    try:
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)))
    finally:
        arbitrator.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
