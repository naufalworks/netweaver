"""Tests for NetWeaver TraceWriter — NW-018 Observability.

Covers:
- TraceWriter: plan header, step transitions, rollback, plan end
- JSONL file creation with ISO timestamp in name
- Trace file content: plan steps, action/intent/pre/post/status/result
- Failed step includes error message + state reached before failure
- Rollback writes to the same trace
- Integration with ActionOrchestrator via trace parameter
- No new dependencies, no browser, no vendor changes
"""

import json
import os
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

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
from netweaver.wnal import ClickAction, FillAction
from netweaver.action_orchestrator import (
    ActionOrchestrator,
    ActionPlan,
    ActionStep,
    ActionType,
    OrchestrationResult,
    PlanStatus,
    StepResult,
    TraceWriter,
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


def _make_success_execution() -> VerifiedExecution:
    """Create a successful VerifiedExecution."""
    return VerifiedExecution(
        execution_id="exec-1",
        action=ClickAction(),
        status=ExecutionStatus.SUCCESS,
        evidence=PrePostEvidence(pre=None, post=None),
    )


def _make_failed_execution(error: str = "execution failed") -> VerifiedExecution:
    """Create a failed VerifiedExecution."""
    return VerifiedExecution(
        execution_id="exec-fail",
        action=ClickAction(),
        status=ExecutionStatus.EXECUTION_ERROR,
        evidence=PrePostEvidence(pre=None, post=None),
        error=error,
    )


def _make_resolved_target(
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    selector: str = "#btn",
    score: float = 0.95,
    error: str = "",
) -> GraphResolvedTarget:
    """Create a GraphResolvedTarget."""
    return GraphResolvedTarget(
        status=status,
        description="test target",
        selector=selector,
        score=score,
        error=error or (None if status == ResolutionStatus.RESOLVED else f"Resolution failed: {status.value}"),
    )


# ---------------------------------------------------------------------------
# TraceWriter unit tests
# ---------------------------------------------------------------------------

class TestTraceWriterCreation:
    """Test TraceWriter initialization and file creation."""

    def test_creates_trace_file_with_timestamp(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        # File created on first write, not on init — check trace_path naming
        assert writer.trace_path.name.startswith("trace_")
        writer.write_plan_header(ActionPlan())
        assert writer.trace_path.exists()
        # Verify ISO timestamp format in filename
        ts_part = writer.trace_path.stem.replace("trace_", "")
        assert "T" in ts_part or len(ts_part) >= 15
    def test_creates_traces_directory(self, tmp_path):
        traces_dir = tmp_path / "new_traces"
        assert not traces_dir.exists()
        writer = TraceWriter(traces_dir=traces_dir)
        assert traces_dir.exists()
        assert traces_dir.is_dir()

    def test_trace_id_includes_plan_id(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path, plan_id="plan-abc123")
        assert "plan-abc123" in writer.trace_id
        assert "plan-abc123" in writer.trace_path.name

    def test_trace_id_without_plan_id(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        assert writer.trace_id
        assert len(writer.trace_id) >= 15


class TestTraceWriterPlanHeader:
    """Test write_plan_header."""

    def test_writes_plan_header(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        plan = ActionPlan(
            plan_id="plan-test",
            description="Login flow",
            steps=[
                ActionStep(ActionType.FILL, "username", intent="enter username",
                           pre_condition="form visible", post_condition="field filled"),
                ActionStep(ActionType.CLICK, "submit", intent="submit form"),
            ],
        )
        writer.write_plan_header(plan)
        entries = writer.read_trace()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["type"] == "plan_start"
        assert entry["plan_id"] == "plan-test"
        assert entry["description"] == "Login flow"
        assert entry["step_count"] == 2
        assert len(entry["steps"]) == 2
        assert entry["steps"][0]["action_type"] == "fill"
        assert entry["steps"][0]["intent"] == "enter username"
        assert entry["steps"][0]["pre_condition"] == "form visible"
        assert entry["steps"][0]["post_condition"] == "field filled"

    def test_plan_header_includes_all_step_fields(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        plan = ActionPlan(
            steps=[ActionStep(ActionType.WAIT, "page", intent="wait for load",
                              condition="attached", timeout_ms=10000)],
        )
        writer.write_plan_header(plan)
        entries = writer.read_trace()
        step = entries[0]["steps"][0]
        assert step["action_type"] == "wait"
        assert step["description"] == "page"
        assert step["intent"] == "wait for load"

    def test_plan_header_empty_plan(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        plan = ActionPlan(plan_id="empty-plan")
        writer.write_plan_header(plan)
        entries = writer.read_trace()
        assert entries[0]["step_count"] == 0
        assert entries[0]["steps"] == []


class TestTraceWriterStepTransition:
    """Test write_step."""

    def test_writes_successful_step(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        step = ActionStep(ActionType.CLICK, "submit button", intent="submit")
        resolution = _make_resolved_target()
        execution = _make_success_execution()
        writer.write_step(
            0, step, PlanStatus.COMPLETED,
            resolution=resolution,
            execution=execution,
            graph_delta={"nodes_added": ["n1"]},
            evidence_chain_ids=["obs-1", "obs-2"],
            completed_steps_before=0,
        )
        entries = writer.read_trace()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["type"] == "step_transition"
        assert entry["step_index"] == 0
        assert entry["action_type"] == "click"
        assert entry["description"] == "submit button"
        assert entry["intent"] == "submit"
        assert entry["status"] == "completed"
        assert entry["resolution_status"] == "resolved"
        assert entry["resolution_score"] == 0.95
        assert entry["graph_delta"] == {"nodes_added": ["n1"]}
        assert entry["evidence_chain_ids"] == ["obs-1", "obs-2"]

    def test_writes_failed_step_with_error_and_state(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        step = ActionStep(ActionType.CLICK, "missing button")
        writer.write_step(
            2, step, PlanStatus.FAILED,
            error="Target not found",
            completed_steps_before=2,
        )
        entries = writer.read_trace()
        entry = entries[0]
        assert entry["status"] == "failed"
        assert entry["error"] == "Target not found"
        assert "state_reached" in entry
        assert entry["state_reached"] == "2 steps completed before failure"

    def test_writes_safety_blocked_step(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        step = ActionStep(ActionType.CLICK, "payment button")
        resolution = _make_resolved_target(
            status=ResolutionStatus.SAFETY_BLOCKED, error="Payment risk"
        )
        writer.write_step(
            1, step, PlanStatus.SAFETY_BLOCKED,
            error="Safety blocked: Payment risk",
            resolution=resolution,
            completed_steps_before=1,
        )
        entries = writer.read_trace()
        entry = entries[0]
        assert entry["status"] == "safety_blocked"
        assert entry["error"] == "Safety blocked: Payment risk"
        assert entry["state_reached"] == "1 steps completed before failure"

    def test_step_includes_pre_post_conditions(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        step = ActionStep(
            ActionType.FILL, "email",
            pre_condition="form visible",
            post_condition="field filled",
        )
        writer.write_step(0, step, PlanStatus.COMPLETED)
        entries = writer.read_trace()
        assert entries[0]["pre_condition"] == "form visible"
        assert entries[0]["post_condition"] == "field filled"

    def test_step_with_execution_evidence_count(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        step = ActionStep(ActionType.CLICK, "btn")
        execution = MagicMock()
        execution.status = ExecutionStatus.SUCCESS
        execution.report = MagicMock()
        execution.report.observations = ["obs1", "obs2", "obs3"]
        writer.write_step(0, step, PlanStatus.COMPLETED, execution=execution)
        entries = writer.read_trace()
        assert entries[0]["evidence_count"] == 3


class TestTraceWriterRollback:
    """Test write_rollback."""

    def test_writes_rollback_action(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        writer.write_rollback(
            step_index=2,
            action_type="fill",
            description="clear email field",
            rollback_status="recorded",
        )
        entries = writer.read_trace()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["type"] == "rollback_action"
        assert entry["step_index"] == 2
        assert entry["action_type"] == "fill"
        assert entry["description"] == "clear email field"
        assert entry["rollback_status"] == "recorded"

    def test_rollback_default_status(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        writer.write_rollback(0, "click", "undo click")
        entries = writer.read_trace()
        assert entries[0]["rollback_status"] == "recorded"


class TestTraceWriterPlanEnd:
    """Test write_plan_end."""

    def test_writes_plan_end_completed(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        writer.write_plan_end("plan-1", PlanStatus.COMPLETED, 3, 3)
        entries = writer.read_trace()
        entry = entries[0]
        assert entry["type"] == "plan_end"
        assert entry["plan_id"] == "plan-1"
        assert entry["status"] == "completed"
        assert entry["completed_steps"] == 3
        assert entry["total_steps"] == 3
        assert "error" not in entry

    def test_writes_plan_end_failed_with_error(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        writer.write_plan_end("plan-2", PlanStatus.FAILED, 1, 3, error="Step 1 failed")
        entries = writer.read_trace()
        entry = entries[0]
        assert entry["status"] == "failed"
        assert entry["error"] == "Step 1 failed"
        assert entry["completed_steps"] == 1

    def test_write_plan_end_closes_writer(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        assert not writer.is_closed
        writer.write_plan_end("plan-1", PlanStatus.COMPLETED, 1, 1)
        assert writer.is_closed


class TestTraceWriterJSONLFormat:
    """Test JSONL format specifics."""

    def test_each_line_is_valid_json(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        plan = ActionPlan(plan_id="p1", steps=[ActionStep(ActionType.CLICK, "btn")])
        writer.write_plan_header(plan)
        writer.write_step(0, plan.steps[0], PlanStatus.COMPLETED)
        writer.write_plan_end("p1", PlanStatus.COMPLETED, 1, 1)
        with open(writer.trace_path) as f:
            for line in f:
                line = line.strip()
                assert line, "No empty lines"
                json.loads(line)

    def test_lines_property_returns_all_lines(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        writer.write_plan_header(ActionPlan())
        writer.write_step(0, ActionStep(ActionType.CLICK, "x"), PlanStatus.COMPLETED)
        assert len(writer.lines) == 2

    def test_read_trace_returns_parsed_entries(self, tmp_path):
        writer = TraceWriter(traces_dir=tmp_path)
        writer.write_plan_header(ActionPlan(description="test"))
        entries = writer.read_trace()
        assert isinstance(entries, list)
        assert isinstance(entries[0], dict)


# ---------------------------------------------------------------------------
# Integration: TraceWriter + ActionOrchestrator
# ---------------------------------------------------------------------------

class TestOrchestratorWithTrace:
    """Integration tests for ActionOrchestrator with TraceWriter."""

    def _make_mock_orchestrator(self, tmp_path, graph):
        """Create orchestrator with mock executor and trace writer."""
        writer = TraceWriter(traces_dir=tmp_path)
        executor = MagicMock(spec=VerifiedExecutor)

        def mock_graph_click(graph, description, **kwargs):
            resolution = _make_resolved_target(selector=f"#{description.replace(' ', '-')}")
            execution = _make_success_execution()
            return execution, resolution

        def mock_graph_fill(graph, description, text="", **kwargs):
            resolution = _make_resolved_target(selector=f"#{description.replace(' ', '-')}")
            execution = _make_success_execution()
            return execution, resolution

        def mock_graph_wait(graph, description, **kwargs):
            resolution = _make_resolved_target(selector=f"#{description.replace(' ', '-')}")
            execution = _make_success_execution()
            return execution, resolution

        executor.execute_graph_click = mock_graph_click
        executor.execute_graph_fill = mock_graph_fill
        executor.execute_graph_wait = mock_graph_wait

        orch = ActionOrchestrator(executor=executor, trace=writer)
        return orch, writer

    def test_happy_path_produces_trace_file(self, tmp_path):
        graph = _make_graph("username", "password", "submit")
        orch, writer = self._make_mock_orchestrator(tmp_path, graph)

        plan = ActionPlan(
            plan_id="login-plan",
            description="Login flow",
            steps=[
                ActionStep(ActionType.FILL, "username", intent="enter username", text="user@test.com"),
                ActionStep(ActionType.FILL, "password", intent="enter password", text="secret"),
                ActionStep(ActionType.CLICK, "submit", intent="submit form"),
            ],
        )

        result = orch.orchestrate(plan, lambda: graph, skip_perspective=True)

        assert result.status == PlanStatus.COMPLETED
        assert writer.trace_path.exists()

        entries = writer.read_trace()
        # plan_start + 3 step_transitions + plan_end = 5 entries
        assert len(entries) == 5

        # Verify plan_start
        assert entries[0]["type"] == "plan_start"
        assert entries[0]["plan_id"] == "login-plan"
        assert entries[0]["step_count"] == 3

        # Verify step transitions
        for i in range(1, 4):
            assert entries[i]["type"] == "step_transition"
            assert entries[i]["status"] == "completed"
            assert entries[i]["step_index"] == i - 1

        # Verify plan_end
        assert entries[4]["type"] == "plan_end"
        assert entries[4]["status"] == "completed"
        assert entries[4]["completed_steps"] == 3

    def test_failed_step_includes_error_and_state(self, tmp_path):
        graph = _make_graph("username", "submit")
        writer = TraceWriter(traces_dir=tmp_path)
        executor = MagicMock(spec=VerifiedExecutor)

        def mock_graph_click(graph, description, **kwargs):
            if description == "submit":
                resolution = _make_resolved_target(selector="#submit")
                execution = _make_failed_execution("Element not clickable")
                return execution, resolution
            resolution = _make_resolved_target()
            return _make_success_execution(), resolution

        def mock_graph_fill(graph, description, text="", **kwargs):
            resolution = _make_resolved_target()
            return _make_success_execution(), resolution

        executor.execute_graph_click = mock_graph_click
        executor.execute_graph_fill = mock_graph_fill
        executor.execute_graph_wait = lambda g, d, **kw: (_make_success_execution(), _make_resolved_target())

        orch = ActionOrchestrator(executor=executor, trace=writer)
        plan = ActionPlan(
            steps=[
                ActionStep(ActionType.FILL, "username", text="user"),
                ActionStep(ActionType.CLICK, "submit"),
                ActionStep(ActionType.CLICK, "next-page"),
            ],
        )

        result = orch.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.status == PlanStatus.FAILED

        entries = writer.read_trace()
        # plan_start + step0_completed + step1_failed + plan_end = 4
        assert len(entries) == 4

        step1 = entries[2]
        assert step1["type"] == "step_transition"
        assert step1["status"] == "failed"
        assert "error" in step1
        assert "state_reached" in step1
        assert step1["state_reached"] == "1 steps completed before failure"

        plan_end = entries[3]
        assert plan_end["status"] == "failed"
        assert plan_end["completed_steps"] == 1
        assert plan_end["total_steps"] == 3

    def test_rollback_writes_to_same_trace(self, tmp_path):
        graph = _make_graph("username")
        orch, writer = self._make_mock_orchestrator(tmp_path, graph)

        plan = ActionPlan(
            steps=[
                ActionStep(ActionType.FILL, "username", text="user"),
            ],
        )

        result = orch.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.status == PlanStatus.COMPLETED

        rollback_result = orch.roll_back(result)
        assert rollback_result.steps_rolled_back == 1

        entries = writer.read_trace()
        # plan_start + step0_completed + plan_end + rollback = 4
        assert len(entries) == 4
        rollback_entry = entries[3]
        assert rollback_entry["type"] == "rollback_action"
        assert rollback_entry["action_type"] == "fill"
        assert rollback_entry["description"] == "username"

    def test_rollback_with_explicit_actions(self, tmp_path):
        graph = _make_graph("username", "password")
        orch, writer = self._make_mock_orchestrator(tmp_path, graph)

        plan = ActionPlan(
            steps=[
                ActionStep(ActionType.FILL, "username", text="user"),
                ActionStep(ActionType.FILL, "password", text="pass"),
            ],
        )

        result = orch.orchestrate(plan, lambda: graph, skip_perspective=True)
        rollback_actions = [
            ActionStep(ActionType.FILL, "clear password"),
            ActionStep(ActionType.FILL, "clear username"),
        ]
        orch.roll_back(result, rollback_actions=rollback_actions)

        entries = writer.read_trace()
        rollback_entries = [e for e in entries if e["type"] == "rollback_action"]
        assert len(rollback_entries) == 2
        assert rollback_entries[0]["action_type"] == "fill"
        assert rollback_entries[0]["description"] == "clear password"
        assert rollback_entries[0]["rollback_status"] == "attempted"

    def test_trace_file_has_iso_timestamp_name(self, tmp_path):
        graph = _make_graph("btn")
        orch, writer = self._make_mock_orchestrator(tmp_path, graph)

        plan = ActionPlan(steps=[ActionStep(ActionType.CLICK, "btn")])
        orch.orchestrate(plan, lambda: graph, skip_perspective=True)

        name = writer.trace_path.name
        assert name.startswith("trace_")
        assert name.endswith(".jsonl")
        ts_part = name.replace("trace_", "").replace(".jsonl", "")
        ts_only = ts_part.split("_")[0]
        assert len(ts_only) >= 15
        assert "T" in ts_only

    def test_empty_plan_produces_header_and_end_only(self, tmp_path):
        graph = _make_graph()
        orch, writer = self._make_mock_orchestrator(tmp_path, graph)

        plan = ActionPlan(plan_id="empty")
        result = orch.orchestrate(plan, lambda: graph, skip_perspective=True)

        entries = writer.read_trace()
        assert len(entries) == 2
        assert entries[0]["type"] == "plan_start"
        assert entries[0]["step_count"] == 0
        assert entries[1]["type"] == "plan_end"
        assert entries[1]["status"] == "completed"
        assert entries[1]["completed_steps"] == 0

    def test_no_trace_writer_means_no_trace_file(self, tmp_path):
        """Verify backward compatibility: no trace param = no trace file."""
        graph = _make_graph("btn")
        executor = MagicMock(spec=VerifiedExecutor)
        executor.execute_graph_click = lambda graph, description, **kw: (
            _make_success_execution(), _make_resolved_target()
        )
        orch = ActionOrchestrator(executor=executor)
        plan = ActionPlan(steps=[ActionStep(ActionType.CLICK, "btn")])
        result = orch.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result.status == PlanStatus.COMPLETED
        assert not list(tmp_path.glob("trace_*.jsonl"))

    def test_resolution_failure_trace(self, tmp_path):
        """Test trace for step where target resolution fails."""
        graph = _make_graph()
        writer = TraceWriter(traces_dir=tmp_path)
        executor = MagicMock(spec=VerifiedExecutor)

        def mock_graph_click(graph, description, **kwargs):
            resolution = _make_resolved_target(
                status=ResolutionStatus.NOT_FOUND,
                error="No matching element found",
            )
            execution = _make_success_execution()
            return execution, resolution

        executor.execute_graph_click = mock_graph_click
        executor.execute_graph_fill = lambda g, d, **kw: (_make_success_execution(), _make_resolved_target())
        executor.execute_graph_wait = lambda g, d, **kw: (_make_success_execution(), _make_resolved_target())

        orch = ActionOrchestrator(executor=executor, trace=writer)
        plan = ActionPlan(steps=[ActionStep(ActionType.CLICK, "nonexistent")])
        result = orch.orchestrate(plan, lambda: graph, skip_perspective=True)

        assert result.status == PlanStatus.FAILED
        entries = writer.read_trace()
        assert len(entries) == 3
        step_entry = entries[1]
        assert step_entry["status"] == "failed"
        assert step_entry["error"]
        assert step_entry["state_reached"] == "0 steps completed before failure"

    def test_multiple_plans_produce_separate_traces(self, tmp_path):
        """Each orchestrate() call gets its own trace file."""
        graph = _make_graph("btn")
        orch, _ = self._make_mock_orchestrator(tmp_path, graph)

        plan1 = ActionPlan(plan_id="p1", steps=[ActionStep(ActionType.CLICK, "btn")])
        plan2 = ActionPlan(plan_id="p2", steps=[ActionStep(ActionType.CLICK, "btn")])

        orch.orchestrate(plan1, lambda: graph, skip_perspective=True)

        writer2 = TraceWriter(traces_dir=tmp_path, plan_id="p2")
        orch.trace = writer2
        orch.orchestrate(plan2, lambda: graph, skip_perspective=True)

        trace_files = list(tmp_path.glob("trace_*.jsonl"))
        assert len(trace_files) == 2

    def test_trace_entries_have_timestamps(self, tmp_path):
        graph = _make_graph("btn")
        orch, writer = self._make_mock_orchestrator(tmp_path, graph)

        plan = ActionPlan(steps=[ActionStep(ActionType.CLICK, "btn")])
        orch.orchestrate(plan, lambda: graph, skip_perspective=True)

        for entry in writer.read_trace():
            assert "timestamp" in entry
            datetime.fromisoformat(entry["timestamp"])

    def test_trace_entries_share_trace_id(self, tmp_path):
        graph = _make_graph("btn")
        orch, writer = self._make_mock_orchestrator(tmp_path, graph)

        plan = ActionPlan(steps=[ActionStep(ActionType.CLICK, "btn")])
        orch.orchestrate(plan, lambda: graph, skip_perspective=True)

        entries = writer.read_trace()
        trace_id = writer.trace_id
        for entry in entries:
            assert entry["trace_id"] == trace_id
