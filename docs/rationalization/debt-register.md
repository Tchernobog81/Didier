# Debt Register

Date: 2026-02-28
Scope: technical debt baseline for lot `A + E + F`
Status: active

## Purpose
This register tracks structural debt items that materially increase regressions, runtime surprises, or maintenance cost.

## Priority Scale
- `P0`: blocks stability or creates repeated regressions
- `P1`: strongly degrades maintainability
- `P2`: cleanup with clear value but lower urgency

## Active Debt Items
| ID | Priority | Area | Symptom | Root Cause | First Action |
| --- | --- | --- | --- | --- | --- |
| DT-001 | `P0` | Configuration | behavior changes hide inside route defaults | config reads and defaults are scattered in route code | centralize config schema and accessors |
| DT-002 | `P0` | AI routing | chat regressions when TTS/routing changes | `core/routers/ai.py` mixes too many concerns | split route, service, policy |
| DT-003 | `P0` | Source of truth | multiple docs contradict current runtime | architecture and operational notes are mixed and stale | establish canonical docs tree |
| DT-004 | `P1` | Runtime state | difficult to distinguish state vs memory vs config | state, caches, and memory files are semantically mixed | define explicit memory domains |
| DT-005 | `P1` | Route contracts | frontend and scripts depend on unstable payload shapes | no strict route response contract layer | document and stabilize critical payloads |
| DT-006 | `P1` | Diagnostics | incidents are fixed ad hoc with weak traceability | no canonical operational memory or benchmark ledger | create incident and benchmark journals |
| DT-007 | `P1` | Documentation | `fondation_didier.md` is overloaded | release notes, architecture, migrations, and ops share one file | split into dedicated documents |
| DT-008 | `P2` | Legacy references | obsolete docs remain visible and tempting | archives are not isolated from active docs | mark and fence legacy docs |

## Immediate Working Rules
Until config and memory are fully rationalized:

- do not add new route-local defaults unless mirrored in config policy
- do not add new "memory" files outside `memory/` without explicit classification
- do not treat `fondation_didier.md` as the only current architecture document
- do not add new operational endpoints without documenting contract and owner

## Exit Criteria For This Lot
The `A + E + F` lot is considered complete when:

- canonical sources are documented and validated
- config priority policy is documented
- technical and operational memory directories exist and are seeded
- architecture and operations entry points exist under `docs/`

No route/service extraction is required for this lot.
