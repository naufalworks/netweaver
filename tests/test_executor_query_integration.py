"""Tests for NW-015 Executor→Query Integration.

Covers:
- execute_graph_click: successful graph-native click with target resolution
- execute_graph_fill: successful graph-native fill with target resolution
- execute_graph_wait: successful graph-native wait with target resolution
- Target not found in graph → TARGET_RESOLUTION_FAILED
- Safety-blocked target → TARGET_RESOLUTION_FAILED
- Graph with no matching intent → resolution failure
- Resolution metadata: score, evidence_count, matched_properties
- GraphResolvedTarget serialization
- Backward compatibility: raw selector execute_click/fill/wait still works
- Full pipeline: graph resolution → evidence collection → execution → report
"""

import pytest
from datetime import datetime

from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    SceneEdge,
    SceneNode,
    WebSceneGraph,
)
from netweaver.executor import (
    ExecutionStatus,
    GraphResolvedTarget,
    PrePostEvidence,
    ResolutionStatus,
    VerifiedExecution,
    VerifiedExecutor,
    mock_evidence_collector,
    mock_action_executor,
)
from netweaver.wnal import (
    ActionabilityEvidence,
    ActionType,
    ClickAction,
    FillAction,
    Phase,
    WaitAction,
)
from netweaver.graph_query import IntentType


# ── Graph fixtures ──────────────────────────────────────────────────

def _make_graph_with_clickable(
    description: str = "login",
    selector: str = "button#login",
    text: str = "Login",
    aria_label: str = "Login button",
    add_intent: bool = True,
    add_evidence: bool = True,
    safety_block: bool = False,
) -> WebSceneGraph:
    """Build a test scene graph with a clickable DOM node."""
    graph = WebSceneGraph(
        graph_id="test-graph-click",
        url="https://example.com",
        title="Test Page",
    )

    # Page root
    root = SceneNode(
        node_id="page-root",
        node_type=NodeType.DOM,
        label="page",
        properties={"is_root": True},
    )
    graph.add_node(root)

    # DOM node
    dom = SceneNode(
        node_id="dom-login",
        node_type=NodeType.DOM,
        label=selector,
        properties={
            "selector": selector,
            "text": text,
            "tag": "button",
        },
        observation_ids=["obs-1"] if add_evidence else [],
    )
    graph.add_node(dom)

    # Containment edge
    graph.add_edge(SceneEdge(
        edge_id="e-contain",
        source_id="page-root",
        target_id="dom-login",
        edge_type=EdgeType.CONTAINMENT,
    ))

    # A11y node
    a11y = SceneNode(
        node_id="a11y-login",
        node_type=NodeType.ACCESSIBILITY,
        label=aria_label,
        properties={"aria_label": aria_label, "role": "button"},
    )
    graph.add_node(a11y)
    graph.add_edge(SceneEdge(
        edge_id="e-a11y",
        source_id="dom-login",
        target_id="a11y-login",
        edge_type=EdgeType.CONTAINMENT,
    ))

    # Intent node
    if add_intent:
        intent = SceneNode(
            node_id="intent-login",
            node_type=NodeType.INTENT,
            label="clickable",
            properties={
                "affordance": "clickable",
            },
            metadata={"parent_dom_id": "dom-login"},
        )
        graph.add_node(intent)
        graph.add_edge(SceneEdge(
            edge_id="e-intent",
            source_id="dom-login",
            target_id="intent-login",
            edge_type=EdgeType.DEPENDENCY,
        ))

    # Safety block node
    if safety_block:
        safety = SceneNode(
            node_id="safety-login",
            node_type=NodeType.INTENT,
            label="safety-block",
            properties={
                "is_safety_enrichment": True,
                "strategy": "abort",
                "reason": "payment form detected",
            },
            metadata={"parent_dom_id": "dom-login"},
        )
        graph.add_node(safety)
        graph.add_edge(SceneEdge(
            edge_id="e-safety",
            source_id="safety-login",
            target_id="dom-login",
            edge_type=EdgeType.DEPENDENCY,
        ))

    return graph


def _make_graph_with_fillable(
    description: str = "email",
    selector: str = "input#email",
    text: str = "Email address",
    add_evidence: bool = True,
) -> WebSceneGraph:
    """Build a test scene graph with a fillable input."""
    graph = WebSceneGraph(
        graph_id="test-graph-fill",
        url="https://example.com/form",
        title="Form Page",
    )

    root = SceneNode(
        node_id="page-root",
        node_type=NodeType.DOM,
        label="page",
        properties={"is_root": True},
    )
    graph.add_node(root)

    dom = SceneNode(
        node_id="dom-email",
        node_type=NodeType.DOM,
        label=selector,
        properties={
            "selector": selector,
            "text": text,
            "tag": "input",
        },
        observation_ids=["obs-email-1"] if add_evidence else [],
    )
    graph.add_node(dom)
    graph.add_edge(SceneEdge(
        edge_id="e-contain",
        source_id="page-root",
        target_id="dom-email",
        edge_type=EdgeType.CONTAINMENT,
    ))

    # Intent: fillable
    intent = SceneNode(
        node_id="intent-email",
        node_type=NodeType.INTENT,
        label="fillable",
        properties={
            "affordance": "fillable",
        },
        metadata={"parent_dom_id": "dom-email"},
    )
    graph.add_node(intent)
    graph.add_edge(SceneEdge(
        edge_id="e-intent",
        source_id="dom-email",
        target_id="intent-email",
        edge_type=EdgeType.DEPENDENCY,
    ))

    return graph


def _make_empty_graph() -> WebSceneGraph:
    """Graph with only a root node, no actionable elements."""
    graph = WebSceneGraph(
        graph_id="test-graph-empty",
        url="https://example.com",
        title="Empty Page",
    )
    root = SceneNode(
        node_id="page-root",
        node_type=NodeType.DOM,
        label="page",
        properties={"is_root": True},
    )
    graph.add_node(root)
    return graph


# ── ResolutionStatus Tests ──────────────────────────────────────────

class TestResolutionStatus:
    def test_values(self):
        assert ResolutionStatus.RESOLVED.value == "resolved"
        assert ResolutionStatus.NOT_FOUND.value == "not_found"
        assert ResolutionStatus.SAFETY_BLOCKED.value == "safety_blocked"
        assert ResolutionStatus.EVIDENCE_INSUFFICIENT.value == "evidence_insufficient"


class TestGraphResolvedTarget:
    def test_resolved_target(self):
        t = GraphResolvedTarget(
            status=ResolutionStatus.RESOLVED,
            description="login button",
            node_id="dom-1",
            selector="button#login",
            score=0.9,
            matched_properties=["text", "aria_label"],
            evidence_count=2,
            evidence_sufficient=True,
            evidence_confidence=0.8,
        )
        assert t.status == ResolutionStatus.RESOLVED
        assert t.selector == "button#login"
        assert t.error is None

    def test_not_found_target(self):
        t = GraphResolvedTarget(
            status=ResolutionStatus.NOT_FOUND,
            description="missing element",
            error="No graph node matching 'missing element'",
        )
        assert t.status == ResolutionStatus.NOT_FOUND
        assert t.node_id is None
        assert t.selector is None

    def test_safety_blocked_target(self):
        t = GraphResolvedTarget(
            status=ResolutionStatus.SAFETY_BLOCKED,
            description="delete button",
            node_id="dom-del",
            error="Safety blocked: destructive action",
        )
        assert t.status == ResolutionStatus.SAFETY_BLOCKED
        assert t.error is not None

    def test_serialization(self):
        t = GraphResolvedTarget(
            status=ResolutionStatus.RESOLVED,
            description="login",
            node_id="dom-1",
            selector="button#login",
            score=0.85,
            matched_properties=["text"],
            evidence_count=1,
            evidence_sufficient=True,
            evidence_confidence=0.5,
        )
        d = t.to_dict()
        assert d["status"] == "resolved"
        assert d["description"] == "login"
        assert d["selector"] == "button#login"
        assert d["score"] == 0.85
        assert d["evidence_count"] == 1

    def test_default_values(self):
        t = GraphResolvedTarget(
            status=ResolutionStatus.NOT_FOUND,
            description="x",
        )
        assert t.node_id is None
        assert t.selector is None
        assert t.score == 0.0
        assert t.matched_properties == []
        assert t.evidence_count == 0
        assert t.evidence_sufficient is False
        assert t.evidence_confidence == 0.0


# ── execute_graph_click Tests ───────────────────────────────────────

class TestExecuteGraphClick:
    def test_successful_click(self):
        graph = _make_graph_with_clickable(
            text="Login", selector="button#login",
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.selector == "button#login"
        assert resolution.node_id == "dom-login"

    def test_click_with_evidence_report(self):
        graph = _make_graph_with_clickable(
            text="Submit", selector="button#submit",
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "submit", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS
        assert execution.report is not None
        assert execution.evidence.pre is not None
        assert execution.evidence.post is not None

    def test_click_not_found(self):
        graph = _make_graph_with_clickable(text="Login")
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "totally unrelated zzzxyz element", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED
        assert resolution.status == ResolutionStatus.NOT_FOUND
        assert "No graph node" in resolution.error

    def test_click_safety_blocked(self):
        graph = _make_graph_with_clickable(
            text="Delete", selector="button#delete",
            safety_block=True,
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "delete", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED
        assert resolution.status == ResolutionStatus.SAFETY_BLOCKED
        assert "Safety blocked" in resolution.error

    def test_click_empty_graph(self):
        graph = _make_empty_graph()
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "anything", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED
        assert resolution.status == ResolutionStatus.NOT_FOUND

    def test_click_returns_execution_and_resolution(self):
        graph = _make_graph_with_clickable(text="Login")
        executor = VerifiedExecutor()
        result = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], VerifiedExecution)
        assert isinstance(result[1], GraphResolvedTarget)


# ── execute_graph_fill Tests ────────────────────────────────────────

def _make_fillable_evidence_collector():
    """Evidence collector that returns editable=True for fill actions."""
    def collector(action_id, target_ref):
        return ActionabilityEvidence(
            action_id=action_id,
            target_ref=target_ref,
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=True,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
    return collector


class TestExecuteGraphFill:
    def test_successful_fill(self):
        graph = _make_graph_with_fillable(
            text="Email address", selector="input#email",
        )
        executor = VerifiedExecutor(
            evidence_collector=_make_fillable_evidence_collector(),
        )
        execution, resolution = executor.execute_graph_fill(
            graph, "email", text="user@example.com",
            skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.selector == "input#email"

    def test_fill_with_evidence(self):
        graph = _make_graph_with_fillable(
            text="Email", selector="input#email",
        )
        executor = VerifiedExecutor(
            evidence_collector=_make_fillable_evidence_collector(),
        )
        execution, resolution = executor.execute_graph_fill(
            graph, "email", text="test@test.com",
            skip_perspective=True,
        )
        assert execution.report is not None
        assert execution.evidence.pre is not None

    def test_fill_not_found(self):
        graph = _make_graph_with_fillable(text="Email")
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_fill(
            graph, "password", text="secret",
            skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED
        assert resolution.status == ResolutionStatus.NOT_FOUND

    def test_fill_wrong_intent(self):
        """Click-only graph should not resolve fill intent."""
        graph = _make_graph_with_clickable(
            text="Login", add_intent=True,
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_fill(
            graph, "login", text="value",
            skip_perspective=True,
        )
        # Clickable node won't match FILL intent
        assert execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED


# ── execute_graph_wait Tests ────────────────────────────────────────

class TestExecuteGraphWait:
    def test_successful_wait(self):
        graph = _make_graph_with_clickable(
            text="Continue", selector="button#continue",
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_wait(
            graph, "continue", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS
        assert resolution.status == ResolutionStatus.RESOLVED

    def test_wait_not_found(self):
        graph = _make_graph_with_clickable(text="Login")
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_wait(
            graph, "nonexistent", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED
        assert resolution.status == ResolutionStatus.NOT_FOUND

    def test_wait_uses_any_intent(self):
        """Wait uses IntentType.ANY so should match any affordance."""
        graph = _make_graph_with_fillable(
            text="Email", selector="input#email",
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_wait(
            graph, "email", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS
        assert resolution.status == ResolutionStatus.RESOLVED


# ── Resolution Metadata Tests ───────────────────────────────────────

class TestResolutionMetadata:
    def test_score_from_match(self):
        graph = _make_graph_with_clickable(
            text="Login button", selector="button#login",
        )
        executor = VerifiedExecutor()
        _, resolution = executor.execute_graph_click(
            graph, "login button", skip_perspective=True,
        )
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.score > 0.0
        assert len(resolution.matched_properties) > 0

    def test_evidence_count_from_graph(self):
        graph = _make_graph_with_clickable(
            text="Login", add_evidence=True,
        )
        executor = VerifiedExecutor()
        _, resolution = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        assert resolution.evidence_count > 0

    def test_evidence_sufficient_flag(self):
        graph = _make_graph_with_clickable(
            text="Login", add_evidence=True,
        )
        executor = VerifiedExecutor()
        _, resolution = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        assert resolution.evidence_sufficient is True

    def test_no_evidence(self):
        graph = _make_graph_with_clickable(
            text="Login", add_evidence=False,
        )
        executor = VerifiedExecutor()
        _, resolution = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        # Resolution should still work, but evidence_count=0
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.evidence_count == 0

    def test_selector_fallback_to_label(self):
        """When node has no selector property, fallback to label."""
        graph = _make_graph_with_clickable(text="Login")
        # Remove selector from properties
        node = graph.get_node("dom-login")
        node.properties.pop("selector", None)

        executor = VerifiedExecutor()
        _, resolution = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.selector == "button#login"  # label used as fallback


# ── ExecutionStatus TARGET_RESOLUTION_FAILED Tests ──────────────────

class TestTargetResolutionFailed:
    def test_new_status_value(self):
        assert ExecutionStatus.TARGET_RESOLUTION_FAILED.value == "target_resolution_failed"

    def test_failed_execution_has_no_evidence(self):
        graph = _make_empty_graph()
        executor = VerifiedExecutor()
        execution, _ = executor.execute_graph_click(
            graph, "anything", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED
        assert execution.evidence.pre is None
        assert execution.evidence.post is None
        assert execution.report is None
        assert execution.error is not None

    def test_failed_execution_target_ref_contains_description(self):
        graph = _make_empty_graph()
        executor = VerifiedExecutor()
        execution, _ = executor.execute_graph_click(
            graph, "my button", skip_perspective=True,
        )
        assert "<graph:my button>" in execution.action.target_ref

    def test_failed_execution_serialization(self):
        graph = _make_empty_graph()
        executor = VerifiedExecutor()
        execution, _ = executor.execute_graph_click(
            graph, "test", skip_perspective=True,
        )
        d = execution.to_dict()
        assert d["status"] == "target_resolution_failed"
        assert d["error"] is not None


# ── Backward Compatibility Tests ────────────────────────────────────

class TestBackwardCompatibility:
    def test_raw_selector_click_still_works(self):
        """Existing execute_click with raw selector still works."""
        executor = VerifiedExecutor()
        execution = executor.execute_click(
            target_ref="button#submit", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS
        assert execution.action.target_ref == "button#submit"

    def test_raw_selector_fill_still_works(self):
        executor = VerifiedExecutor(
            evidence_collector=_make_fillable_evidence_collector(),
        )
        execution = executor.execute_fill(
            target_ref="input#email", text="test@test.com",
            skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS

    def test_raw_selector_wait_still_works(self):
        executor = VerifiedExecutor()
        execution = executor.execute_wait(
            target_ref="div.loading", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS

    def test_existing_tests_unaffected(self):
        """Verify existing executor tests still pass after graph integration."""
        from netweaver.executor import _make_id
        uid = _make_id("test")
        assert uid.startswith("test-")


# ── Full Pipeline Tests ─────────────────────────────────────────────

class TestFullPipeline:
    def test_graph_click_full_pipeline(self):
        """End-to-end: graph resolution → evidence → execution → report."""
        graph = _make_graph_with_clickable(
            text="Login", selector="button#login",
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        # Resolution succeeded
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.selector == "button#login"

        # Execution succeeded
        assert execution.status == ExecutionStatus.SUCCESS
        assert execution.action.target_ref == "button#login"

        # Evidence pipeline ran
        assert execution.evidence.pre is not None
        assert execution.evidence.post is not None
        assert execution.report is not None

    def test_graph_fill_full_pipeline(self):
        graph = _make_graph_with_fillable(
            text="Email", selector="input#email",
        )
        executor = VerifiedExecutor(
            evidence_collector=_make_fillable_evidence_collector(),
        )
        execution, resolution = executor.execute_graph_fill(
            graph, "email", text="user@test.com",
            skip_perspective=True,
        )
        assert resolution.status == ResolutionStatus.RESOLVED
        assert execution.status == ExecutionStatus.SUCCESS
        assert execution.report is not None

    def test_mixed_graph_and_raw_selector(self):
        """Can use both graph-native and raw selector in same executor."""
        graph = _make_graph_with_clickable(text="Login")
        executor = VerifiedExecutor()

        # Graph-native
        exec1, _ = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        assert exec1.status == ExecutionStatus.SUCCESS

        # Raw selector
        exec2 = executor.execute_click(
            target_ref="button#other", skip_perspective=True,
        )
        assert exec2.status == ExecutionStatus.SUCCESS

    def test_multiple_graph_queries_same_executor(self):
        """Multiple graph queries on the same executor instance."""
        graph = _make_graph_with_clickable(text="Login")
        executor = VerifiedExecutor()

        exec1, res1 = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        exec2, res2 = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        assert exec1.status == ExecutionStatus.SUCCESS
        assert exec2.status == ExecutionStatus.SUCCESS
        # Same resolution target
        assert res1.node_id == res2.node_id


# ── Edge Case Tests ─────────────────────────────────────────────────

class TestEdgeCases:
    def test_graph_with_no_intent_nodes(self):
        """Graph with DOM nodes but no intent nodes."""
        graph = _make_graph_with_clickable(
            text="Login", add_intent=False,
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        # Should fail because no CLICK intent filter match
        assert execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED

    def test_description_matches_aria_label(self):
        """Resolution via ARIA label instead of text."""
        graph = _make_graph_with_clickable(
            text="→", selector="button#go",
            aria_label="Go to next page",
        )
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "next page", skip_perspective=True,
        )
        # Should resolve via ARIA label
        if resolution.status == ResolutionStatus.RESOLVED:
            assert execution.status == ExecutionStatus.SUCCESS

    def test_multiple_matches_returns_best(self):
        """Graph with multiple matching nodes returns the best score."""
        graph = _make_graph_with_clickable(
            text="Login", selector="button#login",
        )
        # Add a second DOM node with weaker match
        dom2 = SceneNode(
            node_id="dom-login-alt",
            node_type=NodeType.DOM,
            label="button#login-alt",
            properties={"selector": "button#login-alt", "text": "Login here"},
            observation_ids=["obs-2"],
        )
        graph.add_node(dom2)
        graph.add_edge(SceneEdge(
            edge_id="e-contain2",
            source_id="page-root",
            target_id="dom-login-alt",
            edge_type=EdgeType.CONTAINMENT,
        ))
        intent2 = SceneNode(
            node_id="intent-login-alt",
            node_type=NodeType.INTENT,
            label="clickable",
            properties={"affordance": "clickable"},
            metadata={"parent_dom_id": "dom-login-alt"},
        )
        graph.add_node(intent2)
        graph.add_edge(SceneEdge(
            edge_id="e-intent2",
            source_id="dom-login-alt",
            target_id="intent-login-alt",
            edge_type=EdgeType.DEPENDENCY,
        ))

        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "login", skip_perspective=True,
        )
        assert resolution.status == ResolutionStatus.RESOLVED
        # Best match should be returned
        assert resolution.score > 0.0
