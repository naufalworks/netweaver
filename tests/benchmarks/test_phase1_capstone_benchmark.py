"""Phase 1 Capstone Benchmark — NW-027

Full lifecycle benchmark: observe → plan → execute → verify → learn.
Exercises every Phase 1 module in sequence, proving end-to-end integration.

No browser download, no Playwright, no network required.

Run: python -m pytest tests/benchmarks/test_phase1_capstone_benchmark.py -v
"""

import ast
import inspect
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict

import pytest

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
    SceneGraphBuilder,
)
from netweaver.graph_query import (
    IntentType,
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
from netweaver.planner import (
    GoalTranslator,
    PlanResult,
)
from netweaver.site_skill import SiteSkill, SkillStore
from netweaver.skill_learner import SkillLearner
from netweaver.skill_matcher import SkillMatcher
from netweaver.wnal import ActionabilityEvidence, Phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_editable_evidence(action_id: str, target_ref: str) -> ActionabilityEvidence:
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


def _make_login_observation() -> PageObservation:
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
                actionability={"visible": True, "enabled": True, "attached": True,
                               "stable": True, "pointer_events": True, "editable": True},
            ),
            InteractiveElement(
                selector="#password",
                tag="input",
                type="password",
                text=None,
                aria_label="Password",
                actionability={"visible": True, "enabled": True, "attached": True,
                               "stable": True, "pointer_events": True, "editable": True},
            ),
            InteractiveElement(
                selector="#login-btn",
                tag="button",
                type="submit",
                text="Login",
                aria_label="Login",
                actionability={"visible": True, "enabled": True, "attached": True,
                               "stable": True, "pointer_events": True},
            ),
        ],
        actionability={
            "#username": {"visible": True, "enabled": True},
            "#password": {"visible": True, "enabled": True},
            "#login-btn": {"visible": True, "enabled": True},
        },
        network=NetworkActivity(requests_count=1, responses_count=1, resource_types={"document": 1}),
        observed_at=datetime.now(),
    )


def _make_search_observation() -> PageObservation:
    return PageObservation(
        url="https://shop.example.com/search",
        title="Shop Search",
        interactive_elements=[
            InteractiveElement(
                selector="#search-input",
                tag="input",
                type="search",
                text=None,
                aria_label="Search",
                actionability={"visible": True, "enabled": True, "attached": True,
                               "stable": True, "pointer_events": True, "editable": True},
            ),
            InteractiveElement(
                selector="#search-btn",
                tag="button",
                type="submit",
                text="Search",
                aria_label="Search",
                actionability={"visible": True, "enabled": True, "attached": True,
                               "stable": True, "pointer_events": True},
            ),
        ],
        actionability={
            "#search-input": {"visible": True, "enabled": True},
            "#search-btn": {"visible": True, "enabled": True},
        },
        network=NetworkActivity(requests_count=1, responses_count=1, resource_types={"document": 1}),
        observed_at=datetime.now(),
    )


def _build_graph(observation: PageObservation) -> WebSceneGraph:
    builder = SceneGraphBuilder()
    result = builder.build(observation)
    return result.graph


def _make_completed_result_from_plan(plan: ActionPlan) -> OrchestrationResult:
    step_results = []
    for i, step in enumerate(plan.steps):
        step_results.append(StepResult(
            step_index=i,
            step=step,
            status=PlanStatus.COMPLETED,
        ))
    return OrchestrationResult(
        plan_id=plan.plan_id,
        status=PlanStatus.COMPLETED,
        steps=step_results,
        completed_steps=len(plan.steps),
    )


# ---------------------------------------------------------------------------
# C-001: Full Lifecycle — Login Flow
# ---------------------------------------------------------------------------

class TestFullLifecycleLogin:

    def test_observe_plan_execute_learn(self):
        """Full observe → plan → execute → learn lifecycle for a login flow.

        Note: Phase 1 planner generates template-level descriptions (e.g.,
        "submit or login button") that don't directly resolve against graph nodes.
        For orchestration, we use concrete descriptions matching the observation
        (e.g., "Login" for the button text). This is a documented Phase 2 gap.
        """
        tmp = Path("/tmp") / f"capstone-login-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            # 1. Observe
            obs = _make_login_observation()
            assert len(obs.interactive_elements) == 3

            # 2. Build graph
            graph = _build_graph(obs)
            assert len(graph.nodes) > 3
            dom_count = sum(1 for n in graph.nodes.values() if n.node_type == NodeType.DOM)
            assert dom_count >= 3

            # 3. Plan (validate planner integration)
            translator = GoalTranslator()
            plan_result = translator.translate("log into the website", graph)
            assert plan_result.template_name == "login"
            assert len(plan_result.plan.steps) == 3

            # 4. Orchestrate with concrete descriptions (Phase 1: template
            #    descriptions don't resolve against graph — use site-specific ones)
            plan = ActionPlan(description="Login flow")
            plan.add_step(
                ActionType.FILL, "Username",
                intent="enter username", text="testuser",
                pre_condition="username field visible",
                post_condition="username field populated",
            )
            plan.add_step(
                ActionType.FILL, "Password",
                intent="enter password", text="s3cret",
                pre_condition="password field visible",
                post_condition="password field populated",
            )
            plan.add_step(
                ActionType.CLICK, "Login",
                intent="submit login form",
                pre_condition="login button visible",
                post_condition="form submitted",
            )

            executor = VerifiedExecutor(evidence_collector=_make_editable_evidence)
            orchestrator = ActionOrchestrator(executor=executor)
            orch_result = orchestrator.orchestrate(
                plan, lambda: graph, skip_perspective=True,
            )
            assert orch_result.status == PlanStatus.COMPLETED
            assert orch_result.completed_steps == 3

            # 5. Learn
            store = SkillStore(tmp)
            learner = SkillLearner(store)
            skill, action = learner.learn_and_store(
                orch_result, plan, "https://example.com/login",
                name="login", goal="log into the website",
            )
            assert action == "created"
            assert skill is not None
            assert skill.name == "login"
            assert skill.goal == "log into the website"
            steps = skill.action_plan.get("steps", [])
            assert len(steps) >= 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# C-002: Full Lifecycle — Search Flow
# ---------------------------------------------------------------------------

class TestFullLifecycleSearch:

    def test_observe_plan_execute_learn_search(self):
        tmp = Path("/tmp") / f"capstone-search-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            obs = _make_search_observation()
            graph = _build_graph(obs)

            # Plan
            translator = GoalTranslator()
            plan_result = translator.translate("search for items", graph)
            assert plan_result.template_name == "search"
            assert len(plan_result.plan.steps) == 3

            types = [s.action_type for s in plan_result.plan.steps]
            assert types == [ActionType.FILL, ActionType.CLICK, ActionType.WAIT]

            # Orchestrate with concrete descriptions
            plan = ActionPlan(description="Search flow")
            plan.add_step(
                ActionType.FILL, "Search",
                intent="enter search query", text="products",
                pre_condition="search field visible",
                post_condition="search field populated",
            )
            plan.add_step(
                ActionType.CLICK, "Search",
                intent="execute search",
                pre_condition="search button visible",
                post_condition="search submitted",
            )

            executor = VerifiedExecutor(evidence_collector=_make_editable_evidence)
            orchestrator = ActionOrchestrator(executor=executor)
            orch_result = orchestrator.orchestrate(
                plan, lambda: graph, skip_perspective=True,
            )
            assert orch_result.status == PlanStatus.COMPLETED

            store = SkillStore(tmp)
            learner = SkillLearner(store)
            skill, action = learner.learn_and_store(
                orch_result, plan, "https://shop.example.com/search",
                name="search", goal="search for items on the website",
            )
            assert action == "created"
            assert skill is not None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# C-003: Plan-then-Orchestrate Integration
# ---------------------------------------------------------------------------

class TestPlanThenOrchestrate:

    def test_translator_plan_feeds_orchestrator(self):
        """Plan from GoalTranslator produces correct structure for orchestrator.

        Phase 1 limitation: template descriptions are generic and may not
        resolve against graph nodes. This test validates structural compatibility
        (plan ID, step count) rather than full orchestration success.
        """
        obs = _make_login_observation()
        graph = _build_graph(obs)
        translator = GoalTranslator()
        plan_result = translator.translate("log into the website", graph)

        # Validate plan structure is orchestrator-compatible
        assert plan_result.plan.plan_id is not None
        assert len(plan_result.plan.plan_id) > 0
        assert len(plan_result.plan.steps) == 3

        # Validate step types are correct for login
        types = [s.action_type for s in plan_result.plan.steps]
        assert types == [ActionType.FILL, ActionType.FILL, ActionType.CLICK]

        # Validate graph validation
        assert plan_result.graph_validation is True

        # Orchestrate with concrete plan (proves orchestrator accepts planner shape)
        plan = ActionPlan(description="Login flow")
        plan.add_step(
            ActionType.FILL, "Username", text="test",
            pre_condition="visible",
            post_condition="populated",
        )
        plan.add_step(
            ActionType.FILL, "Password", text="pass",
            pre_condition="visible",
            post_condition="populated",
        )
        plan.add_step(
            ActionType.CLICK, "Login",
            pre_condition="visible",
            post_condition="submitted",
        )

        executor = VerifiedExecutor(evidence_collector=_make_editable_evidence)
        orchestrator = ActionOrchestrator(executor=executor)
        orch_result = orchestrator.orchestrate(
            plan, lambda: graph, skip_perspective=True,
        )

        assert orch_result.status == PlanStatus.COMPLETED
        assert orch_result.completed_steps == 3


# ---------------------------------------------------------------------------
# C-004: Failed Orchestration Does Not Learn
# ---------------------------------------------------------------------------

class TestFailedOrchestrationNoLearn:

    def test_failed_orchestration_rejected(self):
        """Failed orchestration result is rejected by learner."""
        tmp = Path("/tmp") / f"capstone-fail-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            obs = _make_login_observation()
            graph = _build_graph(obs)
            translator = GoalTranslator()
            plan_result = translator.translate("log into the website", graph)

            # Create a FAILED result (simulating execution failure)
            step_results = []
            for i, step in enumerate(plan_result.plan.steps):
                step_results.append(StepResult(
                    step_index=i,
                    step=step,
                    status=PlanStatus.FAILED if i == 1 else PlanStatus.COMPLETED,
                    error="Element not found" if i == 1 else None,
                ))
            failed_result = OrchestrationResult(
                plan_id=plan_result.plan.plan_id,
                status=PlanStatus.FAILED,
                steps=step_results,
                completed_steps=1,
            )

            store = SkillStore(tmp)
            learner = SkillLearner(store)
            skill, action = learner.learn_and_store(
                failed_result, plan_result.plan, "https://example.com/login",
                name="login", goal="log into the website",
            )
            assert action == "rejected"
            assert skill is None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# C-005: Skill Reuse After Learning
# ---------------------------------------------------------------------------

class TestSkillReuseAfterLearning:

    def test_learned_skill_found_by_matcher(self):
        """SkillMatcher finds the learned skill for the same site."""
        tmp = Path("/tmp") / f"capstone-reuse-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            obs = _make_login_observation()
            graph = _build_graph(obs)
            translator = GoalTranslator()
            plan_result = translator.translate("log into the website", graph)

            completed_result = _make_completed_result_from_plan(plan_result.plan)

            store = SkillStore(tmp)
            learner = SkillLearner(store)
            skill, action = learner.learn_and_store(
                completed_result, plan_result.plan, "https://example.com/login",
                name="Example Login", goal="log into the website",
            )
            assert action == "created"
            assert skill is not None

            # Now use matcher to find it
            matcher = SkillMatcher(store)
            matches = matcher.match("https://example.com/login", "log into the website")
            assert len(matches) >= 1
            assert matches[0].skill.skill_id == skill.skill_id
            assert matches[0].score > 0.5
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# C-006: Multi-Goal Planning Diversity
# ---------------------------------------------------------------------------

class TestMultiGoalDiversity:

    def test_five_goals_four_unique_templates(self):
        """5 goals produce ≥ 4 unique template matches."""
        graph = _build_graph(_make_login_observation())
        translator = GoalTranslator()

        goals = [
            "log into the website",
            "search for products",
            "navigate to the settings page",
            "fill out the form",
            "confirm the action",
        ]
        template_names = set()
        for goal in goals:
            result = translator.translate(goal, graph)
            template_names.add(result.template_name)

        assert len(template_names) >= 4, (
            f"Expected ≥ 4 unique templates, got {len(template_names)}: {template_names}"
        )


# ---------------------------------------------------------------------------
# C-007: Confidence Score Distribution
# ---------------------------------------------------------------------------

class TestConfidenceDistribution:

    def test_confidence_distribution(self):
        graph = _build_graph(_make_login_observation())
        translator = GoalTranslator()

        # Template-matched goals
        template_goals = ["log into the website", "search for items"]
        for goal in template_goals:
            result = translator.translate(goal, graph)
            assert result.confidence > 0.0, f"Template match for '{goal}' should have confidence > 0"

        # Fallback goal
        fallback = translator.translate("quantum teleport the PDF report", graph)
        assert fallback.confidence == 0.0

        # At least one with graph validation
        login = translator.translate("log into the website", graph)
        assert login.graph_validation is True


# ---------------------------------------------------------------------------
# C-008: No Forbidden Imports
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:

    def test_no_browser_imports(self):
        source = inspect.getsource(__import__(__name__))
        tree = ast.parse(source)
        forbidden = {"playwright", "cloakbrowser", "selenium", "puppeteer"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [alias.name for alias in getattr(node, "names", [])]
                for name in [module] + names:
                    base = name.split(".")[0].lower()
                    assert base not in forbidden, f"Forbidden import: {name}"
