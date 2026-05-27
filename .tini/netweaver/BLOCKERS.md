# NetWeaver Blockers

(No active blockers.)

## 2026-05-27 — [RESOLVED] NW-026 Circuit Breaker Fix

Resolved: `record_success()` was not clearing `paused_until` timestamp. After circuit breaker tripped, agents could never recover even after a successful run. Fixed by adding `cb[agent]["paused_until"] = None` to `record_success()`. Also added `parse_kanban_done()` to detect_gaps() to prevent duplicate plan generation for completed tasks. All 1446 tests green.

## 2026-05-26 — [RESOLVED] Architect target mismatch

Resolved: Subsequent Architect runs correctly target Python project — produced NW-016 done handoff + NW-017 backlog entry confirming Python project awareness. All implementation paths point at Python codebase.

## 2026-05-24T01:38 — [RESOLVED] Architect target mismatch (TypeScript vs Python)

## 2026-05-25T00:45 — NW-016 action orchestrator 2 test failures [RESOLVED]

Issue: NW-016 Action Orchestrator had 2 test failures — `test_resolution_failure_halts_plan` (error message mismatch) and `test_evidence_chain_collected` (Observation missing timestamp). Both have been fixed by a subsequent run. All 55 orchestrator tests now pass.

## 2026-05-24T22:50 — stale review queue [RESOLVED]
## 2026-05-23T07:12:11Z — review blocker [RESOLVED]
## 2026-05-23T11:04Z — kanban id collision [RESOLVED]
