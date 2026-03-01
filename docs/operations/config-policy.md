# Configuration Policy

Date: 2026-02-28
Status: target policy for professional configuration management

## Purpose
This document defines how Didier configuration should be loaded, validated, overridden, and observed.

The immediate goal is to stop behavior from depending on hidden route-level defaults.

## Canonical Sources
The intended order of precedence is:

1. code defaults defined in schema modules
2. instance file [`config/config.json`](/mnt/didier_ssd/didier/workspace/Didier/config/config.json)
3. environment variables for deployment-specific overrides
4. explicit runtime overrides that are logged and scoped

Anything outside this order is considered accidental complexity.

## Target Modules
The following modules now exist as additive design scaffolds and should be adopted before route cleanup:

- `core/config_schema.py`
- `core/config_loader.py`
- `core/config_access.py`

### Responsibilities
- `config_schema.py`: typed definitions, defaults, validation rules
- `config_loader.py`: merge and validation pipeline
- `config_access.py`: domain-specific access helpers (`chat`, `tts`, `vision`, `routing`, `picobot`)

## Operational Rules
- unknown keys should be logged
- invalid values should fail fast at startup when possible
- defaults must be visible in one place, not hidden across routes
- environment overrides must remain explicit and documented
- runtime overrides must be traceable in operational memory

## Debug Surface
The future debug contract should expose an `effective config` view suitable for diagnosis, with sensitive values redacted.

Possible implementation:

- `/config/effective` (restricted)
- startup summary log
- config fingerprint in operational memory

## Migration Rule
No large route refactor should happen before configuration reads for that domain move behind typed accessors.

Recommended migration order:

1. AI
2. Vision
3. System
4. Core API helpers
