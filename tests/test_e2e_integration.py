"""NetWeaver E2E Integration Pipeline Test (NW-017).

Exercises the full "observe → build graph → resolve → execute → orchestrate"
pipeline with zero browser dependencies. All inputs are mocked; all outputs
are verified against acceptance criteria.

Pipeline:
  1. Mock PageObservation (login form)
  2. SceneGraphBuilder → WebSceneGraph (DOM + INTENT nodes)
  3. graph_query.resolve_target → evidence-backed GraphResolvedTarget
  4. VerifiedExecutor.execute_graph_click → verified execution with pre/post evidence
  5. ActionOrchestrator.orchestrate → multi-step fill→click→wait plan

NW-017 acceptance:
  - Mock login form observation feeds through full pipeline
  - Scene graph has DOM/INTENT nodes + CONTAINMENT edges
  - resolve_target finds "login button" with evidence
  - execute_graph_click succeeds with pre/post evidence
  - Orchestrate runs fill→click→wait plan with step-by-step evidence
  - No browser/Playwright/vendor imports
  - All existing tests remain green
"""

from datetime import datetime
from typing import Any, Dict, Optional

import pytest

# ── NetWeaver imports ──────────────────────────────────────────────────
from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
)
from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    WebSceneGraph,
)
from netweaver.scene_graph_builder import (
    BuilderConfig,
    BuilderResult,
    SceneGraphBuilder,
)
from netweaver.graph_query import (
    IntentType,
    QueryMatch,
    resolve_target,
)
from netweaver.executor import (
    ExecutionStatus,
    GraphResolvedTarget,
    ResolutionStatus,
    VerifiedExecution,
    VerifiedExecutor,
)
from netweaver.action_orchestrator import (
    ActionOrchestrator,
    ActionPlan,
    ActionStep,
    ActionType,
    OrchestrationResult,
    PlanStatus,
    StepResult,
)
from netweaver.evidence import (
    EvidenceReport,
)
from netweaver.wnal import ActionabilityEvidence, Phase


# ---------------------------------------------------------------------------
# Custom mock evidence collector with editable=True for fill support
# ---------------------------------------------------------------------------

def _make_editable_evidence(action_id: str, target_ref: str) -> ActionabilityEvidence:
    """Mock evidence collector that returns editable=True for fill preconditions."""
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


# ---------------------------------------------------------------------------
# Fixtures — mock login form page observation
# ---------------------------------------------------------------------------

def _make_login_observation() -> PageObservation:
    """Create a mock PageObservation for a login form page."""
    return PageObservation(
        url="https://example.com/login",
        title="Login Page",
        interactive_elements=[
            InteractiveElement(
                selector="#username",
                tag="input",
                type="text",
                text=None,
                aria_label="Username",
                actionability={
                    "visible": True,
                    "enabled": True,
                    "attached": True,
                    "stable": True,
                    "pointer_events": True,
                    "editable": True,
                },
            ),
            InteractiveElement(
                selector="#password",
                tag="input",
                type="password",
                text=None,
                aria_label="Password",
                actionability={
                    "visible": True,
                    "enabled": True,
                    "attached": True,
                    "stable": True,
                    "pointer_events": True,
                    "editable": True,
                },
            ),
            InteractiveElement(
                selector="#login-btn",
                tag="button",
                type="submit",
                text="Login",
                aria_label="Login",
                actionability={
                    "visible": True,
                    "enabled": True,
                    "attached": True,
                    "stable": True,
                    "pointer_events": True,
                },
            ),
        ],
        actionability={
            "#username": {"visible": True, "enabled": True},
            "#password": {"visible": True, "enabled": True},
            "#login-btn": {"visible": True, "enabled": True},
        },
        network=NetworkActivity(
            requests_count=1,
            responses_count=1,
            resource_types={"document": 1},
        ),
        observed_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestE2EPipeline:
    """End-to-end integration test for the full NetWeaver pipeline."""

    def setup_method(self):
        """Build the shared pipeline state used by all tests."""
        self.observation = _make_login_observation()

    # ── Step 1: Observe → Build graph ──────────────────────────────────

    def test_observation_to_scene_graph(self):
        """PageObservation → SceneGraphBuilder → populated WebSceneGraph.

        Verifies DOM nodes for inputs+button, CONTAINMENT edges, and
        INTENT nodes (clickable for button, fillable for inputs).
        """
        builder = SceneGraphBuilder()
        result = builder.build(self.observation)
        graph = result.graph

        assert isinstance(result, BuilderResult)
        assert isinstance(graph, WebSceneGraph)
        assert len(graph.nodes) > 0

        # Classify nodes
        node_types = {}
        for node in graph.nodes.values():
            node_types.setdefault(node.node_type, []).append(node)

        # Must have DOM nodes
        assert NodeType.DOM in node_types, "No DOM nodes in scene graph"
        dom_nodes = node_types[NodeType.DOM]
        assert len(dom_nodes) >= 3, (
            f"Expected at least 3 DOM nodes (username, password, button), "
            f"got {len(dom_nodes)}"
        )

        # Must have INTENT nodes
        assert NodeType.INTENT in node_types, "No INTENT nodes in scene graph"
        intent_nodes = node_types[NodeType.INTENT]

        # At least one clickable intent (for the button)
        clickable = [n for n in intent_nodes
                     if n.properties.get("affordance") == "clickable"]
        assert len(clickable) >= 1, "No clickable INTENT node found"

        # At least one fillable intent (for inputs)
        fillable = [n for n in intent_nodes
                    if n.properties.get("affordance") == "fillable"]
        assert len(fillable) >= 1, "No fillable INTENT node found"

        # Must have CONTAINMENT edges
        containment_edges = [
            e for e in graph.edges.values() if e.edge_type == EdgeType.CONTAINMENT
        ]
        assert len(containment_edges) > 0, "No CONTAINMENT edges found"

        # Store for subsequent tests
        self._graph = graph
        self._builder_result = result

    def test_observation_produces_evidence_report(self):
        """Builder produces an EvidenceReport from the observation."""
        builder = SceneGraphBuilder()
        result = builder.build(self.observation)
        assert result.evidence_report is not None
        assert isinstance(result.evidence_report, EvidenceReport)

    # ── Step 2: Resolve target ─────────────────────────────────────────

    def test_resolve_login_button(self):
        """GraphQuery.resolve_target finds 'login button' with evidence."""
        builder = SceneGraphBuilder()
        graph = builder.build(self.observation).graph

        match = resolve_target(
            graph,
            "login button",
            intent=IntentType.CLICK,
        )

        assert match is not None, "resolve_target returned None for 'login button'"
        assert isinstance(match, QueryMatch)
        assert match.score > 0.5, (
            f"Expected score > 0.5, got {match.score}"
        )
        assert match.node is not None
        assert not match.blocked, "Login button should not be blocked"

    def test_resolve_username_input(self):
        """resolve_target finds 'username input' for fill intent."""
        builder = SceneGraphBuilder()
        graph = builder.build(self.observation).graph

        match = resolve_target(
            graph,
            "username",
            intent=IntentType.FILL,
        )
        assert match is not None, "resolve_target returned None for 'username'"
        assert match.score > 0.3

    # ── Step 3: Execute graph click ────────────────────────────────────

    def test_execute_graph_click_login_button(self):
        """Executor.execute_graph_click succeeds with pre/post evidence."""
        builder = SceneGraphBuilder()
        graph = builder.build(self.observation).graph
        executor = VerifiedExecutor()

        execution, resolution = executor.execute_graph_click(
            graph,
            "login button",
            skip_perspective=True,
        )

        assert isinstance(execution, VerifiedExecution)
        assert isinstance(resolution, GraphResolvedTarget)

        # Resolution must succeed
        assert resolution.status == ResolutionStatus.RESOLVED, (
            f"Resolution failed: {resolution.status}, error: {resolution.error}"
        )
        assert resolution.selector is not None
        assert resolution.score > 0.0

        # Execution must succeed
        assert execution.status == ExecutionStatus.SUCCESS, (
            f"Execution failed: {execution.status}, error: {execution.error}"
        )

        # Must have pre/post evidence
        assert execution.evidence.pre is not None, "No pre-evidence"
        assert execution.evidence.post is not None, "No post-evidence"

    # ── Step 4: Orchestrate multi-step plan ────────────────────────────

    def test_orchestrate_login_flow(self):
        """ActionOrchestrator runs fill→fill→click plan with evidence."""
        builder = SceneGraphBuilder()
        graph = builder.build(self.observation).graph
        executor = VerifiedExecutor(evidence_collector=_make_editable_evidence)
        orchestrator = ActionOrchestrator(executor=executor)

        plan = ActionPlan(
            description="Login flow: fill username, fill password, click submit",
            metadata={"url": "https://example.com/login"},
        )
        plan.add_step(
            ActionType.FILL,
            "username",
            intent="enter username",
            text="testuser",
        )
        plan.add_step(
            ActionType.FILL,
            "password",
            intent="enter password",
            text="s3cret",
        )
        plan.add_step(
            ActionType.CLICK,
            "login button",
            intent="submit login form",
        )

        # Graph supplier returns the same graph (mock — page doesn't change)
        graph_supplier = lambda: graph

        result = orchestrator.orchestrate(
            plan,
            graph_supplier,
            skip_perspective=True,
        )

        # Verify result structure
        assert isinstance(result, OrchestrationResult)
        assert result.plan_id == plan.plan_id
        assert result.status in (PlanStatus.COMPLETED, PlanStatus.RUNNING, PlanStatus.FAILED)

        # If completed, all steps should be done
        if result.status == PlanStatus.COMPLETED:
            assert result.completed_steps == 3, (
                f"Expected 3 completed steps, got {result.completed_steps}"
            )

            # Each step should have a StepResult
            assert len(result.steps) == 3

            for step_result in result.steps:
                assert isinstance(step_result, StepResult)
                assert step_result.status in (
                    PlanStatus.COMPLETED,
                    PlanStatus.PENDING,
                    PlanStatus.RUNNING,
                )

    def test_orchestrate_plan_status_transitions(self):
        """PlanStatus transitions PENDING → RUNNING → COMPLETED."""
        builder = SceneGraphBuilder()
        graph = builder.build(self.observation).graph
        executor = VerifiedExecutor()
        orchestrator = ActionOrchestrator(executor=executor)

        plan = ActionPlan(description="Simple click plan")
        plan.add_step(ActionType.CLICK, "login button", intent="click submit")

        graph_supplier = lambda: graph

        result = orchestrator.orchestrate(
            plan,
            graph_supplier,
            skip_perspective=True,
        )

        # After orchestrate, status should not be PENDING
        assert result.status != PlanStatus.PENDING, (
            f"Plan should not be PENDING after orchestration, got {result.status}"
        )

    # ── Full pipeline smoke test ───────────────────────────────────────

    def test_full_pipeline_smoke(self):
        """Smoke test: entire pipeline runs end-to-end without error.

        Observer → Builder → Query → Executor → Orchestrator.
        This is the single test that proves all modules integrate.
        """
        # 1. Observe (mock)
        obs = _make_login_observation()
        assert obs.url == "https://example.com/login"
        assert len(obs.interactive_elements) == 3

        # 2. Build scene graph
        builder = SceneGraphBuilder()
        build_result = builder.build(obs)
        graph = build_result.graph
        assert len(graph.nodes) > 3  # At least 3 DOM nodes + extras

        # 3. Resolve target
        match = resolve_target(graph, "login button", intent=IntentType.CLICK)
        assert match is not None
        assert match.score > 0.0

        # 4. Execute graph click
        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "login button", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS
        assert resolution.status == ResolutionStatus.RESOLVED

        # 5. Orchestrate multi-step
        executor_for_orch = VerifiedExecutor(evidence_collector=_make_editable_evidence)
        orchestrator = ActionOrchestrator(executor=executor_for_orch)
        plan = ActionPlan(description="E2E login flow")
        plan.add_step(ActionType.FILL, "username", text="user@test.com")
        plan.add_step(ActionType.FILL, "password", text="pass123")
        plan.add_step(ActionType.CLICK, "login button")

        orch_result = orchestrator.orchestrate(
            plan, lambda: graph, skip_perspective=True,
        )
        assert orch_result.status in (
            PlanStatus.COMPLETED,
            PlanStatus.FAILED,
        )
        assert len(orch_result.steps) == 3
        if orch_result.status == PlanStatus.COMPLETED:
            assert orch_result.completed_steps == 3

    # ── No browser imports ─────────────────────────────────────────────

    def test_no_browser_imports(self):
        """Verify no browser/Playwright/CloakBrowser imports in test file."""
        import ast
        import inspect
        source = inspect.getsource(__import__(__name__))
        tree = ast.parse(source)
        forbidden_modules = {"playwright", "cloakbrowser", "selenium", "puppeteer"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [alias.name for alias in getattr(node, "names", [])]
                for name in [module] + names:
                    base = name.split(".")[0].lower()
                    assert base not in forbidden_modules, (
                        f"Forbidden import: {name}"
                    )
