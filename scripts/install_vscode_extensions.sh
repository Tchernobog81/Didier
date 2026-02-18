#!/usr/bin/env sh
set -eu

EXTENSIONS="${DIDIER_VSCODE_EXTENSIONS:-ai-titan.ai-titan-deepseek-agent}"

installed="$(code-server --list-extensions 2>/dev/null || true)"
for ext in $EXTENSIONS; do
  if printf '%s\n' "$installed" | grep -qx "$ext"; then
    echo "[vscode-ext] already installed: $ext"
    continue
  fi

  echo "[vscode-ext] installing: $ext"
  if code-server --install-extension "$ext"; then
    installed="$(printf '%s\n%s\n' "$installed" "$ext")"
  else
    echo "[vscode-ext] warning: install failed for $ext" >&2
  fi
done
