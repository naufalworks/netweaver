# NetWeaver Backlog

## NW-027 Self-Healing Test Recovery

tiny_goal: Add a self-healing test recovery module that detects flaky tests, auto-retries them with exponential backoff, and quarantines tests that fail >3 consecutive runs. Integrates with pytest via a plugin hook. No browser/vendor imports.

files_to_touch: netweaver/test_healer.py, tests/test_test_healer.py

acceptance_checks:
- TestHealer class with detect_flaky(test_name, history) method
- Auto-retry with configurable max_attempts (default 3) and backoff (1s, 2s, 4s)
- Quarantine list persisted to .tini/quarantined_tests.json
- Quarantined tests excluded from default pytest runs via marker
- Un-quarantine after manual fix (detected by next green run)
- All existing tests remain green
- 15+ new tests

## NW-028 Auto-Backlog Generator

tiny_goal: Add a gap analysis module that scans the codebase for TODO/FIXME/HACK comments, untested modules, and missing docstrings, then auto-generates backlog entries in BACKLOG.md format. Runs as a daemon sub-task every 10 cycles.

files_to_touch: netweaver/backlog_generator.py, tests/test_backlog_generator.py

acceptance_checks:
- scan_todos() finds all TODO/FIXME/HACK in netweaver/*.py
- scan_coverage() identifies modules with < 50% test coverage
- generate_entries() produces BACKLOG.md formatted entries
- Deduplication: don't re-add items already in backlog
- Each entry has: id, title, tiny_goal, files_to_touch, risk_level
- All existing tests remain green
- 20+ new tests

## NW-029 Evidence Report Generator

tiny_goal: Create a human-readable evidence report generator that takes EvidenceReport objects and produces markdown summaries showing what was observed, what claims were made, and what evidence backs each claim. Used for debugging and audit trails.

files_to_touch: netweaver/evidence_report.py, tests/test_evidence_report.py

acceptance_checks:
- render_markdown(evidence: EvidenceReport) → str
- Sections: Summary, Claims (with status), Evidence Chain, Recommendations
- Each claim shows: statement, status (supported/unsupported/partial), backing evidence IDs
- Evidence chain shows chronological order of observations
- No browser/vendor imports
- All existing tests remain green
- 15+ new tests

## NW-030 Orchestrator Dry-Run Mode

tiny_goal: Add a dry-run mode to ActionOrchestrator that validates the plan against the current scene graph without executing any actions. Reports what WOULD happen, identifies potential issues (missing selectors, safety risks, missing preconditions).

files_to_touch: netweaver/action_orchestrator.py, tests/test_action_orchestrator.py

acceptance_checks:
- dry_run(plan, graph) → DryRunResult with list of DryRunStep
- Each step: action_type, target_resolution (would succeed?), preconditions (met?), safety (clear?)
- Identifies: missing nodes, blocked selectors, unmet preconditions
- No side effects (no executor calls, no state changes)
- Backward compatible: orchestrate() behavior unchanged
- All existing tests remain green
- 10+ new tests

## Completed & Promoted

- NW-025 Skill Learner — completed 2026-05-24, all acceptance met, 45 tests passing
