# NetWeaver Roadmap

Source of truth: `VISION_CLOAK_NET_AGENT.md`, `ARCHITECTURE_DECISIONS.md`, `.tini/netweaver/company/KANBAN.md`

---

## Phase 1: Data Layer (COMPLETE)

- 1360 NetWeaver tests / 1400 total green. All components in mock/no-browser mode.

| Component | Module | Kanban | LOC | Tests |
|-----------|--------|--------|-----|-------|
| MVP Observer | `observer.py` | NW-001 | 372 | ✅ |
| WNAL Typed Actions | `wnal.py` | NW-002 | 427 | ✅ |
| Observer Benchmark | benchmarks | NW-003 | — | ✅ |
| WebSceneGraph | `scene_graph.py` | NW-004 | 452 | ✅ |
| Perspective Engine | `perspective.py` | NW-005 | 570 | ✅ |
| Evidence Report | `evidence.py` | NW-006 | 410 | ✅ |
| Observer→Evidence Adapter | `observer_evidence_adapter.py` | — | 266 | ✅ |
| Verified Click Executor (mock) | `executor.py` | NW-009 | 722 | ✅ |
| Action Ledger | `ledger.py` | NW-010 | 273 | ✅ |
| Pipeline Benchmark | benchmarks | NW-011 | — | ✅ |
| File Leases | `leases.py` | NW-012 | 382 | ✅ |
| Scene Graph Builder | `scene_graph_builder.py` | NW-013 | 629 | ✅ |
| Graph Query Layer | `graph_query.py` | NW-014 | 616 | ✅ |
| Executor→Query Integration | `executor.py` | NW-015 | — | ✅ |
| Action Orchestrator | `action_orchestrator.py` | NW-016 | 1011 | ✅ |
| E2E Integration Pipeline | `test_e2e_integration.py` | NW-017 | — | ✅ |
| SceneGraph+Orchestrator Benchmark | benchmarks | NW-018 | — | ✅ |
| Observability Trace | `action_orchestrator.py` | NW-019 | — | ✅ |
| Retry with Re-Observation | `action_orchestrator.py` | NW-020 | — | ✅ |
| Site Skill Schema + Store | `site_skill.py` | NW-021 | 283 | ✅ |
| Skill Matcher Engine | `skill_matcher.py` | NW-022 | 203 | ✅ |
| Skill Learning Benchmark | benchmarks | NW-023 | — | ✅ |
| Goal-to-Plan Translator | `planner.py` | NW-024 | 631 | ✅ |
| Skill Learner | `skill_learner.py` | NW-025 | 259 | ✅ |

**Architecture complete:** observe → plan → execute → verify → learn loop fully scaffolded.

---

## Phase 2: Live Integration (IN PROGRESS)

**Goal:** Replace mock backends with real CloakBrowser/Playwright integration. Validate end-to-end on real websites.

### Prerequisites (Infrastructure)
- [ ] Fix cron prompt template (inline ~25K skill doc → `skill_view()`)
- [ ] Create initial git commit
- [x] ~~Remove legacy `scene_builder.py`~~ (done 2026-05-24 by Runtime Engineer)
- [ ] Update `PROJECT_GOAL.md` to NetWeaver mission

### P2-001: CloakBrowser Observer Bridge ✅ DONE
- `netweaver/cloak_bridge.py` — CloakBrowser SDK abstraction layer (266 LOC)
- `netweaver/observer.py` — delegates live mode to bridge
- `tests/test_cloak_bridge.py` — 35 tests with mock SDK
- 1354 total tests green

### P2-002: Live Executor Integration
- Wire `executor.py` to real browser actions via CloakBrowser
- Replace mock callbacks with `browser.click()`, `browser.type()`, `browser.wait_for()`
- Evidence collection from real browser (not mock data)
- Scope: `netweaver/executor.py`, `netweaver/cloak_bridge.py`

### P2-003: Real Evidence Pipeline
- Observer→Evidence adapter consumes real (not mock) observations
- EvidenceReport claims backed by actual DOM/network/storage state
- Verify evidence chain integrity on real pages
- Scope: `netweaver/observer_evidence_adapter.py`, `netweaver/evidence.py`

### P2-004: Multi-Step Orchestration on Real Sites
- Run orchestrated action sequences (login, search, form fill) on real websites
- Validate inter-step verification catches real state changes
- Validate rollback on real failures
- Scope: `netweaver/action_orchestrator.py`, integration tests

### P2-005: Skill Learning from Real Executions
- Learn SiteSkills from successful real-browser orchestrations
- Validate skill matching reuses learned skills on repeat visits
- Measure success rate improvement over sessions
- Scope: `netweaver/skill_learner.py`, `netweaver/skill_matcher.py`

### P2-006: Safety Validation on Real Interactions
- Validate PerspectiveEngine catches real safety risks (payment, credential submission)
- Test ASK/ABORT behavior on real risky actions
- Scope: `netweaver/perspective.py`, safety integration tests

---

## Phase 3: Intelligence Layer (NOT STARTED)

**Goal:** Add LLM-powered reasoning for novel goals, advanced recovery, and cross-site generalization.

### P3-001: LLM Intent Compiler
- NL → WNAL for novel goals that don't match templates
- Use LLM only when GoalTranslator template matching fails
- Fallback to deterministic path when available
- Scope: new `netweaver/intent_compiler.py`

### P3-002: Intelligent Recovery Engine
- Automatic failure classification from evidence chain
- Recovery strategy selection based on failure type
- Avoid retry loops with exponential backoff + strategy rotation
- Scope: `netweaver/recovery.py`

### P3-003: Cross-Site Skill Generalization
- Recognize that login flows share structure across sites
- Generalize skills from site-specific to pattern-specific
- Transfer learned selectors to similar site structures
- Scope: `netweaver/skill_matcher.py`, new `netweaver/skill_generalizer.py`

### P3-004: Visual Grounding
- Screenshot analysis for canvas-heavy / overlay-heavy pages
- Visual coordinate clicking when DOM selectors fail
- Visual verification of action results
- Scope: new `netweaver/visual_grounder.py`

### P3-005: JS Runtime Introspection
- React/Vue/Svelte state inspection
- Hydration state detection
- Event handler discovery
- Scope: new `netweaver/js_analyst.py`

### P3-006: Network Intelligence
- fetch/XHR interception and classification
- REST/GraphQL API pattern recognition
- Auth flow detection and validation
- Scope: new `netweaver/network_intelligence.py`

---

## Phase 4: Production (NOT STARTED)

**Goal:** Deployment, monitoring, and real-world validation.

- Benchmark suite against WebArena / Browser Use baselines
- Token efficiency measurement
- Task success rate tracking
- Multi-user session management
- Deployment packaging (Docker, CLI, API server)

---

## Open Questions

1. **CloakBrowser vs Playwright:** Observer has optional CloakBrowser import. Should Playwright be a supported backend alongside CloakBrowser?
2. **LLM provider:** Which LLM for Intent Compiler? Provider-agnostic design suggests configurable.
3. **Graph backend:** In-memory Python graph works for single-page. Multi-page/multi-session may need persistent graph store.
4. **Skill persistence:** Currently JSON files. Scale requires database (SQLite at minimum).
5. **Safety policy configurability:** Hardcoded priority resolution. Should be configurable per deployment.

---

## Known Technical Debt

| Issue | Severity | Location |
|-------|----------|----------|
| ~~`scene_builder.py` dead code~~ | ~~Low~~ | ~~Removed 2026-05-24~~ |
| ~~`EvidenceReport.summary()` mutates via `verify()`~~ | ~~Medium~~ | ~~Fixed 2026-05-24 — `_check_verified()` added~~ |
| ~~`FillAction` stores raw text params (credential leak risk)~~ | ~~Medium~~ | ~~Fixed 2026-05-24 — `is_sensitive` + `masked_value`~~ |
| ~~No git history (all files untracked)~~ | ~~High~~ | ~~Resolved 2026-05-25 — initial commit done~~ |
| `PROJECT_GOAL.md` still TINI-oriented | Medium | Project root |
| Cron prompt inlines ~25K skill doc | Critical | Cron job config |
| ~~History perspective scaffolded but empty~~ | ~~Low~~ | ~~Implemented in `netweaver/perspective.py` — HistoryPerspective assesses past failures and known patterns~~ |
| JS/Visual node types defined but no real collection | Medium | `netweaver/scene_graph.py` |
| ~~Template planner has 5 patterns only~~ | ~~Medium~~ | ~~Expanded to 10 patterns 2026-05-24~~ |
| ~~`action_from_dict` drops `is_sensitive` on FillAction~~ | ~~Medium~~ | ~~Fixed 2026-05-24 — `is_sensitive` now preserved in deserialization~~ |
| ~~`action_from_dict` drops evidence/verification on deserialize~~ | ~~Medium~~ | ~~Fixed 2026-05-25 — `_deserialize_evidence()` + `_deserialize_verification()` added~~ |
| `.tini/netweaver/` duplicates/conflicts with root `netweaver/` | Medium | `.tini/netweaver/` |
