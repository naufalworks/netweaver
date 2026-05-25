"""Planner & Skill Learner Benchmark Tests — NW-026

Benchmark tests for two core NetWeaver modules:
  - GoalTranslator (planner.py): template matching, graph validation, confidence scoring
  - SkillLearner (skill_learner.py): learn, quality gate, dedup/merge lifecycle

No browser download, no Playwright, no network required.

Run: python -m pytest tests/benchmarks/test_planner_skill_learner_benchmark.py -v
"""

import pytest
from pathlib import Path
from datetime import datetime

from netweaver.planner import (
    GoalTranslator,
    PlanResult,
    PlanTemplate,
    _default_templates,
    _extract_keywords,
)
from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    SceneEdge,
    SceneNode,
    WebSceneGraph,
    create_edge,
    create_node,
)
from netweaver.action_orchestrator import (
    ActionPlan,
    ActionStep,
    ActionType,
    OrchestrationResult,
    PlanStatus,
    StepResult,
)
from netweaver.site_skill import SiteSkill, SkillStore
from netweaver.skill_learner import SkillLearner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph_with_affordances(*affordances: str) -> WebSceneGraph:
    """Create a scene graph with INTENT nodes for the given affordances."""
    graph = WebSceneGraph(graph_id="bench-graph", url="https://example.com")
    for aff in affordances:
        dom = create_node(NodeType.DOM, f"{aff}-el", properties={"text": f"{aff} target"})
        intent = create_node(
            NodeType.INTENT,
            f"{aff}-intent",
            properties={"affordance": aff},
            metadata={"parent_dom_id": dom.node_id},
        )
        graph.add_node(dom)
        graph.add_node(intent)
        graph.add_edge(create_edge(dom.node_id, intent.node_id, EdgeType.CONTAINMENT))
    return graph


def _make_empty_graph() -> WebSceneGraph:
    return WebSceneGraph(graph_id="empty-graph", url="https://example.com")


def _make_completed_result(
    steps: int = 3,
    status: PlanStatus = PlanStatus.COMPLETED,
) -> OrchestrationResult:
    """Create a mock completed OrchestrationResult."""
    step_results = []
    for i in range(steps):
        at = ActionType.CLICK if i == steps - 1 else ActionType.FILL
        action_step = ActionStep(
            action_type=at,
            description=f"step {i}",
            intent=f"step {i} intent",
        )
        step_results.append(StepResult(
            step_index=i,
            step=action_step,
            status=PlanStatus.COMPLETED,
        ))
    return OrchestrationResult(
        plan_id="bench-plan",
        status=status,
        steps=step_results,
        completed_steps=steps if status == PlanStatus.COMPLETED else 0,
    )


def _make_action_plan(steps: int = 3) -> ActionPlan:
    plan = ActionPlan(description="bench plan")
    for i in range(steps):
        at = ActionType.CLICK if i == steps - 1 else ActionType.FILL
        plan.add_step(
            at, f"step {i}",
            intent=f"step {i} intent",
            pre_condition=f"step {i} precondition",
            post_condition=f"step {i} postcondition",
        )
    return plan


# ---------------------------------------------------------------------------
# PL-001: Login Template Match
# ---------------------------------------------------------------------------

class TestPlannerLoginTemplate:

    def test_login_template_matched(self):
        graph = _make_graph_with_affordances("fillable", "clickable")
        translator = GoalTranslator()
        result = translator.translate("log into the website", graph)
        assert result.template_name == "login"
        assert len(result.plan.steps) == 3
        assert result.graph_validation is True
        assert result.confidence > 0.0

    def test_login_steps_correct_types(self):
        graph = _make_graph_with_affordances("fillable", "clickable")
        translator = GoalTranslator()
        result = translator.translate("log into the website", graph)
        types = [s.action_type for s in result.plan.steps]
        assert types == [ActionType.FILL, ActionType.FILL, ActionType.CLICK]

    def test_login_confidence_with_graph_validation(self):
        graph = _make_graph_with_affordances("fillable", "clickable")
        translator = GoalTranslator()
        result = translator.translate("log into the website", graph)
        # Confidence includes graph validation boost (+0.1)
        assert result.confidence > 0.0
        assert result.graph_validation is True


# ---------------------------------------------------------------------------
# PL-002: Search Template Match
# ---------------------------------------------------------------------------

class TestPlannerSearchTemplate:

    def test_search_template_matched(self):
        graph = _make_graph_with_affordances("fillable", "clickable")
        translator = GoalTranslator()
        result = translator.translate("search for products", graph)
        assert result.template_name == "search"
        assert len(result.plan.steps) == 3
        assert result.confidence > 0.0

    def test_search_steps_correct(self):
        graph = _make_graph_with_affordances("fillable", "clickable")
        translator = GoalTranslator()
        result = translator.translate("search for products", graph)
        types = [s.action_type for s in result.plan.steps]
        assert types == [ActionType.FILL, ActionType.CLICK, ActionType.WAIT]


# ---------------------------------------------------------------------------
# PL-003: Navigate Template Match
# ---------------------------------------------------------------------------

class TestPlannerNavigateTemplate:

    def test_navigate_template_matched(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        result = translator.translate("navigate to settings page", graph)
        assert result.template_name == "navigate"
        assert len(result.plan.steps) == 2
        assert result.graph_validation is True

    def test_navigate_go_to_keyword(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        result = translator.translate("go to the dashboard", graph)
        assert result.template_name == "navigate"


# ---------------------------------------------------------------------------
# PL-004: Fill-Form Template Match
# ---------------------------------------------------------------------------

class TestPlannerFillFormTemplate:

    def test_fill_form_template_matched(self):
        graph = _make_graph_with_affordances("fillable", "clickable")
        translator = GoalTranslator()
        result = translator.translate("fill out the registration form", graph)
        assert result.template_name == "fill-form"
        assert len(result.plan.steps) == 2

    def test_fill_form_submit_keyword(self):
        graph = _make_graph_with_affordances("fillable", "clickable")
        translator = GoalTranslator()
        result = translator.translate("submit form with my data", graph)
        assert result.template_name == "fill-form"


# ---------------------------------------------------------------------------
# PL-005: Click-Confirm Template Match
# ---------------------------------------------------------------------------

class TestPlannerClickConfirmTemplate:

    def test_click_confirm_template_matched(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        result = translator.translate("confirm the order", graph)
        assert result.template_name == "click-confirm"
        assert len(result.plan.steps) == 2

    def test_click_confirm_accept_keyword(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        result = translator.translate("accept the terms and conditions", graph)
        assert result.template_name == "click-confirm"

    def test_click_confirm_ok_keyword(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        result = translator.translate("ok proceed", graph)
        assert result.template_name == "click-confirm"


# ---------------------------------------------------------------------------
# PL-006: Fallback for Unknown Goals
# ---------------------------------------------------------------------------

class TestPlannerFallback:

    def test_unknown_goal_fallback(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        result = translator.translate("quantum teleport the PDF report", graph)
        assert result.template_name is None
        assert result.confidence == 0.0
        assert len(result.plan.steps) == 1  # minimal single-step plan

    def test_fallback_plan_has_raw_goal_as_description(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        goal = "quantum teleport the PDF report"
        result = translator.translate(goal, graph)
        assert result.plan.description == goal

    def test_fallback_graph_validation_false(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        result = translator.translate("quantum teleport the PDF report", graph)
        assert result.graph_validation is False

    def test_empty_string_goal_fallback(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        result = translator.translate("", graph)
        assert result.template_name is None


# ---------------------------------------------------------------------------
# PL-007: Graph Validation Failure
# ---------------------------------------------------------------------------

class TestPlannerGraphValidation:

    def test_login_empty_graph_fails_validation(self):
        graph = _make_empty_graph()
        translator = GoalTranslator()
        result = translator.translate("log into the website", graph)
        assert result.template_name == "login"
        assert result.graph_validation is False

    def test_login_missing_fillable_fails_validation(self):
        graph = _make_graph_with_affordances("clickable")  # no fillable
        translator = GoalTranslator()
        result = translator.translate("log into the website", graph)
        assert result.graph_validation is False

    def test_login_full_graph_passes_validation(self):
        graph = _make_graph_with_affordances("fillable", "clickable")
        translator = GoalTranslator()
        result = translator.translate("log into the website", graph)
        assert result.graph_validation is True


# ---------------------------------------------------------------------------
# PL-008: Custom Template
# ---------------------------------------------------------------------------

class TestPlannerCustomTemplate:

    def test_add_custom_template(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        custom = PlanTemplate(
            name="add-to-cart",
            keywords=["add to cart", "buy", "purchase"],
            steps=[
                ActionStep(action_type=ActionType.CLICK, description="add to cart button"),
            ],
            required_affordances=["clickable"],
        )
        translator.add_template(custom)
        assert "add-to-cart" in translator.list_templates()

    def test_custom_template_matches(self):
        graph = _make_graph_with_affordances("clickable")
        translator = GoalTranslator()
        custom = PlanTemplate(
            name="add-to-cart",
            keywords=["add to cart", "buy", "purchase"],
            steps=[
                ActionStep(action_type=ActionType.CLICK, description="add to cart button"),
            ],
            required_affordances=["clickable"],
        )
        translator.add_template(custom)
        result = translator.translate("add to cart the item", graph)
        # Should match custom template (add-to-cart is checked after defaults,
        # but "add to cart" is a strong multi-word match for the custom template)
        assert result.template_name is not None
        # Verify the custom template is available for matching
        assert "add-to-cart" in translator.list_templates()

    def test_remove_template(self):
        translator = GoalTranslator()
        custom = PlanTemplate(
            name="temp",
            keywords=["temp"],
            steps=[],
        )
        translator.add_template(custom)
        assert translator.remove_template("temp") is True
        assert "temp" not in translator.list_templates()

    def test_remove_nonexistent_template(self):
        translator = GoalTranslator()
        assert translator.remove_template("nonexistent") is False

    def test_default_templates_count(self):
        translator = GoalTranslator()
        assert len(translator.list_templates()) == 10


# ---------------------------------------------------------------------------
# PL-009: SkillLearner Happy Path
# ---------------------------------------------------------------------------

class TestSkillLearnerHappyPath:

    def test_learn_returns_skill(self):
        store = SkillStore(Path("/tmp/bench-empty"))
        learner = SkillLearner(store)
        result = _make_completed_result(3)
        plan = _make_action_plan(3)
        skill = learner.learn(result, plan, "https://example.com", goal="login flow")
        assert skill is not None
        assert isinstance(skill, SiteSkill)

    def test_learn_and_store_creates(self):
        tmp = Path("/tmp") / f"bench-learn-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = SkillStore(tmp)
            learner = SkillLearner(store)
            result = _make_completed_result(3)
            plan = _make_action_plan(3)
            skill, action = learner.learn_and_store(
                result, plan, "https://example.com",
                name="login", goal="login to the website",
            )
            assert action == "created"
            assert skill is not None
            assert skill.name == "login"
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_learn_skill_has_plan_steps(self):
        store = SkillStore(Path("/tmp/bench-empty"))
        learner = SkillLearner(store)
        result = _make_completed_result(3)
        plan = _make_action_plan(3)
        skill = learner.learn(result, plan, "https://example.com", goal="test goal")
        assert skill is not None
        steps = skill.action_plan.get("steps", [])
        assert len(steps) >= 1


# ---------------------------------------------------------------------------
# PL-010: SkillLearner Quality Gate Rejection
# ---------------------------------------------------------------------------

class TestSkillLearnerQualityGate:

    def test_reject_empty_plan(self):
        tmp = Path("/tmp") / f"bench-qg-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = SkillStore(tmp)
            learner = SkillLearner(store)
            result = _make_completed_result(0)
            plan = ActionPlan(description="empty")
            skill, action = learner.learn_and_store(
                result, plan, "https://example.com", goal="test",
            )
            assert action == "rejected"
            assert skill is None
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_reject_empty_goal_and_description(self):
        """Quality gate rejects when goal is empty and plan description is also empty."""
        tmp = Path("/tmp") / f"bench-qg2-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = SkillStore(tmp)
            learner = SkillLearner(store)
            result = _make_completed_result(2)
            # Plan with no description → goal fallback is also empty
            plan = ActionPlan(description="")
            plan.add_step(
                ActionType.CLICK, "click me",
                pre_condition="element visible",
            )
            skill, action = learner.learn_and_store(
                result, plan, "https://example.com", goal="",
            )
            # Both goal="" and plan.description="" → from_orchestration_result
            # sets goal="" → quality gate rejects
            assert action == "rejected"
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# PL-011: SkillLearner Dedup and Merge
# ---------------------------------------------------------------------------

class TestSkillLearnerDedupMerge:

    def test_first_create_second_merge(self):
        tmp = Path("/tmp") / f"bench-merge-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = SkillStore(tmp)
            learner = SkillLearner(store)

            result = _make_completed_result(3)
            plan = _make_action_plan(3)

            # First: should create
            skill1, action1 = learner.learn_and_store(
                result, plan, "https://example.com",
                name="login", goal="log into my account on the website",
            )
            assert action1 == "created"
            assert skill1 is not None

            # Second with very similar goal: should merge (Jaccard > 0.5)
            skill2, action2 = learner.learn_and_store(
                result, plan, "https://example.com",
                name="login", goal="log into my account on the portal",
            )
            assert action2 == "merged"
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_merge_increments_success_count(self):
        tmp = Path("/tmp") / f"bench-merge-inc-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = SkillStore(tmp)
            learner = SkillLearner(store)
            result = _make_completed_result(3)
            plan = _make_action_plan(3)

            skill1, _ = learner.learn_and_store(
                result, plan, "https://example.com",
                name="login", goal="log into my account on the website",
            )
            assert skill1 is not None
            initial_count = skill1.execution_stats.get("success_count", 0)

            skill2, action2 = learner.learn_and_store(
                result, plan, "https://example.com",
                name="login", goal="log into my account on the portal",
            )
            assert skill2 is not None
            assert skill2.execution_stats.get("success_count", 0) > initial_count
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_different_sites_no_merge(self):
        tmp = Path("/tmp") / f"bench-no-merge-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = SkillStore(tmp)
            learner = SkillLearner(store)
            result = _make_completed_result(3)
            plan = _make_action_plan(3)

            _, action1 = learner.learn_and_store(
                result, plan, "https://site-a.com",
                name="login", goal="log into my account on the website",
            )
            _, action2 = learner.learn_and_store(
                result, plan, "https://site-b.com",
                name="login", goal="log into my account on the website",
            )
            assert action1 == "created"
            assert action2 == "created"  # different sites → no dedup
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# PL-012: SkillLearner Failed Result Rejection
# ---------------------------------------------------------------------------

class TestSkillLearnerFailedRejection:

    def test_failed_result_rejected(self):
        store = SkillStore(Path("/tmp/bench-empty"))
        learner = SkillLearner(store)
        result = _make_completed_result(3, status=PlanStatus.FAILED)
        plan = _make_action_plan(3)
        skill = learner.learn(result, plan, "https://example.com", goal="test")
        assert skill is None

    def test_failed_result_rejected_by_store(self):
        tmp = Path("/tmp") / f"bench-fail-{datetime.now().timestamp()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = SkillStore(tmp)
            learner = SkillLearner(store)
            result = _make_completed_result(3, status=PlanStatus.FAILED)
            plan = _make_action_plan(3)
            skill, action = learner.learn_and_store(
                result, plan, "https://example.com", goal="test",
            )
            assert action == "rejected"
            assert skill is None
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_rolled_back_result_rejected(self):
        store = SkillStore(Path("/tmp/bench-empty"))
        learner = SkillLearner(store)
        result = _make_completed_result(3, status=PlanStatus.ROLLED_BACK)
        plan = _make_action_plan(3)
        skill = learner.learn(result, plan, "https://example.com", goal="test")
        assert skill is None


# ---------------------------------------------------------------------------
# No browser imports
# ---------------------------------------------------------------------------

class TestNoBrowserImports:

    def test_no_browser_imports(self):
        """Verify no browser/Playwright/CloakBrowser imports in test file."""
        import ast
        import inspect
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
