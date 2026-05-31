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

---

## ADR-018: Epistemic OS — Probabilistic Knowledge Management

Status: Accepted (2026-05-27/28)

Implemented: `netweaver/epistemic.py` (789 LOC), `netweaver/epistemic_verifier.py` (498 LOC), `netweaver/epistemic_site_skill.py` (248 LOC), `netweaver/epistemic_daemon.py` (243 LOC)

Knowledge in autonomous systems is traditionally binary (true/false) — a claim is either stored or not. This creates brittle systems that don't account for uncertainty, staleness, or contradictory evidence.

Decision: An `EpistemicOS` class manages all knowledge as nodes with confidence (0.0–1.0), decay (rate of confidence drop over time), provenance (source of knowledge), contradictions (what conflicts), and context (conditions under which knowledge is true). An `AutoVerifier` re-runs tests/skills to re-calibrate stale knowledge. Epistemic tracking is mixed into `SiteSkill` (`EpistemicSiteSkill`) and the daemon loop (`EpistemicDaemon`).

Consequences:
- (+) Knowledge is honest about uncertainty rather than pretending certainty
- (+) Stale knowledge auto-triggers re-verification via `AutoVerifier`
- (+) Contradictions between knowledge nodes detected and surfaced
- (+) Contextual knowledge prevents over-generalization
- (-) Added complexity: ~1,778 LOC across 4 modules for the epistemic subsystem
- (-) Auto-verifier uses `subprocess` to run tests — adds test-cycle latency
- (-) Decay and confidence curves are hardcoded; no empirical calibration yet
- (-) No integration with downstream consumers (planner, orchestrator) yet

---

## ADR-019: Background Analysis Subsystem (Causal + Dreaming)

Status: Accepted (2026-05-27/28)

Implemented: `netweaver/causal.py` (466 LOC), `netweaver/dreaming.py` (490 LOC)

When failures occur, the system needs root-cause analysis beyond surface-level error messages. When idle, the system can generate improvement hypotheses.

Decision: Two background analysis modules:
- **Causal Chain Analysis** (`causal.py`): Traces test failures back to code changes using git history, import graphs, and dependency analysis. Builds causal chains with confidence scores (e.g., `change → import chain → test failure`).
- **Dreaming** (`dreaming.py`): Background hypothesis generation — scans codebase for patterns, simulates outcomes of refactoring proposals, stores hypotheses as low-confidence epistemic knowledge. Proposes architectural improvements without being asked.

Consequences:
- (+) Causal chains improve debugging from symptom-level to root-cause-level
- (+) Dreaming surfaces refactoring opportunities the system wouldn't otherwise consider
- (+) Both modules are pure stdlib + `subprocess` (git inspection only)
- (+) Both feed into EpistemicOS for knowledge management
- (-) **956 LOC with zero test coverage** — both modules untested
- (-) Dreaming hypotheses have no validation gate; could recommend incorrect refactors
- (-) Causal analysis uses `subprocess` for git commands (slow, environment-dependent)
- (-) Dreaming scheduled by daemon — could consume compute on non-useful hypotheses

---

## ADR-020: Agent Intelligence Layer (Competence Matrix + Memory Palace + Knowledge Graph)

Status: Accepted (2026-05-27/28)

Implemented: `netweaver/competence_matrix.py` (431 LOC), `netweaver/memory_palace.py` (419 LOC), `netweaver/knowledge_graph.py` (390 LOC), `netweaver/knowledge_graph_cli.py` (272 LOC), `netweaver/tracker.py` (82 LOC), `netweaver/roadmap.py` (51 LOC)

Multi-agent coordination needs more than round-robin task assignment and static KANBAN. Agents need: (1) historical task-routing data, (2) persistent decision memory, (3) cross-project ecosystem awareness.

Decision: Three new intelligence modules:
- **Competence Matrix** (`competence_matrix.py`): Bayesian scoring from execution history — tracks success rate per task type, file familiarity, current load. Routes tasks to most competent agent. Extends `CompetenceRegistry` (ADR-014).
- **Memory Palace** (`memory_palace.py`): Per-agent persistent memory store (JSON-backed). Stores decisions + outcomes with semantic fingerprinting, temporal decay, and auto-pruning of low-value memories.
- **Knowledge Graph** (`knowledge_graph.py`): Cross-project dependency graph — maps projects→files→modules→functions via AST scanning. CLI tool (`knowledge_graph_cli.py`) for query/visualize.
- **Tracker/Roadmap** (`tracker.py`, `roadmap.py`): Unified Item+StateMachine merging Kanban and Roadmap into programmatic API.

Consequences:
- (+) Task routing improves from round-robin to competence-weighted
- (+) Agents build institutional memory across sessions (MemoryPalace)
- (+) Cross-project dependency awareness enables impact analysis
- (+) Programmatic Tracker API replaces markdown-only KANBAN for machine consumers
- (-) Competence Matrix uses Bayesian scoring but history is sparse — initial routing is effectively random
- (-) **Two modules untested**: `competence_matrix.py` (431 LOC), `knowledge_graph_cli.py` (272 LOC)
- (-) Memory Palace fingerprinting is basic (word overlap); no embedding/semantic search
- (-) Tracker/Roadmap duplicate existing markdown-based KANBAN — dual system (like event_ledger before it)
- (-) Knowledge Graph only scans Python files (AST-based); no JS/TS/Go support

---

## ADR-021: Auto-Skill Learning Subsystem

Status: Accepted (2026-05-31)

Implemented: `netweaver/skill_learner_auto.py` (572 LOC), `netweaver/skill_store.py` (383 LOC), `tests/test_skill_auto_learning.py` (58 tests) — NW-035

The core Skill Learner (ADR-007) learns from successful orchestration results, but the learning loop was manual: someone needed to call `learn_and_store()` with execution results. Without an auto-learning layer, skills never accumulate organically from real agent activity.

Decision: Two new modules extend ADR-007:
- **SkillStore** (`skill_store.py`): Persistent skill storage under `.tini/netweaver/skills/` as JSON files. Supports CRUD, URL-pattern grouping, deduplication via Jaccard similarity (>0.5 overlap merges skills), confidence scoring (>5 uses → "trusted" status), and `find_by_url_and_intent(url, intent)` query.
- **AutoSkillLearner** (`skill_learner_auto.py`): Observes action sequences with evidence, identifies successful patterns via `learn_from_execution(execution_log)`, persists to SkillStore. Integrates with the daemon loop for background learning.

Consequences:
- (+) Skills accumulate automatically from agent activity without manual recording
- (+) SkillStore provides persistence + dedup + confidence scoring out of the box
- (+) URL-pattern grouping enables cross-page skill matching (same domain, different paths)
- (+) 58 tests cover both modules; no browser/vendor/playwright imports
- (-) Auto-learner is daemon-coupled; standalone usage requires daemon context
- (-) Skill dedup threshold (Jaccard > 0.5) is hardcoded; no empirical calibration
- (-) No integration with ActionOrchestrator post-execution hook yet (noted P2-005 gap)
- (-) Confidence scoring increments only; no decay mechanism for stale skills

---

## ADR-022: DSL Validator for WNAL and BASIL Syntax

Status: Accepted (2026-05-31)

Implemented: `netweaver/dsl_validator.py` (497 LOC), `tests/test_dsl_validator.py` (70 tests) — NW-034

WNAL (Web Navigation Action Language) and BASIL (Browser Automation Script Interface Language) are DSLs used to express action sequences (e.g., `click(#login)`, `fill(#user, val)`). Early swarm development relied on ad-hoc string parsing with no validation layer, leading to fragile error reporting and inconsistent action formats across agents.

Decision: A dedicated `DslValidator` with two entry points (`validate_wnal()` / `validate_basil()`) that produce a `ValidationResult` containing errors, warnings, and an `is_valid` flag. Validation includes:
- **Schema validation**: required fields, type checking, enum constraint enforcement
- **Precondition checking**: element selector validity, no conflicting actions
- **Conflict detection**: two actions targeting the same element in incompatible order

Consequences:
- (+) Consistent error messages across all agents — no ad-hoc parsing
- (+) Early detection of malformed DSL before execution (safety gain)
- (+) 70 tests cover valid/invalid DSL, edge cases, conflict scenarios
- (+) Pure data validation — no browser/vendor/playwright imports
- (+) CLI entry for manual validation: `python -m netweaver.dsl_validator --file <path>`
- (-) DSL syntax is defined by validator, not by formal grammar — no BNF/EBNF spec
- (-) Conflict detection is rule-based; complex cross-step interactions may be missed
- (-) No integration with planner or orchestrator — validation is standalone

---

## ADR-023: Quality Automation Tooling Suite

Status: Accepted (2026-05-31)

Implemented: `netweaver/backlog_generator.py` (694 LOC), `netweaver/test_healer.py` (394 LOC), `netweaver/evidence_report.py` (418 LOC), `netweaver/dashboard.py` (373 LOC) — NW-027, NW-028, NW-029

The project grew from 17 to 49 modules with no automated quality tooling beyond pytest. Technical debt (TODO/FIXME), flaky tests, and evidence readability were managed manually. The TUI dashboard was built ad-hoc for internal debugging.

Decision: Four utility modules that form a quality automation toolchain:
- **Backlog Generator** (`backlog_generator.py`, NW-028): Scans netweaver codebase for TODO/FIXME/HACKs, identifies modules with <50% test coverage, auto-generates BACKLOG.md entries with deduplication against existing backlog.
- **Test Healer** (`test_healer.py`, NW-027): Detects flaky tests via configurable retry + exponential backoff (1s/2s/4s). Quarantines consistently-failing tests to `.tini/quarantined_tests.json`. Provides a pytest plugin hook to skip quarantined tests.
- **Evidence Report Renderer** (`evidence_report.py`, NW-029): Renders `EvidenceReport` objects as human-readable markdown — claim statuses, evidence chain, recommendations. Decouples report presentation from evidence data model.
- **TUI Dashboard** (`dashboard.py`): Rich-based live terminal dashboard showing daemon status, KANBAN state, recent events, and test counts.

Consequences:
- (+) Automated tech debt tracking reduces manual backlog grooming
- (+) Flaky test quarantine prevents false CI failures
- (+) Evidence report markdown is usable for audit trails and human review
- (+) Dashboard provides at-a-glance project health
- (-) Backlog generator is heuristic — may generate noisy entries from common patterns
- (-) Test healer uses `pytest` import directly, creating a hard dependency
- (-) Dashboard imports `rich` — adds a non-stdlib dependency for TUI use only
- (-) Dashboard is path-hardcoded to `~/Documents/myhermes/.tini` — not portable

---

## ADR-024: File Lease Coordination for Multi-Agent Swarm

Status: Accepted (2026-05-31)

Implemented: `netweaver/leases.py` (382 LOC)

The multi-agent swarm uses concurrent cron jobs (architect, runtime, QA, WNAL engineers) that may edit the same files. Without coordination, parallel agents risk clobbering each other's edits — especially on shared files like KANBAN.md, DEV_LOG.md, and ARCHITECTURE_DECISIONS.md.

Decision: A `LeaseManager` with `FileLease` dataclass providing agent-id-scoped, TTL-bounded exclusive file access. Leases are persisted as JSON under `.tini/netweaver/leases/`. `acquire()` checks for conflicts and existing active leases, `release()` frees the lease, `renew()` extends the TTL. Expired leases are reclaimed on next acquire attempt.

Consequences:
- (+) Prevents concurrent-writer corruption on shared coordination files
- (+) STD lib only (dataclasses, json, uuid, time) — zero dependencies
- (+) TTL prevents stale lock accumulation from crashed agents
- (+) Lease metadata includes agent_id, file_paths, acquired_at, expires_at for audit
- (-) All agents must cooperate — a non-leasing agent can still clobber files
- (-) Lease granularity is file-level, not section-level (cannot lock single KANBAN line)
- (-) No distributed coordination — leases only work within single filesystem

---

## ADR-025: Autonomous Web Explorer (web_learner.py)

Status: Accepted (2026-05-31)

Implemented: `netweaver/web_learner.py` (452 LOC)

NetWeaver needs autonomous site discovery and exploration to build skills without manual seeding. The `WebLearner` is a self-directed agent that discovers websites (seed + follow links), builds scene graphs via `SceneGraphBuilder`, learns reusable skills via `SkillLearner`, and records outcomes to the epistemic system.

Decision: Exploration is a first-class agent with its own lifecycle (discover → observe → learn → decide next), not a passive crawl. It reuses the same `VerifiedExecutor`/`CloakBrowserBridge`/`SkillLearner` stack as the orchestrator. A visited registry prevents repeat exploration of the same site.

Consequences:
- (+) Skills accumulate without manual seeding — autonomous exploration feeds the skill store
- (+) Shared stack with orchestrator means learned skills are immediately usable
- (-) 452 LOC with zero test coverage — exploration logic is untested
- (-) No ADR until now (3rd consecutive architect review flag) — architectural intent was undocumented
- (-) No exploration budget/rate-limit — could exhaust browser/driver resources

---

## ADR-026: YAML Task Scheduler for Automated Web Monitoring (task_scheduler.py)

Status: Accepted (2026-05-31)

Implemented: `netweaver/task_scheduler.py` (350 LOC)

Certain use cases require recurring web monitoring: check a page, extract structured data, detect changes, notify. Rather than requiring a full orchestration pipeline, `TaskScheduler` reads YAML task definitions (URL + schedule + extractors) and runs them on a cron-like schedule. Uses `CloakBrowserBridge` for headless extraction.

Decision: Scheduling is a separate module from the orchestrator because monitoring tasks have different guarantees (no stateful sequences, no rollback, pure extraction). YAML is chosen over JSON for human readability of task definitions. Change detection uses hash comparison, not full graph diff.

Consequences:
- (+) Simple YAML task definitions are accessible to non-developer operators
- (+) Reuses CloakBrowserBridge — no new browser dependency
- (+) Hash-based change detection is cheap compared to full graph diff
- (-) 350 LOC with zero test coverage
- (-) Imports `yaml` (third-party) — adds dependency not shared by rest of netweaver
- (-) Telegram integration is hardcoded; alert channel is not pluggable
- (-) No ADR until now (3rd consecutive flag) — architectural intent undocumented

---

## ADR-027: External Alert Dispatch (alerts.py)

Status: Accepted (2026-05-31)

Implemented: `netweaver/alerts.py` (236 LOC)

NetWeaver agents need to notify operators when tasks fail, circuit breakers trip, or critical events occur. `alerts.py` provides Telegram and Slack webhook dispatch with suppression and rate-limiting.

Decision: Alert dispatch is a standalone utility, not embedded in the daemon or orchestrator. `requests` is an optional import (guarded try/except) to avoid a hard dependency. Suppression state (last_sent timestamps) is persisted to JSON.

Consequences:
- (+) Decoupled from daemon/orchestrator — usable by any agent
- (+) Optional `requests` import — no hard dependency
- (-) 236 LOC with zero test coverage
- (-) Hard-coded path (`Path.home() / "Documents/myhermes/.tini"`) — not portable
- (-) No retry logic — single failure drops the alert
- (-) No ADR until now (3rd consecutive flag)

---

## ADR-028: Action-Level Event Ledger (ledger.py)

Status: Accepted (2026-05-31)

Implemented: `netweaver/ledger.py` (273 LOC)

Distinct from the daemon coordination ledger (`event_ledger.py`, ADR-013), the action ledger (`ledger.py`) records agent action events — state transitions, file changes, test runs, evidence attachments — as append-only JSONL. Each event carries timestamp, agent identity, and structured payload.

Decision: Two ledgers serve different purposes: `event_ledger.py` records daemon lifecycle events (start/stop/schedule), while `ledger.py` records agent action events (execute/verify/learn). Both are append-only JSONL. The action ledger integrates with `EvidenceBundle` for validation before append.

Consequences:
- (+) Full audit trail of all agent actions — not just daemon lifecycle
- (+) EvidenceBundle validation ensures ledger integrity
- (-) Dual-ledger system creates confusion about which to use
- (-) 273 LOC with zero test coverage
- (-) No migration plan toward a unified event store
- (-) No ADR until now (3rd consecutive flag)

---

## ADR-029: Demo Module for End-to-End Pipeline Validation (demo.py)

Status: Accepted (2026-06-01)

Implemented: `netweaver/demo.py` (587 LOC), `tests/test_demo.py` (34 tests)

The full NetWeaver stack (Observer→SceneGraphBuilder→GoalTranslator→ActionOrchestrator→EvidenceReport) had no single entry point to validate end-to-end behavior without a real browser. Each module was tested in isolation or via benchmarks, creating a gap between unit tests and real pipeline execution.

Decision: A `DemoModule` class chains all real implementations (not mocks) with `observe_page_mock()` as the only replaced layer. The demo accepts a URL (for metadata) and CLI action strings, runs the full pipeline, and produces an `EvidenceReport` with ≥3 claims. `parse_actions()` converts CLI action strings to typed `ActionStep` objects. Supports JSON output for programmatic consumers.

Consequences:
- (+) One-command pipeline validation without browser dependency
- (+) Catches integration failures between modules (wiring, schema drift, import chains)
- (+) 34 tests cover full pipeline, edge cases, and error paths
- (+) Reusable by CI, demo scripts, and developer workflow
- (-) Mock observations may diverge from real PageObservation shapes in Phase 2
- (-) Action string parsing is regex-based and fragile; no formal grammar

---

## ADR-030: Product Specification Data Model (product_spec.py)

Status: Accepted (2026-06-01)

Implemented: `netweaver/product_spec.py` (254 LOC), `tests/test_product_spec.py` (34 tests — implicit via product_spec testing fixtures)

NetWeaver tracks execution milestones across phases (Phase 1 mock, Phase 2 live, Phase 3 intent compiler) with component-level statuses. Before `product_spec.py`, phase tracking was scattered across KANBAN.md, ROADMAP.md, and ad-hoc comments — no programmatic model for generating reports or validating transitions.

Decision: A `ProductSpec` dataclass with versioned phases (`SpecPhase`), components (`SpecComponent`), JSON persistence (`save()`/`load()`), validation (`validate()`/`is_valid()`), and aggregate metrics (`overall_completion()`). Schema is JSON-serializable for programmatic consumers. Phase constants (`PHASE2_TITLE`, `EXECUTOR_COMPONENT_STATUS`) define current project state.

Consequences:
- (+) Programmatic spec enables automated progress reporting
- (+) Validation catches inconsistent status transitions early
- (+) JSON persistence decouples spec storage from markdown coordination files
- (+) 254 LOC is self-contained — zero dependencies beyond stdlib
- (-) Phase constants are hardcoded; no config file or CLI override
- (-) No integration with KANBAN or Tracker — spec is standalone

---

## ADR-031: NetWeaver CLI for Pipeline State Queries (cli.py)

Status: Accepted (2026-06-01)

Implemented: `netweaver/cli.py` (1040 LOC)

Agents and operators had no fast path to query pipeline state without reading coordination files (KANBAN, DEV_LOG, STATUS). Every status check required grep/wc on markdown files or running the full test suite. This created friction for cron jobs, error diagnostics, and automated health checks.

Decision: A `netweaver/cli.py` module providing subcommands (`status`, `test`, `evidence`, `graph`, `skill`, `kanban`, `alerts`, `config`, `health`, `trace`) that query pipeline state programmatically. Output defaults to human-readable text with `--json` flag for machine consumers. Paths are hardcoded to `~/Documents/myhermes/.tini/`. The CLI is a standalone module — no imports from other netweaver modules — minimizing import chains and boot time.

Consequences:
- (+) Fast pipeline queries without reading coordination files
- (+) JSON output enables automated alerting and dashboard consumption
- (+) 1,040 LOC with **zero test coverage** — tested via manual or integration-only
- (-) Path hardcoded to `~/Documents/myhermes/.tini/` — not portable
- (-) Standalone design duplicates file-reading logic from other modules
- (-) No CLI argument validation beyond argparse basics
- (-) Large file (1,040 LOC) with no subcommand-level modularization — hard to test

---

## ADR-032: Unified Kanban — Root KANBAN.md as Canonical Redirect

Status: Accepted (2026-06-03)

Multiple agents (architect, runtime, QA, WNAL) reference KANBAN.md from two locations: root `~/Documents/myhermes/KANBAN.md` and `.tini/netweaver/company/KANBAN.md`. These have diverged repeatedly: root Kanban lists 28 done/2 ready; canonical Kanban has 34+ tasks including NW-036/NW-037 with no root equivalent. Prior reviews flagged this 5+ consecutive times (HANDOFF.md May 23–Jun 1) with Priority 2 items recurring unresolved.

Decision: Root `KANBAN.md` becomes a lightweight redirect referencing `.tini/netweaver/company/KANBAN.md` as canonical. Remove the duplicate task table from root. The root doc becomes: header, redirect note to canonical, cross-project setup table, summary counts read from canonical. Agents that need task state read `.tini/netweaver/company/KANBAN.md` directly.

Consequences:
- (+) Eliminates recurring root-vs-canonical drift (5+ review cycles of unresolved debt)
- (+) Single source of truth for all agents
- (+) Root KANBAN.md still usable for human readers (redirect + summary)
- (-) Any cron job or agent that parses the root task table must switch to canonical path or parse summary-only
- (-) Requires one-time rewrite of root KANBAN.md to redirect format