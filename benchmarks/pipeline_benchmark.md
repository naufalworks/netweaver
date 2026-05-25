# Full Pipeline Benchmark Plan

**Task**: NW-011
**Owner**: QA Benchmark
**Date**: 2026-05-23
**Status**: review

## Purpose

Integration benchmark: Observer → Evidence → Perspective → Executor pipeline.
Tests that the complete NetWeaver stack produces consistent, verifiable output
when modules are chained together. No browser download required.

---

## Benchmark Tasks (4)

### P-001: Observe → Evidence Report

Feed a fixture through the observer, convert to evidence report.

**Steps**:
1. Load `static_page.json` fixture
2. Create mock PageObservation from fixture
3. Run `observation_to_report()` adapter
4. Verify evidence report

**Pass criteria**:
- Report verifies (all claims supported)
- Every interactive element produces at least 1 DOM observation
- Every actionability flag produces at least 1 ACTIONABILITY observation
- Report summary counts match element count

**Metric**: observation coverage (elements → observations)

---

### P-002: Observe → Evidence → Perspective Analysis

Feed fixture through observer, create evidence report, run perspective analysis.

**Steps**:
1. Load `form_page.json` fixture
2. Create mock observation + evidence report
3. Build perspective context from report
4. Run PerspectiveEngine.analyze()
5. Verify safe resolution (ACTION)

**Pass criteria**:
- Perspective engine returns ConflictResolution
- Strategy == ACTION for normal form page
- All 7 perspectives assessed
- No missing perspective errors

**Metric**: perspective coverage (7/7 perspectives run)

---

### P-003: Observe → Evidence → Executor — Blocked Element

Full pipeline: observer detects hidden element → executor blocks.

**Steps**:
1. Load `spa_page.json` fixture
2. Find hidden element (a[href='/hidden'])
3. Create WNAL ClickAction for hidden element
4. Create mock pre-evidence with visible=false
5. Run executor
6. Verify PRECONDITION_FAILED

**Pass criteria**:
- Executor returns PRECONDITION_FAILED
- No action executed
- Evidence report present
- Failed precondition identified (visible)

**Metric**: end-to-end blocking accuracy

---

### P-004: Observe → Evidence → Executor — Happy Path Click

Full pipeline for a safe, actionable element.

**Steps**:
1. Load `static_page.json` fixture
2. Find the submit button
3. Create WNAL ClickAction
4. Create mock pre/post evidence (all true)
5. Run executor with safe perspective context
6. Verify SUCCESS + verified evidence report

**Pass criteria**:
- ExecutionStatus == SUCCESS
- Evidence report verifies
- Pre and post observations linked to claims
- All claims supported

**Metric**: end-to-end success rate

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Pipeline stage completion | 4/4 stages chain correctly |
| Evidence report verification | 100% happy-path claims supported |
| Perspective coverage | 7/7 perspectives |
| End-to-end blocking | Hidden elements blocked 100% |
| End-to-end success | Safe elements execute 100% |

## Scoring

```
task_score = (stage_completion * 0.25) + (evidence_verification * 0.25) +
             (perspective_coverage * 0.25) + (end_to_end_accuracy * 0.25)
```

## Execution

```bash
python -m pytest tests/benchmarks/test_pipeline_benchmark.py -v
```

No browser, no Playwright, no network.
