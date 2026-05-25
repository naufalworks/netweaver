# Phase 1 Metrics & Coverage Report

**Date**: 2026-05-25 (updated)
**Author**: QA Benchmark (glm/glm-5.1)
**Status**: Phase 1 COMPLETE — all modules green

---

## Summary

| Metric | Value |
|--------|-------|
| Total tests | 1150 passed (1116 NetWeaver + 34 TINI), 0 failed |
| Test suite runtime | 1.74s |
| Modules | 17 |
| Lines of code | 7507 |
| ADRs | 12 |
| Benchmark suites | 8 |
| Unit test files | 19 (tests/) + 7 benchmarks (tests/benchmarks/) |

---

## Test Distribution

### Unit Tests (tests/)

| Test File | Tests | Module |
|-----------|-------|--------|
| `test_wnal.py` | 82 | `wnal.py` |
| `test_planner.py` | 76 | `planner.py` |
| `test_action_orchestrator.py` | 71 | `action_orchestrator.py` |
| `test_scene_graph_builder.py` | 58 | `scene_graph_builder.py` |
| `test_graph_query.py` | 55 | `graph_query.py` |
| `test_executor.py` | 53 | `executor.py` |
| `test_leases.py` | 52 | `leases.py` |
| `test_scene_graph.py` | 50 | `scene_graph.py` |
| `test_site_skill.py` | 49 | `site_skill.py` |
| `test_skill_learner.py` | 45 | `skill_learner.py` |
| `test_perspective.py` | 40 | `perspective.py` |
| `test_executor_query_integration.py` | 39 | `executor.py` + `graph_query.py` |
| `test_observer_evidence_adapter.py` | 35 | `observer_evidence_adapter.py` |
| `test_tini.py` | 34 | `tini.py` (TINI) |
| `test_ledger.py` | 36 | `ledger.py` |
| `test_skill_matcher.py` | 41 | `skill_matcher.py` |
| `test_trace_writer.py` | 31 | `action_orchestrator.py` |
| `test_evidence.py` | 28 | `evidence.py` |
| `test_netweaver_observer.py` | 17 | `observer.py` |
| `test_e2e_integration.py` | 9 | Full pipeline |
| **Unit subtotal** | **901** | |

### Benchmark Tests (tests/benchmarks/)

| Benchmark File | Tests | Kanban |
|----------------|-------|--------|
| `test_skill_learning_benchmark.py` | 76 | NW-023 |
| `test_scenegraph_orchestrator_benchmark.py` | 60 | NW-018 |
| `test_planner_skill_learner_benchmark.py` | 36 | NW-026 |
| `test_observer_benchmark.py` | 31 | NW-003 |
| `test_executor_benchmark.py` | 26 | NW-010 |
| `test_pipeline_benchmark.py` | 12 | NW-011 |
| `test_phase1_capstone_benchmark.py` | 8 | NW-027 |
| **Benchmark subtotal** | **249** | |

**Breakdown**: 901 unit + 249 benchmark = **1150 total**. NetWeaver = 1150 - 34 (TINI) = **1116 NetWeaver**.

---

## Module Coverage Map

| Module | LOC | Unit Tests | Benchmark | Coverage |
|--------|-----|-----------|-----------|----------|
| `observer.py` | 372 | 17 ✅ | NW-003 ✅ | Full |
| `wnal.py` | 427 | 82 ✅ | — | Full |
| `evidence.py` | 410 | 28 ✅ | NW-006 ✅ | Full |
| `perspective.py` | 570 | 40 ✅ | — | Full |
| `scene_graph.py` | 452 | 50 ✅ | NW-018 ✅ | Full |
| `scene_graph_builder.py` | 629 | 58 ✅ | — | Full |
| `graph_query.py` | 616 | 55 ✅ | NW-018 ✅ | Full |
| `executor.py` | 722 | 53 + 39 ✅ | NW-010 ✅ | Full |
| `ledger.py` | 273 | 36 ✅ | — | Full |
| `leases.py` | 382 | 52 ✅ | — | Full |
| `action_orchestrator.py` | 1011 | 71 + 31 ✅ | NW-018 ✅ | Full |
| `observer_evidence_adapter.py` | 266 | 35 ✅ | — | Full |
| `site_skill.py` | 283 | 49 ✅ | NW-023 ✅ | Full |
| `skill_matcher.py` | 203 | 41 ✅ | NW-023 ✅ | Full |
| `skill_learner.py` | 259 | 45 ✅ | NW-026 ✅ | Full |
| `planner.py` | 631 | 76 ✅ | NW-026 ✅ | Full |
| `__init__.py` | 1 | — | — | — |

---

## Benchmark Coverage

| Benchmark Suite | Task | Tests | Status |
|-----------------|------|-------|--------|
| Observer Benchmark | NW-003 | 31 | ✅ Done |
| Evidence Report | NW-006 | — | ✅ Done |
| Executor Benchmark | NW-010 | 26 | ✅ Done |
| Pipeline Benchmark | NW-011 | 12 | ✅ Done |
| SceneGraph & Orchestrator | NW-018 | 60 | ✅ Done |
| Skill Learning | NW-023 | 76 | ✅ Done |
| Planner & Skill Learner | NW-026 | 36 | ✅ Done |
| Phase 1 Capstone | NW-027 | 8 | ✅ Done |

---

## Capstone Findings (NW-027)

### Finding 1: Planner → Orchestrator Description Gap (Medium)

**Description**: GoalTranslator generates template-level descriptions (e.g., "submit or login button") that don't directly resolve against scene graph nodes built from PageObservation. The graph resolver uses text/label matching against actual element text, not generic descriptions.

**Impact**: Planner output cannot be fed directly to orchestrator in Phase 1. Hand-crafted plans with concrete element descriptions must be used instead.

**Recommendation**: Phase 2 should add a "description adapter" step between planner and orchestrator that maps template descriptions to graph-resolvable ones using the current scene graph.

### Finding 2: Confidence Scoring Conservative (Low)

**Description**: Template keyword matching produces low confidence scores when goal keywords don't exactly match template keyword entries. E.g., "log into the website" → confidence 0.1 (graph boost only, no keyword hits).

**Impact**: Confidence scores are not useful for ranking competing templates in Phase 1.

**Recommendation**: Phase 2 should add fuzzy/stem matching (e.g., "log" matches "login") or use graph-based confidence.

---

## Changes Since Initial Report (2026-05-24)

| Change | Delta |
|--------|-------|
| Total tests | 1106 → 1150 (+44) |
| WNAL unit tests | 73 → 82 (+9 evidence round-trip) |
| Planner unit tests | 57 → 76 (+19 template expansion) |
| Runtime planner template count | 5 → 10 |
| ADRs | 10 → 12 (ADR-011 FillAction masking, ADR-012 evidence round-trip) |
| LOC | ~7400 → 7507 |
| Planner LOC | 490 → 631 |
| WNAL LOC | 354 → 427 |
| Evidence LOC | 392 → 410 |

---

## Phase 2 Benchmark Prerequisites

Before Phase 2 begins, these benchmark extensions are needed:

1. **Live Integration Benchmark** — test observer with real browser (CloakBrowser/Playwright)
2. **Executor Live Benchmark** — real click/fill/wait on test pages
3. **Skill Real-World Benchmark** — learn skills from live executions, measure reuse accuracy
4. **Safety Validation Benchmark** — test PerspectiveEngine on real risky actions

---

## No Forbidden Imports

All benchmark files pass AST scan for forbidden imports:
- playwright ✗
- cloakbrowser ✗
- selenium ✗
- puppeteer ✗

All imports are stdlib + internal `netweaver.*` only.
