# NetWeaver — Novel Contributions

## What Makes NetWeaver Different from Existing Browser Automation Agents

Most web automation agents (Playwright MCP, Browser Use, LaVague, WebArena agents) follow the same pattern: LLM sees page → LLM picks selector → LLM clicks → LLM checks screenshot. NetWeaver's architecture differs at every layer.

---

## 1. Multi-Graph World Model (Not a DOM Snapshot)

**Existing approach:** DOM snapshot or accessibility tree as flat text.

**NetWeaver:** Heterogeneous typed graph (`WebSceneGraph`) with 7 node types (DOM, A11y, Visual, Network, JS, Storage, Intent) and 4 edge types (Containment, Dependency, Causality, Evidence). Cross-layer edges enable causal reasoning: "this button's click triggers this network request that updates this DOM node."

**Novelty:** No existing browser agent maintains a multi-layer causal graph of page state. Most treat the page as a flat snapshot. The graph enables:
- Intent-based node search (not just selector matching)
- Evidence-backed confidence scoring per node
- Cross-layer causality tracking
- Graph diff for state change detection

Implemented: `netweaver/scene_graph.py` (452 LOC), `netweaver/scene_graph_builder.py` (629 LOC), `netweaver/graph_query.py` (616 LOC).

---

## 2. Evidence-Native Verification (Not Screenshot Checking)

**Existing approach:** "Did the page change?" via screenshot comparison or DOM diff after action.

**NetWeaver:** Every action produces a typed evidence envelope (ADR-001) with 6 boolean actionability fields collected *before* and *after* execution. `EvidenceReport` links verifiable claims to structured observations with deterministic pass/fail. No claim is accepted without an evidence chain: claim → observation → source → timestamp.

**Novelty:** Most agents check results post-hoc. NetWeaver requires pre-conditions to be satisfied before execution and post-conditions to be verified after. The evidence chain is auditable, not just a binary success/fail.

Implemented: `netweaver/evidence.py` (410 LOC), `netweaver/wnal.py` (427 LOC), `netweaver/observer_evidence_adapter.py` (266 LOC).

---

## 3. Multi-Perspective Pre-Execution Risk Assessment

**Existing approach:** Safety is "don't click buy buttons" — a simple rule list.

**NetWeaver:** `PerspectiveEngine` evaluates every proposed action from 7 perspectives (User, DOM, Visual, Network, JS, Safety, History) before execution. Conflicting assessments are resolved via priority-based strategy (Safety > Critical > Payment > High-risk > Technical). Actions can be PROCEED, ASK (human confirmation), ABORT, or RECOVER.

**Novelty:** No existing agent evaluates actions from multiple stakeholder perspectives before execution. Most have a flat "is this dangerous?" check. NetWeaver's approach enables nuanced risk assessment where, e.g., a DOM perspective sees no issue but the Network perspective flags credential exfiltration risk.

Implemented: `netweaver/perspective.py` (570 LOC).

---

## 4. Graph-Native Target Resolution (Not Selector Guessing)

**Existing approach:** LLM generates CSS selector or XPath. Fallback to visual coordinate clicking.

**NetWeaver:** Action targets are resolved through the WebSceneGraph via natural-language descriptions. `resolve_target()` uses intent-based search, evidence confidence filtering, and safety blocking to find the best graph node. Selectors are a byproduct of graph resolution, not the primary mechanism.

**Novelty:** Most agents treat selector generation as a text generation problem. NetWeaver treats target resolution as a graph search problem with evidence-backed confidence and safety constraints.

Implemented: `netweaver/graph_query.py` (616 LOC), executor integration in `netweaver/executor.py` (722 LOC).

---

## 5. Orchestrated Sequences with Inter-Step Verification and Rollback

**Existing approach:** Multi-step actions are independent LLM turns. Failure = try again from scratch.

**NetWeaver:** `ActionOrchestrator` chains graph-resolved actions into verified sequences with inter-step state verification, graph delta computation, and rollback via `EvidenceLedger` on failure. Retry policy supports re-observation (rebuild graph, retry step) for retryable failures.

**Novelty:** No existing browser agent provides multi-step orchestration with inter-step verification and rollback as a first-class primitive. Most treat each action independently.

Implemented: `netweaver/action_orchestrator.py` (1011 LOC), `netweaver/ledger.py` (273 LOC), `netweaver/leases.py` (382 LOC).

---

## 6. Deterministic Learned Skill Reuse (Not Prompt Engineering)

**Existing approach:** "Remember this website" = store previous conversation context or few-shot examples in the prompt.

**NetWeaver:** `SkillLearner` extracts `SiteSkill` from successful orchestrations. `SkillMatcher` ranks stored skills via composite scoring (0.4×site_match + 0.3×goal_Jaccard + 0.3×success_rate). `GoalTranslator` maps NL goals to `ActionPlan` via template matching against learned skills. All matching is deterministic — no LLM call needed for skill reuse.

**Novelty:** Most browser agents have no structured memory of successful interactions. NetWeaver's skill system is:
- Deterministic (no LLM cost for matching)
- Quality-gated (rejects low-quality skills)
- Self-improving (success_count, selector union on merge)
- Deduplicated (Jaccard similarity on goal tokens)

Implemented: `netweaver/site_skill.py` (283 LOC), `netweaver/skill_matcher.py` (203 LOC), `netweaver/skill_learner.py` (259 LOC), `netweaver/planner.py` (631 LOC).

---

## What NetWeaver Is NOT

- Not an LLM — NetWeaver is the cognitive layer; an LLM can be the language/reasoning layer on top
- Not a browser — CloakBrowser/Playwright is the body; NetWeaver is the brain
- Not a web scraper — NetWeaver reasons about page state transitions, not just data extraction
- Not a test framework — NetWeaver automates real web tasks with verification, not regression tests

---

## Current State (Phase 1 Complete)

All components implemented in mock/no-browser mode:
- 17 Python modules, 7507 LOC (legacy `scene_builder.py` removed 2026-05-24)
- 1116 NetWeaver tests passing (1150 total incl. TINI wrapper)
- Zero external dependencies (stdlib + internal only)
- Zero browser/vendor/Playwright imports in any module except optional `cloakbrowser` in observer
- Full observe→plan→execute→verify→learn loop scaffolded
- 12 ADRs documented in `ARCHITECTURE_DECISIONS.md`

---

## Remaining Novelty Gaps (Phase 2+)

These are areas where the architecture is novel but not yet implemented:

1. **Live browser evidence collection** — currently mock; real CloakBrowser integration needed
2. **LLM-powered Intent Compiler** — NL→WNAL currently uses template matching; LLM-based compilation would handle novel goals
3. **Cross-session skill transfer** — skills are site-specific; no cross-site pattern generalization
4. **Concurrent orchestration** — sequences are strictly sequential; no parallel action support
5. **Visual grounding** — Visual node type exists but no screenshot/coordinate integration
6. **JS runtime facts** — JS node type exists but no real runtime introspection
7. **Recovery engine** — failure classification exists but no automatic fallback selection
