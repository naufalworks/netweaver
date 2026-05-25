"""Tests for NetWeaver Action Orchestrator (NW-016).

Covers:
- ActionPlan construction and serialization
- ActionOrchestrator with mock executor/graph
- Graph delta computation
- Step verification
- Rollback on failure
- Safety blocking halts plan
- Full pipeline: multi-step login flow
- Edge cases: empty plan, single step, all steps fail
"""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, Optional

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
)
from netweaver.action_orchestrator import (
    ActionOrchestrator,
    ActionPlan,
    ActionStep,
    ActionType,
    GraphDelta,
    OrchestrationResult,
    PlanStatus,
    RollbackResult,
    StepResult,
    VerificationResult,
    compute_graph_delta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph(*node_labels: str) -> WebSceneGraph:
    """Create a minimal graph with DOM nodes for each label."""
    graph = WebSceneGraph(graph_id="test-graph", url="https://example.com")
    root = SceneNode(
        node_id="root", node_type=NodeType.DOM,
        label="page", properties={"is_root": True},
    )
    graph.add_node(root)

    for label in node_labels:
        nid = f"node-{label}"
        node = SceneNode(
            node_id=nid, node_type=NodeType.DOM,
            label=label,
            properties={
                "selector": f"#{label}",
                "text": label,
            },
            observation_ids=["obs-1"],
        )
        graph.add_node(node)
        graph.add_edge(SceneEdge(
            edge_id=f"edge-{nid}",
            source_id="root",
            target_id=nid,
            edge_type=EdgeType.CONTAINMENT,
        ))
    return graph


def _make_graph_with_intent(label: str, affordance: str = "clickable") -> WebSceneGraph:
    """Create a graph with a DOM node and its INTENT child."""
    graph = _make_graph(label)
    dom_id = f"node-{label}"
    intent_id = f"intent-{label}"

    intent = SceneNode(
        node_id=intent_id,
        node_type=NodeType.INTENT,
        label=f"intent:{affordance}",
        properties={
            "affordance": affordance,
            "parent_dom_id": dom_id,
        },
    )
    graph.add_node(intent)
    graph.add_edge(SceneEdge(
        edge_id=f"edge-intent-{label}",
        source_id=dom_id,
        target_id=intent_id,
        edge_type=EdgeType.DEPENDENCY,
    ))
    return graph


def _make_success_execution(target_ref: str = "#btn") -> VerifiedExecution:
    """Create a successful VerifiedExecution."""
    from netweaver.wnal import ActionType, ClickAction
    return VerifiedExecution(
        execution_id="exec-test",
        action=ClickAction(action_id="act-test", target_ref=target_ref),
        status=ExecutionStatus.SUCCESS,
        evidence=PrePostEvidence(),
    )


def _make_failed_execution(error: str = "fail") -> VerifiedExecution:
    """Create a failed VerifiedExecution."""
    from netweaver.wnal import ActionType, TypedAction
    return VerifiedExecution(
        execution_id="exec-fail",
        action=TypedAction(action_id="act-fail", action_type=ActionType.CLICK, target_ref="#x"),
        status=ExecutionStatus.EXECUTION_ERROR,
        evidence=PrePostEvidence(),
        error=error,
    )


def _make_resolution_failed() -> GraphResolvedTarget:
    return GraphResolvedTarget(
        status=ResolutionStatus.NOT_FOUND,
        description="missing",
        error="No graph node matching 'missing'",
    )


def _make_resolution_safety_blocked() -> GraphResolvedTarget:
    return GraphResolvedTarget(
        status=ResolutionStatus.SAFETY_BLOCKED,
        description="dangerous",
        error="Safety blocked: high risk",
    )


def _make_resolution_ok(selector: str = "#btn") -> GraphResolvedTarget:
    return GraphResolvedTarget(
        status=ResolutionStatus.RESOLVED,
        description="button",
        selector=selector,
        score=0.9,
        node_id="node-btn",
    )


# ---------------------------------------------------------------------------
# ActionPlan tests
# ---------------------------------------------------------------------------

class TestActionPlan:
    def test_empty_plan(self):
        plan = ActionPlan()
        assert plan.plan_id.startswith("plan-")
        assert plan.steps == []
        assert plan.description == ""

    def test_custom_plan_id(self):
        plan = ActionPlan(plan_id="my-plan")
        assert plan.plan_id == "my-plan"

    def test_add_step_builder(self):
        plan = ActionPlan()
        result = plan.add_step(ActionType.CLICK, "login button", intent="submit")
        assert result is plan  # builder pattern
        assert len(plan.steps) == 1
        assert plan.steps[0].action_type == ActionType.CLICK
        assert plan.steps[0].description == "login button"
        assert plan.steps[0].intent == "submit"

    def test_add_multiple_steps(self):
        plan = ActionPlan()
        plan.add_step(ActionType.FILL, "email", text="user@test.com")
        plan.add_step(ActionType.FILL, "password", text="secret")
        plan.add_step(ActionType.CLICK, "submit")
        assert len(plan.steps) == 3
        assert plan.steps[0].text == "user@test.com"
        assert plan.steps[1].text == "secret"
        assert plan.steps[2].action_type == ActionType.CLICK

    def test_to_dict(self):
        plan = ActionPlan(description="login flow")
        plan.add_step(ActionType.CLICK, "btn")
        d = plan.to_dict()
        assert "plan_id" in d
        assert d["description"] == "login flow"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["action_type"] == "click"

    def test_step_pre_post_conditions(self):
        step = ActionStep(
            action_type=ActionType.CLICK,
            description="submit",
            pre_condition="form is filled",
            post_condition="page navigates to /dashboard",
        )
        assert step.pre_condition == "form is filled"
        assert step.post_condition == "page navigates to /dashboard"

    def test_action_type_values(self):
        assert ActionType.CLICK.value == "click"
        assert ActionType.FILL.value == "fill"
        assert ActionType.WAIT.value == "wait"


# ---------------------------------------------------------------------------
# GraphDelta tests
# ---------------------------------------------------------------------------

class TestGraphDelta:
    def test_empty_delta(self):
        delta = GraphDelta()
        assert not delta.has_changes

    def test_delta_with_additions(self):
        delta = GraphDelta(nodes_added=["n1"])
        assert delta.has_changes

    def test_delta_with_removals(self):
        delta = GraphDelta(nodes_removed=["n2"])
        assert delta.has_changes

    def test_delta_with_modifications(self):
        delta = GraphDelta(nodes_modified=["n3"])
        assert delta.has_changes

    def test_delta_with_edge_changes(self):
        delta = GraphDelta(edges_added=["e1"], edges_removed=["e2"])
        assert delta.has_changes

    def test_to_dict(self):
        delta = GraphDelta(
            nodes_added=["a"],
            nodes_removed=["b"],
            nodes_modified=["c"],
            edges_added=["e1"],
            edges_removed=["e2"],
        )
        d = delta.to_dict()
        assert d["has_changes"] is True
        assert d["nodes_added"] == ["a"]
        assert d["nodes_removed"] == ["b"]


class TestComputeGraphDelta:
    def test_identical_graphs(self):
        g = _make_graph("a", "b")
        delta = compute_graph_delta(g, g)
        assert not delta.has_changes

    def test_node_added(self):
        g1 = _make_graph("a")
        g2 = _make_graph("a", "b")
        delta = compute_graph_delta(g1, g2)
        assert "node-b" in delta.nodes_added
        assert not delta.nodes_removed

    def test_node_removed(self):
        g1 = _make_graph("a", "b")
        g2 = _make_graph("a")
        delta = compute_graph_delta(g1, g2)
        assert "node-b" in delta.nodes_removed

    def test_node_modified(self):
        g1 = _make_graph("a")
        g2 = _make_graph("a")
        # Modify the node in g2
        g2.nodes["node-a"].label = "changed"
        delta = compute_graph_delta(g1, g2)
        assert "node-a" in delta.nodes_modified

    def test_observation_change_is_modification(self):
        g1 = _make_graph("a")
        g2 = _make_graph("a")
        g2.nodes["node-a"].observation_ids.append("obs-2")
        delta = compute_graph_delta(g1, g2)
        assert "node-a" in delta.nodes_modified

    def test_empty_graphs(self):
        g1 = WebSceneGraph(graph_id="test", url="http://test")
        g2 = WebSceneGraph(graph_id="test", url="http://test")
        delta = compute_graph_delta(g1, g2)
        assert not delta.has_changes

    def test_root_always_present(self):
        g1 = _make_graph("a")
        g2 = _make_graph("a")
        delta = compute_graph_delta(g1, g2)
        assert not delta.has_changes


# ---------------------------------------------------------------------------
# StepResult tests
# ---------------------------------------------------------------------------

class TestStepResult:
    def test_default_status(self):
        sr = StepResult(step_index=0, step=ActionStep(ActionType.CLICK, "btn"))
        assert sr.status == PlanStatus.PENDING
        assert sr.execution is None
        assert sr.resolution is None
        assert sr.error is None

    def test_with_execution(self):
        exec_ = _make_success_execution()
        sr = StepResult(
            step_index=0,
            step=ActionStep(ActionType.CLICK, "btn"),
            execution=exec_,
            status=PlanStatus.COMPLETED,
        )
        assert sr.execution.status == ExecutionStatus.SUCCESS


# ---------------------------------------------------------------------------
# OrchestrationResult tests
# ---------------------------------------------------------------------------

class TestOrchestrationResult:
    def test_default_status(self):
        r = OrchestrationResult(plan_id="p1")
        assert r.status == PlanStatus.PENDING
        assert r.started_at is not None
        assert r.completed_steps == 0

    def test_to_dict(self):
        r = OrchestrationResult(plan_id="p1", plan_description="test")
        d = r.to_dict()
        assert d["plan_id"] == "p1"
        assert d["status"] == "pending"
        assert d["total_steps"] == 0


# ---------------------------------------------------------------------------
# ActionOrchestrator tests
# ---------------------------------------------------------------------------

class TestActionOrchestrator:
    """Tests using mock executor to avoid real browser interaction."""

    def _mock_orchestrator(self, step_results=None):
        """Create an orchestrator with a mock executor.

        step_results: list of (VerifiedExecution, GraphResolvedTarget) tuples
            returned in order for each step. If None, all succeed.
        """
        executor = MagicMock(spec=VerifiedExecutor)

        if step_results is None:
            # Default: all steps succeed
            def default_graph_click(*a, **kw):
                return _make_success_execution(), _make_resolution_ok()
            executor.execute_graph_click.side_effect = default_graph_click
            executor.execute_graph_fill.side_effect = lambda *a, **kw: (_make_success_execution(), _make_resolution_ok())
            executor.execute_graph_wait.side_effect = lambda *a, **kw: (_make_success_execution(), _make_resolution_ok())
        else:
            results = list(step_results)
            call_count = [0]

            def next_result(*a, **kw):
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(results):
                    return results[idx]
                return _make_success_execution(), _make_resolution_ok()

            executor.execute_graph_click.side_effect = next_result
            executor.execute_graph_fill.side_effect = next_result
            executor.execute_graph_wait.side_effect = next_result

        return ActionOrchestrator(executor=executor)

    def test_empty_plan(self):
        orch = self._mock_orchestrator()
        plan = ActionPlan()
        graph = _make_graph()
        result = orch.orchestrate(plan, lambda: graph)
        assert result.status == PlanStatus.COMPLETED
        assert result.completed_steps == 0

    def test_single_click_success(self):
        orch = self._mock_orchestrator()
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "login button")
        graph = _make_graph("login button")
        result = orch.orchestrate(plan, lambda: graph)
        assert result.status == PlanStatus.COMPLETED
        assert result.completed_steps == 1
        assert result.steps[0].status == PlanStatus.COMPLETED

    def test_multi_step_login_flow(self):
        orch = self._mock_orchestrator()
        plan = ActionPlan(description="login flow")
        plan.add_step(ActionType.FILL, "email", text="user@test.com")
        plan.add_step(ActionType.FILL, "password", text="secret")
        plan.add_step(ActionType.CLICK, "submit")
        graph = _make_graph("email", "password", "submit")
        result = orch.orchestrate(plan, lambda: graph)
        assert result.status == PlanStatus.COMPLETED
        assert result.completed_steps == 3

    def test_step_failure_halts_plan(self):
        fail_exec = _make_failed_execution("executor error")
        fail_res = _make_resolution_ok()
        ok_exec = _make_success_execution()
        ok_res = _make_resolution_ok()

        orch = self._mock_orchestrator(step_results=[
            (ok_exec, ok_res),      # step 0 succeeds
            (fail_exec, fail_res),   # step 1 fails
            (ok_exec, ok_res),       # step 2 never reached
        ])

        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn1")
        plan.add_step(ActionType.CLICK, "btn2")
        plan.add_step(ActionType.CLICK, "btn3")

        graph = _make_graph("btn1", "btn2", "btn3")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.status == PlanStatus.FAILED
        assert result.completed_steps == 1
        assert len(result.steps) == 2  # step 0 + failed step 1
        assert "Step 1 failed" in result.error

    def test_resolution_failure_halts_plan(self):
        ok_exec = _make_success_execution()
        ok_res = _make_resolution_ok()
        fail_res = _make_resolution_failed()
        fail_exec = _make_success_execution()  # won't be reached

        orch = self._mock_orchestrator(step_results=[
            (ok_exec, ok_res),
            (fail_exec, fail_res),
        ])

        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "found")
        plan.add_step(ActionType.CLICK, "missing")

        graph = _make_graph("found")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.status == PlanStatus.FAILED
        assert result.completed_steps == 1
        # Error comes from resolution.error field
        assert "no graph node matching" in result.steps[1].error.lower()

    def test_safety_block_halts_plan(self):
        ok_exec = _make_success_execution()
        ok_res = _make_resolution_ok()
        blocked_res = _make_resolution_safety_blocked()
        blocked_exec = _make_success_execution()

        orch = self._mock_orchestrator(step_results=[
            (ok_exec, ok_res),
            (blocked_exec, blocked_res),
        ])

        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "safe button")
        plan.add_step(ActionType.CLICK, "dangerous button")

        graph = _make_graph("safe button")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.status == PlanStatus.SAFETY_BLOCKED
        assert result.completed_steps == 1

    def test_perspective_blocked_execution(self):
        """When executor returns PERSPECTIVE_BLOCKED, plan fails."""
        from netweaver.wnal import ActionType as WNALActionType, TypedAction
        blocked_exec = VerifiedExecution(
            execution_id="exec-blocked",
            action=TypedAction(action_id="a", action_type=WNALActionType.CLICK, target_ref="#x"),
            status=ExecutionStatus.PERSPECTIVE_BLOCKED,
            evidence=PrePostEvidence(),
            error="Perspective abort: high risk",
        )

        orch = self._mock_orchestrator(step_results=[
            (blocked_exec, _make_resolution_ok()),
        ])

        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "risky btn")

        graph = _make_graph("risky btn")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.status == PlanStatus.FAILED
        assert "Step 0 failed" in result.error

    def test_graph_supplier_called_per_step(self):
        """Graph supplier should be called fresh for each step."""
        call_count = [0]
        graphs = [_make_graph("a"), _make_graph("b"), _make_graph("c")]

        def supplier():
            idx = min(call_count[0], len(graphs) - 1)
            call_count[0] += 1
            return graphs[idx]

        orch = self._mock_orchestrator()
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "a")
        plan.add_step(ActionType.CLICK, "b")

        result = orch.orchestrate(plan, supplier)
        assert result.status == PlanStatus.COMPLETED
        assert call_count[0] >= 2  # at least once per step

    def test_on_step_complete_callback(self):
        completed = []

        def on_complete(step_result):
            completed.append(step_result.step_index)

        orch = self._mock_orchestrator()
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "a")
        plan.add_step(ActionType.CLICK, "b")

        graph = _make_graph("a", "b")
        orch.orchestrate(plan, lambda: graph, on_step_complete=on_complete)

        assert completed == [0, 1]

    def test_evidence_chain_collected(self):
        """Evidence IDs from the execution report are captured."""
        from netweaver.evidence import EvidenceReport, Observation, EvidenceType
        from netweaver.wnal import ClickAction

        exec_with_report = VerifiedExecution(
            execution_id="exec-rpt",
            action=ClickAction(action_id="a", target_ref="#btn"),
            status=ExecutionStatus.SUCCESS,
            evidence=PrePostEvidence(),
            report=EvidenceReport(
                report_id="rpt-1", url="http://test", timestamp=datetime.now(),
            ),
        )
        # Add observations to report
        exec_with_report.report.add_observation(Observation(
            observation_id="obs-a",
            evidence_type=EvidenceType.DOM,
            timestamp=datetime.now(),
            data={"k": "v"},
            source="test",
        ))

        orch = self._mock_orchestrator(step_results=[
            (exec_with_report, _make_resolution_ok()),
        ])

        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")
        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.steps[0].evidence_chain_ids == ["obs-a"]

    def test_fill_action_passes_text(self):
        """FILL steps should pass the text parameter to the executor."""
        executor = MagicMock(spec=VerifiedExecutor)
        executor.execute_graph_fill.return_value = (
            _make_success_execution(), _make_resolution_ok()
        )
        orch = ActionOrchestrator(executor=executor)

        plan = ActionPlan()
        plan.add_step(ActionType.FILL, "email", text="user@test.com")
        graph = _make_graph("email")
        orch.orchestrate(plan, lambda: graph)

        executor.execute_graph_fill.assert_called_once()
        call_kwargs = executor.execute_graph_fill.call_args
        assert call_kwargs.kwargs.get("text") == "user@test.com" or (
            len(call_kwargs.args) > 2 and call_kwargs.args[2] == "user@test.com"
        )

    def test_wait_action_passes_condition(self):
        """WAIT steps should pass condition and timeout."""
        executor = MagicMock(spec=VerifiedExecutor)
        executor.execute_graph_wait.return_value = (
            _make_success_execution(), _make_resolution_ok()
        )
        orch = ActionOrchestrator(executor=executor)

        plan = ActionPlan()
        plan.add_step(ActionType.WAIT, "loading", condition="visible", timeout_ms=10000)
        graph = _make_graph("loading")
        orch.orchestrate(plan, lambda: graph)

        executor.execute_graph_wait.assert_called_once()


# ---------------------------------------------------------------------------
# verify_step tests
# ---------------------------------------------------------------------------

class TestVerifyStep:
    def test_no_post_condition_passes(self):
        orch = ActionOrchestrator()
        g1 = _make_graph("a")
        g2 = _make_graph("a")
        step = ActionStep(ActionType.CLICK, "btn")
        result = orch.verify_step(step, g1, g2)
        assert result.passed
        assert "No post_condition" in result.reason

    def test_post_condition_with_changes(self):
        orch = ActionOrchestrator()
        g1 = _make_graph("a")
        g2 = _make_graph("a", "b")
        step = ActionStep(ActionType.CLICK, "btn", post_condition="page changes")
        result = orch.verify_step(step, g1, g2)
        assert result.passed

    def test_post_condition_no_changes(self):
        orch = ActionOrchestrator()
        g1 = _make_graph("a")
        g2 = _make_graph("a")
        step = ActionStep(ActionType.CLICK, "btn", post_condition="page navigates")
        result = orch.verify_step(step, g1, g2)
        assert not result.passed
        assert "No graph changes" in result.reason

    def test_verification_result_to_dict(self):
        orch = ActionOrchestrator()
        g1 = _make_graph("a")
        g2 = _make_graph("a", "b")
        step = ActionStep(ActionType.CLICK, "btn")
        result = orch.verify_step(step, g1, g2)
        d = result.to_dict()
        assert "delta" in d
        assert "passed" in d


# ---------------------------------------------------------------------------
# Rollback tests
# ---------------------------------------------------------------------------

class TestRollback:
    def test_nothing_to_rollback(self):
        orch = ActionOrchestrator()
        result = OrchestrationResult(plan_id="p1", status=PlanStatus.PENDING)
        rb = orch.roll_back(result)
        assert rb.status == "nothing_to_rollback"
        assert rb.steps_rolled_back == 0

    def test_rollback_completed_steps(self):
        orch = ActionOrchestrator()

        # Build a result with 2 completed steps + 1 failed
        result = OrchestrationResult(plan_id="p1", status=PlanStatus.FAILED)
        for i in range(2):
            result.steps.append(StepResult(
                step_index=i,
                step=ActionStep(ActionType.CLICK, f"btn{i}"),
                status=PlanStatus.COMPLETED,
            ))
        result.steps.append(StepResult(
            step_index=2,
            step=ActionStep(ActionType.CLICK, "btn2"),
            status=PlanStatus.FAILED,
            error="failed",
        ))
        result.completed_steps = 2

        rb = orch.roll_back(result)
        assert rb.status == "completed"
        assert rb.steps_rolled_back == 2
        # Rollback should be in reverse order
        assert rb.rollback_steps[0]["step_index"] == 1
        assert rb.rollback_steps[1]["step_index"] == 0

    def test_rollback_with_explicit_actions(self):
        orch = ActionOrchestrator()
        result = OrchestrationResult(plan_id="p1", status=PlanStatus.FAILED)
        result.steps.append(StepResult(
            step_index=0,
            step=ActionStep(ActionType.FILL, "email"),
            status=PlanStatus.COMPLETED,
        ))
        result.completed_steps = 1

        rb_actions = [ActionStep(ActionType.FILL, "email", text="")]
        rb = orch.roll_back(result, rollback_actions=rb_actions)
        assert rb.status == "completed"
        assert rb.steps_rolled_back == 1

    def test_rollback_result_to_dict(self):
        orch = ActionOrchestrator()
        result = OrchestrationResult(plan_id="p1", status=PlanStatus.FAILED)
        rb = orch.roll_back(result)
        d = rb.to_dict()
        assert d["plan_id"] == "p1"
        assert d["status"] == "nothing_to_rollback"


# ---------------------------------------------------------------------------
# Full pipeline / integration tests
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_login_flow_end_to_end(self):
        """Simulate a full login flow: fill email, fill password, click submit."""
        executor = MagicMock(spec=VerifiedExecutor)

        def mock_graph_action(graph, description, **kw):
            """Resolve any target that exists in the graph."""
            exec_ = _make_success_execution(f"#{description.replace(' ', '-')}")
            res = _make_resolution_ok(f"#{description.replace(' ', '-')}")
            return exec_, res

        executor.execute_graph_click.side_effect = mock_graph_action
        executor.execute_graph_fill.side_effect = mock_graph_action
        executor.execute_graph_wait.side_effect = mock_graph_action

        orch = ActionOrchestrator(executor=executor)

        plan = ActionPlan(description="login flow")
        plan.add_step(ActionType.FILL, "email input", text="user@test.com")
        plan.add_step(ActionType.FILL, "password input", text="secret123")
        plan.add_step(ActionType.CLICK, "submit button")

        graph = _make_graph_with_intent("email input", "fillable")
        # Add more nodes for password and submit
        for label, affordance in [("password input", "fillable"), ("submit button", "clickable")]:
            dom_id = f"node-{label}"
            node = SceneNode(
                node_id=dom_id, node_type=NodeType.DOM,
                label=label,
                properties={"selector": f"#{label}", "text": label},
                observation_ids=["obs-1"],
            )
            graph.add_node(node)
            intent_id = f"intent-{label}"
            intent = SceneNode(
                node_id=intent_id,
                node_type=NodeType.INTENT,
                label=f"intent:{affordance}",
                properties={"affordance": affordance, "parent_dom_id": dom_id},
            )
            graph.add_node(intent)

        result = orch.orchestrate(plan, lambda: graph)
        assert result.status == PlanStatus.COMPLETED
        assert result.completed_steps == 3
        assert len(result.steps) == 3

    def test_failed_plan_with_rollback(self):
        """Plan fails mid-sequence, then rollback is attempted."""
        executor = MagicMock(spec=VerifiedExecutor)

        ok_exec = _make_success_execution()
        ok_res = _make_resolution_ok()
        fail_exec = _make_failed_execution("network timeout")

        call_count = [0]
        def step_fn(*a, **kw):
            idx = call_count[0]
            call_count[0] += 1
            if idx < 2:
                return ok_exec, ok_res
            return fail_exec, ok_res

        executor.execute_graph_click.side_effect = step_fn
        executor.execute_graph_fill.side_effect = step_fn

        orch = ActionOrchestrator(executor=executor)

        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn1")
        plan.add_step(ActionType.CLICK, "btn2")
        plan.add_step(ActionType.CLICK, "btn3")

        graph = _make_graph("btn1", "btn2", "btn3")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.status == PlanStatus.FAILED
        assert result.completed_steps == 2

        # Rollback
        rb = orch.roll_back(result)
        assert rb.steps_rolled_back == 2

    def test_orchestration_result_serialization(self):
        """Full result serializes cleanly."""
        orch = self._make_passing_orchestrator()
        plan = ActionPlan(description="test")
        plan.add_step(ActionType.CLICK, "btn")
        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph)

        d = result.to_dict()
        assert d["status"] == "completed"
        assert d["completed_steps"] == 1
        assert d["total_steps"] == 1
        assert d["plan_description"] == "test"
        assert len(d["steps"]) == 1

    def _make_passing_orchestrator(self):
        executor = MagicMock(spec=VerifiedExecutor)
        executor.execute_graph_click.return_value = (
            _make_success_execution(), _make_resolution_ok()
        )
        executor.execute_graph_fill.return_value = (
            _make_success_execution(), _make_resolution_ok()
        )
        executor.execute_graph_wait.return_value = (
            _make_success_execution(), _make_resolution_ok()
        )
        return ActionOrchestrator(executor=executor)


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_step_plan(self):
        orch = self._make_passing_orchestrator()
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")
        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph)
        assert result.status == PlanStatus.COMPLETED
        assert result.completed_steps == 1

    def test_precondition_failed_first_step(self):
        """If the very first step fails, completed_steps should be 0."""
        from netweaver.wnal import ActionType as WNALActionType, TypedAction
        precon_fail = VerifiedExecution(
            execution_id="exec-pf",
            action=TypedAction(action_id="a", action_type=WNALActionType.CLICK, target_ref="#x"),
            status=ExecutionStatus.PRECONDITION_FAILED,
            evidence=PrePostEvidence(),
            error="Not visible",
        )

        executor = MagicMock(spec=VerifiedExecutor)
        executor.execute_graph_click.return_value = (precon_fail, _make_resolution_ok())

        orch = ActionOrchestrator(executor=executor)
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "hidden btn")
        graph = _make_graph("hidden btn")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.status == PlanStatus.FAILED
        assert result.completed_steps == 0
        assert len(result.steps) == 1

    def test_postcondition_mismatch(self):
        """POSTCONDITION_MISMATCH should also fail the plan."""
        from netweaver.wnal import ActionType as WNALActionType, TypedAction
        mismatch = VerifiedExecution(
            execution_id="exec-mm",
            action=TypedAction(action_id="a", action_type=WNALActionType.CLICK, target_ref="#x"),
            status=ExecutionStatus.POSTCONDITION_MISMATCH,
            evidence=PrePostEvidence(),
            error="State changed unexpectedly",
        )

        executor = MagicMock(spec=VerifiedExecutor)
        executor.execute_graph_click.return_value = (mismatch, _make_resolution_ok())

        orch = ActionOrchestrator(executor=executor)
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")
        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.status == PlanStatus.FAILED

    def test_unknown_action_type_raises(self):
        """Orchestrator should raise for unsupported action types."""
        orch = ActionOrchestrator()
        plan = ActionPlan()
        # Manually inject an invalid action type
        step = ActionStep(action_type=ActionType.CLICK, description="btn")
        step.action_type = "invalid"  # type: ignore
        plan.steps.append(step)

        graph = _make_graph("btn")
        with pytest.raises((ValueError, AttributeError)):
            orch.orchestrate(plan, lambda: graph)

    def test_graph_supplier_returns_different_graphs(self):
        """Each call to supplier should provide a fresh graph state."""
        graphs = [_make_graph("a"), _make_graph("a", "new")]
        call_idx = [0]

        def supplier():
            idx = call_idx[0]
            call_idx[0] += 1
            return graphs[min(idx, len(graphs) - 1)]

        orch = self._make_passing_orchestrator()
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "a")
        plan.add_step(ActionType.CLICK, "a")

        result = orch.orchestrate(plan, supplier)
        assert result.status == PlanStatus.COMPLETED

    def test_plan_status_values(self):
        assert PlanStatus.PENDING.value == "pending"
        assert PlanStatus.RUNNING.value == "running"
        assert PlanStatus.COMPLETED.value == "completed"
        assert PlanStatus.FAILED.value == "failed"
        assert PlanStatus.ROLLED_BACK.value == "rolled_back"
        assert PlanStatus.SAFETY_BLOCKED.value == "safety_blocked"

    def _make_passing_orchestrator(self):
        executor = MagicMock(spec=VerifiedExecutor)
        executor.execute_graph_click.return_value = (
            _make_success_execution(), _make_resolution_ok()
        )
        executor.execute_graph_fill.return_value = (
            _make_success_execution(), _make_resolution_ok()
        )
        executor.execute_graph_wait.return_value = (
            _make_success_execution(), _make_resolution_ok()
        )
        return ActionOrchestrator(executor=executor)


# ---------------------------------------------------------------------------
# Ledger integration tests
# ---------------------------------------------------------------------------

class TestLedgerIntegration:
    def test_orchestration_with_ledger(self):
        """Orchestrator should log plan start if ledger provided."""
        from netweaver.ledger import ActionLedger
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            ledger_path = Path(f.name)

        try:
            ledger = ActionLedger(ledger_path=ledger_path)
            executor = MagicMock(spec=VerifiedExecutor)
            executor.execute_graph_click.return_value = (
                _make_success_execution(), _make_resolution_ok()
            )
            orch = ActionOrchestrator(executor=executor, ledger=ledger)

            plan = ActionPlan(metadata={"task_id": "NW-016"})
            plan.add_step(ActionType.CLICK, "btn")
            graph = _make_graph("btn")
            result = orch.orchestrate(plan, lambda: graph)

            assert result.status == PlanStatus.COMPLETED
            # Ledger should have recorded the plan start
            events = ledger.read_events()
            assert len(events) >= 1
            assert events[0].payload.get("plan_id") == plan.plan_id
        finally:
            ledger_path.unlink(missing_ok=True)

    def test_rollback_with_ledger(self):
        """Rollback should log to ledger if provided."""
        from netweaver.ledger import ActionLedger
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            ledger_path = Path(f.name)

        try:
            ledger = ActionLedger(ledger_path=ledger_path)
            orch = ActionOrchestrator(ledger=ledger)

            result = OrchestrationResult(plan_id="p1", status=PlanStatus.FAILED)
            result.steps.append(StepResult(
                step_index=0,
                step=ActionStep(ActionType.CLICK, "btn"),
                status=PlanStatus.COMPLETED,
            ))
            result.completed_steps = 1

            rb = orch.roll_back(result)
            events = ledger.read_events()
            assert len(events) >= 1
            assert events[0].payload.get("steps_rolled_back") == 1
        finally:
            ledger_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# RetryPolicy tests (NW-020)
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    """Tests for RetryPolicy dataclass and retry-with-reobservation logic."""

    def test_retry_policy_defaults(self):
        from netweaver.action_orchestrator import RetryPolicy, StepStatus
        policy = RetryPolicy()
        assert policy.max_retries == 1
        assert StepStatus.FAILED in policy.retryable_statuses
        assert StepStatus.EVIDENCE_INSUFFICIENT in policy.retryable_statuses
        assert StepStatus.SAFETY_BLOCKED not in policy.retryable_statuses
        assert policy.reobserve is None

    def test_retry_policy_custom(self):
        from netweaver.action_orchestrator import RetryPolicy, StepStatus
        callback = lambda: None
        policy = RetryPolicy(max_retries=3, reobserve=callback)
        assert policy.max_retries == 3
        assert policy.reobserve is callback

    def test_retry_success_on_second_attempt(self):
        """Step fails first, reobserve, retry succeeds."""
        from netweaver.action_orchestrator import RetryPolicy

        fail_exec = _make_failed_execution("transient")
        ok_exec = _make_success_execution()
        ok_res = _make_resolution_ok()
        fail_res = _make_resolution_ok()  # resolved ok, but execution fails

        call_count = [0]
        executor = MagicMock(spec=VerifiedExecutor)

        def next_result(*a, **kw):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return (fail_exec, fail_res)
            return (ok_exec, ok_res)

        executor.execute_graph_click.side_effect = next_result
        executor.execute_graph_fill.side_effect = next_result
        executor.execute_graph_wait.side_effect = next_result

        reobserve_calls = [0]

        def reobserve():
            reobserve_calls[0] += 1

        orch = ActionOrchestrator(executor=executor)
        policy = RetryPolicy(max_retries=1, reobserve=reobserve)
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")

        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph, retry_policy=policy)

        assert result.status == PlanStatus.COMPLETED
        assert result.completed_steps == 1
        assert reobserve_calls[0] == 1
        assert call_count[0] == 2  # fail + retry success

    def test_max_retries_exhausted(self):
        """Step keeps failing, max retries exhausted → plan fails."""
        from netweaver.action_orchestrator import RetryPolicy

        fail_exec = _make_failed_execution("persistent")
        fail_res = _make_resolution_ok()

        call_count = [0]
        executor = MagicMock(spec=VerifiedExecutor)

        def always_fail(*a, **kw):
            call_count[0] += 1
            return (fail_exec, fail_res)

        executor.execute_graph_click.side_effect = always_fail
        executor.execute_graph_fill.side_effect = always_fail
        executor.execute_graph_wait.side_effect = always_fail

        reobserve_calls = [0]

        def reobserve():
            reobserve_calls[0] += 1

        orch = ActionOrchestrator(executor=executor)
        policy = RetryPolicy(max_retries=2, reobserve=reobserve)
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")

        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph, retry_policy=policy)

        assert result.status == PlanStatus.FAILED
        assert result.completed_steps == 0
        assert call_count[0] == 3  # initial + 2 retries
        assert reobserve_calls[0] == 2

    def test_non_retryable_status_skips_retry(self):
        """SAFETY_BLOCKED should never retry regardless of policy."""
        from netweaver.action_orchestrator import RetryPolicy

        blocked_res = _make_resolution_safety_blocked()
        blocked_exec = _make_success_execution()

        call_count = [0]
        executor = MagicMock(spec=VerifiedExecutor)

        def count_calls(*a, **kw):
            call_count[0] += 1
            return (blocked_exec, blocked_res)

        executor.execute_graph_click.side_effect = count_calls
        executor.execute_graph_fill.side_effect = count_calls
        executor.execute_graph_wait.side_effect = count_calls

        reobserve_calls = [0]

        def reobserve():
            reobserve_calls[0] += 1

        orch = ActionOrchestrator(executor=executor)
        policy = RetryPolicy(max_retries=3, reobserve=reobserve)
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "dangerous")

        graph = _make_graph("dangerous")
        result = orch.orchestrate(plan, lambda: graph, retry_policy=policy)

        assert result.status == PlanStatus.SAFETY_BLOCKED
        assert call_count[0] == 1  # no retry
        assert reobserve_calls[0] == 0

    def test_no_retry_policy_backward_compat(self):
        """retry_policy=None → no retry, identical to pre-NW-020 behavior."""
        fail_exec = _make_failed_execution("error")
        fail_res = _make_resolution_ok()

        call_count = [0]
        executor = MagicMock(spec=VerifiedExecutor)

        def count_calls(*a, **kw):
            call_count[0] += 1
            return (fail_exec, fail_res)

        executor.execute_graph_click.side_effect = count_calls
        executor.execute_graph_fill.side_effect = count_calls
        executor.execute_graph_wait.side_effect = count_calls

        orch = ActionOrchestrator(executor=executor)
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")

        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph)

        assert result.status == PlanStatus.FAILED
        assert call_count[0] == 1  # exactly one attempt

    def test_retry_logs_trace_entries(self):
        """Retry attempts are logged to TraceWriter."""
        from netweaver.action_orchestrator import RetryPolicy, TraceWriter

        fail_exec = _make_failed_execution("transient")
        ok_exec = _make_success_execution()
        ok_res = _make_resolution_ok()
        fail_res = _make_resolution_ok()

        call_count = [0]
        executor = MagicMock(spec=VerifiedExecutor)

        def next_result(*a, **kw):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return (fail_exec, fail_res)
            return (ok_exec, ok_res)

        executor.execute_graph_click.side_effect = next_result
        executor.execute_graph_fill.side_effect = next_result
        executor.execute_graph_wait.side_effect = next_result

        trace = TraceWriter(traces_dir=Path("/tmp/nw_retry_traces"))
        orch = ActionOrchestrator(executor=executor, trace=trace)
        policy = RetryPolicy(max_retries=1, reobserve=lambda: None)

        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")

        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph, retry_policy=policy)

        assert result.status == PlanStatus.COMPLETED
        entries = trace.read_trace()

        # Should have: plan_start, retry log, step completed, plan_end
        assert len(entries) >= 3
        retry_entries = [e for e in entries if "retry" in e.get("error", "").lower()
                         or "reobserv" in e.get("error", "").lower()]
        assert len(retry_entries) >= 1

    def test_reobserve_exception_stops_retry(self):
        """If reobserve callback raises, retry stops and failure is returned."""
        from netweaver.action_orchestrator import RetryPolicy

        fail_exec = _make_failed_execution("fail")
        fail_res = _make_resolution_ok()

        executor = MagicMock(spec=VerifiedExecutor)
        executor.execute_graph_click.return_value = (fail_exec, fail_res)
        executor.execute_graph_fill.return_value = (fail_exec, fail_res)
        executor.execute_graph_wait.return_value = (fail_exec, fail_res)

        def broken_reobserve():
            raise RuntimeError("observation failed")

        orch = ActionOrchestrator(executor=executor)
        policy = RetryPolicy(max_retries=3, reobserve=broken_reobserve)
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")

        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph, retry_policy=policy)

        assert result.status == PlanStatus.FAILED
        assert result.completed_steps == 0

    def test_evidence_insufficient_is_retryable(self):
        """EVIDENCE_INSUFFICIENT resolution triggers retry."""
        from netweaver.action_orchestrator import RetryPolicy

        insufficient_res = GraphResolvedTarget(
            status=ResolutionStatus.EVIDENCE_INSUFFICIENT,
            description="btn",
            error="Not enough evidence",
        )
        ok_exec = _make_success_execution()
        ok_res = _make_resolution_ok()

        call_count = [0]
        executor = MagicMock(spec=VerifiedExecutor)

        def next_result(*a, **kw):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return (ok_exec, insufficient_res)
            return (ok_exec, ok_res)

        executor.execute_graph_click.side_effect = next_result
        executor.execute_graph_fill.side_effect = next_result
        executor.execute_graph_wait.side_effect = next_result

        orch = ActionOrchestrator(executor=executor)
        policy = RetryPolicy(max_retries=1, reobserve=lambda: None)
        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn")

        graph = _make_graph("btn")
        result = orch.orchestrate(plan, lambda: graph, retry_policy=policy)

        assert result.status == PlanStatus.COMPLETED
        assert result.completed_steps == 1
        assert call_count[0] == 2

    def test_retry_second_step_in_plan(self):
        """Only the failing step is retried, not the whole plan."""
        from netweaver.action_orchestrator import RetryPolicy

        ok_exec = _make_success_execution()
        ok_res = _make_resolution_ok()
        fail_exec = _make_failed_execution("transient")

        call_count = [0]
        executor = MagicMock(spec=VerifiedExecutor)

        def next_result(*a, **kw):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 1:
                return (fail_exec, ok_res)  # step 1 fails first time
            return (ok_exec, ok_res)

        executor.execute_graph_click.side_effect = next_result
        executor.execute_graph_fill.side_effect = next_result
        executor.execute_graph_wait.side_effect = next_result

        orch = ActionOrchestrator(executor=executor)
        policy = RetryPolicy(max_retries=1, reobserve=lambda: None)

        plan = ActionPlan()
        plan.add_step(ActionType.CLICK, "btn1")  # succeeds
        plan.add_step(ActionType.CLICK, "btn2")  # fails then retries ok
        plan.add_step(ActionType.CLICK, "btn3")  # succeeds

        graph = _make_graph("btn1", "btn2", "btn3")
        result = orch.orchestrate(plan, lambda: graph, retry_policy=policy)

        assert result.status == PlanStatus.COMPLETED
        assert result.completed_steps == 3
        assert call_count[0] == 4  # 3 steps + 1 retry for step 1


class TestStepStatus:
    """Tests for StepStatus enum and classification."""

    def test_step_status_values(self):
        from netweaver.action_orchestrator import StepStatus
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.RUNNING.value == "running"
        assert StepStatus.COMPLETED.value == "completed"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SAFETY_BLOCKED.value == "safety_blocked"
        assert StepStatus.EVIDENCE_INSUFFICIENT.value == "evidence_insufficient"
        assert StepStatus.ABORT.value == "abort"

    def test_classify_safety_blocked(self):
        orch = ActionOrchestrator()
        exec_result = _make_success_execution()
        res_result = _make_resolution_safety_blocked()
        from netweaver.action_orchestrator import StepStatus
        status = orch._classify_step_status(exec_result, res_result)
        assert status == StepStatus.SAFETY_BLOCKED

    def test_classify_success(self):
        orch = ActionOrchestrator()
        exec_result = _make_success_execution()
        res_result = _make_resolution_ok()
        from netweaver.action_orchestrator import StepStatus
        status = orch._classify_step_status(exec_result, res_result)
        assert status == StepStatus.COMPLETED

    def test_classify_execution_failure(self):
        orch = ActionOrchestrator()
        exec_result = _make_failed_execution()
        res_result = _make_resolution_ok()
        from netweaver.action_orchestrator import StepStatus
        status = orch._classify_step_status(exec_result, res_result)
        assert status == StepStatus.FAILED

    def test_classify_resolution_not_found(self):
        orch = ActionOrchestrator()
        exec_result = _make_success_execution()
        res_result = _make_resolution_failed()
        from netweaver.action_orchestrator import StepStatus
        status = orch._classify_step_status(exec_result, res_result)
        assert status == StepStatus.FAILED

    def test_classify_evidence_insufficient(self):
        orch = ActionOrchestrator()
        exec_result = _make_success_execution()
        res_result = GraphResolvedTarget(
            status=ResolutionStatus.EVIDENCE_INSUFFICIENT,
            description="btn",
            error="low confidence",
        )
        from netweaver.action_orchestrator import StepStatus
        status = orch._classify_step_status(exec_result, res_result)
        assert status == StepStatus.EVIDENCE_INSUFFICIENT
