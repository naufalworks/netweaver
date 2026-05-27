# Project Standards

## Goal
Every project must stay clean, professional, structured, efficient, and maintainable.

## Repository Hygiene
- Project must have its own git root.
- Do not rely on parent repository state.
- Keep `.gitignore` strict.
- Do not track vendored upstream repos; clone via documented setup.
- No secrets/env/auth files in git.
- No generated caches in git.

## Structure
- `netweaver/` product code
- `tests/` unit tests
- `benchmarks/` evaluation assets
- `.tini/netweaver/` autonomous dev state
- `.tini/netweaver/company/` product/ops docs
- `vendor/` local external repos, ignored

## Task Quality
Every task needs:
- ID
- owner/model
- status
- scope/files
- acceptance checks
- verification
- risk
- handoff note

## Done Definition
A task is only done when:
- scoped files exist
- tests/demo pass
- DEV_LOG entry exists
- REVIEW entry or review handoff exists
- KANBAN done entry includes completion metadata

## Efficiency Rules
- One tiny goal per worker run.
- Prefer tests/mocks over live browser downloads.
- Avoid broad rewrites.
- Prune stale tasks.
- Keep reports compact.
