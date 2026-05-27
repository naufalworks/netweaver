# STATE — NetWeaver (project view)

Last updated: 2026-05-25 12:30

## Project Health

- 1380 tests ✅ passing (was 1354 before executor.py corruption)
- daemon.py: heartbeat fix applied ✅, file rollback added ✅
- executor.py: fully reconstructed ✅ (daemon had overwritten with broken LLM code)
- circuit_breaker.json: active ✅

## Active Work

| Component | Status | Notes |
|-----------|--------|-------|
| VerifiedExecutor | ✅ | Full test suite passing |
| SceneGraph resolution | ✅ | Intent nodes + safety check + DOM fallback |
| Perspective engine | ✅ | ABORT + ASK strategies block execution |
| Evidence report | ✅ | Pre/post claims, observations, verify |
| Wait actions | ✅ | timeout_ms=5000 default |
| Fill actions | ✅ | editable precondition check |
| Click actions | ✅ | visible/enabled/stable/pointer_events gates |
| Graph click/fill/wait | ✅ | Exact affordance match + wait fallback |
| cloak_bridge | ❌ | 23 test failures (pre-existing, out of scope) |
| observer_evidence_adapter | ❌ | 18 test failures (pre-existing, out of scope) |

## Recent Fixes (this session)

1. **executor.py reconstruction** — daemon's LLM overwrite removed `VerifiedExecutor`, `GraphResolvedTarget`, `ResolutionStatus`; used wrong API calls (fill_value, in_viewport, BLOCK). Full rewrite using correct project APIs.

2. **execute_step file rollback** — saves file content before writing, reverts on test failure. Prevents future broken file pollution.

3. **Graph resolution safety check** — detects safety enrichment nodes with strategy=abort → returns SAFETY_BLOCKED.

4. **Perspective blocking** — both ABORT and ASK strategies now block execution (was only ABORT).

5. **Daemon heartbeat fix** — increased timeout to 600s, added `claude-combo` model awareness.

## Blockers

- cloak_bridge tests (23 failures) — pre-existing, unrelated to executor
- observer_evidence_adapter tests (18 failures) — pre-existing
