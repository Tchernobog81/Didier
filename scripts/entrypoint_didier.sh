#!/usr/bin/env bash
set -eu

# Nettoie un éventuel process orphelin sur le port legacy.
if command -v fuser >/dev/null 2>&1; then
  fuser -k 5003/tcp >/dev/null 2>&1 || true
fi

exec "$@"
