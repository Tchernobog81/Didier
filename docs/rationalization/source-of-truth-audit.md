# Source Of Truth Audit

Date: 2026-02-28
Scope: lot fondation `A + E + F`
Status: working baseline for rationalization; no route refactor applied yet

## Purpose
This document identifies the current sources of truth in Didier and classifies them as:

- `canonical`: should remain authoritative
- `derived`: generated or runtime projections of canonical data
- `transitional`: still used, but should be replaced or narrowed
- `archive`: historical reference only

The objective is to reduce competing sources and prevent future regressions caused by hidden defaults or duplicated knowledge.

## Current Reality
The codebase currently mixes several layers of truth:

- static configuration in [`config/config.json`](/mnt/didier_ssd/didier/workspace/Didier/config/config.json)
- runtime state in [`core/shared_state.py`](/mnt/didier_ssd/didier/workspace/Didier/core/shared_state.py)
- route-level inline defaults spread across routers
- multiple overlapping architecture documents
- memory files with different purposes but no formal separation

The highest risk today is not missing data; it is conflicting data.

## Domain Classification
| Domain | Current Source | Status | Decision |
| --- | --- | --- | --- |
| Static application configuration | [`config/config.json`](/mnt/didier_ssd/didier/workspace/Didier/config/config.json) | `canonical` | Keep as instance configuration until typed config loader replaces direct reads |
| Config defaults in route code (`orchestrator.config.get(..., default)`) | [`core/routers/ai.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/ai.py), [`core/routers/system.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/system.py), [`core/routers/vision.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/vision.py) | `transitional` | Replace with centralized config accessors |
| Runtime shared state | [`core/shared_state.py`](/mnt/didier_ssd/didier/workspace/Didier/core/shared_state.py) -> `data/shared_state.json` | `canonical` | Keep as authoritative runtime state projection |
| IPC service discovery | [`shared/ipc.py`](/mnt/didier_ssd/didier/workspace/Didier/shared/ipc.py) | `canonical` | Keep, but document as adapter layer, not business logic |
| Conversation memory | `data/memory.json` | `canonical` for user memory only | Keep, but isolate from technical and operational memory |
| Boost memory | `data/gemini_boost_memory.jsonl` | `transitional` | Keep as feature-specific cache, not system memory |
| Architecture reference | [`ARCHITECTURE.md`](/mnt/didier_ssd/didier/workspace/Didier/ARCHITECTURE.md) | `archive` | Obsolete: still describes Docker-era topology |
| Runtime foundation notes | [`fondation_didier.md`](/mnt/didier_ssd/didier/workspace/Didier/fondation_didier.md) | `transitional` | Keep as release/runtime notebook until split into architecture + operations |
| Export copy of foundation | [`fondation_didier_export.md`](/mnt/didier_ssd/didier/workspace/Didier/fondation_didier_export.md) | `derived` | Keep only if explicitly needed for export; otherwise redundant |
| Legacy foundation typo archive | [`fondation_dider.md`](/mnt/didier_ssd/didier/workspace/Didier/fondation_dider.md) | `archive` | Historical only; exclude from active references |
| Operational docs | `docs/` root files | `transitional` | Keep, but re-index under `docs/operations/` |

## Canonical Direction
The target state for Didier should be:

- `docs/architecture/`: architecture truth
- `docs/operations/`: operational truth
- `docs/adr/`: architectural decisions
- `memory/technical/`: technical memory registry and invariants
- `memory/operations/`: incidents, benchmarks, runbooks
- `config/config.json`: instance values only
- `core/config_*`: future typed config loading and access
- `data/shared_state.json`: runtime projection only

## High-Risk Duplications
### Configuration
- `orchestrator.config.get(..., default)` appears heavily in hot-path files.
- Current snapshot:
  - [`core/routers/ai.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/ai.py): 49 direct reads
  - [`core/routers/system.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/system.py): 24 direct reads
  - [`core/routers/vision.py`](/mnt/didier_ssd/didier/workspace/Didier/core/routers/vision.py): 18 direct reads
  - [`core/api.py`](/mnt/didier_ssd/didier/workspace/Didier/core/api.py): 4 direct reads

Impact:
- hidden defaults
- inconsistent behavior
- harder regression analysis

### Documentation
- `ARCHITECTURE.md` conflicts with the current non-Docker runtime.
- `fondation_didier.md` mixes architecture, release notes, migrations, and operations.

Impact:
- teams and agents can use stale architecture assumptions

### Memory Semantics
- `data/memory.json` and `data/gemini_boost_memory.jsonl` are both "memory" but serve different concerns.

Impact:
- no explicit contract for what Didier should remember

## Immediate Decisions
- Treat [`config/config.json`](/mnt/didier_ssd/didier/workspace/Didier/config/config.json) as the only static config input file.
- Treat [`core/shared_state.py`](/mnt/didier_ssd/didier/workspace/Didier/core/shared_state.py) as the only runtime state authority.
- Treat `memory/technical/` and `memory/operations/` as the new long-term canonical system memory.
- Treat [`ARCHITECTURE.md`](/mnt/didier_ssd/didier/workspace/Didier/ARCHITECTURE.md) as legacy until rewritten into `docs/architecture/`.

## Follow-Up
- Build typed config modules before any large route cleanup.
- Move active architecture truth out of `fondation_didier.md`.
- Stop adding new implicit defaults inside route handlers.
