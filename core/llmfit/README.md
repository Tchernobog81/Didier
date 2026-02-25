# Didier `llmfit` Bridge

This directory is the integration anchor for `llmfit` in Didier.

## Modes supported

1. Python dependency mode (recommended first):
   - install `llmfit` in the active venv
   - `core/hardware_aware.py` imports module `llmfit` at runtime

2. Vendored mode (optional later):
   - clone upstream source inside `core/llmfit/vendor/llmfit`
   - update `config/config.json` key `llmfit.python.module` accordingly

## Upstream reference

- Repository: `https://github.com/AlexsJones/llmfit`

## Notes

- Didier keeps a strict fallback path: if `llmfit` is unavailable, routing stays functional.
- No hardcoded host path should be required; all behavior is controlled by `config/config.json`.

