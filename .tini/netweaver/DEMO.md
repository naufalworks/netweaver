# NetWeaver Demo — End-to-End Pipeline (NW-032)

## Architecture Flow

```
URL
 │
 ▼
┌─────────────────────┐
│  Observer            │  observe_page_mock(url) → PageObservation
│  (observer.py)       │  Extracts: elements, actionability, network, storage
└──────────┬──────────┘
           │ PageObservation
           ▼
┌─────────────────────┐
│  SceneGraphBuilder   │  builder.build(observation) → BuilderResult
│  (scene_graph_builder│  Creates: DOM/A11Y/Visual/Intent nodes
│   .py)               │  + CONTAINMENT/EVIDENCE/DEPENDENCY edges
└──────────┬──────────┘
           │ WebSceneGraph + EvidenceReport
           ▼
┌─────────────────────┐
│  GoalTranslator      │  translator.translate(goal, graph) → PlanResult
│  (planner.py)        │  Matches templates: login, search, fill-form...
└──────────┬──────────┘
           │ ActionPlan
           ▼
┌─────────────────────┐
│  ActionOrchestrator  │  orchestrator.orchestrate(plan, graph_supplier)
│  (action_orchestrator│  Chains: resolve → execute → verify per step
│   .py)               │  Rollback on failure, safety blocking
└──────────┬──────────┘
           │ OrchestrationResult
           ▼
┌─────────────────────┐
│  EvidenceReport      │  ≥3 claims with evidence chain
│  (evidence.py)       │  All claims verified (SUPPORTED status)
└─────────────────────┘
```

## Quick Start

```bash
# Run demo with explicit actions
python -m netweaver.demo --url example.com --actions "click(#login),fill(#user,admin)"

# Run demo with auto-planning (goal-based)
python -m netweaver.demo --url example.com --goal login

# JSON output
python -m netweaver.demo --url example.com --json
```

## Example Output

```
NetWeaver Demo Pipeline — example.com
==================================================
Status: SUCCESS
Observation: 3 elements on 'Example Domain'
Scene Graph: 18 nodes, 12 edges
Plan: template=login, confidence=0.83, steps=3
Orchestration: status=completed, completed=3
Evidence Report: 4 claims, 4 observations, verified=True
```

## Module API

```python
from netweaver.demo import DemoModule, parse_actions
from netweaver.action_orchestrator import ActionStep, ActionType

# Option 1: Auto-planning from goal
demo = DemoModule()
result = demo.run_demo("https://example.com/login", goal="login")

# Option 2: Explicit actions
actions = [
    ActionStep(ActionType.FILL, "#user", text="admin"),
    ActionStep(ActionType.FILL, "#pass", text="secret"),
    ActionStep(ActionType.CLICK, "#submit"),
]
result = demo.run_demo("https://example.com/login", actions=actions)

# Inspect results
print(result.summary())
print(result.evidence_report.claims)
```

## Evidence Report Structure

The demo produces an EvidenceReport with 4 claims:

1. **Observation claim** (DOM): Page observation collected with N interactive elements
2. **Scene graph claim** (DOM): Graph built with N nodes and M edges
3. **Execution claim** (ACTIONABILITY): Plan executed with N steps, status=X
4. **Network claim** (NETWORK): Network activity observed (requests/failures)

All claims are verified (SUPPORTED) with linked observations.

## Design Decisions

- **Mock browser only**: Uses `observe_page_mock()` — no real Chromium needed
- **Injectable observer**: `DemoModule(observer_fn=custom_fn)` for testing
- **No Playwright/vendor imports**: Pure Python pipeline
- **Error resilience**: Pipeline stages fail gracefully with error EvidenceReport
- **CLI + library**: Use as module or command-line tool
