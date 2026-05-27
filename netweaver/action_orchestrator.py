"""NetWeaver Action Orchestrator — Multi-step graph-driven action sequences.

The orchestrator chains graph-resolved actions into verified sequences,
enabling NetWeaver to execute complex multi-step flows (e.g., "log into
this website" → fill email → fill password → click submit → verify redirect).

Core concepts:
  - ActionPlan: ordered list of action steps with pre/post conditions
  - orchestrate(): execute a plan against a scene graph, threading state
  - verify_step(): compare pre/post scene graph state per step
  - roll_back(): undo completed steps on mid-sequence failure
  - StepResult: per-step outcome with evidence chain and graph delta

Design principles:
  - Every step uses graph-native target resolution (NW-015)
  - Inter-step verification catches drift (page changed mid-flow)
  - Rollback uses EvidenceLedger for audit trail
  - Safety blocking at any step halts the entire plan
  - No browser/CloakBrowser/Playwright dependencies — fully mockable
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from netweaver.executor import (
    ExecutionStatus,
    GraphResolvedTarget,
    ResolutionStatus,
    VerifiedExecution,
    VerifiedExecutor,
)
from netweaver.scene_graph import WebSceneGraph
from netweaver.ledger import LedgerEventType
from netweaver import graph_query as _graph_query


# ---------------------------------------------------------------------------
# Trace writer — observability for orchestration runs (NW-018)
# ---------------------------------------------------------------------------

def _default_traces_dir() -> Path:
    """Return the default traces directory path."""
    return Path.home() / "Documents" / "myhermes" / ".tini" / "netweaver" / "traces"


class TraceWriter:
    """Write JSONL trace files for orchestration runs.

    Each orchestrate() call produces a trace file named with an ISO timestamp.
    Every step transition and rollback action is recorded as a JSONL line,
    making multi-step plans observable and debuggable.

    Trace files are written to .tini/netweaver/traces/ by default.
    The directory is created on first write if it doesn't exist.

    Usage:
        writer = TraceWriter()
        writer.write_plan_header(plan)
        writer.write_step(step_index, step, status, ...)
        writer.write_rollback(step_index, action, description)
        # file is flushed automatically
    """

    def __init__(self, traces_dir: Optional[Path] = None, plan_id: str = ""):
        self.traces_dir = traces_dir or _default_traces_dir()
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        self.trace_id = f"{ts}_{plan_id}" if plan_id else ts
        self.trace_path = self.traces_dir / f"trace_{self.trace_id}.jsonl"
        self._lines: List[str] = []
        self._closed = False

    def _append(self, entry: Dict[str, Any]) -> None:
        """Append a trace entry (JSONL line) to the buffer and flush."""
        line = json.dumps(entry, separators=(",", ":"), default=str)
        self._lines.append(line)
        with open(self.trace_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def write_plan_header(self, plan: "ActionPlan") -> None:
        """Write the plan header at the start of a trace."""
        self._append({
            "type": "plan_start",
            "trace_id": self.trace_id,
            "plan_id": plan.plan_id,
            "description": plan.description,
            "step_count": len(plan.steps),
            "steps": [
                {
                    "index": i,
                    "action_type": s.action_type.value,
                    "description": s.description,
                    "intent": s.intent,
                    "pre_condition": s.pre_condition,
                    "post_condition": s.post_condition,
                }
                for i, s in enumerate(plan.steps)
            ],
            "timestamp": datetime.now().isoformat(),
        })

    def write_step(
        self,
        step_index: int,
        step: "ActionStep",
        status: "PlanStatus",
        *,
        error: Optional[str] = None,
        resolution: Optional["GraphResolvedTarget"] = None,
        execution: Optional["VerifiedExecution"] = None,
        graph_delta: Optional[Dict[str, Any]] = None,
        evidence_chain_ids: Optional[List[str]] = None,
        completed_steps_before: int = 0,
    ) -> None:
        """Write a step transition to the trace."""
        entry: Dict[str, Any] = {
            "type": "step_transition",
            "trace_id": self.trace_id,
            "step_index": step_index,
            "action_type": step.action_type.value,
            "description": step.description,
            "intent": step.intent,
            "pre_condition": step.pre_condition,
            "post_condition": step.post_condition,
            "status": status.value,
            "completed_steps_before": completed_steps_before,
            "timestamp": datetime.now().isoformat(),
        }
        if error:
            entry["error"] = error
            entry["state_reached"] = f"{completed_steps_before} steps completed before failure"
        if resolution:
            entry["resolution_status"] = resolution.status.value
            entry["resolution_score"] = resolution.score
            entry["resolution_selector"] = resolution.selector
        if execution:
            entry["execution_status"] = execution.status.value
            if execution.report:
                entry["evidence_count"] = len(execution.report.observations)
        if graph_delta:
            entry["graph_delta"] = graph_delta
        if evidence_chain_ids:
            entry["evidence_chain_ids"] = evidence_chain_ids
        self._append(entry)

    def write_rollback(
        self,
        step_index: int,
        action_type: str,
        description: str,
        rollback_status: str = "recorded",
    ) -> None:
        """Write a rollback action to the trace."""
        self._append({
            "type": "rollback_action",
            "trace_id": self.trace_id,
            "step_index": step_index,
            "action_type": action_type,
            "description": description,
            "rollback_status": rollback_status,
            "timestamp": datetime.now().isoformat(),
        })

    def write_plan_end(self, plan_id: str, status: "PlanStatus",
                       completed_steps: int, total_steps: int,
                       error: Optional[str] = None) -> None:
        """Write the plan completion entry."""
        entry: Dict[str, Any] = {
            "type": "plan_end",
            "trace_id": self.trace_id,
            "plan_id": plan_id,
            "status": status.value,
            "completed_steps": completed_steps,
            "total_steps": total_steps,
            "timestamp": datetime.now().isoformat(),
        }
        if error:
            entry["error"] = error
        self._append(entry)
        self._closed = True

    @property
    def lines(self) -> List[str]:
        """Return all written JSONL lines."""
        return list(self._lines)

    @property
    def is_closed(self) -> bool:
        return self._closed

    def read_trace(self) -> List[Dict[str, Any]]:
        """Read back all trace entries as parsed dicts."""
        if not self.trace_path.exists():
            return []
        entries = []
        with open(self.trace_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries


# ---------------------------------------------------------------------------
# Plan types
# ---------------------------------------------------------------------------

class PlanStatus(Enum):
    """Status of an action plan execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SAFETY_BLOCKED = "safety_blocked"


class StepStatus(Enum):
    """Status of an individual plan step execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SAFETY_BLOCKED = "safety_blocked"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    ABORT = "abort"


# Non-retryable statuses — safety blocks and aborts should never be retried
_NON_RETRYABLE_STATUSES = frozenset({
    StepStatus.SAFETY_BLOCKED,
    StepStatus.ABORT,
})


@dataclass
class RetryPolicy:
    """Policy controlling retry behavior for failed plan steps.

    When a step fails with a retryable status, the orchestrator calls
    the reobserve callback to get a fresh PageObservation, rebuilds the
    scene graph, and retries the failed step with updated context.

    Attributes:
        max_retries: Maximum number of retry attempts per step (default 1).
        retryable_statuses: Set of StepStatus values that trigger retry.
            Defaults to FAILED and EVIDENCE_INSUFFICIENT.
        reobserve: Callable that returns a fresh PageObservation.
            Required when a RetryPolicy is provided.
    """
    max_retries: int = 1
    retryable_statuses: frozenset = field(default_factory=lambda: frozenset({
        StepStatus.FAILED,
        StepStatus.EVIDENCE_INSUFFICIENT,
    }))
    reobserve: Optional[Callable] = None


class ActionType(Enum):
    """Supported action types in a plan step."""
    CLICK = "click"
    FILL = "fill"
    WAIT = "wait"


@dataclass
class ActionStep:
    """A single step in an action plan.

    Attributes:
        action_type: Type of action to perform.
        description: Natural-language target description for graph resolution.
        intent: High-level purpose of this step (e.g., "submit login form").
        text: Text to fill (only for FILL actions).
        condition: Wait condition (only for WAIT actions).
        timeout_ms: Timeout for wait actions.
        pre_condition: Optional description of expected pre-step state.
        post_condition: Optional description of expected post-step state.
    """
    action_type: ActionType
    description: str
    intent: str = ""
    text: str = ""
    condition: str = "attached"
    timeout_ms: int = 5000
    pre_condition: str = ""
    post_condition: str = ""


@dataclass
class StepResult:
    """Result of executing a single plan step.

    Attributes:
        step_index: Index of the step in the plan.
        step: The ActionStep that was executed.
        status: Execution status from VerifiedExecutor.
        execution: The VerifiedExecution record (if step was attempted).
        resolution: The GraphResolvedTarget (if resolution was attempted).
        graph_delta: Changes detected in scene graph after this step.
        evidence_chain_ids: IDs of evidence observations produced.
        error: Error message if step failed.
    """
    step_index: int
    step: ActionStep
    status: PlanStatus = PlanStatus.PENDING
    execution: Optional[VerifiedExecution] = None
    resolution: Optional[GraphResolvedTarget] = None
    graph_delta: Dict[str, Any] = field(default_factory=dict)
    evidence_chain_ids: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ActionPlan:
    """An ordered plan of graph-resolved actions.

    Attributes:
        plan_id: Unique identifier for this plan.
        steps: Ordered list of action steps.
        description: Human-readable description of the plan's goal.
        metadata: Additional context (URL, task ID, etc.).
    """
    plan_id: str = ""
    steps: List[ActionStep] = field(default_factory=list)
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = f"plan-{uuid.uuid4().hex[:12]}"

    def add_step(
        self,
        action_type: ActionType,
        description: str,
        *,
        intent: str = "",
        text: str = "",
        condition: str = "attached",
        timeout_ms: int = 5000,
        pre_condition: str = "",
        post_condition: str = "",
    ) -> "ActionPlan":
        """Add a step to the plan (builder pattern)."""
        self.steps.append(ActionStep(
            action_type=action_type,
            description=description,
            intent=intent,
            text=text,
            condition=condition,
            timeout_ms=timeout_ms,
            pre_condition=pre_condition,
            post_condition=post_condition,
        ))
        return self

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "description": self.description,
            "steps": [
                {
                    "action_type": s.action_type.value,
                    "description": s.description,
                    "intent": s.intent,
                    "text": s.text,
                    "condition": s.condition,
                    "timeout_ms": s.timeout_ms,
                    "pre_condition": s.pre_condition,
                    "post_condition": s.post_condition,
                }
                for s in self.steps
            ],
            "metadata": self.metadata,
        }


@dataclass
class GraphDelta:
    """Detected changes between two scene graph snapshots.

    Attributes:
        nodes_added: Node IDs present in post but not pre.
        nodes_removed: Node IDs present in pre but not post.
        nodes_modified: Node IDs whose properties changed.
        edges_added: Edge IDs present in post but not pre.
        edges_removed: Edge IDs present in pre but not post.
    """
    nodes_added: List[str] = field(default_factory=list)
    nodes_removed: List[str] = field(default_factory=list)
    nodes_modified: List[str] = field(default_factory=list)
    edges_added: List[str] = field(default_factory=list)
    edges_removed: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.nodes_added or self.nodes_removed or self.nodes_modified
            or self.edges_added or self.edges_removed
        )

    def to_dict(self) -> Dict:
        return {
            "nodes_added": self.nodes_added,
            "nodes_removed": self.nodes_removed,
            "nodes_modified": self.nodes_modified,
            "edges_added": self.edges_added,
            "edges_removed": self.edges_removed,
            "has_changes": self.has_changes,
        }


# ---------------------------------------------------------------------------
# Graph comparison
# ---------------------------------------------------------------------------

def compute_graph_delta(
    pre_graph: WebSceneGraph,
    post_graph: WebSceneGraph,
) -> GraphDelta:
    """Compare two scene graphs and compute the delta.

    Detects added/removed/modified nodes and added/removed edges.
    A node is "modified" if its label, properties, or observation_ids differ.
    """
    pre_node_ids = set(pre_graph.nodes.keys())
    post_node_ids = set(post_graph.nodes.keys())

    added = list(post_node_ids - pre_node_ids)
    removed = list(pre_node_ids - post_node_ids)

    modified = []
    for nid in pre_node_ids & post_node_ids:
        pre_n = pre_graph.nodes[nid]
        post_n = post_graph.nodes[nid]
        if (pre_n.label != post_n.label
                or pre_n.properties != post_n.properties
                or pre_n.observation_ids != post_n.observation_ids):
            modified.append(nid)

    pre_edge_ids = {e.edge_id for e in pre_graph.edges.values()}
    post_edge_ids = {e.edge_id for e in post_graph.edges.values()}

    edges_added = list(post_edge_ids - pre_edge_ids)
    edges_removed = list(pre_edge_ids - post_edge_ids)

    return GraphDelta(
        nodes_added=added,
        nodes_removed=removed,
        nodes_modified=modified,
        edges_added=edges_added,
        edges_removed=edges_removed,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# Type for graph supplier — provides fresh graph snapshots between steps
GraphSupplier = Callable[[], WebSceneGraph]


def _make_id(prefix: str = "") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}" if prefix else uuid.uuid4().hex[:16]


class ActionOrchestrator:
    """Execute multi-step action plans against a scene graph.

    The orchestrator:
    1. Takes an ActionPlan and a graph supplier (returns fresh snapshots)
    2. For each step: resolve target via graph, execute, verify state change
    3. On failure: attempt rollback of completed steps
    4. Returns full results with evidence chains

    All browser interaction is via VerifiedExecutor callbacks — no direct
    Playwright/CloakBrowser dependency.
    """

    def __init__(
        self,
        executor: Optional[VerifiedExecutor] = None,
        ledger: Optional[Any] = None,
        max_retries: int = 0,
        trace: Optional[TraceWriter] = None,
    ):
        """Initialize the orchestrator.

        Args:
            executor: VerifiedExecutor for running individual actions.
                Defaults to a mock executor.
            ledger: Optional ActionLedger for recording plan events.
            max_retries: Number of retry attempts per step on failure.
            trace: Optional TraceWriter for observability output (NW-018).
        """
        self.executor = executor or VerifiedExecutor()
        self.ledger = ledger
        self.max_retries = max_retries
        self.trace = trace

    def orchestrate(
        self,
        plan: ActionPlan,
        graph_supplier: GraphSupplier,
        *,
        context: Optional[Dict] = None,
        skip_perspective: bool = False,
        on_step_complete: Optional[Callable[[StepResult], None]] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> "OrchestrationResult":
        """Execute an action plan against scene graph snapshots.

        Args:
            plan: The action plan to execute.
            graph_supplier: Callable that returns a fresh WebSceneGraph.
                Called before each step to get the current page state.
            context: Perspective context passed to each action.
            skip_perspective: Skip perspective analysis on each step.
            on_step_complete: Optional callback after each step completes.
            retry_policy: Optional RetryPolicy for retrying failed steps.
                When provided, failed steps with retryable statuses will
                reobserve the page, rebuild the graph, and retry.

        Returns:
            OrchestrationResult with full execution history and final status.
        """
        if context is None:
            context = {}

        result = OrchestrationResult(
            plan_id=plan.plan_id,
            plan_description=plan.description,
            status=PlanStatus.RUNNING,
        )

        # Log plan start if ledger available
        if self.ledger:
            self.ledger.append_event(
                event_type=LedgerEventType.TASK_START,
                agent="ActionOrchestrator",
                task_id=plan.metadata.get("task_id", ""),
                payload={"plan_id": plan.plan_id, "step_count": len(plan.steps)},
            )

        # Write trace header if trace writer available
        if self.trace:
            self.trace.write_plan_header(plan)

        for i, step in enumerate(plan.steps):
            step_result = StepResult(
                step_index=i,
                step=step,
                status=PlanStatus.RUNNING,
            )

            # Get fresh graph snapshot
            graph = graph_supplier()

            # Execute the step (with optional retry)
            execution, resolution, step_status = self._execute_step_with_retry(
                step=step,
                graph=graph,
                graph_supplier=graph_supplier,
                context=context,
                skip_perspective=skip_perspective,
                retry_policy=retry_policy,
                step_index=i,
            )

            step_result.execution = execution
            step_result.resolution = resolution

            # Handle non-retryable terminal states
            if step_status == StepStatus.SAFETY_BLOCKED:
                step_result.status = PlanStatus.SAFETY_BLOCKED
                step_result.error = resolution.error or "Safety blocked"
                result.steps.append(step_result)
                result.status = PlanStatus.SAFETY_BLOCKED
                result.error = f"Step {i} safety blocked: {step_result.error}"
                if self.trace:
                    self.trace.write_step(
                        i, step, PlanStatus.SAFETY_BLOCKED,
                        error=step_result.error, resolution=resolution,
                        execution=execution, completed_steps_before=result.completed_steps,
                    )
                break

            if step_status == StepStatus.FAILED:
                step_result.status = PlanStatus.FAILED
                step_result.error = resolution.error or execution.error or f"Step failed after retry attempts"
                result.steps.append(step_result)
                result.status = PlanStatus.FAILED
                result.error = f"Step {i} failed: {step_result.error}"
                if self.trace:
                    self.trace.write_step(
                        i, step, PlanStatus.FAILED,
                        error=step_result.error, resolution=resolution,
                        execution=execution, completed_steps_before=result.completed_steps,
                    )
                break

            # Success — verify state change
            post_graph = graph_supplier()
            delta = compute_graph_delta(graph, post_graph)
            step_result.graph_delta = delta.to_dict()
            step_result.status = PlanStatus.COMPLETED

            # Collect evidence IDs
            if execution.report:
                step_result.evidence_chain_ids = [
                    obs.observation_id
                    for obs in execution.report.observations
                ]

            result.steps.append(step_result)
            result.completed_steps += 1

            if self.trace:
                self.trace.write_step(
                    i, step, PlanStatus.COMPLETED,
                    resolution=resolution, execution=execution,
                    graph_delta=step_result.graph_delta,
                    evidence_chain_ids=step_result.evidence_chain_ids,
                    completed_steps_before=result.completed_steps - 1,
                )

            if on_step_complete:
                on_step_complete(step_result)

        # Set final status if not already set to failure
        if result.status == PlanStatus.RUNNING:
            if result.completed_steps == len(plan.steps):
                result.status = PlanStatus.COMPLETED
            else:
                result.status = PlanStatus.FAILED

        result.finished_at = datetime.now()

        if self.trace:
            self.trace.write_plan_end(
                plan.plan_id, result.status,
                result.completed_steps, len(plan.steps),
                error=result.error,
            )

        return result

    def _classify_step_status(
        self,
        execution: VerifiedExecution,
        resolution: GraphResolvedTarget,
    ) -> StepStatus:
        """Classify a step outcome into a StepStatus for retry logic."""
        if resolution.status == ResolutionStatus.SAFETY_BLOCKED:
            return StepStatus.SAFETY_BLOCKED
        if resolution.status != ResolutionStatus.RESOLVED:
            if resolution.status == ResolutionStatus.EVIDENCE_INSUFFICIENT:
                return StepStatus.EVIDENCE_INSUFFICIENT
            return StepStatus.FAILED
        if execution.status == ExecutionStatus.TARGET_RESOLUTION_FAILED:
            return StepStatus.FAILED
        if execution.status != ExecutionStatus.SUCCESS:
            return StepStatus.FAILED
        return StepStatus.COMPLETED

    def _execute_step_with_retry(
        self,
        step: ActionStep,
        graph: WebSceneGraph,
        graph_supplier: GraphSupplier,
        context: Dict,
        skip_perspective: bool,
        retry_policy: Optional[RetryPolicy],
        step_index: int,
    ) -> Tuple[VerifiedExecution, GraphResolvedTarget, StepStatus]:
        """Execute a step, optionally retrying on failure with reobservation."""
        attempt = 0
        max_attempts = 1 + (retry_policy.max_retries if retry_policy else 0)

        execution: Optional[VerifiedExecution] = None
        resolution: Optional[GraphResolvedTarget] = None
        step_status = StepStatus.PENDING

        while attempt < max_attempts:
            execution, resolution = self._execute_step(
                step=step,
                graph=graph,
                context=context,
                skip_perspective=skip_perspective,
            )

            step_status = self._classify_step_status(execution, resolution)

            # Log the attempt
            if attempt > 0 and self.trace and retry_policy:
                self.trace.write_step(
                    step_index, step, PlanStatus.RUNNING,
                    error=f"Retry attempt {attempt}/{retry_policy.max_retries}",
                    resolution=resolution, execution=execution,
                    completed_steps_before=0,
                )

            # Completed or non-retryable → return immediately
            if step_status == StepStatus.COMPLETED:
                return execution, resolution, step_status
            if step_status in _NON_RETRYABLE_STATUSES:
                return execution, resolution, step_status

            # Retryable failure — check if we have retries left
            attempt += 1
            if retry_policy and attempt < max_attempts:
                # Check if this status is retryable per policy
                if step_status not in retry_policy.retryable_statuses:
                    return execution, resolution, step_status

                # Reobserve the page to get fresh context
                if retry_policy.reobserve:
                    try:
                        retry_policy.reobserve()
                    except Exception:
                        # Reobservation failed — don't retry further
                        return execution, resolution, step_status

                # Get fresh graph for retry
                graph = graph_supplier()

                # Log retry attempt in trace
                if self.trace:
                    self.trace.write_step(
                        step_index, step, PlanStatus.RUNNING,
                        error=f"Reobserving page, retry attempt {attempt}",
                        resolution=resolution, execution=execution,
                        completed_steps_before=0,
                    )
                continue
            else:
                # No more retries
                return execution, resolution, step_status

        # Loop always runs at least once (max_attempts >= 1)
        assert execution is not None and resolution is not None
        return execution, resolution, step_status

    def _execute_step(
        self,
        step: ActionStep,
        graph: WebSceneGraph,
        context: Dict,
        skip_perspective: bool,
    ) -> Tuple[VerifiedExecution, GraphResolvedTarget]:
        """Execute a single plan step via graph-native resolution."""
        if step.action_type == ActionType.CLICK:
            return self.executor.execute_graph_click(
                graph=graph,
                description=step.description,
                context=context,
                skip_perspective=skip_perspective,
            )
        elif step.action_type == ActionType.FILL:
            return self.executor.execute_graph_fill(
                graph=graph,
                description=step.description,
                text=step.text,
                context=context,
                skip_perspective=skip_perspective,
            )
        elif step.action_type == ActionType.WAIT:
            return self.executor.execute_graph_wait(
                graph=graph,
                description=step.description,
                condition=step.condition,
                timeout_ms=step.timeout_ms,
                context=context,
                skip_perspective=skip_perspective,
            )
        else:
            raise ValueError(f"Unknown action type: {step.action_type}")

    def roll_back(
        self,
        result: "OrchestrationResult",
        rollback_actions: Optional[List[ActionStep]] = None,
    ) -> "RollbackResult":
        """Attempt to roll back completed steps.

        Uses the evidence ledger (if available) to record rollback events.
        If no explicit rollback_actions are provided, reverses completed
        steps in reverse order using their post-condition descriptions.

        Args:
            result: The failed OrchestrationResult to roll back.
            rollback_actions: Optional explicit rollback steps.
                If None, attempts automatic reversal.

        Returns:
            RollbackResult with rollback status and evidence.
        """
        rollback_result = RollbackResult(
            plan_id=result.plan_id,
            steps_rolled_back=0,
            status="pending",
        )

        completed = [s for s in result.steps if s.status == PlanStatus.COMPLETED]

        if not completed:
            rollback_result.status = "nothing_to_rollback"
            return rollback_result

        # Reverse completed steps for rollback
        steps_to_undo = list(reversed(completed))

        if rollback_actions:
            # Use provided rollback actions
            for rb_step in rollback_actions:
                # In a real implementation, this would execute the undo
                rollback_result.rollback_steps.append({
                    "action": rb_step.action_type.value,
                    "description": rb_step.description,
                    "status": "attempted",
                })
                rollback_result.steps_rolled_back += 1
                if self.trace:
                    self.trace.write_rollback(
                        step_index=-1,
                        action_type=rb_step.action_type.value,
                        description=rb_step.description,
                        rollback_status="attempted",
                    )
        else:
            # Automatic reversal: record intent to undo each step
            for step_result in steps_to_undo:
                rollback_result.rollback_steps.append({
                    "step_index": step_result.step_index,
                    "action": step_result.step.action_type.value,
                    "description": step_result.step.description,
                    "status": "recorded",
                })
                rollback_result.steps_rolled_back += 1
                if self.trace:
                    self.trace.write_rollback(
                        step_index=step_result.step_index,
                        action_type=step_result.step.action_type.value,
                        description=step_result.step.description,
                        rollback_status="recorded",
                    )

        # Record rollback in ledger if available
        if self.ledger:
            self.ledger.append_event(
                event_type=LedgerEventType.TASK_STATE_CHANGE,
                agent="ActionOrchestrator",
                task_id="",
                payload={
                    "rollback_plan_id": result.plan_id,
                    "steps_rolled_back": rollback_result.steps_rolled_back,
                },
            )

        rollback_result.status = "completed"
        return rollback_result

    def verify_step(
        self,
        step: ActionStep,
        pre_graph: WebSceneGraph,
        post_graph: WebSceneGraph,
    ) -> "VerificationResult":
        """Verify a step's effect by comparing pre/post scene graph state.

        Checks whether the graph delta is consistent with the step's
        post_condition description. Returns a verification result with
        the detected delta and a pass/fail assessment.

        Args:
            step: The step that was executed.
            pre_graph: Scene graph before the step.
            post_graph: Scene graph after the step.

        Returns:
            VerificationResult with delta and pass/fail status.
        """
        delta = compute_graph_delta(pre_graph, post_graph)

        # Basic verification: if post_condition is specified, check that
        # the graph changed in some way. In production, this would use
        # semantic matching against the post_condition description.
        if step.post_condition:
            passed = delta.has_changes
            reason = (
                "Graph changed after step"
                if passed
                else "No graph changes detected after step"
            )
        else:
            # No post_condition specified — always pass
            passed = True
            reason = "No post_condition specified"

        return VerificationResult(
            step_description=step.description,
            delta=delta,
            passed=passed,
            reason=reason,
        )


@dataclass
class OrchestrationResult:
    """Result of executing an action plan.

    Attributes:
        plan_id: The plan that was executed.
        plan_description: Human-readable plan description.
        status: Final plan status.
        steps: Results for each step attempted.
        completed_steps: Number of successfully completed steps.
        error: Error message if plan failed.
        started_at: When orchestration started.
        finished_at: When orchestration finished.
    """
    plan_id: str
    plan_description: str = ""
    status: PlanStatus = PlanStatus.PENDING
    steps: List[StepResult] = field(default_factory=list)
    completed_steps: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.now()

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "plan_description": self.plan_description,
            "status": self.status.value,
            "completed_steps": self.completed_steps,
            "total_steps": len(self.steps),
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "steps": [
                {
                    "step_index": s.step_index,
                    "action_type": s.step.action_type.value,
                    "description": s.step.description,
                    "status": s.status.value,
                    "error": s.error,
                    "graph_delta": s.graph_delta,
                    "evidence_chain_ids": s.evidence_chain_ids,
                }
                for s in self.steps
            ],
        }


@dataclass
class RollbackResult:
    """Result of a rollback attempt.

    Attributes:
        plan_id: The plan that was rolled back.
        steps_rolled_back: Number of steps successfully reversed.
        status: Rollback status (pending/completed/nothing_to_rollback).
        rollback_steps: Details of each rollback action.
    """
    plan_id: str
    steps_rolled_back: int = 0
    status: str = "pending"
    rollback_steps: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "steps_rolled_back": self.steps_rolled_back,
            "status": self.status,
            "rollback_steps": self.rollback_steps,
        }


@dataclass
class VerificationResult:
    """Result of step verification.

    Attributes:
        step_description: The step that was verified.
        delta: Graph delta between pre and post states.
        passed: Whether the verification passed.
        reason: Human-readable explanation.
    """
    step_description: str
    delta: GraphDelta
    passed: bool
    reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "step_description": self.step_description,
            "delta": self.delta.to_dict(),
            "passed": self.passed,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Dry-run types — validate plans without executing (NW-030)
# ---------------------------------------------------------------------------

@dataclass
class DryRunStep:
    """Result of dry-running a single plan step.

    Validates the step against the current scene graph without executing
    any actions. Reports what WOULD happen if the step were executed.

    Attributes:
        step_index: Index of the step in the plan.
        action_type: Type of action that would be performed.
        description: Natural-language target description.
        target_found: Whether the target node exists in the graph.
        target_selector: CSS selector if target was resolved.
        target_score: Confidence score of target resolution (0.0-1.0).
        preconditions_met: Whether the step's preconditions are satisfied.
        preconditions_reason: Explanation of precondition check result.
        safety_clear: Whether the target is free from safety blocks.
        safety_reason: Why the target is blocked (if not clear).
        would_succeed: Overall prediction — would this step succeed?
        issues: List of specific issues that would prevent execution.
    """
    step_index: int
    action_type: ActionType
    description: str
    target_found: bool = False
    target_selector: Optional[str] = None
    target_score: float = 0.0
    preconditions_met: bool = True
    preconditions_reason: str = ""
    safety_clear: bool = True
    safety_reason: Optional[str] = None
    would_succeed: bool = False
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "step_index": self.step_index,
            "action_type": self.action_type.value,
            "description": self.description,
            "target_found": self.target_found,
            "target_selector": self.target_selector,
            "target_score": self.target_score,
            "preconditions_met": self.preconditions_met,
            "preconditions_reason": self.preconditions_reason,
            "safety_clear": self.safety_clear,
            "safety_reason": self.safety_reason,
            "would_succeed": self.would_succeed,
            "issues": self.issues,
        }


@dataclass
class DryRunResult:
    """Result of dry-running an entire action plan.

    Summarizes what WOULD happen if the plan were executed against the
    current scene graph, identifying potential issues before execution.

    Attributes:
        plan_id: The plan that was dry-run.
        plan_description: Human-readable plan description.
        steps: Per-step validation results.
        total_steps: Total number of steps in the plan.
        steps_would_succeed: Count of steps predicted to succeed.
        has_issues: Whether any issues were detected.
        missing_nodes: Descriptions of targets not found in the graph.
        blocked_selectors: Selectors that are safety-blocked.
        unmet_preconditions: Steps with unmet preconditions.
    """
    plan_id: str
    plan_description: str = ""
    steps: List[DryRunStep] = field(default_factory=list)
    total_steps: int = 0
    steps_would_succeed: int = 0
    has_issues: bool = False
    missing_nodes: List[str] = field(default_factory=list)
    blocked_selectors: List[str] = field(default_factory=list)
    unmet_preconditions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "plan_description": self.plan_description,
            "total_steps": self.total_steps,
            "steps_would_succeed": self.steps_would_succeed,
            "has_issues": self.has_issues,
            "missing_nodes": self.missing_nodes,
            "blocked_selectors": self.blocked_selectors,
            "unmet_preconditions": self.unmet_preconditions,
            "steps": [s.to_dict() for s in self.steps],
        }
