#!/usr/bin/env python3
"""Thin Didier entrypoint.

Step 4.3: keep entrypoint small (<50 lines) and delegate runtime details.
"""

from orchestrator.flask_runtime import app, didier_parle
import os


def main() -> int:
    didier_parle("Je suis opérationnel. Lancez les festivités.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
