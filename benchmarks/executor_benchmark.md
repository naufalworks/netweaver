# Executor Benchmark Plan

**Task**: NW-010
**Owner**: QA Benchmark
**Date**: 2026-05-23
**Status**: review

## Purpose

Define repeatable benchmark tasks and success metrics for the NetWeaver Verified Executor. The executor implements a 6-phase evidence-first pipeline: PRE → PRECONDITION → PERSPECTIVE → EXECUTE → POST → VERIFY.

All benchmarks use **mocked callbacks** — no browser download, no Playwright, no network access required.

---

## Benchmark Tasks (6)

### E-001: Happy Path Click — Full Pipeline

A simple click on a visible, enabled button with no safety concerns.

- Pre/post evidence: all actionability flags true
- Perspective: all safe (no risk context)
- Expected: SUCCESS, evidence report with supported claims

**Pass criteria**:
- ExecutionStatus == SUCCESS
- Evidence report verifies (all claims supported)
- Pre and post observations present
- Unique execution ID generated
- Duration recorded

**Metric**: pipeline completion rate, claim support rate

---

### E-002: Precondition Gate — Invisible Element

Click attempt on a hidden element (visible=false).

- Pre evidence: visible=false
- Expected: PRECONDITION_FAILED at PRE phase, no execution

**Pass criteria**:
- ExecutionStatus == PRECONDITION_FAILED
- No EXECUTE phase reached
- No post evidence collected
- Evidence report shows precondition claim

**Metric**: precondition detection accuracy (100%)

---

### E-003: Perspective Safety Gate — Critical Risk

Click attempt on a visible element in a high-risk context (payment form).

- Pre evidence: all flags true
- Perspective: SafetyPerspective returns critical risk
- Expected: PERSPECTIVE_BLOCKED with ABORT strategy

**Pass criteria**:
- ExecutionStatus == PERSPECTIVE_BLOCKED
- Resolution strategy == ABORT
- No EXECUTE phase reached
- Evidence report links safety observation

**Metric**: safety gate accuracy

---

### E-004: Perspective Safety Gate — High Risk (ASK)

Click attempt on a visible element with high (non-critical) risk.

- Pre evidence: all flags true
- Perspective: SafetyPerspective returns high risk
- Expected: PERSPECTIVE_BLOCKED with ASK strategy

**Pass criteria**:
- ExecutionStatus == PERSPECTIVE_BLOCKED
- Resolution strategy == ASK
- No EXECUTE phase reached

**Metric**: risk tiering accuracy (critical vs high vs low)

---

### E-005: Execution Failure — Executor Error

Click attempt on a valid element where executor callback raises exception.

- Pre evidence: all flags true
- Perspective: all safe
- Executor: raises RuntimeError
- Expected: EXECUTION_ERROR

**Pass criteria**:
- ExecutionStatus == EXECUTION_ERROR
- Error captured in execution record
- No post evidence collected

**Metric**: error propagation accuracy

---

### E-006: Multiple Preconditions — Fill Action

Fill action on a disabled, non-editable input.

- Pre evidence: enabled=false, editable=false
- Expected: PRECONDITION_FAILED (first failed condition detected)

**Pass criteria**:
- ExecutionStatus == PRECONDITION_FAILED
- No EXECUTE phase reached
- Reports which precondition(s) failed

**Metric**: compound precondition detection

---

## Success Metrics Summary

| Metric | Target | Measurement |
|--------|--------|-------------|
| Pipeline phase completion | 100% (happy path) | All 6 phases execute |
| Precondition gate accuracy | 100% | Failed preconditions always blocked |
| Safety gate accuracy | 100% | Critical → ABORT, high → ASK, low → pass |
| Error propagation | 100% | Executor errors captured, not swallowed |
| Evidence report verification | 100% | All happy-path claims supported |
| Unique execution IDs | 100% | No ID collisions across runs |
| Phase ordering | 100% | PRE → PRECOND → PERSP → EXEC → POST → VERIFY |

## Scoring

```
task_score = (phase_accuracy * 0.3) + (evidence_completeness * 0.3) +
             (gate_accuracy * 0.2) + (error_handling * 0.2)
```

**Overall benchmark score** = mean of 6 task scores.

| Score | Rating |
|-------|--------|
| 90–100 | Excellent |
| 75–89 | Good |
| 60–74 | Acceptable |
| < 60 | Needs work |

---

## Test Execution

```bash
python -m pytest tests/benchmarks/test_executor_benchmark.py -v
```

No browser download, no network, no Playwright required.
