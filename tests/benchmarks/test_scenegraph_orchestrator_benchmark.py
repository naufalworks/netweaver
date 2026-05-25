"""SceneGraph & Orchestrator Benchmark Tests — NW-018

Benchmark tests for three core NetWeaver modules:
  - WebSceneGraph (scene_graph.py): construction, serialization, query ops
  - Graph Query Layer (graph_query.py): target resolution, actionable discovery, safe pathfinding
  - Action Orchestrator (action_orchestrator.py): multi-step plans, failure handling, delta computation

No browser download, no Playwright, no network required.

Run: python -m pytest tests/benchmarks/test_scenegraph_orchestrator_benchmark.py -v
"""

import pytest
from datetime import datetime
from typing import List

from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    SceneEdge,
    SceneNode,
    WebSceneGraph,
)
from netweaver.graph_query import (
    EvidenceStatus,
    IntentType,
    PathResult,
    QueryMatch,
    check_evidence_chain,
    find_actionable_nodes,
    find_safe_path,
    resolve_target,
)
from netweaver.action_orchestrator import (
    ActionOrchestrator,
    ActionPlan,
    ActionStep,
    ActionType,
    GraphDelta,
    OrchestrationResult,
    PlanStatus,
    StepResult,
    compute_graph_delta,
)
from netweaver.executor import (
    ExecutionStatus,
    ResolutionStatus,
    VerifiedExecutor,
)
from netweaver.wnal import ActionabilityEvidence, Phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    node_id: str,
    node_type: NodeType = NodeType.DOM,
    label: str = "",
    properties: dict = None,
    observation_ids: list = None,
) -> SceneNode:
    return SceneNode(
        node_id=node_id,
        node_type=node_type,
        label=label,
        properties=properties or {},
        observation_ids=observation_ids or [],
    )


def _make_edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    edge_type: EdgeType = EdgeType.CONTAINMENT,
    **extra_props,
) -> SceneEdge:
    props = dict(extra_props) if extra_props else {}
    return SceneEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        properties=props,
    )


def _build_login_graph() -> WebSceneGraph:
    """Build a realistic login-form scene graph for benchmark tests.

    Structure:
      root (DOM) → form (DOM) → [username-input (DOM), password-input (DOM), submit-btn (DOM)]
      Each DOM element has an INTENT node with affordance.
      submit-btn also has a CONTAINMENT edge from form.
    """
    graph = WebSceneGraph(graph_id="bench-login", url="https://example.com/login", title="Login")

    # DOM nodes
    root = _make_node("root", NodeType.DOM, "html", {"is_root": True})
    form = _make_node("form", NodeType.DOM, "form#login", {"text": "login form", "selector": "#login"}, ["obs-1"])
    username = _make_node("username", NodeType.DOM, "input#username", {"text": "Username", "selector": "#username", "tag": "input"}, ["obs-2"])
    password = _make_node("password", NodeType.DOM, "input#password", {"text": "Password", "selector": "#password", "tag": "input"}, ["obs-3"])
    submit = _make_node("submit", NodeType.DOM, "button#submit", {"text": "Login", "selector": "#submit", "tag": "button"}, ["obs-4"])

    for n in [root, form, username, password, submit]:
        graph.add_node(n)

    # CONTAINMENT edges
    graph.add_edge(_make_edge("e-root-form", "root", "form"))
    graph.add_edge(_make_edge("e-form-user", "form", "username"))
    graph.add_edge(_make_edge("e-form-pass", "form", "password"))
    graph.add_edge(_make_edge("e-form-submit", "form", "submit"))

    # INTENT nodes (affordance classification)
    # parent_dom_id goes in metadata (used by graph_query to resolve back to DOM)
    intent_user = _make_node("intent-user", NodeType.INTENT, "fill username",
                             {"affordance": "fillable"}, [])
    intent_user.metadata["parent_dom_id"] = "username"
    intent_pass = _make_node("intent-pass", NodeType.INTENT, "fill password",
                             {"affordance": "fillable"}, [])
    intent_pass.metadata["parent_dom_id"] = "password"
    intent_submit = _make_node("intent-submit", NodeType.INTENT, "click submit",
                               {"affordance": "clickable"}, [])
    intent_submit.metadata["parent_dom_id"] = "submit"
    intent_nav = _make_node("intent-nav", NodeType.INTENT, "navigate link",
                            {"affordance": "navigable"}, [])
    # Use a separate node for navigable (don't overwrite submit's clickable intent)
    nav_node = _make_node("nav-link", NodeType.DOM, "a#home",
                          {"text": "Home", "selector": "#home", "tag": "a"}, ["obs-5"])
    graph.add_node(nav_node)
    graph.add_edge(_make_edge("e-form-nav", "form", "nav-link"))
    intent_nav.metadata["parent_dom_id"] = "nav-link"

    for n in [intent_user, intent_pass, intent_submit, intent_nav]:
        graph.add_node(n)

    # EVIDENCE edges from INTENT → DOM parent
    graph.add_edge(_make_edge("e-intent-user", "intent-user", "username", EdgeType.EVIDENCE))
    graph.add_edge(_make_edge("e-intent-pass", "intent-pass", "password", EdgeType.EVIDENCE))
    graph.add_edge(_make_edge("e-intent-submit", "intent-submit", "submit", EdgeType.EVIDENCE))

    # ACCESSIBILITY node for submit (aria-label)
    a11y_submit = _make_node("a11y-submit", NodeType.ACCESSIBILITY, "aria: Submit Login",
                             {"aria_label": "Submit Login", "role": "button"}, [])
    graph.add_node(a11y_submit)
    graph.add_edge(_make_edge("e-a11y-submit", "submit", "a11y-submit", EdgeType.CONTAINMENT))

    return graph


def _build_graph_with_safety_block() -> WebSceneGraph:
    """Build a graph where 'submit' node is safety-blocked."""
    graph = _build_login_graph()

    # Add safety enrichment INTENT node blocking submit
    safety_node = _make_node("safety-block", NodeType.INTENT, "safety: payment risk",
                             {"is_safety_enrichment": True, "strategy": "abort", "reason": "payment form"}, [])
    graph.add_node(safety_node)
    graph.add_edge(_make_edge("e-safety-dep", "safety-block", "submit", EdgeType.DEPENDENCY))

    return graph


def _make_editable_evidence(action_id: str, target_ref: str) -> ActionabilityEvidence:
    return ActionabilityEvidence(
        action_id=action_id, target_ref=target_ref, phase=Phase.PRE,
        attached=True, visible=True, enabled=True, editable=True,
        stable=True, pointer_events=True, observed_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# SG-001: SceneGraph Construction & Serialization
# ---------------------------------------------------------------------------

class TestSG001ConstructionSerialization:
    """SG-001: Build graph, verify structure, test serialization round-trip."""

    def test_graph_contains_expected_node_types(self):
        graph = _build_login_graph()
        dom_nodes = graph.get_nodes_by_type(NodeType.DOM)
        intent_nodes = graph.get_nodes_by_type(NodeType.INTENT)
        a11y_nodes = graph.get_nodes_by_type(NodeType.ACCESSIBILITY)
        assert len(dom_nodes) == 6  # root, form, username, password, submit, nav-link
        assert len(intent_nodes) == 4  # user, pass, submit, nav
        assert len(a11y_nodes) == 1

    def test_edge_source_target_exist_in_graph(self):
        graph = _build_login_graph()
        for edge in graph.edges.values():
            assert edge.source_id in graph.nodes
            assert edge.target_id in graph.nodes

    def test_node_count(self):
        graph = _build_login_graph()
        # 6 DOM + 4 INTENT + 1 ACCESSIBILITY = 11
        assert graph.node_count() == 11

    def test_edge_count(self):
        graph = _build_login_graph()
        # 5 CONTAINMENT + 3 EVIDENCE + 1 CONTAINMENT(a11y) = 9
        assert graph.edge_count() == 9

    def test_node_serialization_round_trip(self):
        graph = _build_login_graph()
        node = graph.get_node("submit")
        d = node.to_dict()
        restored = SceneNode.from_dict(d)
        assert restored.node_id == node.node_id
        assert restored.node_type == node.node_type
        assert restored.label == node.label
        assert restored.properties == node.properties
        assert restored.observation_ids == node.observation_ids

    def test_edge_serialization_round_trip(self):
        graph = _build_login_graph()
        edge = list(graph.edges.values())[0]
        d = edge.to_dict()
        restored = SceneEdge.from_dict(d)
        assert restored.edge_id == edge.edge_id
        assert restored.source_id == edge.source_id
        assert restored.target_id == edge.target_id
        assert restored.edge_type == edge.edge_type

    def test_graph_serialization_round_trip(self):
        graph = _build_login_graph()
        d = graph.to_dict()
        restored = WebSceneGraph.from_dict(d)
        assert restored.graph_id == graph.graph_id
        assert restored.url == graph.url
        assert len(restored.nodes) == len(graph.nodes)
        assert len(restored.edges) == len(graph.edges)
        # Verify a specific node survived round-trip
        original_submit = graph.get_node("submit")
        restored_submit = restored.get_node("submit")
        assert restored_submit.label == original_submit.label
        assert restored_submit.properties == original_submit.properties


# ---------------------------------------------------------------------------
# SG-002: SceneGraph Query Operations
# ---------------------------------------------------------------------------

class TestSG002QueryOperations:
    """SG-002: Verify graph query methods on populated graph."""

    def test_get_nodes_by_type_dom(self):
        graph = _build_login_graph()
        dom_nodes = graph.get_nodes_by_type(NodeType.DOM)
        labels = {n.label for n in dom_nodes}
        assert "button#submit" in labels
        assert "input#username" in labels

    def test_get_nodes_by_type_empty_for_missing(self):
        graph = _build_login_graph()
        js_nodes = graph.get_nodes_by_type(NodeType.JS)
        assert js_nodes == []

    def test_get_edges_by_type(self):
        graph = _build_login_graph()
        containment = graph.get_edges_by_type(EdgeType.CONTAINMENT)
        evidence = graph.get_edges_by_type(EdgeType.EVIDENCE)
        assert len(containment) >= 4
        assert len(evidence) >= 3

    def test_get_children_containment(self):
        graph = _build_login_graph()
        children = graph.get_children("form")
        assert "username" in children
        assert "password" in children
        assert "submit" in children
        assert "nav-link" in children

    def test_get_parent_containment(self):
        graph = _build_login_graph()
        assert graph.get_parent("username") == "form"
        assert graph.get_parent("form") == "root"
        assert graph.get_parent("root") is None

    def test_get_neighbors_both_directions(self):
        graph = _build_login_graph()
        neighbors = graph.get_neighbors("form")
        assert "root" in neighbors
        assert "username" in neighbors

    def test_get_outgoing_edges(self):
        graph = _build_login_graph()
        outgoing = graph.get_outgoing_edges("form")
        targets = {e.target_id for e in outgoing}
        assert "username" in targets

    def test_get_incoming_edges(self):
        graph = _build_login_graph()
        incoming = graph.get_incoming_edges("submit")
        sources = {e.source_id for e in incoming}
        assert "form" in sources

    def test_empty_graph_returns_empty(self):
        graph = WebSceneGraph(graph_id="empty", url="about:blank")
        assert graph.get_nodes_by_type(NodeType.DOM) == []
        assert graph.get_edges_by_type(EdgeType.CONTAINMENT) == []
        assert graph.get_children("nonexistent") == []
        assert graph.get_parent("nonexistent") is None
        assert graph.get_neighbors("nonexistent") == []

    def test_causality_edges(self):
        graph = WebSceneGraph(graph_id="causal", url="test")
        n1 = _make_node("js1", NodeType.JS, "onclick handler")
        n2 = _make_node("dom1", NodeType.DOM, "button")
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_edge(_make_edge("c1", "js1", "dom1", EdgeType.CAUSALITY))

        assert graph.get_causes("dom1") == ["js1"]
        assert graph.get_effects("js1") == ["dom1"]
        assert graph.get_causes("js1") == []
        assert graph.get_effects("dom1") == []


# ---------------------------------------------------------------------------
# SG-003: Graph Target Resolution (resolve_target)
# ---------------------------------------------------------------------------

class TestSG003ResolveTarget:
    """SG-003: Natural-language element resolution via resolve_target."""

    def test_login_button_resolves(self):
        graph = _build_login_graph()
        match = resolve_target(graph, "submit button")
        assert match is not None
        assert match.node.node_id == "submit"
        assert match.score > 0.3

    def test_login_button_matches_text_content(self):
        graph = _build_login_graph()
        # "submit" matches label "button#submit" and selector "#submit" exactly
        match = resolve_target(graph, "submit")
        assert match is not None
        assert match.node.node_id == "submit"

    def test_email_input_resolves(self):
        graph = _build_login_graph()
        match = resolve_target(graph, "username")
        assert match is not None
        assert match.node.node_id == "username"

    def test_aria_label_match(self):
        graph = _build_login_graph()
        match = resolve_target(graph, "Submit Login")
        assert match is not None
        assert match.node.node_id == "submit"

    def test_unknown_description_returns_none(self):
        graph = _build_login_graph()
        match = resolve_target(graph, "totally made up xyzzy widget")
        assert match is None

    def test_safety_blocked_excluded_by_default(self):
        graph = _build_graph_with_safety_block()
        match = resolve_target(graph, "submit button", exclude_blocked=True)
        assert match is None  # submit is safety-blocked, excluded

    def test_safety_blocked_included_when_requested(self):
        graph = _build_graph_with_safety_block()
        match = resolve_target(graph, "submit button", exclude_blocked=False)
        assert match is not None
        assert match.node.node_id == "submit"
        assert match.blocked is True

    def test_intent_filter_narrows_candidates(self):
        graph = _build_login_graph()
        match = resolve_target(graph, "username", intent=IntentType.FILL)
        assert match is not None
        assert match.node.node_id == "username"


# ---------------------------------------------------------------------------
# SG-004: Actionable Node Discovery (find_actionable_nodes)
# ---------------------------------------------------------------------------

class TestSG004FindActionableNodes:
    """SG-004: Intent-based node discovery with evidence/safety filtering."""

    def test_click_intent_returns_clickable(self):
        graph = _build_login_graph()
        matches = find_actionable_nodes(graph, IntentType.CLICK)
        node_ids = {m.node.node_id for m in matches}
        assert "submit" in node_ids

    def test_fill_intent_returns_fillable(self):
        graph = _build_login_graph()
        matches = find_actionable_nodes(graph, IntentType.FILL)
        node_ids = {m.node.node_id for m in matches}
        assert "username" in node_ids
        assert "password" in node_ids

    def test_navigate_intent_returns_navigable(self):
        graph = _build_login_graph()
        matches = find_actionable_nodes(graph, IntentType.NAVIGATE)
        assert len(matches) >= 1
        node_ids = {m.node.node_id for m in matches}
        assert "nav-link" in node_ids

    def test_safety_blocked_excluded_by_default(self):
        graph = _build_graph_with_safety_block()
        matches = find_actionable_nodes(graph, IntentType.CLICK, exclude_blocked=True)
        node_ids = {m.node.node_id for m in matches}
        assert "submit" not in node_ids

    def test_safety_blocked_included_when_requested(self):
        graph = _build_graph_with_safety_block()
        matches = find_actionable_nodes(graph, IntentType.CLICK, exclude_blocked=False)
        node_ids = {m.node.node_id for m in matches}
        assert "submit" in node_ids

    def test_min_evidence_threshold(self):
        graph = _build_login_graph()
        # root has no observations → filtered out at min_evidence=1
        matches = find_actionable_nodes(graph, IntentType.CLICK, min_evidence=1)
        node_ids = {m.node.node_id for m in matches}
        # submit has ["obs-4"] → 1 evidence
        assert "submit" in node_ids

    def test_results_sorted_by_score_descending(self):
        graph = _build_login_graph()
        matches = find_actionable_nodes(graph, IntentType.ANY)
        scores = [m.score for m in matches]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# SG-005: Safe Pathfinding (find_safe_path)
# ---------------------------------------------------------------------------

class TestSG005SafePathfinding:
    """SG-005: BFS pathfinding with safety-blocked node exclusion."""

    def test_direct_path_adjacent(self):
        graph = _build_login_graph()
        result = find_safe_path(graph, "root", "form")
        assert result.length == 1
        assert result.path == ["root", "form"]

    def test_multi_hop_path(self):
        graph = _build_login_graph()
        result = find_safe_path(graph, "root", "submit")
        assert result.length >= 1
        assert "submit" in result.path

    def test_path_blocked_by_safety(self):
        graph = _build_graph_with_safety_block()
        # Path from root to submit should be blocked (submit has safety node)
        result = find_safe_path(graph, "root", "submit")
        # Either blocked or empty (submit is blocked)
        assert result.blocked or result.path == []

    def test_self_path_returns_length_zero(self):
        graph = _build_login_graph()
        result = find_safe_path(graph, "root", "root")
        assert result.length == 0
        assert result.path == ["root"]

    def test_missing_node_returns_empty(self):
        graph = _build_login_graph()
        result = find_safe_path(graph, "root", "nonexistent")
        assert result.path == []
        assert result.length == 0

    def test_path_includes_edges(self):
        graph = _build_login_graph()
        result = find_safe_path(graph, "root", "form")
        assert len(result.edges) >= 1


# ---------------------------------------------------------------------------
# SG-006: Orchestrator Happy Path — Multi-Step Plan
# ---------------------------------------------------------------------------

class TestSG006OrchestratorHappyPath:
    """SG-006: 3-step fill→fill→click plan completes successfully."""

    def _make_orchestrator_and_plan(self):
        graph = _build_login_graph()
        executor = VerifiedExecutor(evidence_collector=_make_editable_evidence)
        orchestrator = ActionOrchestrator(executor=executor)

        plan = ActionPlan(description="Login flow")
        plan.add_step(ActionType.FILL, "username", text="user@test.com")
        plan.add_step(ActionType.FILL, "password", text="secret123")
        plan.add_step(ActionType.CLICK, "submit")

        return orchestrator, plan, graph

    def test_plan_completes(self):
        orchestrator, plan, graph = self._make_orchestrator_and_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.status == PlanStatus.COMPLETED

    def test_all_steps_completed(self):
        orchestrator, plan, graph = self._make_orchestrator_and_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.completed_steps == 3
        for step in result.steps:
            assert step.status == PlanStatus.COMPLETED

    def test_each_step_has_execution_and_resolution(self):
        orchestrator, plan, graph = self._make_orchestrator_and_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        for step in result.steps:
            assert step.execution is not None
            assert step.resolution is not None

    def test_evidence_chain_collected(self):
        orchestrator, plan, graph = self._make_orchestrator_and_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        for step in result.steps:
            if step.execution and step.execution.report:
                assert len(step.evidence_chain_ids) > 0

    def test_result_has_plan_id(self):
        orchestrator, plan, graph = self._make_orchestrator_and_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.plan_id == plan.plan_id

    def test_result_timestamps_set(self):
        orchestrator, plan, graph = self._make_orchestrator_and_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.started_at is not None
        assert result.finished_at is not None


# ---------------------------------------------------------------------------
# SG-007: Orchestrator Failure Handling — Mid-Sequence Halt
# ---------------------------------------------------------------------------

class TestSG007OrchestratorFailure:
    """SG-007: Plan halts when step 2 fails (target not found)."""

    def _make_failing_plan(self):
        graph = _build_login_graph()
        executor = VerifiedExecutor(evidence_collector=_make_editable_evidence)
        orchestrator = ActionOrchestrator(executor=executor)

        plan = ActionPlan(description="Login with missing element")
        plan.add_step(ActionType.FILL, "username", text="user@test.com")  # OK
        plan.add_step(ActionType.CLICK, "totally made up xyzzy widget")    # FAIL (no match)
        plan.add_step(ActionType.CLICK, "submit")                          # Not reached

        return orchestrator, plan, graph

    def test_plan_status_failed(self):
        orchestrator, plan, graph = self._make_failing_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.status == PlanStatus.FAILED

    def test_step_0_completed(self):
        orchestrator, plan, graph = self._make_failing_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.steps[0].status == PlanStatus.COMPLETED

    def test_step_1_failed(self):
        orchestrator, plan, graph = self._make_failing_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.steps[1].status == PlanStatus.FAILED

    def test_step_2_not_attempted(self):
        orchestrator, plan, graph = self._make_failing_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert len(result.steps) == 2  # Only 2 steps attempted

    def test_completed_steps_count(self):
        orchestrator, plan, graph = self._make_failing_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.completed_steps == 1

    def test_error_message_references_failed_step(self):
        orchestrator, plan, graph = self._make_failing_plan()
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.error is not None
        assert "1" in result.error  # Step index 1


# ---------------------------------------------------------------------------
# SG-008: Graph Delta Computation
# ---------------------------------------------------------------------------

class TestSG008GraphDelta:
    """SG-008: Scene graph comparison and delta detection."""

    def test_added_nodes_detected(self):
        pre = _build_login_graph()
        post = _build_login_graph()
        new_node = _make_node("extra", NodeType.NETWORK, "xhr /api/data")
        post.add_node(new_node)
        delta = compute_graph_delta(pre, post)
        assert "extra" in delta.nodes_added

    def test_removed_nodes_detected(self):
        pre = _build_login_graph()
        post = _build_login_graph()
        post.remove_node("submit")
        delta = compute_graph_delta(pre, post)
        assert "submit" in delta.nodes_removed

    def test_modified_nodes_detected(self):
        pre = _build_login_graph()
        post = _build_login_graph()
        # Modify submit's properties
        post.nodes["submit"].properties["text"] = "Sign In"
        delta = compute_graph_delta(pre, post)
        assert "submit" in delta.nodes_modified

    def test_added_edges_detected(self):
        pre = WebSceneGraph(graph_id="pre", url="test")
        post = WebSceneGraph(graph_id="post", url="test")
        n1 = _make_node("a", NodeType.DOM, "a")
        n2 = _make_node("b", NodeType.DOM, "b")
        for n in [n1, n2]:
            pre.add_node(n)
            post.add_node(n)
        post.add_edge(_make_edge("e-new", "a", "b"))
        delta = compute_graph_delta(pre, post)
        assert "e-new" in delta.edges_added

    def test_removed_edges_detected(self):
        pre = WebSceneGraph(graph_id="pre", url="test")
        post = WebSceneGraph(graph_id="post", url="test")
        n1 = _make_node("a", NodeType.DOM, "a")
        n2 = _make_node("b", NodeType.DOM, "b")
        pre.add_node(n1)
        pre.add_node(n2)
        post.add_node(n1)
        post.add_node(n2)
        pre.add_edge(_make_edge("e-old", "a", "b"))
        delta = compute_graph_delta(pre, post)
        assert "e-old" in delta.edges_removed

    def test_identical_graphs_empty_delta(self):
        graph = _build_login_graph()
        delta = compute_graph_delta(graph, graph)
        assert delta.nodes_added == []
        assert delta.nodes_removed == []
        assert delta.nodes_modified == []
        assert delta.edges_added == []
        assert delta.edges_removed == []

    def test_has_changes_property(self):
        pre = _build_login_graph()
        post = _build_login_graph()
        delta = compute_graph_delta(pre, post)
        assert delta.has_changes is False

        post.nodes["submit"].properties["text"] = "Changed"
        delta = compute_graph_delta(pre, post)
        assert delta.has_changes is True

    def test_delta_serialization(self):
        pre = _build_login_graph()
        post = _build_login_graph()
        post.add_node(_make_node("extra", NodeType.NETWORK, "xhr"))
        delta = compute_graph_delta(pre, post)
        d = delta.to_dict()
        assert "extra" in d["nodes_added"]
        assert isinstance(d["has_changes"], bool)

    def test_orchestrator_verify_step(self):
        """Integration: verify_step uses compute_graph_delta internally."""
        orchestrator = ActionOrchestrator()
        pre = _build_login_graph()
        post = _build_login_graph()
        post.nodes["submit"].properties["text"] = "Clicked!"

        step = ActionStep(
            action_type=ActionType.CLICK,
            description="submit",
            post_condition="button text changes",
        )
        result = orchestrator.verify_step(step, pre, post)
        assert result.passed is True
        assert result.delta.has_changes is True

    def test_orchestrator_verify_step_no_changes_fails(self):
        """verify_step fails when post_condition expects change but graph is identical."""
        orchestrator = ActionOrchestrator()
        graph = _build_login_graph()
        step = ActionStep(
            action_type=ActionType.CLICK,
            description="submit",
            post_condition="something should change",
        )
        result = orchestrator.verify_step(step, graph, graph)
        assert result.passed is False


# ---------------------------------------------------------------------------
# Benchmark scoring helper
# ---------------------------------------------------------------------------

def score_benchmark(results: dict) -> float:
    """Calculate benchmark score as percentage of passed tests."""
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    return (passed / total) * 100 if total > 0 else 0.0
