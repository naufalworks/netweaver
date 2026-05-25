# SceneGraph & Orchestrator Benchmark Plan

**Task**: NW-018
**Owner**: QA Benchmark
**Date**: 2026-05-24
**Status**: review

## Purpose

Define repeatable benchmark tasks and success metrics for three core NetWeaver modules that currently lack dedicated benchmark coverage:

1. **WebSceneGraph** (`scene_graph.py`) — browser-native world model data structure
2. **Graph Query Layer** (`graph_query.py`) — evidence-native target resolution
3. **Action Orchestrator** (`action_orchestrator.py`) — multi-step graph-driven action sequences

All benchmarks use **mocked graphs and callbacks** — no browser download, no Playwright, no network access required.

---

## Benchmark Tasks (8)

### SG-001: SceneGraph Construction & Serialization

Build a scene graph with DOM, INTENT, and CONTAINMENT nodes; verify round-trip serialization.

**Pass criteria**:
- Graph contains expected node types
- `to_dict()` / `from_dict()` round-trip preserves all fields
- Edge source/target refer to existing nodes
- Node/edge count matches expectations

### SG-002: SceneGraph Query Operations

Populate a graph with mixed node/edge types; verify query methods.

**Pass criteria**:
- `get_nodes_by_type()` filters correctly
- `get_children()` / `get_parent()` traverse CONTAINMENT edges
- `get_neighbors()` returns both directions
- `get_causes()` / `get_effects()` traverse CAUSALITY edges
- Empty graph returns empty results

### SG-003: Graph Target Resolution (resolve_target)

Test natural-language element resolution against a realistic scene graph.

**Pass criteria**:
- "login button" resolves to the correct DOM node with score > 0.3
- "email input" resolves to fillable element
- Unknown description returns None
- Safety-blocked node excluded when exclude_blocked=True
- Safety-blocked node returned when exclude_blocked=False

### SG-004: Actionable Node Discovery (find_actionable_nodes)

Test intent-based node discovery with evidence and safety filtering.

**Pass criteria**:
- CLICK intent returns only clickable nodes
- FILL intent returns only fillable nodes
- Safety-blocked nodes excluded by default
- min_evidence threshold filters correctly
- Results sorted by score (descending)

### SG-005: Safe Pathfinding (find_safe_path)

Test BFS pathfinding with safety-blocked nodes.

**Pass criteria**:
- Direct path found between adjacent nodes
- Multi-hop path found through intermediate nodes
- Path blocked when intermediate node is safety-blocked
- Self-path returns length 0
- Missing node returns empty result

### SG-006: Orchestrator Happy Path — Multi-Step Plan

Execute a 3-step plan (fill → fill → click) against mock graph supplier.

**Pass criteria**:
- PlanStatus transitions PENDING → RUNNING → COMPLETED
- All 3 steps have status COMPLETED
- Each StepResult has execution and resolution records
- Evidence chain IDs collected per step
- OrchestrationResult.completed_steps == 3

### SG-007: Orchestrator Failure Handling — Mid-Sequence Halt

Execute a 3-step plan where step 2 fails (target not found).

**Pass criteria**:
- Step 0 COMPLETED
- Step 1 FAILED
- Step 2 not attempted
- PlanStatus == FAILED
- Error message references failed step
- completed_steps == 1

### SG-008: Graph Delta Computation

Compare two scene graph snapshots and verify delta detection.

**Pass criteria**:
- Added nodes detected
- Removed nodes detected
- Modified nodes (property change) detected
- Added/removed edges detected
- Empty delta when graphs are identical
- `has_changes` property correct

---

## Scoring Formula

```
benchmark_score = (tests_passed / total_tests) * 100

quality_gates:
  - All serialization round-trips pass
  - Safety filtering works in both directions
  - Orchestrator handles both success and failure paths
  - Score >= 90% for PASS
```

## Module Coverage

| Module | Benchmarks | Key APIs Covered |
|--------|-----------|-----------------|
| `scene_graph.py` | SG-001, SG-002 | SceneNode, SceneEdge, WebSceneGraph CRUD, query ops, serialization |
| `graph_query.py` | SG-003, SG-004, SG-005 | resolve_target, find_actionable_nodes, find_safe_path, check_evidence_chain |
| `action_orchestrator.py` | SG-006, SG-007, SG-008 | orchestrate, roll_back, verify_step, compute_graph_delta, GraphDelta |
