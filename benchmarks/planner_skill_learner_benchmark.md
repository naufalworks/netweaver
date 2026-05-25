# Planner & Skill Learner Benchmark Plan

**Task**: NW-026
**Owner**: QA Benchmark
**Date**: 2026-05-24
**Status**: review

## Purpose

Define repeatable benchmark tasks and success metrics for two NetWeaver modules that lack dedicated benchmark coverage beyond unit tests:

1. **GoalTranslator** (`planner.py`) — template-based goal → ActionPlan translation with graph validation
2. **SkillLearner** (`skill_learner.py`) — successful execution → persistent skill with quality gate, dedup, merge

All benchmarks use **mocked graphs and stores** — no browser download, no Playwright, no network access required.

---

## Benchmark Tasks (12)

### PL-001: GoalTranslator Login Template Match

Translate "log into the website" with a graph containing fillable+clickable nodes. Verify template_name="login", confidence > 0, graph_validation=True.

**Pass criteria**:
- Returns PlanResult with template_name == "login"
- Plan has 3 steps (fill, fill, click)
- graph_validation == True
- confidence > 0.0

### PL-002: GoalTranslator Search Template Match

Translate "search for products" with fillable+clickable graph. Verify "search" template matched.

**Pass criteria**:
- template_name == "search"
- Plan has 3 steps (fill, click, wait)
- Confidence > 0.0

### PL-003: GoalTranslator Navigate Template Match

Translate "navigate to settings page" with clickable graph. Verify "navigate" template.

**Pass criteria**:
- template_name == "navigate"
- Plan has 2 steps (click, wait)

### PL-004: GoalTranslator Fill-Form Template Match

Translate "fill out the registration form" with fillable+clickable graph. Verify "fill-form" template.

**Pass criteria**:
- template_name == "fill-form"
- Plan has 2 steps (fill, click)

### PL-005: GoalTranslator Click-Confirm Template Match

Translate "confirm the order" with clickable graph. Verify "click-confirm" template.

**Pass criteria**:
- template_name == "click-confirm"
- Plan has 2 steps (click, wait)

### PL-006: GoalTranslator Fallback for Unknown Goals

Translate "download the PDF report" with any graph. No template matches. Verify fallback behavior.

**Pass criteria**:
- template_name is None
- confidence == 0.0
- Plan has 1 step (minimal fallback)

### PL-007: GoalTranslator Graph Validation Failure

Translate "log into the website" with an empty graph (no nodes). Template matches but graph validation fails.

**Pass criteria**:
- template_name == "login"
- graph_validation == False
- Plan still produced (validation is advisory)

### PL-008: GoalTranslator Custom Template

Add a custom template "add-to-cart" and verify it matches before built-in templates.

**Pass criteria**:
- Custom template matched
- add_template / list_templates work
- remove_template cleans up

### PL-009: SkillLearner Happy Path Learn

Learn a skill from a successful 3-step orchestration. Verify skill created with correct fields.

**Pass criteria**:
- learn() returns non-None SiteSkill
- Skill has non-empty action_plan steps
- Skill has non-empty goal

### PL-010: SkillLearner Quality Gate Rejection

Attempt to learn from a result that produces an empty-plan skill. Verify rejection.

**Pass criteria**:
- learn_and_store() returns (None, "rejected")

### PL-011: SkillLearner Dedup and Merge

Learn two skills with similar goals (Jaccard > 0.5) at the same URL. Verify second triggers merge.

**Pass criteria**:
- First learn_and_store() returns "created"
- Second learn_and_store() returns "merged"
- Merged skill has success_count incremented
- Merged skill has unioned learned_selectors

### PL-012: SkillLearner Failed Result Rejection

Attempt to learn from a FAILED OrchestrationResult. Verify rejection.

**Pass criteria**:
- learn() returns None
- learn_and_store() returns (None, "rejected")

---

## Scoring

| Metric | Formula | Threshold |
|--------|---------|-----------|
| Template match accuracy | correct / total | ≥ 95% |
| Fallback correctness | correct fallbacks / unknown goals | 100% |
| Skill creation rate | created / valid results | 100% |
| Merge accuracy | correct merges / similar pairs | 100% |
| Quality gate precision | rejected / invalid | 100% |

---

## Run

```bash
python -m pytest tests/benchmarks/test_planner_skill_learner_benchmark.py -v
```
