"""Tests for netweaver.planner — Goal-to-Plan Translator.

Tests cover:
  - PlanTemplate construction and serialization
  - PlanResult construction and serialization
  - GoalTranslator with default templates (login, search, navigate, fill-form, click-confirm)
  - Keyword extraction
  - Template matching by keyword
  - Graph validation filters unavailable targets
  - Fallback for unknown goals
  - Multi-step plan generation
  - Confidence scoring
  - Empty graph handling
  - Custom templates (add/remove/list)
  - Edge cases (empty goal, empty templates, etc.)

No browser/Playwright/vendor imports.
"""

import pytest

from netweaver.action_orchestrator import ActionPlan, ActionStep, ActionType
from netweaver.planner import (
    GoalTranslator,
    PlanResult,
    PlanTemplate,
    _default_templates,
    _extract_keywords,
    _match_template,
    _validate_against_graph,
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


# ---------------------------------------------------------------------------
# Helpers — graph construction
# ---------------------------------------------------------------------------

def _make_graph_with_intent_nodes(*affordances: str) -> WebSceneGraph:
    """Create a minimal scene graph with INTENT nodes for the given affordances.

    Each affordance gets one DOM node + one INTENT node + one CONTAINMENT edge.
    """
    graph = WebSceneGraph(graph_id="test-graph", url="https://example.com")

    for affordance in affordances:
        dom = create_node(NodeType.DOM, f"{affordance}-element", properties={"text": f"{affordance} target"})
        intent = create_node(
            NodeType.INTENT,
            f"{affordance}-intent",
            properties={"affordance": affordance},
            metadata={"parent_dom_id": dom.node_id},
        )
        graph.add_node(dom)
        graph.add_node(intent)
        graph.add_edge(create_edge(dom.node_id, intent.node_id, EdgeType.CONTAINMENT))

    return graph


def _make_empty_graph() -> WebSceneGraph:
    """Create an empty scene graph (no nodes)."""
    return WebSceneGraph(graph_id="empty-graph", url="https://example.com")


# ---------------------------------------------------------------------------
# Test: PlanTemplate
# ---------------------------------------------------------------------------

class TestPlanTemplate:

    def test_construction(self):
        t = PlanTemplate(
            name="test",
            keywords=["hello", "world"],
            steps=[ActionStep(action_type=ActionType.CLICK, description="click me")],
            required_affordances=["clickable"],
        )
        assert t.name == "test"
        assert t.keywords == ["hello", "world"]
        assert len(t.steps) == 1
        assert t.required_affordances == ["clickable"]

    def test_default_required_affordances(self):
        t = PlanTemplate(name="x", keywords=["x"], steps=[])
        assert t.required_affordances == []

    def test_to_dict(self):
        t = PlanTemplate(
            name="login",
            keywords=["login", "sign in"],
            steps=[
                ActionStep(action_type=ActionType.FILL, description="email", intent="fill email"),
                ActionStep(action_type=ActionType.CLICK, description="submit", intent="submit"),
            ],
            required_affordances=["fillable", "clickable"],
        )
        d = t.to_dict()
        assert d["name"] == "login"
        assert d["keywords"] == ["login", "sign in"]
        assert len(d["steps"]) == 2
        assert d["steps"][0]["action_type"] == "fill"
        assert d["required_affordances"] == ["fillable", "clickable"]

    def test_to_dict_empty_steps(self):
        t = PlanTemplate(name="empty", keywords=[], steps=[])
        d = t.to_dict()
        assert d["steps"] == []
        assert d["keywords"] == []


# ---------------------------------------------------------------------------
# Test: PlanResult
# ---------------------------------------------------------------------------

class TestPlanResult:

    def test_construction(self):
        plan = ActionPlan(description="test plan")
        result = PlanResult(
            plan=plan,
            template_name="login",
            confidence=0.8,
            graph_validation=True,
        )
        assert result.plan is plan
        assert result.template_name == "login"
        assert result.confidence == 0.8
        assert result.graph_validation is True

    def test_to_dict(self):
        plan = ActionPlan(description="test")
        result = PlanResult(plan=plan, template_name=None, confidence=0.0, graph_validation=False)
        d = result.to_dict()
        assert d["template_name"] is None
        assert d["confidence"] == 0.0
        assert d["graph_validation"] is False
        assert "plan" in d
        assert "plan_id" in d["plan"]


# ---------------------------------------------------------------------------
# Test: _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:

    def test_basic_extraction(self):
        kw = _extract_keywords("log into the website")
        assert "log" in kw
        assert "website" in kw
        # stop words removed
        assert "into" not in kw
        assert "the" not in kw

    def test_punctuation_removed(self):
        kw = _extract_keywords("search for 'hello world'!")
        assert "search" in kw
        assert "hello" in kw
        assert "world" in kw
        assert "'" not in kw

    def test_short_tokens_filtered(self):
        kw = _extract_keywords("I am a go")
        # tokens < 2 chars removed: I, a
        # "am" is a stop word, also removed
        assert "go" in kw  # exactly 2 chars

    def test_stop_words_removed(self):
        kw = _extract_keywords("click the button and wait for the page")
        assert "click" in kw
        assert "button" in kw
        assert "wait" in kw
        assert "page" in kw
        assert "the" not in kw
        assert "and" not in kw
        assert "for" not in kw

    def test_empty_string(self):
        assert _extract_keywords("") == []

    def test_only_stop_words(self):
        assert _extract_keywords("the a an is it") == []

    def test_case_insensitive(self):
        kw = _extract_keywords("LOGIN to the Website")
        assert "login" in kw
        assert "website" in kw


# ---------------------------------------------------------------------------
# Test: _match_template
# ---------------------------------------------------------------------------

class TestMatchTemplate:

    def test_login_match(self):
        templates = _default_templates()
        kw = _extract_keywords("log in to the website")
        t = _match_template(kw, templates)
        assert t is not None
        assert t.name == "login"

    def test_search_match(self):
        templates = _default_templates()
        kw = _extract_keywords("search for shoes")
        t = _match_template(kw, templates)
        assert t is not None
        assert t.name == "search"

    def test_navigate_match(self):
        templates = _default_templates()
        kw = _extract_keywords("navigate to the homepage")
        t = _match_template(kw, templates)
        assert t is not None
        assert t.name == "navigate"

    def test_fill_form_match(self):
        templates = _default_templates()
        kw = _extract_keywords("fill the form and submit")
        t = _match_template(kw, templates)
        assert t is not None
        assert t.name in ("fill-form", "login")  # both could match

    def test_click_confirm_match(self):
        templates = _default_templates()
        kw = _extract_keywords("click the confirm button")
        t = _match_template(kw, templates)
        assert t is not None
        assert t.name == "click-confirm"

    def test_no_match_returns_none(self):
        templates = _default_templates()
        kw = _extract_keywords("something completely random xyzzy")
        t = _match_template(kw, templates)
        assert t is None

    def test_empty_keywords_returns_none(self):
        templates = _default_templates()
        t = _match_template([], templates)
        assert t is None

    def test_empty_templates_returns_none(self):
        kw = _extract_keywords("login to website")
        t = _match_template(kw, [])
        assert t is None

    def test_multi_word_keyword_match(self):
        t = PlanTemplate(
            name="multi",
            keywords=["log in"],  # multi-word keyword
            steps=[],
        )
        kw = _extract_keywords("log in to the website")
        result = _match_template(kw, [t])
        assert result is not None
        assert result.name == "multi"


# ---------------------------------------------------------------------------
# Test: _validate_against_graph
# ---------------------------------------------------------------------------

class TestValidateAgainstGraph:

    def test_valid_affordances(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        t = PlanTemplate(
            name="login",
            keywords=["login"],
            steps=[],
            required_affordances=["clickable", "fillable"],
        )
        assert _validate_against_graph(t, graph) is True

    def test_missing_affordance(self):
        graph = _make_graph_with_intent_nodes("clickable")
        t = PlanTemplate(
            name="login",
            keywords=["login"],
            steps=[],
            required_affordances=["clickable", "fillable"],
        )
        assert _validate_against_graph(t, graph) is False

    def test_empty_affordances_always_valid(self):
        graph = _make_empty_graph()
        t = PlanTemplate(name="x", keywords=["x"], steps=[], required_affordances=[])
        assert _validate_against_graph(t, graph) is True

    def test_empty_graph_fails_nonempty_affordances(self):
        graph = _make_empty_graph()
        t = PlanTemplate(name="x", keywords=["x"], steps=[], required_affordances=["clickable"])
        assert _validate_against_graph(t, graph) is False


# ---------------------------------------------------------------------------
# Test: GoalTranslator — template matching
# ---------------------------------------------------------------------------

class TestGoalTranslatorMatching:

    def test_login_goal(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("log in to the website", graph)
        assert result.template_name == "login"
        assert result.confidence > 0.0
        assert len(result.plan.steps) == 3  # fill, fill, click

    def test_search_goal(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("search for products", graph)
        assert result.template_name == "search"
        assert len(result.plan.steps) == 3  # fill, click, wait

    def test_navigate_goal(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("navigate to the dashboard", graph)
        assert result.template_name == "navigate"
        assert len(result.plan.steps) == 2  # click, wait

    def test_fill_form_goal(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("fill out the registration form", graph)
        assert result.template_name == "fill-form"
        assert len(result.plan.steps) == 2  # fill, click

    def test_click_confirm_goal(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("confirm the order", graph)
        assert result.template_name == "click-confirm"
        assert len(result.plan.steps) == 2  # click, wait

    def test_register_goal(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("register for an account", graph)
        assert result.template_name == "register"
        assert len(result.plan.steps) == 4  # fill name, fill email, fill password, click
        assert result.plan.steps[0].action_type == ActionType.FILL
        assert result.plan.steps[1].action_type == ActionType.FILL
        assert result.plan.steps[2].action_type == ActionType.FILL
        assert result.plan.steps[3].action_type == ActionType.CLICK

    def test_register_create_account_keyword(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("create account on website", graph)
        assert result.template_name == "register"

    def test_register_signup_keyword(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("signup for newsletter", graph)
        assert result.template_name == "register"

    def test_logout_goal(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("logout of the website", graph)
        assert result.template_name == "logout"
        assert len(result.plan.steps) == 3  # click menu, click logout, wait

    def test_logout_sign_out_keyword(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("sign out", graph)
        assert result.template_name == "logout"

    def test_logout_log_off_keyword(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("log off", graph)
        assert result.template_name == "logout"

    def test_select_goal(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("select an option from dropdown", graph)
        assert result.template_name == "select"
        assert len(result.plan.steps) == 3  # click dropdown, click option, wait

    def test_select_choose_keyword(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("choose a shipping method", graph)
        assert result.template_name == "select"

    def test_toggle_goal(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("toggle the switch", graph)
        assert result.template_name == "toggle"
        assert len(result.plan.steps) == 2  # click, wait

    def test_toggle_enable_keyword(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("enable notifications", graph)
        assert result.template_name == "toggle"

    def test_toggle_checkbox_keyword(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("check the checkbox", graph)
        assert result.template_name == "toggle"

    def test_download_goal(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("download the report", graph)
        assert result.template_name == "download"
        assert len(result.plan.steps) == 2  # click, wait

    def test_download_export_keyword(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("export data to csv", graph)
        assert result.template_name == "download"


# ---------------------------------------------------------------------------
# Test: GoalTranslator — fallback
# ---------------------------------------------------------------------------

class TestGoalTranslatorFallback:

    def test_unknown_goal_fallback(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("do something weird and xyzzy", graph)
        assert result.template_name is None
        assert result.confidence == 0.0
        assert result.graph_validation is False
        assert len(result.plan.steps) == 1  # minimal single-step
        assert result.plan.steps[0].action_type == ActionType.CLICK

    def test_empty_goal_fallback(self):
        graph = _make_empty_graph()
        translator = GoalTranslator()
        result = translator.translate("", graph)
        assert result.template_name is None
        assert result.confidence == 0.0

    def test_fallback_plan_description_is_goal(self):
        graph = _make_empty_graph()
        translator = GoalTranslator()
        result = translator.translate("random action xyzzy", graph)
        assert result.plan.description == "random action xyzzy"


# ---------------------------------------------------------------------------
# Test: GoalTranslator — graph validation
# ---------------------------------------------------------------------------

class TestGoalTranslatorGraphValidation:

    def test_graph_validates_with_required_affordances(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("login", graph)
        assert result.graph_validation is True

    def test_graph_fails_without_required_affordances(self):
        graph = _make_graph_with_intent_nodes("clickable")  # no fillable
        translator = GoalTranslator()
        result = translator.translate("login", graph)
        # login needs fillable + clickable, only clickable present
        assert result.graph_validation is False

    def test_empty_graph_login_fails_validation(self):
        graph = _make_empty_graph()
        translator = GoalTranslator()
        result = translator.translate("login", graph)
        assert result.graph_validation is False

    def test_navigate_only_needs_clickable(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("navigate to the page", graph)
        assert result.graph_validation is True

    def test_register_needs_fillable_and_clickable(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("register", graph)
        assert result.graph_validation is True

    def test_register_fails_without_fillable(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("register", graph)
        assert result.graph_validation is False

    def test_logout_only_needs_clickable(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("logout", graph)
        assert result.graph_validation is True

    def test_select_only_needs_clickable(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("select an option", graph)
        assert result.graph_validation is True

    def test_toggle_only_needs_clickable(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("toggle the switch", graph)
        assert result.graph_validation is True

    def test_download_only_needs_clickable(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("download the file", graph)
        assert result.graph_validation is True


# ---------------------------------------------------------------------------
# Test: GoalTranslator — confidence scoring
# ---------------------------------------------------------------------------

class TestGoalTranslatorConfidence:

    def test_exact_keyword_match_high_confidence(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("login", graph)
        # "login" matches 1 of 6 login keywords, with graph boost
        assert result.confidence >= 0.2  # 1/6 + 0.1 boost ≈ 0.27

    def test_partial_match_lower_confidence(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        # "log in" matches via multi-word keyword "log in"
        result = translator.translate("log in to the portal", graph)
        assert result.confidence > 0.0
        assert result.confidence <= 1.0

    def test_graph_boost_adds_0_1(self):
        # Compare same goal with and without graph validation
        graph_valid = _make_graph_with_intent_nodes("clickable", "fillable")
        graph_empty = _make_empty_graph()
        translator = GoalTranslator()

        result_valid = translator.translate("login", graph_valid)
        result_empty = translator.translate("login", graph_empty)

        # Validated result should have higher confidence due to +0.1 boost
        assert result_valid.confidence > result_empty.confidence

    def test_confidence_bounded_at_1(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("login", graph)
        assert result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Test: GoalTranslator — multi-step plans
# ---------------------------------------------------------------------------

class TestGoalTranslatorMultiStep:

    def test_login_has_three_steps(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("login", graph)
        assert len(result.plan.steps) == 3
        assert result.plan.steps[0].action_type == ActionType.FILL
        assert result.plan.steps[1].action_type == ActionType.FILL
        assert result.plan.steps[2].action_type == ActionType.CLICK

    def test_search_has_three_steps(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("search for items", graph)
        assert len(result.plan.steps) == 3
        assert result.plan.steps[0].action_type == ActionType.FILL
        assert result.plan.steps[1].action_type == ActionType.CLICK
        assert result.plan.steps[2].action_type == ActionType.WAIT

    def test_navigate_has_two_steps(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("navigate to page", graph)
        assert len(result.plan.steps) == 2

    def test_plan_description_is_goal(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("login to my account", graph)
        assert result.plan.description == "login to my account"


# ---------------------------------------------------------------------------
# Test: GoalTranslator — custom templates
# ---------------------------------------------------------------------------

class TestGoalTranslatorCustomTemplates:

    def test_custom_template(self):
        custom = PlanTemplate(
            name="custom-download",
            keywords=["download", "export", "save file"],
            steps=[
                ActionStep(action_type=ActionType.CLICK, description="download button", intent="download"),
                ActionStep(action_type=ActionType.WAIT, description="download complete", intent="wait"),
            ],
            required_affordances=["clickable"],
        )
        translator = GoalTranslator([custom])
        graph = _make_graph_with_intent_nodes("clickable")
        result = translator.translate("download the report", graph)
        assert result.template_name == "custom-download"
        assert len(result.plan.steps) == 2

    def test_add_template(self):
        translator = GoalTranslator()
        original_count = len(translator.templates)
        translator.add_template(PlanTemplate(
            name="custom-test",
            keywords=["frobnicate"],
            steps=[],
        ))
        assert len(translator.templates) == original_count + 1

    def test_remove_template(self):
        translator = GoalTranslator()
        assert translator.remove_template("login") is True
        assert "login" not in translator.list_templates()

    def test_remove_nonexistent_template(self):
        translator = GoalTranslator()
        assert translator.remove_template("nonexistent") is False

    def test_list_templates(self):
        translator = GoalTranslator()
        names = translator.list_templates()
        assert "login" in names
        assert "search" in names
        assert "navigate" in names
        assert "fill-form" in names
        assert "click-confirm" in names
        assert "register" in names
        assert "logout" in names
        assert "select" in names
        assert "toggle" in names
        assert "download" in names
        assert len(names) == 10

    def test_empty_custom_templates_fallback(self):
        translator = GoalTranslator([])
        graph = _make_empty_graph()
        result = translator.translate("login", graph)
        assert result.template_name is None  # no templates → fallback


# ---------------------------------------------------------------------------
# Test: GoalTranslator — edge cases
# ---------------------------------------------------------------------------

class TestGoalTranslatorEdgeCases:

    def test_only_stop_words_fallback(self):
        graph = _make_empty_graph()
        translator = GoalTranslator()
        result = translator.translate("the a an is it", graph)
        assert result.template_name is None

    def test_plan_id_generated(self):
        graph = _make_graph_with_intent_nodes("clickable")
        translator = GoalTranslator()
        result = translator.translate("click the button", graph)
        assert result.plan.plan_id.startswith("plan-")

    def test_steps_are_copies_not_references(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result1 = translator.translate("login", graph)
        result2 = translator.translate("login", graph)
        # Different plan instances
        assert result1.plan is not result2.plan
        assert result1.plan.steps is not result2.plan.steps

    def test_default_templates_count(self):
        templates = _default_templates()
        assert len(templates) == 10

    def test_result_serialization_round_trip(self):
        graph = _make_graph_with_intent_nodes("clickable", "fillable")
        translator = GoalTranslator()
        result = translator.translate("login", graph)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "plan" in d
        assert "template_name" in d
        assert "confidence" in d
        assert "graph_validation" in d
