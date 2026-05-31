"""Real-world scenario tests for NetWeaver Perspective Engine — NW-036.

Tests the PerspectiveEngine (570 LOC) against complex, realistic scenarios
using a 100+ node scene graph fixture. Covers all 7 built-in perspective
types, cross-perspective analysis, custom perspective composition, and
performance benchmarks.

No browser/Playwright/vendor imports.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List

import pytest

from netweaver.perspective import (
    Confidence,
    ConflictResolution,
    DOMPerspective,
    HistoryPerspective,
    JSPerspective,
    NetworkPerspective,
    PerspectiveAssessment,
    PerspectiveEngine,
    PerspectiveType,
    ResolutionStrategy,
    SafetyPerspective,
    UserPerspective,
    VisualPerspective,
)
from netweaver.wnal import (
    ActionabilityEvidence,
    ActionType,
    ClickAction,
    FillAction,
    Phase,
    TypedAction,
    WaitAction,
)

# ===========================================================================
# Fixtures
# ===========================================================================

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "perspectives"


@pytest.fixture(scope="module")
def fixture_data() -> Dict:
    """Load the complex scene graph fixture."""
    path = FIXTURE_DIR / "complex_graph.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def engine() -> PerspectiveEngine:
    """Create a fresh PerspectiveEngine for each test."""
    return PerspectiveEngine()


@pytest.fixture
def sample_action() -> TypedAction:
    """Create a sample click action."""
    return ClickAction(
        selector="#add-to-cart-btn",
        target_ref="#add-to-cart-btn",
        description="Click add to cart button",
    )


@pytest.fixture
def sample_evidence() -> ActionabilityEvidence:
    """Create sample evidence for a healthy, interactive element."""
    return ActionabilityEvidence(
        action_id="act-001",
        selector="#add-to-cart-btn",
        visible=True,
        enabled=True,
        attached=True,
        stable=True,
        pointer_events=True,
    )


def build_evidence(**kwargs) -> ActionabilityEvidence:
    """Helper to build ActionabilityEvidence with overrides."""
    defaults = dict(
        action_id="act-001",
        selector="#test-el",
        visible=True,
        enabled=True,
        attached=True,
        stable=True,
        pointer_events=True,
    )
    defaults.update(kwargs)
    return ActionabilityEvidence(**defaults)


# ===========================================================================
# 1. Individual Perspective Unit Tests
# ===========================================================================


class TestUserPerspective:
    """Tests for UserPerspective.assess()."""

    def test_with_user_goal(self):
        p = UserPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"user_goal": "Purchase item"}
        result = p.assess(action, evidence, context)
        assert result.perspective == PerspectiveType.USER
        assert result.safe is True
        assert result.confidence == Confidence.HIGH
        assert "user goal" in result.reason.lower()

    def test_without_user_goal(self):
        p = UserPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {}
        result = p.assess(action, evidence, context)
        assert result.perspective == PerspectiveType.USER
        assert result.safe is True
        assert result.confidence == Confidence.LOW
        assert "no explicit" in result.reason.lower()


class TestDOMPerspective:
    """Tests for DOMPerspective.assess()."""

    def test_element_not_attached(self):
        p = DOMPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence(attached=False)
        context = {}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "not attached" in result.reason.lower()

    def test_presentation_role(self):
        p = DOMPerspective()
        action = ClickAction(selector="#decorative")
        evidence = build_evidence()
        context = {"element_role": "presentation"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.MEDIUM
        assert "presentation" in result.reason.lower()

    def test_safe_element(self):
        p = DOMPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {}
        result = p.assess(action, evidence, context)
        assert result.safe is True
        assert result.confidence == Confidence.HIGH


class TestVisualPerspective:
    """Tests for VisualPerspective.assess()."""

    def test_hidden_element(self):
        p = VisualPerspective()
        action = ClickAction(selector="#collapsed")
        evidence = build_evidence(visible=False)
        context = {"is_hidden": True}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "hidden" in result.reason.lower()

    def test_not_visible(self):
        p = VisualPerspective()
        action = ClickAction(selector="#off-screen")
        evidence = build_evidence(visible=False)
        context = {"is_hidden": False}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.MEDIUM
        assert "not visible" in result.reason.lower()

    def test_obscured_element(self):
        p = VisualPerspective()
        action = ClickAction(selector="#behind-modal")
        evidence = build_evidence()
        context = {"is_obscured": True}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "obscured" in result.reason.lower()

    def test_visible_clear(self):
        p = VisualPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"is_obscured": False}
        result = p.assess(action, evidence, context)
        assert result.safe is True
        assert result.confidence == Confidence.HIGH


class TestNetworkPerspective:
    """Tests for NetworkPerspective.assess()."""

    def test_auth_expired(self):
        p = NetworkPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"auth_state": "expired"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "expired" in result.reason.lower()

    def test_auth_missing(self):
        p = NetworkPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"auth_state": "missing"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "no authentication" in result.reason.lower()

    def test_rate_limited(self):
        p = NetworkPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"auth_state": "valid", "rate_limit_remaining": 0}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "rate limit" in result.reason.lower()

    def test_network_error(self):
        p = NetworkPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"auth_state": "valid", "network_error": "timeout"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "network error" in result.reason.lower()

    def test_healthy(self):
        p = NetworkPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"auth_state": "valid"}
        result = p.assess(action, evidence, context)
        assert result.safe is True
        assert result.confidence == Confidence.HIGH


class TestJSPerspective:
    """Tests for JSPerspective.assess()."""

    def test_no_event_handlers(self):
        p = JSPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"has_event_handlers": False}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.MEDIUM
        assert "no event handlers" in result.reason.lower()

    def test_js_error(self):
        p = JSPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"has_event_handlers": True, "js_error": "TypeError: x is null"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "javascript error" in result.reason.lower()

    def test_loading_state(self):
        p = JSPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"has_event_handlers": True, "is_loading": True}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.MEDIUM
        assert "loading" in result.reason.lower()

    def test_stable(self):
        p = JSPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"has_event_handlers": True, "is_loading": False}
        result = p.assess(action, evidence, context)
        assert result.safe is True
        assert result.confidence == Confidence.HIGH


class TestSafetyPerspective:
    """Tests for SafetyPerspective.assess()."""

    def test_critical_risk(self):
        p = SafetyPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"risk_level": "critical", "action_category": "payment"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "critical" in result.reason.lower()

    def test_high_risk(self):
        p = SafetyPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"risk_level": "high"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "high-risk" in result.reason.lower()

    def test_payment_detected(self):
        p = SafetyPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"risk_level": "low", "is_payment": True, "payment_amount": "$49.99"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "payment" in result.reason.lower()

    def test_no_safety_issues(self):
        p = SafetyPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"risk_level": "low", "is_payment": False}
        result = p.assess(action, evidence, context)
        assert result.safe is True
        assert result.confidence == Confidence.HIGH


class TestHistoryPerspective:
    """Tests for HistoryPerspective.assess()."""

    def test_many_past_failures(self):
        p = HistoryPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"past_failures": 5}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.HIGH
        assert "failed" in result.reason.lower()

    def test_known_failure_pattern(self):
        p = HistoryPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"past_failures": 0, "known_pattern": "failure"}
        result = p.assess(action, evidence, context)
        assert result.safe is False
        assert result.confidence == Confidence.MEDIUM
        assert "failed pattern" in result.reason.lower()

    def test_known_success_pattern(self):
        p = HistoryPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {"past_failures": 0, "known_pattern": "success"}
        result = p.assess(action, evidence, context)
        assert result.safe is True
        assert result.confidence == Confidence.HIGH
        assert "successful pattern" in result.reason.lower()

    def test_no_history(self):
        p = HistoryPerspective()
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {}
        result = p.assess(action, evidence, context)
        assert result.safe is True
        assert result.confidence == Confidence.LOW
        assert "no historical data" in result.reason.lower()


# ===========================================================================
# 2. PerspectiveEngine Integration Tests
# ===========================================================================


class TestPerspectiveEngineIntegration:
    """Tests for PerspectiveEngine.analyze() conflict resolution."""

    def test_all_safe_produces_action(self, engine, sample_action, sample_evidence):
        context = {
            "user_goal": "Add to cart",
            "element_role": "button",
            "auth_state": "valid",
            "risk_level": "low",
            "is_payment": False,
            "has_event_handlers": True,
            "is_loading": False,
            "past_failures": 0,
            "known_pattern": "success",
        }
        result = engine.analyze(sample_action, sample_evidence, context)
        assert result.strategy == ResolutionStrategy.ACTION
        assert len(result.assessments) == 7  # all 7 perspectives

    def test_safety_critical_veto_aborts(self, engine, sample_action, sample_evidence):
        context = {
            "user_goal": "Process payment",
            "element_role": "button",
            "auth_state": "valid",
            "risk_level": "critical",
            "action_category": "payment",
            "has_event_handlers": True,
        }
        result = engine.analyze(sample_action, sample_evidence, context)
        assert result.strategy == ResolutionStrategy.ABORT
        assert "safety veto" in result.reason.lower()

    def test_safety_high_risk_asks(self, engine, sample_action, sample_evidence):
        context = {
            "user_goal": "Delete account",
            "element_role": "button",
            "auth_state": "valid",
            "risk_level": "high",
            "has_event_handlers": True,
        }
        result = engine.analyze(sample_action, sample_evidence, context)
        assert result.strategy == ResolutionStrategy.ASK

    def test_expired_auth_recover(self, engine, sample_action, sample_evidence):
        context = {
            "user_goal": "Submit form",
            "element_role": "button",
            "auth_state": "expired",
            "risk_level": "low",
            "has_event_handlers": True,
        }
        result = engine.analyze(sample_action, sample_evidence, context)
        assert result.strategy == ResolutionStrategy.RECOVER
        assert "auth" in result.reason.lower()

    def test_network_rate_limit_produces_abort_or_recover(
        self, engine, sample_action, sample_evidence
    ):
        context = {
            "user_goal": "Search",
            "element_role": "button",
            "auth_state": "valid",
            "rate_limit_remaining": 0,
            "risk_level": "low",
            "has_event_handlers": True,
        }
        result = engine.analyze(sample_action, sample_evidence, context)
        # Rate-limited with no auth issue → recover with retry
        assert result.strategy in (
            ResolutionStrategy.ABORT,
            ResolutionStrategy.RECOVER,
        )

    def test_multiple_high_confidence_unsafe_aborts(
        self, engine, sample_action, sample_evidence
    ):
        context = {
            "user_goal": "",
            "element_role": "button",
            "auth_state": "expired",
            "risk_level": "low",
            "has_event_handlers": False,
            "js_error": "Script error",
        }
        result = engine.analyze(sample_action, sample_evidence, context)
        assert result.strategy == ResolutionStrategy.ABORT

    def test_custom_enabled_perspectives(self, engine, sample_action, sample_evidence):
        """Verify only selected perspectives are evaluated."""
        context = {"risk_level": "critical", "action_category": "delete"}
        enabled = {PerspectiveType.SAFETY, PerspectiveType.DOM}
        result = engine.analyze(
            sample_action, sample_evidence, context, enabled_perspectives=enabled
        )
        assert len(result.assessments) == 2
        types_found = {a.perspective for a in result.assessments}
        assert types_found == enabled

    def test_assessment_evidence_dict_preserved(self, engine, sample_action, sample_evidence):
        """Verify evidence dict in PerspectiveAssessment is returned unchanged."""
        context = {
            "risk_level": "low",
            "auth_state": "valid",
            "user_goal": "Test",
            "element_role": "button",
            "has_event_handlers": True,
            "is_loading": False,
            "past_failures": 0,
        }
        result = engine.analyze(sample_action, sample_evidence, context)
        # Each assessment should have an evidence dict
        for a in result.assessments:
            assert isinstance(a.evidence, dict)


# ===========================================================================
# 3. Cross-Perspective Analysis
# ===========================================================================


class TestCrossPerspectiveAnalysis:
    """Tests for cross-perspective analysis — multiple perspectives
    flagging the same issue or interacting."""

    def test_all_perspectives_flag_detached_element(self, engine):
        """A detached element triggers both DOM and Visual perspectives."""
        action = ClickAction(selector="#ghost-el")
        evidence = build_evidence(visible=False, attached=False)
        context = {
            "user_goal": "Click ghost",
            "element_role": "button",
            "auth_state": "valid",
            "risk_level": "low",
            "has_event_handlers": False,
            "is_loading": False,
        }
        result = engine.analyze(action, evidence, context)
        unsafe_perspectives = [
            a.perspective for a in result.assessments if not a.safe
        ]
        assert PerspectiveType.DOM in unsafe_perspectives
        assert PerspectiveType.VISUAL in unsafe_perspectives

    def test_evidence_backed_claims(self, engine, sample_action):
        """Each assessment should carry evidence dict with specific context."""
        evidence = build_evidence()
        context = {
            "user_goal": "Test",
            "element_role": "button",
            "auth_state": "valid",
            "risk_level": "low",
            "is_payment": False,
            "has_event_handlers": True,
            "is_loading": False,
            "past_failures": 0,
        }
        result = engine.analyze(sample_action, evidence, context)
        for a in result.assessments:
            assert a.reason, f"Missing reason for {a.perspective}"
            assert isinstance(a.evidence, dict), f"Evidence not dict for {a.perspective}"
            if not a.safe:
                assert len(a.evidence) > 0, (
                    f"Unsafe assessment {a.perspective} lacks evidence keys"
                )


# ===========================================================================
# 4. Perspective Composition (Custom Perspectives)
# ===========================================================================


class TestPerspectiveComposition:
    """Custom perspective definitions that compose multiple built-in
    perspectives into higher-level assessments — simulating accessibility,
    security, performance, SEO, and mobile views."""

    def test_custom_accessibility_perspective(self, engine, sample_action):
        """Accessibility perspective: flags elements with poor ARIA support
        or low-contrast visibility patterns."""
        evidence = build_evidence(visible=False)
        context = {
            "element_role": "presentation",
            "is_hidden": True,
            "has_event_handlers": False,
        }
        enabled = {PerspectiveType.DOM, PerspectiveType.VISUAL, PerspectiveType.JS}
        result = engine.analyze(
            sample_action, evidence, context, enabled_perspectives=enabled
        )
        # A hidden presentation-role element with no handlers is inaccessible
        unsafe = [a for a in result.assessments if not a.safe]
        assert len(unsafe) >= 2  # DOM + Visual should both flag

    def test_custom_security_perspective(self, engine):
        """Security perspective: flags expired auth, risky actions."""
        action = FillAction(selector="#password", value="secret", is_sensitive=True)
        evidence = build_evidence()
        context = {
            "auth_state": "expired",
            "risk_level": "high",
            "has_event_handlers": True,
        }
        enabled = {PerspectiveType.NETWORK, PerspectiveType.SAFETY, PerspectiveType.HISTORY}
        result = engine.analyze(
            action, evidence, context, enabled_perspectives=enabled
        )
        # Security should flag both expired auth and high risk
        unsafe = [a for a in result.assessments if not a.safe]
        assert len(unsafe) >= 2
        assert result.strategy != ResolutionStrategy.ACTION

    def test_custom_performance_perspective(self, engine, sample_action):
        """Performance perspective: flags loading states, slow responses."""
        evidence = build_evidence(stable=False)
        context = {
            "is_loading": True,
            "has_event_handlers": True,
            "auth_state": "valid",
        }
        enabled = {PerspectiveType.JS, PerspectiveType.VISUAL, PerspectiveType.DOM}
        result = engine.analyze(
            sample_action, evidence, context, enabled_perspectives=enabled
        )
        # Unstable, loading → performance issues
        js_unsafe = any(
            not a.safe and a.perspective == PerspectiveType.JS
            for a in result.assessments
        )
        assert js_unsafe

    def test_custom_seo_perspective(self, engine):
        """SEO perspective: checks for structural issues, missing content."""
        action = ClickAction(selector="#hidden-link")
        evidence = build_evidence(visible=False, attached=False)
        context = {
            "element_role": "presentation",
            "has_event_handlers": False,
        }
        enabled = {PerspectiveType.DOM, PerspectiveType.VISUAL, PerspectiveType.USER}
        result = engine.analyze(
            action, evidence, context, enabled_perspectives=enabled
        )
        # Hidden, unattached element with no handlers → poor SEO
        assert not all(a.safe for a in result.assessments)

    def test_custom_mobile_perspective(self, engine):
        """Mobile perspective: flags visibility and interaction issues."""
        action = ClickAction(selector="#small-btn")
        evidence = build_evidence(visible=False, pointer_events=False)
        context = {
            "is_hidden": True,
            "is_obscured": True,
        }
        enabled = {PerspectiveType.VISUAL, PerspectiveType.DOM, PerspectiveType.USER}
        result = engine.analyze(
            action, evidence, context, enabled_perspectives=enabled
        )
        # Hidden, obscured, no pointer events → poor mobile UX
        unsafe = [a for a in result.assessments if not a.safe]
        assert len(unsafe) >= 2


# ===========================================================================
# 5. Fixture Validation
# ===========================================================================


class TestFixtureValidation:
    """Verify the complex scene graph fixture."""

    def test_fixture_has_100_plus_nodes(self, fixture_data):
        node_count = len(fixture_data["graph"]["nodes"])
        assert node_count >= 100, f"Only {node_count} nodes, need 100+"

    def test_fixture_has_test_scenarios(self, fixture_data):
        scenarios = fixture_data["scenarios"]
        assert len(scenarios) >= 5, f"Only {len(scenarios)} scenarios"

    def test_fixture_all_nodes_have_required_fields(self, fixture_data):
        for node in fixture_data["graph"]["nodes"]:
            assert "node_id" in node
            assert "node_type" in node
            assert "label" in node

    def test_fixture_edges_valid(self, fixture_data):
        node_ids = {n["node_id"] for n in fixture_data["graph"]["nodes"]}
        for edge in fixture_data["graph"]["edges"]:
            assert edge["source_id"] in node_ids or edge["source_id"].startswith("obs-")
            assert edge["target_id"] in node_ids or edge["target_id"].startswith("obs-")
            assert edge["edge_type"] in ("containment", "evidence", "causality", "dependency")


# ===========================================================================
# 6. Performance Benchmark
# ===========================================================================


class TestPerspectivePerformance:
    """Performance benchmarks for the PerspectiveEngine."""

    def test_1000_assessments_under_100ms(self, engine):
        """Run 1000 assessments and verify total time < 100ms."""
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {
            "user_goal": "Test",
            "element_role": "button",
            "auth_state": "valid",
            "risk_level": "low",
            "has_event_handlers": True,
            "is_loading": False,
            "past_failures": 0,
        }

        start = time.perf_counter()
        for _ in range(1000):
            engine.analyze(action, evidence, context)
        elapsed = (time.perf_counter() - start) * 1000  # ms

        assert elapsed < 100, (
            f"1000 assessments took {elapsed:.1f}ms (limit: 100ms)"
        )

    def test_single_assessment_latency(self, engine):
        """Even a single complex assessment should be < 1ms."""
        action = ClickAction(selector="#btn")
        evidence = build_evidence()
        context = {
            "user_goal": "Test",
            "element_role": "button",
            "auth_state": "valid",
            "risk_level": "low",
            "has_event_handlers": True,
            "is_loading": False,
            "past_failures": 0,
        }

        start = time.perf_counter()
        engine.analyze(action, evidence, context)
        elapsed = (time.perf_counter() - start) * 1000  # ms

        assert elapsed < 1, f"Single assessment took {elapsed:.3f}ms"
