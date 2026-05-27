# NetWeaver + Pipeline Backlog

## NW-031 Observer & Playwright Integration Tests

tiny_goal: Add comprehensive integration tests for observer.py (301 LOC) and playwright_bridge.py (399 LOC) — the 2 untested modules. Mock browser interactions, test page parsing, action dispatch, error handling. No real browser needed.

files_to_touch: tests/test_observer.py, tests/test_playwright_bridge.py

acceptance_checks:
- test_observer: parse static/SPA/form pages, extract interactive elements, actionability scoring
- test_observer: error handling for malformed pages, timeouts, network failures
- test_playwright_bridge: connect/disconnect lifecycle, action dispatch (click/fill/wait/navigate)
- test_playwright_bridge: error recovery — stale elements, detached frames, navigation interrupts
- test_playwright_bridge: screenshot capture and evidence attachment
- All tests use mocked browser (no real Chromium)
- 30+ new tests, coverage ≥80% for both modules
- All existing 1446 tests remain green

## NW-032 End-to-End Demo Pipeline

tiny_goal: Create a runnable demo that exercises the full stack: URL → Observer → SceneGraph → Planner → Executor → EvidenceReport. Uses mocked browser but real modules end-to-end. Proves architecture works.

files_to_touch: netweaver/demo.py, tests/test_demo.py, .tini/netweaver/DEMO.md

acceptance_checks:
- DemoModule class with run_demo(url, actions) → EvidenceReport
- Chains: Observer.analyze() → SceneGraphBuilder.build() → Planner.plan() → Executor.execute()
- Mock browser returns realistic page fixtures (use tests/fixtures/*.json)
- Produces EvidenceReport with ≥3 claims and evidence chain
- CLI entry: python -m netweaver.demo --url example.com --actions "click(#login),fill(#user,admin)"
- DEMO.md documents architecture flow with example output
- All existing tests remain green
- 15+ new tests

## NW-033 Real-Site Golden Snapshot Tests

tiny_goal: Create integration tests using 3-5 real URLs with pre-captured golden snapshots (HTML + network traces). Tests parse real-world complexity — SPAs, infinite scroll, iframes, shadow DOM.

files_to_touch: tests/test_real_sites.py, tests/fixtures/golden/

acceptance_checks:
- 3+ golden snapshot fixtures (static blog, e-commerce SPA, complex dashboard)
- Each fixture: raw HTML, network trace JSON, expected SceneGraph structure
- Test parses HTML → builds SceneGraph → validates structure matches golden
- Network trace replay: simulates XHR/fetch patterns, validates graph_query results
- Regression detection: alerts if SceneGraph structure changes after code modifications
- All tests use mocked browser (no real network)
- All existing tests remain green
- 10+ new tests

## NW-034 WNAL/BASIL DSL Validator

tiny_goal: Add a standalone validator for WNAL (Web Navigation Action Language) and BASIL (Browser Automation Script Interface Language) files. Parse, validate schema, check preconditions, detect conflicts.

files_to_touch: netweaver/dsl_validator.py, tests/test_dsl_validator.py

acceptance_checks:
- validate_wnal(content: str) → ValidationResult with errors/warnings
- validate_basil(content: str) → ValidationResult with errors/warnings
- Schema validation: required fields, type checking, enum constraints
- Precondition checking: element selectors valid, no conflicting actions
- Conflict detection: two actions targeting same element in wrong order
- CLI: python -m netweaver.dsl_validator --file actions.wnal
- 20+ test cases covering valid/invalid DSL files
- All existing tests remain green

## NW-035 Site Skill Auto-Learning

tiny_goal: Implement automatic skill learning from successful navigation flows. When a sequence of actions succeeds (all evidence positive), persist as a reusable site skill. Skills include URL pattern, action sequence, selectors, and success criteria.

files_to_touch: netweaver/skill_learner_auto.py, netweaver/skill_store.py, tests/test_skill_auto_learning.py

acceptance_checks:
- AutoSkillLearner: observes action sequences with evidence, identifies successful patterns
- learn_from_execution(execution_log: List[ActionEvidence]) → List[SiteSkill]
- SkillStore: persist skills to .tini/netweaver/skills/ as JSON
- URL pattern matching: group skills by site (e.g., github.com/*, amazon.com/product/*)
- Skill deduplication: merge similar skills, keep highest success rate version
- Skill retrieval: given new URL + intent, find matching skills
- Confidence scoring: skills with >5 successful uses get "trusted" status
- 25+ new tests
- All existing tests remain green

## NW-036 Perspective Engine Real-World Tests

tiny_goal: Add real-world scenario tests for the perspective engine (570 LOC). Test multi-perspective queries on complex scene graphs — accessibility, security, performance, SEO perspectives on same page.

files_to_touch: tests/test_perspective_scenarios.py, tests/fixtures/perspectives/

acceptance_checks:
- 5+ perspective definitions (accessibility, security, performance, SEO, mobile)
- Test complex scene graph with 100+ nodes, multiple relationship types
- Perspective queries return filtered subgraphs with correct node counts
- Cross-perspective analysis: find nodes flagged by multiple perspectives
- Perspective composition: combine accessibility + security into custom view
- Performance: queries on 1000-node graphs complete in <100ms
- 20+ new tests
- All existing tests remain green

## NW-037 Thin Module Expansion

tiny_goal: Expand the 5 thin modules (<150 LOC) to production quality. Add proper error handling, type annotations, docstrings, and comprehensive tests for each.

files_to_touch: netweaver/tracker.py, netweaver/skill_view.py, netweaver/product_spec.py, netweaver/roadmap.py, netweaver/skill_doc_extractor.py, tests/test_thin_modules.py

acceptance_checks:
- tracker.py (82→200+ LOC): add event tracking, query interface, persistence
- skill_view.py (32→100+ LOC): add rendering, filtering, export formats
- product_spec.py (11→80+ LOC): add validation, schema, versioning
- roadmap.py (51→150+ LOC): add phase tracking, dependency resolution, status queries
- skill_doc_extractor.py (70→180+ LOC): add multi-format extraction (md, html, rst)
- Each module: proper type hints, docstrings, error handling
- 40+ new tests covering all 5 modules
- All existing tests remain green

## NW-038 Performance Benchmark Suite

tiny_goal: Create a comprehensive benchmark suite measuring: page parse time, scene graph build time, action execution latency, evidence report generation, perspective query speed. Establishes baselines for optimization.

files_to_touch: tests/benchmarks/test_performance.py, .tini/netweaver/benchmarks/performance_baseline.md

acceptance_checks:
- benchmark_page_parse(): measures observer.parse() on 1KB, 10KB, 100KB pages
- benchmark_graph_build(): measures SceneGraphBuilder on 10, 100, 1000 node graphs
- benchmark_action_exec(): measures executor latency for click/fill/wait/navigate
- benchmark_evidence_report(): measures report generation for 10, 50, 100 claims
- benchmark_perspective_query(): measures query on 100, 500, 1000 node graphs
- Baseline thresholds: each benchmark must have upper bound (e.g., <50ms for 10KB parse)
- performance_baseline.md: auto-generated with current baselines
- CI-friendly: benchmarks fail if >2x baseline (regression detection)
- 10+ benchmark tests
- All existing tests remain green

## P-01 Metrics Anomaly Detector

tiny_goal: Add anomaly detection to the metrics system. Flag metrics that deviate >2 standard deviations from rolling average. Auto-alerts on: plan_gen >2x avg, test_duration >3x avg, cycle_time spike, failure rate increase.

files_to_touch: netweaver/anomaly_detector.py, tests/test_anomaly_detector.py, daemon.py

acceptance_checks:
- AnomalyDetector class with check(metric_name, value) → Optional[Anomaly]
- Rolling window: last 20 data points, compute mean + stddev
- Thresholds: configurable per-metric (default: 2σ for warning, 3σ for critical)
- Integration: daemon calls detector after each record_metric()
- Alerts logged to events.jsonl with type "anomaly_detected"
- AnomalyReport: metric, value, expected_range, severity, timestamp
- 15+ new tests
- All existing tests remain green

## P-02 Failure Pattern Digester

tiny_goal: Add intelligent failure analysis that groups repeated failures, identifies root cause patterns, and surfaces top-N stuck loops. Replaces raw failure logs with actionable digests.

files_to_touch: netweaver/failure_digester.py, tests/test_failure_digester.py, daemon.py

acceptance_checks:
- FailureDigester class with ingest(failure_event) → Optional[FailurePattern]
- Pattern detection: group by task_id + error_type, detect stuck loops (>3 same failure)
- Root cause hinting: match common patterns (import error, syntax, timeout, API 429)
- DigestReport: top-N patterns, affected tasks, suggested actions, time wasted
- Integration: daemon calls digester on record_failure(), logs digest every 10 failures
- Auto-kill stuck tasks: if same task_id fails 5+ times, quarantine it
- DigestEvent in events.jsonl with pattern summary
- 20+ new tests
- All existing tests remain green

## P-03 Daily Digest Cron

tiny_goal: Create a daily summary cron that reports: plans generated/approved/executed/failed, test pass rate, metrics trends, anomalies detected, stuck tasks, coverage changes. Delivered as markdown.

files_to_touch: ~/.hermes/scripts/daily_digest.py

acceptance_checks:
- Reads events.jsonl for last 24h
- Counts: plans_generated, plans_approved, plans_executed, plans_failed
- Test stats: pass/fail count, duration trend
- Metrics: avg plan_gen_time, test_duration, trend arrows (↑↓→)
- Anomalies: count and top-3 details
- Stuck tasks: list of quarantined tasks with failure counts
- Output: clean markdown summary, 500-1000 chars
- Cron: runs daily at 8AM, delivers to user
- Script-only (no LLM tokens)

## P-04 Cross-Project Infrastructure Scanner

tiny_goal: Extend the auto-backlog generator (NW-028) to scan Pipeline infrastructure too — not just NetWeaver modules. Detect: missing tests for daemon functions, unhandled edge cases in cleanup/metrics/reaper, missing monitoring for new features.

files_to_touch: netweaver/infra_scanner.py, tests/test_infra_scanner.py

acceptance_checks:
- scan_daemon(): check daemon.py for untested functions, missing error handling
- scan_scripts(): check ~/.hermes/scripts/ for missing tests, hardcoded values
- scan_crons(): verify all cron scripts exist, are executable, have output
- scan_tini(): check .tini/ for orphan files, missing expected files
- Each scan produces structured findings with severity (critical/warning/info)
- Auto-generates backlog entries for critical findings
- 15+ new tests
- All existing tests remain green

## P-05 Backup Integrity Verifier

tiny_goal: Add backup integrity verification — don't just check backups exist, verify they're restorable. Periodically test-restore from backup, compare with current state, detect corruption.

files_to_touch: netweaver/backup_verifier.py, tests/test_backup_verifier.py

acceptance_checks:
- BackupVerifier class with verify(backup_path, original_path) → VerifyResult
- Integrity check: backup file readable, valid encoding, non-empty
- Restore test: copy backup to temp, compare with original (diff)
- Corruption detection: detect if backup was truncated or zeroed
- Integration: cleanup_loop calls verifier weekly on random backup sample
- VerifyReport in events.jsonl: backup_path, original_path, status, diff_summary
- Auto-alert if >30% of verified backups fail integrity
- 10+ new tests
- All existing tests remain green
