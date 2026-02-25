#!/usr/bin/env python3
"""Thin Didier entrypoint.

Step 4.3: keep entrypoint small (<50 lines) and delegate runtime details.
"""

from orchestrator.flask_runtime import app, didier_parle
from orchestrator.openclaw_bridge import get_openclaw_bridge, register_openclaw_blueprint
import asyncio
import os


def _start_openclaw_bridge() -> None:
    register_openclaw_blueprint(app)

    async def _bootstrap() -> None:
        # Explicit async task startup as requested by the integration plan.
        task = asyncio.create_task(asyncio.to_thread(get_openclaw_bridge().start))
        await task

    asyncio.run(_bootstrap())


def main() -> int:
    _start_openclaw_bridge()
    didier_parle("Je suis opérationnel. Lancez les festivités.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
