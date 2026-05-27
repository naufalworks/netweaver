# Changelog

All notable changes to NetWeaver are tracked here.
Auto-maintained — the development pipeline appends entries as tasks complete.

## [2026-05-25] — Auto-development pipeline v2

### Added
- **Auto-reviewer cron job** (`netweaver-auto-reviewer`): evaluates PENDING_APPROVAL plans in REVIEW_QUEUE.md, auto-approves LOW-risk clear-scope plans. Runs at :03/:18/:33/:48.
- **Daemon auto-execution**: daemon checks for APPROVED plans every cycle, executes them directly with full test verification. Bypasses PLAN_ONLY for approved plans.
- **REVIEW_QUEUE.md** added to WATCHED_FILES — daemon detects when reviewer approves a plan and acts immediately.
- **Plan status tracking**: plans flow PENDING_APPROVAL → APPROVED → EXECUTING → DONE/FAILED with events logged to events.jsonl.

### Fixed
- **Daemon self-trigger loop**: poll hash sync after writing REVIEW_QUEUE.md prevents infinite cycle.
- **PLAN_ONLY list flattening** (daemon.py:432): `', '.join([s.get('write_files', []) for s in steps])` → flattened generator.
- **NW-A002** resolved (CRON_PROMPT.md defunct — Hermes skill system replaced inline templates with reference-based loading).

### Changed
- **IDLE_TIMEOUT** 21600s (6h) → 300s (5min): daemon self-checks for approved plans more frequently.
- **REVIEW_QUEUE.md** purged of 8+ stale duplicate plans (same safety-review CB fix, different IDs).
- **KANBAN** cleaned: NW-A002 moved to done, ready section focused on Phase 2.

## [2026-05-24] — TINI anti-hallucination rules

### Added
- **`tini-anti-hallucination` skill**: 23 binding rules for evidence-grounded agent behavior. Injected into all 5 netweaver agent cron jobs.
- **Quick-reference card**: BEFORE EDIT / AFTER COMMAND / FINAL CHECK checklist for rule compliance.
- **TINI rules in daemon STEP_SYSTEM**: 7 core rules (assumptions, plan-first, evidence-tag, invariant, scope claims, stale check, minimal change) embedded in daemon's internal code generator prompt.

### Changed
- All 5 netweaver agent cron jobs now load `tini-anti-hallucination` skill.
- Daemon STEP_SYSTEM prompt updated with binding anti-hallucination rules.

## [2026-05-24] — Phase 2: CloakBrowser integration

### Added
- **P2-001 CloakBrowser Observer Bridge**: `cloak_bridge.py` — CloakBrowser SDK wrapper. Observer live mode delegates to real browser. PageObservation contract unchanged vs mock.
- **P2-002 Live Executor Integration**: `executor.py` uses real browser actions (click, type, wait) via CloakBrowser. Backward compatible: mock mode fallback.
- **P2-003 Real Evidence Pipeline**: `observer_evidence_adapter.py` — EvidenceReport backed by actual DOM/network/storage state. Chain integrity verified on real pages.
- **P2-004 Multi-Step Orchestration**: `playwright_bridge.py` — orchestrated action sequences on real browser. Inter-step verification, rollback on real failures. 1400 tests total.
- **P2-005 Skill Learner**: `skill_learner.py` — transform successful orchestrations into persistent, deduplicated, reusable site skills. Jaccard dedup, quality gates. 45 new tests.
- **NW-025 Skill Learner** → done. Full mock-mode pipeline: observe → graph → query → plan → execute → orchestrate → trace → retry → learn → reuse.

### Fixed
- **executor.py reconstruction**: daemon LLM overwrite removed `VerifiedExecutor`, `GraphResolvedTarget`, `ResolutionStatus`. Full rewrite with correct APIs. All 1380 tests passing.
- **File rollback in `execute_step`**: tests-broken revert correctly handles new + modified files.
- **Daemon heartbeat fix**: stale timestamp watchdog fix applied.

## [2026-05-23] — Phase 1: Mock-mode foundation

### Added
- Observer, scene graph, planner, executor, action orchestrator, skill matcher.
- WebSceneGraph+WNAL/BASIL DSL system.
- Evidence-first verifier, PerspectiveEngine (ABORT/ASK strategies).
- Self-healing pipeline architecture: event ledger (JSONL), competence registry, prompt-as-code.
- 1360+ tests passing in mock mode.

## Format

```
## [YYYY-MM-DD] — Title

### Added
- Feature descriptions

### Fixed
- Bug descriptions

### Changed
- Modifications to existing behavior

### Optimized
- Performance/quality improvements
```

## [2026-05-25]

### Added
- **NW-202** ❌ Add input validation and rate limiting to executor — Failed

- **NW-103** ❌ Implement trace observability skeleton for NW-201 — Failed

- **NW-103** ❌ Sync ROADMAP.md with actual completion status from kanban — Failed

- **PLAN-NW-103** ❌ Create initial git repository and commit existing NetWeaver codebase — Failed, scoped: @['scripts/init_git.py', 'tests/test_init_git.py']

- **NW-104** ❌ Implement CloakBrowser integration for Observer & Executor — Failed

- **PLAN-NW-102** ❌ Initialize git repository and create initial commit — Failed, scoped: @['scripts/init_git.py', 'tests/test_git_initialization.py']


## [2026-05-26]

### Added
- **NW-103** ❌ Add circuit breaker entry for stale test-agent — Failed

- **NW-103** ❌ Move completed items from ready to done in KANBAN — Failed

- **NW-103** ❌ Mark NW-200 as completed in ROADMAP.md — Failed

- **NW-103** ❌ Implement persistent learning loop for skill_learner — Failed

- **NW-103** ❌ Update PRODUCT_SPEC.md to reflect MVP completion with live executor and skill learning — Failed

