#!/usr/bin/env bash
set -e
ROOT="${1:-$(pwd)}"
cd "${ROOT}"
git init || true
git add .
git commit -m "Initial commit - Didier orchestrator skeleton" || true
echo "Repository initialized at ${ROOT}"
