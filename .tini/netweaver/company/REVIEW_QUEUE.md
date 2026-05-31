# NetWeaver Review Queue

Set **Status** to **APPROVED** to execute.
Set **Status** to **BLOCKED** to reject.

Plans are auto-approved by the reviewer agent when LOW risk + clear scope.

---

(No pending plans. Daemon will add new plans here when backlog gaps are detected.)
### NW-027 Self-Healing Test Recovery
**Status**: DONE — Implemented and verified. 42 tests pass, 1604 total suite green. Completed 2026-05-27.
**Risk**: MEDIUM
**Scope**: netweaver/test_healer.py, tests/test_test_healer.py
**Tiny Goal**: Add a self-healing test recovery module that detects flaky tests, auto-retries them with exponential backoff, and quarantines tests that fail >3 consecutive runs. Integrates with pytest via a plugin hook. No browser/vendor imports.
**Acceptance**: TestHealer class with detect_flaky(test_name, history) method Auto-retry with configurable max_attempts (default 3) and backoff (1s, 2s, 4s) Quarantine list persisted to .tini/quarantined_tests.json Quarantined tests excluded from default pytest runs via marker Un-quarantine after manual fix (detected by next green run) All existing tests remain green 15+ new tests
**Generated**: 2026-05-27T15:16:34.957309+00:00

---

### NW-028 Auto-Backlog Generator
**Status**: DONE — Implemented and verified. 63 new tests pass, 1769 total suite (12 pre-existing epistemic failures). Completed 2026-05-27.
**Risk**: MEDIUM
**Scope**: netweaver/backlog_generator.py, tests/test_backlog_generator.py
**Tiny Goal**: Add a gap analysis module that scans the codebase for TODO/FIXME/HACK comments, untested modules, and missing docstrings, then auto-generates backlog entries in BACKLOG.md format. Runs as a daemon sub-task every 10 cycles.
**Acceptance**: scan_todos() finds all TODO/FIXME/HACK in netweaver/*.py scan_coverage() identifies modules with < 50% test coverage generate_entries() produces BACKLOG.md formatted entries Deduplication: don't re-add items already in backlog Each entry has: id, title, tiny_goal, files_to_touch, risk_level All existing tests remain green 20+ new tests
**Generated**: 2026-05-27T15:16:34.957331+00:00

---

### NW-029 Evidence Report Generator
**Status**: DONE — Implemented and verified. 46 new tests pass, 1885 total suite green. Completed 2026-05-28.
**Risk**: MEDIUM
**Scope**: netweaver/evidence_report.py, tests/test_evidence_report.py
**Tiny Goal**: Create a human-readable evidence report generator that takes EvidenceReport objects and produces markdown summaries showing what was observed, what claims were made, and what evidence backs each claim. Used for debugging and audit trails.
**Acceptance**: render_markdown(evidence: EvidenceReport) → str Sections: Summary, Claims (with status), Evidence Chain, Recommendations Each claim shows: statement, status (supported/unsupported/partial), backing evidence IDs Evidence chain shows chronological order of observations No browser/vendor imports All existing tests remain green 15+ new tests
**Generated**: 2026-05-27T15:16:34.957335+00:00

---
### NW-030 Orchestrator Dry-Run Mode
**Status**: DONE — Implemented and verified. 15 new tests pass, 1900 total suite green. Completed 2026-05-28.
**Risk**: MEDIUM
**Scope**: netweaver/action_orchestrator.py, tests/test_action_orchestrator.py
**Tiny Goal**: Add a dry-run mode to ActionOrchestrator that validates the plan against the current scene graph without executing any actions. Reports what WOULD happen, identifies potential issues (missing selectors, safety risks, missing preconditions).
**Acceptance**: dry_run(plan, graph) → DryRunResult with list of DryRunStep Each step: action_type, target_resolution (would succeed?), preconditions (met?), safety (clear?) Identifies: missing nodes, blocked selectors, unmet preconditions No side effects (no executor calls, no state changes) Backward compatible: orchestrate() behavior unchanged All existing tests remain green 10+ new tests
**Generated**: 2026-05-27T15:18:34.966610+00:00

---
### NW-031 Observer & Playwright Integration Tests
**Status**: DONE — Implemented and verified. 86 new tests pass, 1986 total suite green. Completed 2026-05-28.
**Risk**: MEDIUM
**Scope**: tests/test_observer.py, tests/test_playwright_bridge.py
**Tiny Goal**: Add comprehensive integration tests for observer.py (301 LOC) and playwright_bridge.py (399 LOC) — the 2 untested modules. Mock browser interactions, test page parsing, action dispatch, error handling. No real browser needed.
**Acceptance**: test_observer: parse static/SPA/form pages, extract interactive elements, actionability scoring test_observer: error handling for malformed pages, timeouts, network failures test_playwright_bridge: connect/disconnect lifecycle, action dispatch (click/fill/wait/navigate) test_playwright_bridge: error recovery — stale elements, detached frames, navigation interrupts test_playwright_bridge: screenshot capture and evidence attachment All tests use mocked browser (no real Chromium) 30+ new tests, coverage ≥80% for both modules All existing 1446 tests remain green
**Generated**: 2026-05-27T15:38:15.371897+00:00

---

### NW-032 End-to-End Demo Pipeline
**Status**: DONE — Implemented and verified. 32 new tests pass, 2018 total suite green. Completed 2026-05-28.
**Risk**: MEDIUM
**Scope**: netweaver/demo.py, tests/test_demo.py, .tini/netweaver/DEMO.md
**Tiny Goal**: Create a runnable demo that exercises the full stack: URL → Observer → SceneGraph → Planner → Executor → EvidenceReport. Uses mocked browser but real modules end-to-end. Proves architecture works.
**Acceptance**: DemoModule class with run_demo(url, actions) → EvidenceReport Chains: Observer.analyze() → SceneGraphBuilder.build() → Planner.plan() → Executor.execute() Mock browser returns realistic page fixtures (use tests/fixtures/*.json) Produces EvidenceReport with ≥3 claims and evidence chain CLI entry: python -m netweaver.demo --url example.com --actions "click(#login),fill(#user,admin)" DEMO.md documents architecture flow with example output All existing tests remain green 15+ new tests
**Generated**: 2026-05-27T15:38:15.371922+00:00

---

### NW-033 Real-Site Golden Snapshot Tests
**Status**: DONE — Implemented and verified. 49 new tests pass, all golden snapshots validated. Completed 2026-05-28.
**Risk**: MEDIUM
**Scope**: tests/test_real_sites.py, tests/fixtures/golden/
**Tiny Goal**: Create integration tests using 3-5 real URLs with pre-captured golden snapshots (HTML + network traces). Tests parse real-world complexity — SPAs, infinite scroll, iframes, shadow DOM.
**Acceptance**: 3+ golden snapshot fixtures (static blog, e-commerce SPA, complex dashboard) Each fixture: raw HTML, network trace JSON, expected SceneGraph structure Test parses HTML → builds SceneGraph → validates structure matches golden Network trace replay: simulates XHR/fetch patterns, validates graph_query results Regression detection: alerts if SceneGraph structure changes after code modifications All tests use mocked browser (no real network) All existing tests remain green 10+ new tests
**Generated**: 2026-05-27T15:38:15.371927+00:00

---
### NW-034 WNAL/BASIL DSL Validator
**Status**: DONE — Implemented and verified. 70 new tests pass, 2137 total suite green. Completed 2026-05-29.
**Risk**: MEDIUM
**Scope**: netweaver/dsl_validator.py, tests/test_dsl_validator.py
**Tiny Goal**: Add a standalone validator for WNAL (Web Navigation Action Language) and BASIL (Browser Automation Script Interface Language) files. Parse, validate schema, check preconditions, detect conflicts.
**Acceptance**: validate_wnal(content: str) → ValidationResult with errors/warnings validate_basil(content: str) → ValidationResult with errors/warnings Schema validation: required fields, type checking, enum constraints Precondition checking: element selectors valid, no conflicting actions Conflict detection: two actions targeting same element in wrong order CLI: python -m netweaver.dsl_validator --file actions.wnal 20+ test cases covering valid/invalid DSL files All existing tests remain green
**Generated**: 2026-05-27T15:40:15.383562+00:00

---

|### NW-035 Site Skill Auto-Learning
**Status**: DONE — Implemented and verified. 58 new tests pass, 2192 total suite green. Completed 2026-05-30.
**Risk**: MEDIUM
**Scope**: netweaver/skill_learner_auto.py, netweaver/skill_store.py, tests/test_skill_auto_learning.py
**Tiny Goal**: Implement automatic skill learning from successful navigation flows. When a sequence of actions succeeds (all evidence positive), persist as a reusable site skill. Skills include URL pattern, action sequence, selectors, and success criteria.
**Acceptance**: AutoSkillLearner: observes action sequences with evidence, identifies successful patterns learn_from_execution(execution_log: List[ActionEvidence]) → List[SiteSkill] SkillStore: persist skills to .tini/netweaver/skills/ as JSON URL pattern matching: group skills by site (e.g., github.com/*, amazon.com/product/*) Skill deduplication: merge similar skills, keep highest success rate version Skill retrieval: given new URL + intent, find matching skills Confidence scoring: skills with >5 successful uses get "trusted" status 58 new tests All existing tests remain green
**Generated**: 2026-05-27T15:40:15.383575+00:00

---

### NW-036 Perspective Engine Real-World Tests
**Status**: DONE — Implemented and verified. 47 new tests pass, 2242 total suite green. Completed 2026-05-31.
**Risk**: MEDIUM
**Scope**: tests/test_perspective_scenarios.py, tests/fixtures/perspectives/
**Tiny Goal**: Add real-world scenario tests for the perspective engine (570 LOC). Test multi-perspective queries on complex scene graphs — accessibility, security, performance, SEO perspectives on same page.
**Acceptance**: 5+ perspective definitions (accessibility, security, performance, SEO, mobile) Test complex scene graph with 100+ nodes, multiple relationship types Perspective queries return filtered subgraphs with correct node counts Cross-perspective analysis: find nodes flagged by multiple perspectives Perspective composition: combine accessibility + security into custom view Performance: queries on 1000-node graphs complete in <100ms 20+ new tests All existing tests remain green
**Generated**: 2026-05-27T15:40:15.383584+00:00

---
### NW-037 Thin Module Expansion
**Status**: DONE — Implemented and verified. 94 new tests pass, 2305 total suite green. Completed 2026-05-31.
**Risk**: MEDIUM
**Scope**: netweaver/tracker.py, netweaver/skill_view.py, netweaver/product_spec.py, netweaver/roadmap.py, netweaver/skill_doc_extractor.py, tests/test_thin_modules.py
**Tiny Goal**: Expand the 5 thin modules (<150 LOC) to production quality. Add proper error handling, type annotations, docstrings, and comprehensive tests for each.
**Acceptance**: tracker.py (82→200+ LOC): add event tracking, query interface, persistence skill_view.py (32→100+ LOC): add rendering, filtering, export formats product_spec.py (11→80+ LOC): add validation, schema, versioning roadmap.py (51→150+ LOC): add phase tracking, dependency resolution, status queries skill_doc_extractor.py (70→180+ LOC): add multi-format extraction (md, html, rst) Each module: proper type hints, docstrings, error handling 40+ new tests covering all 5 modules All existing tests remain green
**Generated**: 2026-05-27T15:42:15.397164+00:00

---

### NW-038 Performance Benchmark Suite
**Status**: BLOCKED — Garbled acceptance criteria: plan title says "Performance Benchmark Suite" but acceptance text merges ≥4 unrelated tasks (benchmark suite, AnomalyDetector, FailureDigester, daily health report) into one plan. Scope (backup_verifier.py) doesn't match acceptance criteria. Needs decomposition into separate plans with coherent scope. Reviewed 2026-05-27.
**Risk**: MEDIUM
**Scope**: netweaver/backup_verifier.py, tests/test_backup_verifier.py
**Tiny Goal**: Add backup integrity verification — don't just check backups exist, verify they're restorable. Periodically test-restore from backup, compare with current state, detect corruption.
**Acceptance**: benchmark_page_parse(): measures observer.parse() on 1KB, 10KB, 100KB pages benchmark_graph_build(): measures SceneGraphBuilder on 10, 100, 1000 node graphs benchmark_action_exec(): measures executor latency for click/fill/wait/navigate benchmark_evidence_report(): measures report generation for 10, 50, 100 claims benchmark_perspective_query(): measures query on 100, 500, 1000 node graphs Baseline thresholds: each benchmark must have upper bound (e.g., <50ms for 10KB parse) performance_baseline.md: auto-generated with current baselines CI-friendly: benchmarks fail if >2x baseline (regression detection) 10+ benchmark tests All existing tests remain green AnomalyDetector class with check(metric_name, value) → Optional[Anomaly] Rolling window: last 20 data points, compute mean + stddev Thresholds: configurable per-metric (default: 2σ for warning, 3σ for critical) Integration: daemon calls detector after each record_metric() Alerts logged to events.jsonl with type "anomaly_detected" AnomalyReport: metric, value, expected_range, severity, timestamp 15+ new tests All existing tests remain green FailureDigester class with ingest(failure_event) → Optional[FailurePattern] Pattern detection: group by task_id + error_type, detect stuck loops (>3 same failure) Root cause hinting: match common patterns (import error, syntax, timeout, API 429) DigestReport: top-N patterns, affected tasks, suggested actions, time wasted Integration: daemon calls digester on record_failure(), logs digest every 10 failures Auto-kill stuck tasks: if same task_id fails 5+ times, quarantine it DigestEvent in events.jsonl with pattern summary 20+ new tests All existing tests remain green Reads events.jsonl for last 24h Counts: plans_generated, plans_approved, plans_executed, plans_failed Test stats: pass/fail count, duration trend Metrics: avg plan_gen_time, test_duration, trend arrows (↑↓→) Anomalies: count and top-3 details Stuck tasks: list of quarantined tasks with failure counts Output: clean markdown summary, 500-1000 chars Cron: runs daily at 8AM, delivers to user Script-only (no LLM tokens) scan_daemon(): check daemon.py for untested functions, missing error handling scan_scripts(): check ~/.hermes/scripts/ for missing tests, hardcoded values scan_crons(): verify all cron scripts exist, are executable, have output scan_tini(): check .tini/ for orphan files, missing expected files Each scan produces structured findings with severity (critical/warning/info) Auto-generates backlog entries for critical findings 15+ new tests All existing tests remain green BackupVerifier class with verify(backup_path, original_path) → VerifyResult Integrity check: backup file readable, valid encoding, non-empty Restore test: copy backup to temp, compare with original (diff) Corruption detection: detect if backup was truncated or zeroed Integration: cleanup_loop calls verifier weekly on random backup sample VerifyReport in events.jsonl: backup_path, original_path, status, diff_summary Auto-alert if >30% of verified backups fail integrity 10+ new tests All existing tests remain green
**Generated**: 2026-05-27T15:42:15.397183+00:00

---
### NW-035 Site Skill Auto-Learning
**Status**: BLOCKED — Duplicate: NW-035 already DONE. KANBAN confirms completion (58 tests, 2192 suite green, 2026-05-30). No re-implementation needed.
**Risk**: MEDIUM
**Scope**: netweaver/skill_learner_auto.py, netweaver/skill_store.py, tests/test_skill_auto_learning.py
**Tiny Goal**: Implement automatic skill learning from successful navigation flows. When a sequence of actions succeeds (all evidence positive), persist as a reusable site skill. Skills include URL pattern, action sequence, selectors, and success criteria.
**Acceptance**: AutoSkillLearner: observes action sequences with evidence, identifies successful patterns learn_from_execution(execution_log: List[ActionEvidence]) → List[SiteSkill] SkillStore: persist skills to .tini/netweaver/skills/ as JSON URL pattern matching: group skills by site (e.g., github.com/*, amazon.com/product/*) Skill deduplication: merge similar skills, keep highest success rate version Skill retrieval: given new URL + intent, find matching skills Confidence scoring: skills with >5 successful uses get "trusted" status 25+ new tests All existing tests remain green
**Generated**: 2026-05-29T21:26:29.808739+00:00

**Epistemic Analysis**:
**Confidence**: 0%
**Supporting knowledge**: 5 facts
  - [likely] Task web_learning_cycle outcome: success
  - [likely] Task explore_https://example.com outcome: success
  - [likely] Task explore_https://httpbin.org/forms/post outcome: success
**Warnings**: 2
  - ⚠️  Low epistemic confidence (0%) — Resolve 46 contradiction(s). Gather more evidence before acting on this.
  - ⚠️  13 high-severity contradiction(s) — resolve before shipping
**Recommendation**: Resolve 46 contradiction(s). Gather more evidence before acting on this.
**Provenance**: 3 sources

---
