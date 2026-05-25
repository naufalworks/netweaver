# Phase 1 Capstone Benchmark Plan

**Task**: NW-027
**Owner**: QA Benchmark
**Date**: 2026-05-24
**Status**: review

## Purpose

Validate the complete Phase 1 lifecycle: **observe → plan → execute → verify → learn**.

This benchmark exercises every module in sequence, proving that the full
NetWeaver data layer integrates end-to-end. It goes beyond the existing
NW-017 E2E test by including the planner (GoalTranslator) and skill
learner (SkillLearner) in the pipeline.

All benchmarks use **mocked data** — no browser download, no Playwright,
no network access required.

---

## Benchmark Tasks (8)

### C-001: Full Lifecycle — Login Flow

Observe a login form → build graph → translate goal → orchestrate → learn skill.

**Pass criteria**:
- PageObservation produces scene graph with DOM + INTENT nodes
- GoalTranslator produces ActionPlan for "log into the website"
- OrchestrationResult status is COMPLETED
- SkillLearner creates a persistent skill from the result
- Skill has non-empty goal, steps, and preconditions

### C-002: Full Lifecycle — Search Flow

Observe a search page → plan "search for items" → execute → learn.

**Pass criteria**:
- GoalTranslator matches "search" template
- Plan has FILL + CLICK + WAIT steps
- Skill created and persisted

### C-003: Plan-then-Orchestrate Integration

Plan a login, then feed the plan to the orchestrator (not hand-crafted).

**Pass criteria**:
- Plan from GoalTranslator used directly in orchestrator
- Orchestrator completes all steps from the plan

### C-004: Failed Orchestration Does Not Learn

Execute a failing orchestration and verify learner rejects it.

**Pass criteria**:
- OrchestrationResult status is FAILED or ROLLED_BACK
- learn_and_store returns (None, "rejected")

### C-005: Skill Reuse After Learning

Learn a skill, then verify SkillMatcher can find it for the same site.

**Pass criteria**:
- SkillMatcher returns the learned skill as top match
- Match score > 0.5

### C-006: Multi-Goal Planning Diversity

Translate 5 different goals, verify at least 4 unique templates matched.

**Pass criteria**:
- 5 translations produce ≥ 4 unique template_name values
- Fallback (None) counts as a unique template

### C-007: Confidence Score Distribution

Verify confidence scores are well-distributed across templates.

**Pass criteria**:
- All template-matched plans have confidence > 0.0
- Fallback plans have confidence == 0.0
- At least one plan has graph_validation == True

### C-008: No Forbidden Imports

Verify no browser/Playwright/vendor imports in test file.

**Pass criteria**:
- AST scan finds zero forbidden imports

---

## Run

```bash
python -m pytest tests/benchmarks/test_phase1_capstone_benchmark.py -v
```
