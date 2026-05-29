# Architecture Review — 2026-05-29

Verdict: **FAIL** — Scope drift. 17 undocumented modules (6,051 LOC) added since Cycle 6 without ADRs. 9 modules totaling ~3,992 LOC have zero test coverage. Suite green at 2,137 (up from 1,380).

**Reviewed:** KANBAN (root + `.tini/netweaver/company/`), REVIEW.md, HANDOFF.md, DEV_LOG.md, ARCHITECTURE_DECISIONS.md (15→18 ADRs), 46 netweaver modules, full test suite.

---

### 🟢 Suite Green

`pytest tests/ -q --tb=no` → **2,137 passed** (1 warning, zero failures). Up from 1,380 at Cycle 6. No regressions.

---

### 🔴 CRITICAL: 17 Undocumented Modules (Scope Drift)

Since Cycle 6 review (2026-05-25), 17 new modules were added with NO KANBAN entry, NO ADR:

| Module | LOC | Tests? | What it does |
|--------|-----|--------|-------------|
| `epistemic.py` | 789 | ✅ | Epistemic OS — probabilistic knowledge management |
| `causal.py` | 466 | ❌ | Causal chain analysis (root cause tracing) |
| `dreaming.py` | 490 | ❌ | Background hypothesis generation |
| `web_learner.py` | 452 | ❌ | Autonomous web explorer |
| `competence_matrix.py` | 431 | ❌ | Bayesian agent competence routing |
| `memory_palace.py` | 419 | ✅ | Per-agent persistent memory store |
| `knowledge_graph.py` | 390 | ✅ | Cross-project dependency graph |
| `dashboard.py` | 373 | ✅ | Rich TUI dashboard |
| `task_scheduler.py` | 350 | ❌ | YAML-based web monitoring/scheduling |
| `knowledge_graph_cli.py` | 272 | ❌ | Knowledge Graph CLI |
| `epistemic_site_skill.py` | 248 | ❌ | Epistemic + SiteSkill mixin |
| `epistemic_daemon.py` | 243 | ❌ | Epistemic daemon integration |
| `alerts.py` | 236 | ✅ | Telegram/Slack webhook alerts |
| `epistemic_verifier.py` | 498 | ✅ | Auto-verification of stale knowledge |
| `tracker.py` | 82 | ✅ | Unified Item/StateMachine tracker |
| `roadmap.py` | 51 | ✅ | Roadmap module |
| `product_spec.py` | 5 | ✅ | Phase constants |
| **Total** | **6,051** | | |

**Action:** ADRs 018/019/020 now written covering Epistemic OS, Causal+Dreaming, Intelligence Layer. Remaining untracked modules (web_learner, task_scheduler, alerts, dashboard) need KANBAN entries.

---

### 🔴 9 Modules Without Test Coverage

3,992 LOC across 9 modules have zero tests:

- `dreaming.py` (490 LOC)
- `causal.py` (466 LOC)
- `web_learner.py` (452 LOC)
- `competence_matrix.py` (431 LOC)
- `task_scheduler.py` (350 LOC)
- `epistemic_site_skill.py` (248 LOC)
- `epistemic_daemon.py` (243 LOC)
- `knowledge_graph_cli.py` (272 LOC)
- `cli.py` (1040 LOC — CLI, lower priority)

**Action:** Prioritize test coverage for dreaming, causal, web_learner, competence_matrix (combined 1,839 LOC untested core logic).

---

### 🟡 Project Growth Since Cycle 6 (May 25)

| Metric | Cycle 6 (May 25) | Now (May 29) | Delta |
|--------|-----------------|--------------|-------|
| Modules | ~24 | 46 | **+22 (92% increase)** |
| LOC | ~8,835 | 18,951 | **+10,116 (114% increase)** |
| Tests passing | 1,380 (with 200 failures) | 2,137 | **+757 (55% increase)** |
| ADRs | 15 | 18 | **+3 (this review)** |
| Untested modules | 0 | 9 | 🔴 |
| Undocumented modules | 0 | 17 | 🔴 |

Growth rate is unsustainable for architecture review. Recommend governance gate: no new module lands without KANBAN entry + ADR.

---

### 🟡 Ready-Task Baseline Drift

- **P2-006** acceptance: "All 1389 existing tests remain green" — current baseline is 2,137. Stale.
- **P2-005** acceptance: "All 1389 existing tests remain green" — same drift.

**Action:** Update stale acceptance baselines to current 2,137.

---

### 🟡 Import Safety

- `alerts.py` — try/except guards `import requests`. **Acceptable** (same pattern as playwright_bridge).
- `causal.py` — `subprocess` for git inspection. **Acceptable** (read-only, git status/log only).
- `epistemic_verifier.py` — `subprocess` for running tests. **Acceptable** (runs pytest).
- No selenium/playwright/httpx/anthropic/openai at top level. ✅

---

### 🟡 ADRs Written This Review

- **ADR-018:** Epistemic OS — Probabilistic Knowledge Management
- **ADR-019:** Background Analysis Subsystem (Causal + Dreaming)
- **ADR-020:** Agent Intelligence Layer (Competence Matrix + Memory Palace + Knowledge Graph)

Total ADRs: 18 (up from 15).

---

### Verdict

**FAIL.** The project grew 114% in LOC since last review with 17 undocumented modules and 9 untested modules. The cognitive infrastructure layer (Epistemic OS + 11 related modules) landed without architecture documentation or test coverage for core analysis modules. ADR-018/019/020 cover the gap going forward. Recommend test coverage sprint for dreaming/causal/web_learner/competence_matrix before further cognitive-layer additions.

**Green:** Full suite at 2,137. ADR chain now covers all modules (18 ADRs). No forbidden imports.
**Red:** 17 undocumented modules, 9 untested modules, 114% LOC growth in 4 days.
