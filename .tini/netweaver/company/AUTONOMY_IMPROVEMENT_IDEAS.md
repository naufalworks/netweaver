# Autonomy Improvement Ideas

## Why `git diff unavailable` happened
Fresh local repo had no baseline commit; all files were untracked. `git diff` only shows tracked-file changes, so tools relying only on `git diff` saw no paths. Fix: include staged + untracked paths in risk scanner.

## Best next upgrades

### 1. EvidenceBundle gate
Every task output creates structured evidence:
- task id
- files changed
- diff/ref
- commands run
- test results
- claims -> evidence refs
- risk

### 2. FSM worker protocol
Replace loose agent behavior with states:
PLAN -> INSPECT -> PATCH -> TEST -> REVIEW -> DONE
Failure paths: TRIAGE, BLOCKED, HUMAN_GATE.

### 3. Append-only action ledger
Record task events as durable JSONL:
- timestamp
- agent
- state
- action
- files
- command result
- evidence ref

### 4. Blackboard memory
Separate:
- Facts: verified only
- Hypotheses: unverified
- Decisions: owner + TTL
- Tasks: Kanban refs
- Artifacts: diffs/tests/logs

### 5. File lease system
Agents must claim file scopes before edits. Conflicts go to review queue.

### 6. Eval harness from failures
Every failed/stuck run becomes a regression eval.

### 7. Stuck-loop detector
Detect repeated errors, oscillating files, growing diffs without tests improving.

### 8. Patch minimizer
After passing tests, remove unrelated edits/debug logs and shrink diff.

### 9. Invariant tests
Always check:
- no secrets
- no vendor edits
- no broad config/deploy changes without review
- task id present
- tests pass

### 10. Risk-based human gate
High-risk patch requires rollback plan + extra review.

## Recommended MVP order
1. EvidenceBundle schema
2. JSONL action ledger
3. FSM status per task
4. file lease metadata
5. stuck-loop detector
6. eval harness
