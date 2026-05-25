# Blockers

## RESOLVED (2026-05-24 03:55)

- ~~NW-016 orchestrator tests broken (33 failures)~~ — fixed by WNAL Engineer. `_make_graph()` now passes required args. 829/829 green.
- ~~NW-020 Retry, NW-019 Trace, NW-018 Benchmark, NW-017 E2E, NW-021 Site Skill~~ — all done, reviewed, green.

## 2026-05-24 12:00 WIB — Cron prompt template overflows worker context (NEW)

Issue: Cron prompt for ALL three preceding workers (qa-benchmark, wnal-engineer, runtime-engineer) inlines the full ~25K char hermes-agent skill doc. Workers receive ~25K of boilerplate before any instruction, consuming their entire context budget.

Impact: All three preceding jobs failed. Workers cannot function until template is fixed.

Recommended fix: Replace inline skill doc with `skill_view(name='hermes-agent')` in the cron prompt template. This is what the skill system is designed for.

## 2026-05-23 23:35 WIB — Legacy scene_builder.py dead code

Issue: ~~`netweaver/scene_builder.py` (352 LOC) exists on disk but is superseded by `scene_graph_builder.py` (NW-013, done). No active imports reference it.~~ **RESOLVED 2026-05-24 08:34** — removed by Runtime Engineer.

Impact: Confusing for new workers; may be accidentally used instead of the NW-013 builder.

Recommended fix candidate: remove `netweaver/scene_builder.py` or move to `netweaver/_legacy/scene_builder.py`.

## 2026-05-23 23:35 WIB — No initial git commit

Issue: `.gitignore` exists but no initial commit has been made. All project files show as `??` in `git status`.

Impact: No ownership attribution, no diff history, no rollback capability.

Recommended fix candidate: create initial commit with all tracked files.

## 2026-05-23 23:35 WIB — Cron review path mismatch (recurring)

Issue: Scheduled review prompts read `company/KANBAN.md`, `company/COMMUNICATION.md`, `company/SAFETY.md`, `ROADMAP.md` from root. None exist. Canonical docs are at `.tini/netweaver/company/KANBAN.md` and `~/Documents/myhermes/`.

Impact: Every review run wastes cycles discovering path mismatch.

Recommended fix candidate: update cron prompts to point to `~/Documents/myhermes/.tini/netweaver/company/` as canonical path.

## 2026-05-23 23:35 WIB — PROJECT_GOAL.md still TINI-oriented (recurring)

Issue: `PROJECT_GOAL.md` describes TINI anti-hallucination wrapper, not NetWeaver/Cloak Net Agent.

Impact: Goal-alignment checks produce noise.

Recommended fix candidate: update to NetWeaver mission or add redirect note.

## RESOLVED (2026-05-24 12:00)

- ~~High-risk safety confirmation mismatch~~ — fix confirmed: `risk_level == "high"` now resolves `ASK`.
- ~~Kanban duplicate IDs (NW-009/NW-010/NW-011/NW-012)~~ — all resolved, NW-001→NW-016 unique.
- ~~Executor/WNAL precondition regression~~ — suite green (608 non-orchestrator passed).
- ~~Scene builder untested~~ — superseded by NW-013 (58 tests).
- ~~Missing Kanban entries for myhermes work~~ — now comprehensive NW-001→NW-016.

## RESOLVED (2026-05-23 23:35)

The following blockers from earlier reviews are now resolved:
- ~~Kanban duplicate IDs~~ — all IDs unique (NW-001→NW-015).
- ~~Executor/WNAL API regression~~ — suite green (608 passed).
- ~~scene_builder shipped without tests~~ — superseded by `scene_graph_builder.py` (NW-013, 58 tests).
- ~~Scene builder has no Kanban entry~~ — tracked as NW-013 (done).
- ~~High-risk safety confirmation mismatch~~ — fixed (`risk_level == "high"` → `ASK`).
- ~~Adapter work missing Kanban task~~ — tracked in Kanban.
- ~~Safety fix missing Kanban task~~ — tracked in Kanban.
- ~~Kanban stale for myhermes workspace~~ — now comprehensive (NW-001→NW-015).
- ~~Ledger default path mismatch~~ — NW-010 marked done with acceptance noted.

## 2026-05-23 14:36 WIB — Coordination docs missing

Issue: Safety/integration review prompt requires files that are absent:
- `company/KANBAN.md`
- `company/COMMUNICATION.md`
- `company/SAFETY.md`
- `STATUS.md`
- `ROADMAP.md`

Impact: Cannot fully verify worker ownership, lane conflicts, stale candidates, roadmap alignment, or communication completeness.

Recommended fix candidate: create minimal coordination scaffold before next swarm run; include Runtime/WNAL/QA ownership table and current NetWeaver milestone.

## 2026-05-23 14:36 WIB — Project goal drift

Issue: `PROJECT_GOAL.md` describes TINI anti-hallucination wrapper, while active swarm work targets NetWeaver/Cloak Net Agent.

Impact: Goal-alignment checks can produce false positives/negatives.

Recommended fix candidate: update root goal or split TINI and NetWeaver into separate workdirs/projects.

## 2026-05-23 15:04 WIB — High-risk safety confirmation mismatch

Issue: `netweaver/perspective.py::SafetyPerspective` marks `risk_level == "high"` as “requires user confirmation”, but `PerspectiveEngine._resolve_conflicts()` returns `ABORT` for that high-confidence safety concern unless it is `critical` or payment.

Impact: Product semantics drift from intended human-confirmation flow; high-risk but reversible tasks cannot enter `ASK` state.

Recommended fix candidate: add resolver branch for safety evidence `risk_level == "high"` → `ResolutionStrategy.ASK`, with regression test covering otherwise-safe action + high safety risk.

## 2026-05-23 15:04 WIB — Worktree isolation still unresolved

Issue: `git status --short` from current review dir reports broad parent/home changes and `.Trash` permission warning.

Impact: Cannot reliably attribute changes to Runtime/WNAL/QA lanes or detect file ownership conflicts.

Recommended fix candidate: run NetWeaver swarm in a dedicated git repo/worktree rooted at this project, or initialize/enter correct repo before worker tasks.

## 2026-05-23 15:27 WIB — Roadmap source still missing

Issue: Review prompt requires `ROADMAP.md`, but no root `ROADMAP.md` exists. Current task direction is recoverable only from `VISION_CLOAK_NET_AGENT.md` and `.tini/netweaver/company/KANBAN.md`.

Impact: Roadmap alignment checks remain partial and can drift as Kanban grows.

Recommended fix candidate: create `ROADMAP.md` with NetWeaver milestones or add an explicit pointer to the canonical roadmap file.

## 2026-05-23 16:57 WIB — Adapter work missing Kanban task

Issue: `netweaver/observer_evidence_adapter.py` and `tests/test_observer_evidence_adapter.py` are in review via handoff, but `.tini/netweaver/company/KANBAN.md` has no matching task id/owner/scope/status.

Impact: Reviewer cannot cleanly move the work review -> done/blocked; ownership/stale-state checks are noisy.

Recommended fix candidate: add an explicit adapter task (e.g. NW-009 Observer→Evidence Adapter) or fold the adapter into NW-004 as a prerequisite with reviewed acceptance criteria.

## 2026-05-23 17:24 WIB — Safety fix missing Kanban task

Issue: `netweaver/perspective.py` high-risk confirmation fix and new `tests/test_perspective.py` regression coverage appear landed, but `.tini/netweaver/company/KANBAN.md` has no corresponding task id/owner/status.

Impact: Safety review can verify behavior, but cannot cleanly move the work review → done or attribute ownership.

Recommended fix candidate: add a completed/reviewed Kanban task (e.g. NW-010 High-Risk Safety Confirmation) with scope `netweaver/perspective.py`, `tests/test_perspective.py`, acceptance `risk_level == "high" resolves ASK`.

## 2026-05-23 17:42 WIB — Root docs still point reviewers at stale/noisy source

Issue: Scheduled review prompt asks for root `company/*` and `ROADMAP.md`, but canonical NetWeaver docs live under `.tini/netweaver/`; root `PROJECT_GOAL.md` and `DEV_LOG.md` still primarily describe TINI.

Impact: Repeated reviewer runs spend cycles rediscovering path/source-of-truth mismatch and risk false goal-alignment findings.

Recommended fix candidate: add root pointer docs (`ROADMAP.md`, `company/*`) that redirect to `.tini/netweaver/`, or update cron prompt paths to the canonical NetWeaver docs.

## 2026-05-23 18:13 WIB — Duplicate Kanban task ID

Issue: `.tini/netweaver/company/KANBAN.md` uses `NW-009` for two tasks: Project Hygiene Enforcement (ready) and Verified Click Executor (review).

Impact: Reviewer cannot safely move `NW-009` review → done/blocked without ambiguity; ownership/status automation may corrupt the wrong task.

Recommended fix candidate: rename one task before next review transition, e.g. hygiene → `NW-010` or executor → `NW-011`, preserving scope and verification notes.

## 2026-05-23 20:27 WIB — Full suite red: executor/WNAL API mismatch

Issue: `python -m pytest tests/ -q` fails with `71 failed, 328 passed in 2.00s`. Representative error: `AttributeError: 'ClickAction' object has no attribute 'get_preconditions'` at `netweaver/executor.py:384`; same mismatch affects `FillAction` and `WaitAction` executor paths.

Impact: Cannot mark `NW-009` executor, `NW-010` ledger, or `NW-012` leases review work done while shared suite is failing. Pipeline benchmark and executor benchmark are broken.

Recommended fix candidate: restore `get_preconditions()` on typed actions or update `VerifiedExecutor._check_preconditions()` to use the current WNAL precondition API; add regression tests for click/fill/wait precondition checking.

## 2026-05-23 20:27 WIB — Expanded duplicate Kanban task IDs

Issue: `.tini/netweaver/company/KANBAN.md` now contains duplicate IDs beyond prior `NW-009`: `NW-010` is both EvidenceBundle + Action Ledger and Executor Benchmark Suite; `NW-011` is both Worker FSM Protocol and Full Pipeline Benchmark; `NW-012` is both Project Hygiene Enforcement and File Lease System.

Impact: Review transitions and ownership attribution are ambiguous; moving any duplicate-numbered task to done/blocked may corrupt the wrong task state.

Recommended fix candidate: assign unique IDs to all ready/review/done tasks before next review transition, preserving owner/scope/status and benchmark completion notes.

## 2026-05-23 20:27 WIB — Ledger default path may miss project acceptance

Issue: `ActionLedger` default path is `Path.home() / ".hermes" / ".tini" / "netweaver" / "ledger.jsonl"`, but `NW-010` acceptance says append JSONL ledger events under project `.tini/netweaver/ledger.jsonl`.

Impact: Ledger events may be written outside the reviewed project/worktree, weakening auditability and making tests pass with an explicit temp path while runtime default violates task acceptance.

Recommended fix candidate: decide canonical storage root; if project-local, derive from cwd/project root or accept explicit path and document no unsafe home-profile default.

## 2026-05-23 22:12 WIB — Kanban completely stale for myhermes workspace

Issue: `.tini/netweaver/company/KANBAN.md` only has NW-001→NW-005 (all DONE). The `~/Documents/myhermes/` workspace has delivered NW-006+ work (evidence, perspective, executor, ledger, leases, scene_graph, observer_evidence_adapter, safety fix) with no Kanban entries. Prior review docs in `~/Documents/myhermes/` referenced NW-009/010/011/012 but those IDs don't exist in the actual Kanban file.

Impact: Reviewer cannot formally move any myhermes-delivered task to done/blocked. Ownership attribution and progress tracking are completely broken for the main workspace.

Recommended fix candidate: create comprehensive Kanban entries covering all delivered myhermes work, or merge the two workspaces into a single source-of-truth Kanban.

## 2026-05-23 22:25 WIB — scene_builder.py shipped without tests

Issue: `netweaver/scene_builder.py` (352 LOC, timestamped 22:00) was committed by Runtime/WNAL lane with zero test coverage. No `tests/test_scene_builder.py` exists. No test file references any scene_builder export.

Impact: First NetWeaver module to ship without tests. Process regression. Cannot verify correctness of builder pipeline (observer → scene graph conversion, edge creation, query helpers, evidence attachment).

Recommended fix candidate: Runtime/WNAL Engineer writes `tests/test_scene_builder.py` covering `build_scene_graph`, `element_to_dom_node`, `element_to_accessibility_node`, `element_to_visual_node`, `network_to_network_node`, `get_actionable_element_nodes`, `get_network_health`, `get_element_actionability`, plus edge cases (empty page, no network, evidence attachment).

## 2026-05-23 22:25 WIB — scene_builder has no Kanban entry

Issue: `netweaver/scene_builder.py` is not tracked in `.tini/netweaver/company/KANBAN.md`. No task ID, owner, scope, or acceptance criteria.

Impact: Reviewer cannot formally move scene builder work to done/blocked. Contributes to ongoing Kanban stale/incomplete state for myhermes workspace.

Recommended fix candidate: create Kanban entry (e.g. NW-013 Observer→SceneGraph Builder) or fold into NW-004 scope update with explicit scene_builder.py + test file in scope.

## 2026-05-23 22:12 WIB — Cron review path mismatch continues

Issue: Scheduled review prompts read `company/KANBAN.md`, `company/COMMUNICATION.md`, `company/SAFETY.md`, `ROADMAP.md` from root. None exist. Canonical docs are split between `.tini/netweaver/` and `~/Documents/myhermes/`.

Impact: Every review run wastes cycles discovering path mismatch and working from partial state. Recommend updating cron prompts to point to `~/Documents/myhermes/` as primary workspace.
