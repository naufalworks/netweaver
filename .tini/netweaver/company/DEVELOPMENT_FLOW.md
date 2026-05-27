# NetWeaver Development Flow

updated: 2026-05-23T14:42

## Goal
Keep NetWeaver development autonomous, dynamic, efficient, effective, and safe while avoiding generic wrapper drift.

## Source of Truth
1. `VISION_CLOAK_NET_AGENT.md` — product vision
2. `.tini/netweaver/NOVELTY.md` — novelty thesis
3. `.tini/netweaver/company/KANBAN.md` — work queue
4. `.tini/netweaver/HANDOFF.md` — agent communication
5. `.tini/netweaver/REVIEW.md` — review verdicts
6. `.tini/netweaver/BLOCKERS.md` — stuck points
7. `.tini/netweaver/DEV_LOG.md` — implementation audit log

## Operating Loop

### 0. Review Gate (PLAN_ONLY mode)
Before any file write, the daemon must **produce a plan** for human approval:
- Daemon picks a KANBAN task → generates plan → writes to `REVIEW_QUEUE.md`
- Plan shows: goal, files to read/write, steps, risk level
- **Status: PENDING_APPROVAL** by default
- Human sets **Status: APPROVED** to authorize execution
- Daemon next cycle reads approved plans and executes
- Toggle via `NETWEAVER_PLAN_ONLY=true/false` env var

### 1. Product/Architect
- keep vision sharp
- split work into tiny tasks
- prevent wrapper drift
- add only tasks with owner/scope/acceptance/risk

### 2. Specialist Workers
- pick one assigned Kanban task
- touch only scoped files
- implement smallest working artifact
- verify with tests/demo
- write handoff

### 3. Review/Safety
- inspect latest changes
- verify evidence/tests
- detect unsafe scope drift/conflicts
- move work to done/blocked or create fix task

### 4. Meta-Review
- every 2h evaluate whole pipeline
- reduce noise/stuck loops
- recommend schedule/model/task changes

## Quality Gates
Every task needs:
- clear task id
- owner/model
- files_to_touch
- acceptance checks
- risk_level
- verification result
- handoff note
- review verdict

## Parallelism Rule
Parallel work allowed only when file scopes do not overlap.

Current safe parallel lanes:
- Runtime: `netweaver/observer.py`, browser runtime tests
- WNAL: `netweaver/wnal.py`, `netweaver/perspective.py`
- QA: `benchmarks/*`, evidence tests
- Architect: docs/ADR/Kanban
- Review: review/handoff/status only

## Stop Conditions
Stop/flag if:
- task touches secrets/env/auth/vendor
- broad refactor without acceptance checks
- repeated failed tests twice
- no handoff after implementation
- claim lacks evidence
- generic Playwright-wrapper drift detected

## Best Current Flow Verdict
Strong foundation. Improvements still needed:
1. Kanban status movement should become more mechanical/consistent.
2. Worker reports should include exact task id every time.
3. Meta-review should suggest pruning/pausing noisy jobs.
4. Add CI-like command: `python -m unittest discover -s tests -v` as default verification.
5. Add evidence contract tests before expanding executor.
