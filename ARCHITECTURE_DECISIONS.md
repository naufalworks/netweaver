# Architecture Decisions

## ADR-001: Actionability Evidence Envelope

Status: Accepted (2026-05-23)

NetWeaver records CloakBrowser actionability checks as verifier input, not executor behavior. The executor still delegates interaction to CloakBrowser/Playwright-compatible actions; the verifier consumes a typed evidence envelope before and after interaction.

Minimal envelope fields:

```json
{
  "action_id": "string",
  "target_ref": "string",
  "phase": "pre|post",
  "attached": true,
  "visible": true,
  "enabled": true,
  "editable": false,
  "stable": true,
  "pointer_events": true,
  "observed_at": "2026-05-23T00:00:00Z"
}
```

Field mapping:

- `attached` → target remains connected to DOM/actionability tree.
- `visible` → target has visible box/rendered affordance.
- `enabled` → target is not disabled for activation.
- `editable` → target can accept text input when the typed action requires input.
- `stable` → target geometry/state is stable enough for humanized interaction.
- `pointer_events` → target can receive pointer input; no blocking pointer-event state.

Verifier use:

- `pre` envelope proves the selected target is actionable before dispatch.
- `post` envelope captures whether the same target or resulting surface remains valid after dispatch.
- Typed actions may require a subset: click requires `attached`, `visible`, `enabled`, `stable`, `pointer_events`; fill additionally requires `editable`.

Non-goals:

- No executor implementation change.
- No CloakBrowser/vendor change.
- No new retry policy.

---

## ADR-002: Multi-Graph Web World Model (WebSceneGraph)

Status: Accepted (2026-05-23)

Implemented: `netweaver/scene_graph.py` (NW-004)

A single DOM tree is insufficient for web cognition. NetWeaver models a page as a heterogeneous graph with typed nodes (DOM, Accessibility, Visual, Network, JS, Storage, Intent) and typed edges (Containment, Dependency, Causality, Evidence). This enables cross-layer reasoning (e.g., "this button triggers a network request that updates this DOM node").

Decision: Use a single `WebSceneGraph` dataclass with `NodeType`/`EdgeType` enums rather than separate per-layer graphs. This simplifies serialization and cross-edge queries at the cost of a larger single structure.

Consequences:
- (+) Single graph supports cross-layer edge queries (element → network → DOM change)
- (+) Simple serialization/deserialization via `to_dict()`/`from_dict()`
- (+) Graph diff (`compute_delta()`) enables before/after state comparison
- (-) Monolithic structure; very large pages may need subgraph extraction
- (-) No graph database backend; limited to in-memory Python objects

---

## ADR-003: Evidence-First Verification Pipeline

Status: Accepted (2026-05-23)

Implemented: `netweaver/evidence.py` (NW-006), `netweaver/observer_evidence_adapter.py`

Every NetWeaver action must produce verifiable evidence before its outcome is accepted. The `EvidenceReport` links claims to observations, and claims can be in `supported`, `unsupported`, or `missing` states. The observer→evidence adapter bridges raw `PageObservation` data into structured `EvidenceReport` claims.

Decision: Evidence is a first-class data product, not a side channel. The pipeline is: observe → claim → verify → decide. No action outcome is trusted without evidence chain.

Consequences:
- (+) Eliminates hallucinated-success problem — actions can't claim success without browser evidence
- (+) Evidence chain is auditable: claim → observation → source → timestamp
- (+) `EvidenceReport.verify()` produces deterministic pass/fail
- (-) ~~`summary()` calls `verify()` and mutates claim states~~ — **Fixed 2026-05-24**: `_check_verified()` provides non-mutating read path
- (-) Evidence collection is mock-only in Phase 1; real browser evidence pending Phase 2

---

## ADR-004: Perspective Engine for Multi-Stakeholder Risk Assessment

Status: Accepted (2026-05-23)

Implemented: `netweaver/perspective.py` (NW-005)

Before any action executes, NetWeaver evaluates it from multiple perspectives (User, DOM, Visual, Network, JS, Safety, History). Each perspective emits risk assessments. The `PerspectiveEngine` resolves conflicts between perspectives using a priority-based strategy: Safety > Critical > Payment > High-risk > Technical.

Decision: Multi-perspective evaluation happens before execution, not after. The engine produces a single `ResolutionStrategy` (PROCEED, ASK, ABORT, RECOVER) that gates execution.

Consequences:
- (+) Safety-critical actions are caught before execution, not after damage
- (+) ASK strategy enables human-in-the-loop for high-risk operations
- (+) Extensible — new perspectives can be added without changing the resolution logic
- (-) Resolution priority is hardcoded, not configurable per deployment
- (-) ~~History perspective is scaffolded but not yet populated with real data~~ — **Implemented**: `HistoryPerspective` assesses past failures and known patterns (Phase 1 uses mock data; real data pending Phase 2)

---

## ADR-005: Graph-Native Action Resolution

Status: Accepted (2026-05-24)

Implemented: `netweaver/graph_query.py` (NW-014), `netweaver/executor.py` graph integration (NW-015)

Rather than using raw CSS selectors directly, NetWeaver resolves action targets through the WebSceneGraph. The `resolve_target()` function accepts natural-language descriptions and finds the best matching graph node using intent-based search, evidence confidence filtering, and safety blocking.

Decision: The graph is the source of truth for target resolution, not the DOM. Selectors are a fallback, not the primary mechanism.

Consequences:
- (+) NL descriptions ("click login button") resolve to concrete targets via semantic graph
- (+) Safety-blocked nodes are excluded from resolution, not silently filtered
- (+) Evidence confidence scoring provides ranked alternatives
- (-) NL resolution accuracy depends on graph quality; poor observation → poor resolution
- (-) Backward-compatible raw-selector path must be maintained for migration

---

## ADR-006: Orchestrated Action Sequences with Rollback

Status: Accepted (2026-05-24)

Implemented: `netweaver/action_orchestrator.py` (NW-016, NW-019, NW-020)

Multi-step web actions (e.g., login: fill username → fill password → click submit → wait) require inter-step verification and rollback on failure. The `ActionOrchestrator` chains graph-resolved actions, verifies state after each step, and rolls back on failure using the `EvidenceLedger`.

Decision: Orchestration is a first-class concern with its own state machine (PENDING → RUNNING → COMPLETED/FAILED/ROLLED_BACK/SAFETY_BLOCKED). Each step produces a `StepResult` with graph delta and evidence chain.

Consequences:
- (+) Mid-sequence failures are handled with rollback, not silent corruption
- (+) `RetryPolicy` enables re-observation on retryable failures (reobserve → rebuild graph → retry)
- (+) `TraceWriter` produces per-orchestration execution traces for audit
- (-) Rollback is currently mock-based; real undo operations require browser support
- (-) No concurrent orchestration support; sequences are strictly sequential

---

## ADR-007: Learned Skill Reuse via Composite Matching

Status: Accepted (2026-05-24)

Implemented: `netweaver/site_skill.py` (NW-021), `netweaver/skill_matcher.py` (NW-022), `netweaver/skill_learner.py` (NW-025), `netweaver/planner.py` (NW-024)

NetWeaver closes the learning loop: successful orchestrations produce `SiteSkill` entries stored in `SkillStore`. Future tasks query the store via `SkillMatcher` using composite scoring (0.4×site_match + 0.3×goal_overlap + 0.3×success_rate). The `GoalTranslator` maps NL goals to `ActionPlan` via template matching against learned skills.

Decision: Skills are a cache of successful execution patterns, not an LLM prompt. Matching is deterministic (Jaccard similarity + regex site matching + success rate), not neural.

Consequences:
- (+) Deterministic skill matching — no LLM cost or latency for skill reuse
- (+) Skills improve over time: success_count increments, selectors union on merge
- (+) Quality gate prevents low-quality skills from polluting the store
- (+) `SkillLearner.learn_and_store()` handles dedup via Jaccard > 0.5 goal overlap
- (-) Template-based planning covers 10 patterns (login, search, navigate, fill-form, click-confirm, register, logout, select, toggle, download); unmatched goals get single-step fallback
- (-) No LLM-based plan generation for novel goals yet
- (-) Skill matching is URL+goal based; no semantic similarity across different URL patterns for same site

---

## ADR-008: Observer Dual-Mode (Mock/Live)

Status: Accepted (2026-05-23)

Implemented: `netweaver/observer.py` (NW-001)

The observer operates in two modes: **mock** (returns structured fixture data without browser) and **live** (connects to CloakBrowser for real DOM/network/storage inspection). Mode is selected via `--no-cloak` CLI flag or `cloak_mode` parameter. This enables Phase 1 development and testing without browser dependency while preserving the live-mode code path for Phase 2.

Decision: Mock mode is the default during Phase 1. Live mode code exists but is gated behind the optional `cloakbrowser` import. No live browser execution is permitted until Phase 2 safety review.

Consequences:
- (+) All 1048 tests run without browser/CloakBrowser dependency
- (+) Live mode code path is exercised in CLI but not in automated tests
- (-) Mock observations may not match real CloakBrowser output shape; adapter contract may need adjustment in Phase 2
- (-) `PageObservation` dataclass fields are based on expected CloakBrowser SDK output, not validated against real data

---

## ADR-009: TINI Wrapper Coexistence with NetWeaver

Status: Accepted (2026-05-24)

The project root contains both the **TINI** anti-hallucination wrapper (`tini.py`, `.tini/`) and the **NetWeaver** browser cognition engine (`netweaver/`). TINI was the original project; NetWeaver grew out of it. They share the `.tini/` directory structure but serve different purposes:

- **TINI**: CLI wrapper that generates constrained prompts for AI coding agents, with evidence rules, risk scanning, and verification checklists.
- **NetWeaver**: Python library for browser automation cognition — observe, plan, execute, verify, learn.

Decision: TINI and NetWeaver coexist in the same repository. TINI is a meta-tool (prompt engineering wrapper); NetWeaver is the core product. `PROJECT_GOAL.md` should be updated to reflect NetWeaver as the primary mission. The `.tini/` directory serves as shared infrastructure (negative cache, company docs, kanban).

Consequences:
- (+) Shared `.tini/` infrastructure avoids duplication
- (+) TINI's evidence rules (rule 1-18) informed NetWeaver's evidence-first architecture
- (-) `PROJECT_GOAL.md` still describes TINI, causing goal-alignment noise in reviews
- (-) `.tini/netweaver/` contains a partial Python subset + TypeScript skeleton that duplicates/conflicts with root `netweaver/`
- (-) Two parallel test suites (TINI tests + NetWeaver tests) in the same `tests/` directory

---

## ADR-010: Deterministic Planning over LLM Planning

Status: Accepted (2026-05-24)

Implemented: `netweaver/planner.py` (NW-024)

The `GoalTranslator` maps NL goals to `ActionPlan` via template matching (10 built-in templates: login, search, navigate, fill-form, click-confirm, register, logout, select, toggle, download), not LLM calls. This is an explicit architectural choice: deterministic planning is preferred for known patterns, with LLM-based planning deferred to Phase 3 (P3-001 Intent Compiler) as a fallback for novel goals.

Decision: Determinism > flexibility for the planning layer. Template matching is O(n) in template count, requires zero API calls, and produces reproducible plans. Novel goals receive a single-step fallback plan rather than an LLM-generated plan.

Consequences:
- (+) Zero latency and zero cost for plan generation
- (+) Plans are reproducible — same goal always produces same plan
- (+) Template API supports add/remove/list for extensibility
- (-) 10 patterns now; novel multi-step goals still get single-step fallback (poor UX for truly novel patterns)
- (-) Template matching is keyword-based (stop-word filtered); semantic matches are missed
- (-) Graph validation via `GraphQuery.find_actionable_nodes()` adds overhead but ensures plan feasibility

---

## ADR-011: FillAction Credential Masking

Status: Accepted (2026-05-24)

Implemented: `netweaver/wnal.py` (NW-002, tech debt fix)

FillAction values may contain credentials (passwords, API keys, tokens). Without explicit marking, serialized FillActions leak secrets in logs, traces, and evidence chains. The `is_sensitive` field (default `False`) enables opt-in credential masking.

Decision: Masking is opt-in at the action level, not opt-out. Default `to_dict()` masks sensitive values (replaces with first char + `********`). Consumers needing full values (e.g., for deserialization/storage) must explicitly pass `mask_sensitive=False`.

Consequences:
- (+) Default serialization is safe for logging — no accidental credential leaks
- (+) `masked_value` property provides audit-safe display (first char + stars)
- (+) `action_from_dict()` preserves `is_sensitive` through round-trips
- (+) Backward compatible — default `is_sensitive=False` matches pre-fix behavior
- (-) Masking is textual only; in-memory FillAction still holds raw credential
- (-) Round-trip contract: `to_dict()` (masked) → `action_from_dict()` loses the original value; must use `to_dict(mask_sensitive=False)` for storage

---

## ADR-012: Evidence Round-Trip Fidelity

Status: Accepted (2026-05-25)

Implemented: `netweaver/wnal.py` (WNAL Engineer tech debt fix)

`action_from_dict()` silently dropped `pre_evidence`, `post_evidence`, and `verification` fields during deserialization. This meant any deserialized action lost its evidence chain — critical for ledger replay, skill learning, and audit trails that require full action state.

Decision: Deserialization must restore the full evidence envelope. `_deserialize_evidence()` and `_deserialize_verification()` helpers reconstruct typed evidence objects from serialized dicts. `VerificationResult` fields (`checks`, `all_met`) are restored from serialized values rather than re-computed, ensuring exact round-trip fidelity even if precondition logic evolves.

Consequences:
- (+) Full action state preserved through serialize→deserialize cycle
- (+) Ledger replay can restore complete evidence chains
- (+) Skill learning from stored orchestrations gets full pre/post evidence
- (+) Backward compatible — actions without evidence still deserialize with `None` (same as before)
- (-) `VerificationResult` is frozen-from-dict rather than recomputed — if precondition logic changes, old stored results are preserved exactly (not revalidated)
- (-) Evidence round-trip requires `to_dict(mask_sensitive=False)` to avoid losing sensitive FillAction values

---

## ADR-013: Append-Only Event Ledger

Status: Accepted (2026-05-25)

Implemented: `netweaver/event_ledger.py` (170 LOC)

The project uses multiple markdown coordination files (KANBAN, HANDOFF, DEV_LOG, REVIEW) as the source of truth for agent activity. This creates dual-coordination risk: both the markdown files and the event ledger track state, with no migration plan.

Decision: The `EventLedger` is an append-only JSONL store — one file per day under `.tini/netweaver/ledger/`. Events are structured (timestamp, event_type, payload, agent_id). The ledger is designed to eventually replace markdown coordination files as the canonical activity record. Currently both systems coexist.

Consequences:
- (+) Append-only design prevents accidental state corruption
- (+) JSONL format enables streaming reads and efficient grep
- (+) Per-day file rotation prevents unbounded growth
- (+) Structured events enable programmatic queries (vs. freeform markdown)
- (-) Dual-coordination exists today: markdown files + event ledger both active
- (-) No migration plan documented for retiring markdown coordination
- (-) No consumers yet read from event_ledger (KANBAN/HANDOFF still markdown-sourced)

---

## ADR-014: Worker Competence Registry

Status: Accepted (2026-05-25)

Implemented: `netweaver/competence.py` (285 LOC)

Multi-agent systems need to route tasks to the best-fit worker. Without a competence model, task assignment is ad-hoc (cron round-robin or manual).

Decision: The `CompetenceRegistry` tracks worker profiles with weighted skill sets. Each worker has a name, model, role, and a set of competence entries (skill_name → weight 0.0–1.0). Registry persists as Markdown + JSON under `.tini/netweaver/company/`. Matching logic ranks workers by competence overlap with task requirements.

Consequences:
- (+) Data-driven task routing replaces hardcoded worker assignments
- (+) Competence weights enable nuanced matching (not just binary can/cannot)
- (+) Markdown+JSON dual format: human-readable + machine-parseable
- (-) Registry is currently static — no feedback loop to update weights from outcomes
- (-) Weight calibration is manual — no automatic adjustment from success/failure rates
- (-) Matching is scalar sum — no interaction effects between competences

---

## ADR-015: Prompt-as-Code Management

Status: Accepted (2026-05-25)

Implemented: `netweaver/prompt_manager.py` (296 LOC)

Agent prompts are critical configuration that evolved through Phase 1. Without versioning, prompt changes are invisible, unreproducible, and un-auditable. The cron prompt context overflow (15+ wasted worker runs) demonstrated the cost of unmanaged prompts.

Decision: Prompts are stored as `.prompt` files under `.tini/prompts/<agent-name>/v<N>.prompt`. A `current` file holds the active version number. `PromptVersion` tracks content, metadata (created_at, author, reason), and activation state. The manager supports list/activate/compare/rollback operations.

Consequences:
- (+) Prompt changes are versioned and auditable
- (+) Rollback to any previous version is a single operation
- (+) Diff between versions enables prompt debugging
- (+) Separates prompt content from code — no inline prompt strings
- (-) Adds filesystem dependency (`.prompt` files + `current` pointer)
|- (-) No automatic A/B testing or quality metrics per version
|- (-) Prompt activation is global — no per-session or per-task overrides

---

## ADR-016: Playwright as Alternative Browser Backend

Status: Accepted (2026-05-25)

Implemented: `netweaver/playwright_bridge.py` (399 LOC)

P2-004 required real-site orchestration but CloakBrowser SDK is not universally available. The observer/executor stack needs a working browser backend for live integration tests and eventual production use.

Decision: A `PlaywrightBridge` class implements the same interface as `CloakBrowserBridge` (observe, collect_evidence, execute_action) using Playwright Chromium directly. Observer falls back to Playwright only when CloakBrowser is not installed (ImportError). If CloakBrowser is installed but errors, the error propagates — no silent fallback. All Playwright imports are guarded behind try/except blocks to maintain the import-safety invariant (`FORBIDDEN_MODULES` check).

Consequences:
- (+) Real browser integration without CloakBrowser SDK dependency
- (+) Same interface as CloakBrowserBridge — no executor/orchestrator changes needed
- (+) Live integration tests work without CloakBrowser
- (+) Import-safety invariant preserved via guarded imports
- (-) Duplicate bridge implementations (CloakBrowserBridge + PlaywrightBridge) to maintain
- (-) Playwright adds ~260MB browser cache (user-local, not in repo)
- (-) Two-version drift risk — CloakBrowser and Playwright may behave differently on edge cases
- (-) CloakBrowser-first, Playwright-fallback creates implicit priority order not explicit config

---

## ADR-017: Daemon Auto-Development of Approved Plans

Status: Accepted (2026-05-25)

Implemented: `daemon.py` (auto-development functions)

The daemon previously operated as a poll-and-dispatch system: it watched KANBAN.md for file changes, generated tasks via LLM, and dispatched them to agent workers. The REVIEW_QUEUE.md served as a manual review gate — plans were approved by a reviewer and awaited human execution.

Decision: The daemon now also scans REVIEW_QUEUE.md for plans marked `**Status:** APPROVED`, parses their steps, and executes them autonomously. `_execute_task_direct()` bypasses the PLAN_ONLY gate to enable zero-delay execution of approved plans. Failed steps trigger auto-fix: if tests break after a step, the daemon generates a fix step for the same files and retries.

Consequences:
- (+) APPROVED plans execute without delay — no human-in-loop needed for low-risk approved work
- (+) Auto-fix on test breakage reduces manual intervention
- (+) REVIEW_QUEUE.md status progression: PENDING_APPROVAL → EXECUTING → DONE/FAILED (auditable)
- (+) Events logged to `.tini/events.jsonl` for all auto-executed plans
- (-) Daemon now both dispatches AND executes work — single point of failure for the execution pipeline
- (-) Auto-fix on test breakage may mask genuine regression if fix step is incorrect
- (-) No approval expiry: APPROVED plans execute regardless of age
- (-) No concurrent execution guard: if multiple APPROVED plans exist, they execute sequentially in one daemon cycle, blocking file polling
- (-) REVIEW_QUEUE.md status modifications bypass the formal KANBAN handoff mechanism
