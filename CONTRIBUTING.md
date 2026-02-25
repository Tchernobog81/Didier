# Contributing to Didier

## Scope

Didier is an edge-first framework for Raspberry Pi and similar devices.  
Contributions must keep the runtime stable before adding features.

## Ground Rules

1. Keep all runtime paths configurable via `config/config.json`.
2. Keep async routes non-blocking (`asyncio.to_thread` for sync hardware calls).
3. Enforce defensive timeouts (`2.0s` default on HTTP/subprocess unless justified).
4. Prefer fallback modes over startup failures when hardware is absent.
5. Avoid hardcoded hostnames/IPs in Python modules.

## Minimal PR Checklist

1. Add or update tests in `tests/` for every routing or hardware decision change.
2. Run targeted tests locally:
   ```bash
   pytest -q tests/test_hardware_aware.py tests/test_backend_routing.py tests/test_network_discovery.py tests/test_shared_state_hardware_profile.py
   ```
3. Run syntax check for touched modules:
   ```bash
   python -m py_compile core/backend_routing.py core/hardware_aware.py core/network_discovery.py
   ```
4. Verify API health:
   ```bash
   curl -sS http://127.0.0.1:5010/health
   curl -sS http://127.0.0.1:5010/hardware/llmfit
   ```

## Extension Contracts

Use abstract contracts in `core/contracts.py`:
- `TentacleContract`
- `ActuatorContract`
- `PeripheralContract`

Extension modules should expose deterministic health snapshots and degrade safely when dependencies are missing.

## Commit Convention

- Keep commits focused by module or feature.
- Use imperative subject lines (`add routing device gating`, `fix llmfit timeout fallback`).
- Include affected services/endpoints in the commit body when runtime behavior changes.

## Release Discipline (Hard Rule)

If a commit includes code changes, it must also include:
1. `VERSION` update
2. `RELEASE_NOTES.md` update

This rule is enforced by the versioned pre-commit hook:
```bash
bash scripts/install_githooks.sh
```

Quick release bump helper:
```bash
bash scripts/bump_release.sh "didier-vXrY-your-suffix" "Short summary"
```
