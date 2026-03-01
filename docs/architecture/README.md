# Didier Architecture

Date: 2026-02-28
Status: new canonical entry point

## Role
This directory is the future canonical architecture reference for Didier.

It replaces the previous habit of mixing architecture, release notes, migrations, and operational notes in a single document.

## Current Rule
For now:

- [`docs/rationalization/source-of-truth-audit.md`](/mnt/didier_ssd/didier/workspace/Didier/docs/rationalization/source-of-truth-audit.md) is the authoritative guide for source ownership
- [`docs/rationalization/routes-map.md`](/mnt/didier_ssd/didier/workspace/Didier/docs/rationalization/routes-map.md) is the authoritative route inventory
- [`fondation_didier.md`](/mnt/didier_ssd/didier/workspace/Didier/fondation_didier.md) remains a transitional runtime notebook, not the long-term architecture source
- [`ARCHITECTURE.md`](/mnt/didier_ssd/didier/workspace/Didier/ARCHITECTURE.md) should be treated as legacy context because it still describes a Docker-era topology

## Intended Contents
This directory should eventually host:

- system context
- runtime topology
- service boundaries
- route contracts
- state and memory model
- dependency maps

## Working Convention
- architecture docs describe stable design and invariants
- operational docs describe procedures, incidents, and runtime behavior
- ADRs describe decisions and tradeoffs
