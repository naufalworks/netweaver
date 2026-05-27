# Failure Ledger — self-healing patterns

## Known failure patterns

### FW-001: Context overflow
- symptoms: job last_status=error, model returns 429/empty, prompt is large
- diagnose: count chars in prompt. if >2000, overflow likely.
- fix: rewrite prompt to <500 chars. remove inlined content. use skills param.
- verify: run job one tick. check last_status=ok.
- added: 2026-05-24

### FW-002: Model unavailable
- symptoms: job last_status=error, all jobs error same model
- diagnose: test model endpoint directly with curl/simple query
- fix: if endpoint down → flag human. if model key wrong → switch to known-good model.
- verify: check next job tick
- added: 2026-05-24

### FW-003: Duplicate task IDs
- symptoms: watchdog detects duplicate_task_ids:N010,N011
- diagnose: grep KANBAN.md for ID pattern, find lines with same NW-XXX
- fix: renumber duplicates in KANBAN.md, keep latest content, drop stale.
- verify: run watchdog, check no duplicate_task_ids
- added: 2026-05-24

### FW-004: Worker has no task
- symptoms: job runs but produces empty or "nothing to do" repeatedly
- diagnose: check KANBAN ready section for that worker's lane
- fix: if no tasks AND ready queue < 3 → flag research to propose tasks. if no tasks for 7 days → propose archiving.
- verify: next job tick should pick a task
- added: 2026-05-24

### FW-005: Tests failing
- symptoms: watchdog detects tests=FAIL
- diagnose: run full test suite, capture failures
- fix: if regressions from recent changes → revert or fix. if pre-existing → skip test.
- verify: tests pass
- added: 2026-05-24
