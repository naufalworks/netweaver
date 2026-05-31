# Architecture Review — 2026-05-31

Verdict: **FAIL** — Scope drift continues (decelerated). 4 modules still uncovered. 9 untested. 2 flaky live tests. 1 hanging test.

**Reviewed:** KANBAN (root + `.tini/netweaver/company/`), REVIEW.md, HANDOFF.md, DEV_LOG.md, ARCHITECTURE_DECISIONS.md (21→24 ADRs), 49 netweaver modules (19,906 LOC), partial test suite.

---

### 🟢 Suite Mostly Green

`pytest tests/ -k "not test_observe_httpbin and not test_orchestrator_multi_step and not test_verify_stale" --ignore=tests/test_epistemic_verifier.py -m "not live"` → **2,186 passed** (11 deselected live tests, 1 warning).

Flaky (network-dependent):
- `test_observe_httpbin_form` — depends on httpbin.org reachability
- `test_orchestrator_multi_step_plan_graceful` — depends on real site orchestration
- `test_verify_stale_knowledge_with_stale` — **hangs** (subprocess invokes full suite which exceeds timeout)

---

### 🔴 4 Modules Still Uncovered by ADRs (from last review)

Persistent since May 29 review — still no ADR, still no KANBAN entry:

| Module | LOC | Function |
|--------|-----|----------|
| `web_learner.py` | 452 | Autonomous web explorer — crawls sites to learn interaction patterns |
| `task_scheduler.py` | 350 | YAML-based web monitoring/scheduling daemon |
| `alerts.py` | 236 | Telegram/Slack webhook alert dispatcher |
| `ledger.py` | 273 | Event ledger (duplicate of event_ledger.py?) — path coordination needed |

**Total: 1,311 LOC undocumented.** Action: write ADRs or formally deprecate. These have been flagged 2 consecutive reviews.

---

### 🔴 9 Untested Modules (unchanged)

No test coverage improvement since last review:

| Module | LOC |
|--------|-----|
| `dreaming.py` | 490 |
| `causal.py` | 466 |
| `web_learner.py` | 452 |
| `competence_matrix.py` | 431 |
| `task_scheduler.py` | 350 |
| `knowledge_graph_cli.py` | 272 |
| `epistemic_daemon.py` | 243 |
| `epistemic_site_skill.py` | 248 |
| `cli.py` | 1040 |

**Total: 3,992 LOC untested.** Recommended: test coverage sprint for dreaming/causal/web_learner/competence_matrix as noted last review.

---

### 🟡 Growth Since Last Review (May 29)

| Metric | May 29 | May 31 | Delta |
|--------|--------|--------|-------|
| Modules | 46 | 49 | **+3 (7% increase)** |
| LOC | 18,951 | 19,906 | **+955 (5% increase)** |
| Tests passing | 2,137 | ~2,186 | **+49 (2% increase)** |
| ADRs | 18 | 24 | **+6 (33% increase)** |
| Untested modules | 9 | 9 | — |
| Uncov. modules | 4 | 4 | — |

**Growth rate decelerated significantly** vs last review's 114% LOC surge. ADR count now covers 22/26 total modules.

---

### 🟡 New This Cycle (May 29→31)

| KANBAN | Module(s) | LOC | Tests | ADR |
|--------|-----------|-----|-------|-----|
| NW-034 | `dsl_validator.py` | 497 | 70 | ✅ ADR-022 |
| NW-035 | `skill_learner_auto.py`, `skill_store.py` | 955 | 58 | ✅ ADR-021 |
| NW-036 | test-only (perspective scenarios) | — | 47 | N/A (tests) |

---

### 🟡 ADRs Written This Review

- **ADR-022:** DSL Validator for WNAL and BASIL Syntax (`dsl_validator.py`, NW-034)
- **ADR-023:** Quality Automation Tooling Suite (`backlog_generator.py`, `test_healer.py`, `evidence_report.py`, `dashboard.py`)
- **ADR-024:** File Lease Coordination for Multi-Agent Swarm (`leases.py`)

Total ADRs: 24 (up from 21).

---

### 🟡 Stale Acceptance Baselines

- **P2-006 acceptance**: "All 1389 existing tests remain green" — suite is now ~2,186. **STALE.**
- **P2-005 acceptance** (not visible in current KANBAN excerpt): likely same drift.
- **Root KANBAN.md**: shows 28 done + 2 ready with claude-combo model. Canonical KANBAN at `.tini/` has 36+ entries.

---

### 🟡 Epistemic Verifier Test Hangs

`test_verify_stale_knowledge_with_stale` in `test_epistemic_verifier.py` calls `verify_stale_knowledge()` which runs `subprocess` pytest — hangs because the test suite now exceeds a sub-second run. **Bug**: the verifier should not invoke the full suite in a unit test; it should mock the subprocess call.

---

### 🔴 Persistent (Since Cycle 1)

- **No git commit** — all 19,906 LOC untracked. No blame, no rollback, no diff history.
- **Root KANBAN.md stale** — real tracking is `.tini/netweaver/company/KANBAN.md`

---

### Verdict

**FAIL.** Scope drift continues — 4 modules (1,311 LOC) still uncovered by ADRs after 2 consecutive reviews flagged them. 9 modules (3,992 LOC) remain untested. One epistemic verifier test hangs due to unbounded subprocess call. Two live tests flaky on network.

**Green:** Suite stable at ~2,186 (pre-flaky). ADR chain now covers 22/26 modules (85%). Growth decelerated from +10,116 LOC to +955 LOC. KANBAN is comprehensive in `.tini/`. No forbidden imports, no safety issues.

**Red:** 4 uncovered modules persistent 2 reviews. 9 untested modules unchanged 2 reviews. No git history. Stale P2-006 acceptance baseline. Epistemic verifier test hangs.
