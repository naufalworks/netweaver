# NetWeaver Review Queue

Set **Status** to **APPROVED** to execute.
Set **Status** to **BLOCKED** to reject.

Plans are auto-approved by the reviewer agent when LOW risk + clear scope.

---

(No pending plans. Daemon will add new plans here when backlog gaps are detected.)
### NW-027 Self-Healing Test Recovery
**Status**: APPROVED — MEDIUM risk, clear scope (netweaver/test_healer.py + tests/), testable acceptance criteria, no KANBAN conflicts, 4 failures < quarantine threshold. Reviewed 2026-05-27.
**Risk**: MEDIUM
**Scope**: netweaver/test_healer.py, tests/test_test_healer.py
**Tiny Goal**: Add a self-healing test recovery module that detects flaky tests, auto-retries them with exponential backoff, and quarantines tests that fail >3 consecutive runs. Integrates with pytest via a plugin hook. No browser/vendor imports.
**Acceptance**: TestHealer class with detect_flaky(test_name, history) method Auto-retry with configurable max_attempts (default 3) and backoff (1s, 2s, 4s) Quarantine list persisted to .tini/quarantined_tests.json Quarantined tests excluded from default pytest runs via marker Un-quarantine after manual fix (detected by next green run) All existing tests remain green 15+ new tests
**Generated**: 2026-05-27T15:16:34.957309+00:00

---

### NW-028 Auto-Backlog Generator
**Status**: APPROVED — MEDIUM risk, clear scope (netweaver/backlog_generator.py + tests/), testable acceptance criteria, no KANBAN conflicts, no failure history. Reviewed 2026-05-27.
**Risk**: MEDIUM
**Scope**: netweaver/backlog_generator.py, tests/test_backlog_generator.py
**Tiny Goal**: Add a gap analysis module that scans the codebase for TODO/FIXME/HACK comments, untested modules, and missing docstrings, then auto-generates backlog entries in BACKLOG.md format. Runs as a daemon sub-task every 10 cycles.
**Acceptance**: scan_todos() finds all TODO/FIXME/HACK in netweaver/*.py scan_coverage() identifies modules with < 50% test coverage generate_entries() produces BACKLOG.md formatted entries Deduplication: don't re-add items already in backlog Each entry has: id, title, tiny_goal, files_to_touch, risk_level All existing tests remain green 20+ new tests
**Generated**: 2026-05-27T15:16:34.957331+00:00

---

### NW-029 Evidence Report Generator
**Status**: APPROVED — MEDIUM risk, clear scope (netweaver/evidence_report.py + tests/), testable acceptance criteria, no KANBAN conflicts, 2 failures < quarantine threshold. NOTE: NW-008 (ready) mentions evidence report UX — coordinate to avoid duplication. Reviewed 2026-05-27.
**Risk**: MEDIUM
**Scope**: netweaver/evidence_report.py, tests/test_evidence_report.py
**Tiny Goal**: Create a human-readable evidence report generator that takes EvidenceReport objects and produces markdown summaries showing what was observed, what claims were made, and what evidence backs each claim. Used for debugging and audit trails.
**Acceptance**: render_markdown(evidence: EvidenceReport) → str Sections: Summary, Claims (with status), Evidence Chain, Recommendations Each claim shows: statement, status (supported/unsupported/partial), backing evidence IDs Evidence chain shows chronological order of observations No browser/vendor imports All existing tests remain green 15+ new tests
**Generated**: 2026-05-27T15:16:34.957335+00:00

---
### NW-030 Orchestrator Dry-Run Mode
**Status**: APPROVED — MEDIUM risk, clear scope (netweaver/action_orchestrator.py + tests/), testable acceptance criteria including no-side-effects guarantee, no KANBAN conflicts, no failure history. Reviewed 2026-05-27.
**Risk**: MEDIUM
**Scope**: netweaver/action_orchestrator.py, tests/test_action_orchestrator.py
**Tiny Goal**: Add a dry-run mode to ActionOrchestrator that validates the plan against the current scene graph without executing any actions. Reports what WOULD happen, identifies potential issues (missing selectors, safety risks, missing preconditions).
**Acceptance**: dry_run(plan, graph) → DryRunResult with list of DryRunStep Each step: action_type, target_resolution (would succeed?), preconditions (met?), safety (clear?) Identifies: missing nodes, blocked selectors, unmet preconditions No side effects (no executor calls, no state changes) Backward compatible: orchestrate() behavior unchanged All existing tests remain green 10+ new tests
**Generated**: 2026-05-27T15:18:34.966610+00:00

---
