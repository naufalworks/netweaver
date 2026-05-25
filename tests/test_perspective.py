"""Tests for NetWeaver Perspective Engine."""

import unittest
from datetime import datetime

from netweaver.perspective import (
    PerspectiveEngine,
    PerspectiveType,
    ResolutionStrategy,
    Confidence,
    UserPerspective,
    DOMPerspective,
    VisualPerspective,
    NetworkPerspective,
    JSPerspective,
    SafetyPerspective,
    HistoryPerspective,
)
from netweaver.wnal import (
    ActionabilityEvidence,
    ClickAction,
    FillAction,
    Phase,
)


class TestUserPerspective(unittest.TestCase):
    """Test UserPerspective."""
    
    def test_assess_with_user_goal(self):
        """Test assessment when user goal is provided."""
        perspective = UserPerspective()
        action = ClickAction(action_id="act-001", target_ref="#submit")
        evidence = self._create_evidence()
        context = {"user_goal": "Submit the form"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertEqual(assessment.perspective, PerspectiveType.USER)
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("Submit the form", assessment.reason)
    
    def test_assess_without_user_goal(self):
        """Test assessment when no user goal is provided."""
        perspective = UserPerspective()
        action = ClickAction(action_id="act-001", target_ref="#submit")
        evidence = self._create_evidence()
        context = {}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.LOW)
    
    def _create_evidence(self):
        return ActionabilityEvidence(
            action_id="act-001",
            target_ref="#submit",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )


class TestDOMPerspective(unittest.TestCase):
    """Test DOMPerspective."""
    
    def test_assess_detached_element(self):
        """Test assessment when element is not attached."""
        perspective = DOMPerspective()
        action = ClickAction(action_id="act-001", target_ref="#submit")
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#submit",
            phase=Phase.PRE,
            attached=False,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        context = {}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("not attached", assessment.reason)
    
    def test_assess_presentation_role(self):
        """Test assessment when element has presentation role."""
        perspective = DOMPerspective()
        action = ClickAction(action_id="act-001", target_ref="#submit")
        evidence = self._create_evidence()
        context = {"element_role": "presentation"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.MEDIUM)
        self.assertIn("presentation role", assessment.reason)
    
    def test_assess_valid_element(self):
        """Test assessment when element is valid."""
        perspective = DOMPerspective()
        action = ClickAction(action_id="act-001", target_ref="#submit")
        evidence = self._create_evidence()
        context = {}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
    
    def _create_evidence(self):
        return ActionabilityEvidence(
            action_id="act-001",
            target_ref="#submit",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )


class TestVisualPerspective(unittest.TestCase):
    """Test VisualPerspective."""
    
    def test_assess_hidden_element(self):
        """Test assessment when element is hidden (acceptance criteria scenario)."""
        perspective = VisualPerspective()
        action = ClickAction(action_id="act-001", target_ref="#hidden-button")
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#hidden-button",
            phase=Phase.PRE,
            attached=True,
            visible=False,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        context = {"is_hidden": True}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("hidden", assessment.reason.lower())
        self.assertTrue(assessment.evidence["is_hidden"])
    
    def test_assess_obscured_element(self):
        """Test assessment when element is obscured."""
        perspective = VisualPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"is_obscured": True}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("obscured", assessment.reason)
    
    def test_assess_visible_element(self):
        """Test assessment when element is visible and not obscured."""
        perspective = VisualPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"is_obscured": False}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
    
    def _create_evidence(self):
        return ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )


class TestNetworkPerspective(unittest.TestCase):
    """Test NetworkPerspective."""
    
    def test_assess_expired_auth(self):
        """Test assessment when auth is expired (acceptance criteria scenario)."""
        perspective = NetworkPerspective()
        action = ClickAction(action_id="act-001", target_ref="#api-button")
        evidence = self._create_evidence()
        context = {"auth_state": "expired"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("expired", assessment.reason.lower())
        self.assertEqual(assessment.evidence["auth_state"], "expired")
    
    def test_assess_missing_auth(self):
        """Test assessment when auth is missing."""
        perspective = NetworkPerspective()
        action = ClickAction(action_id="act-001", target_ref="#api-button")
        evidence = self._create_evidence()
        context = {"auth_state": "missing"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertIn("authentication", assessment.reason.lower())
    
    def test_assess_rate_limit_exceeded(self):
        """Test assessment when rate limit is exceeded."""
        perspective = NetworkPerspective()
        action = ClickAction(action_id="act-001", target_ref="#api-button")
        evidence = self._create_evidence()
        context = {"rate_limit_remaining": 0}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertIn("rate limit", assessment.reason)
    
    def test_assess_network_error(self):
        """Test assessment when network error is present."""
        perspective = NetworkPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"network_error": "Connection timeout"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertIn("Connection timeout", assessment.reason)
    
    def test_assess_healthy_network(self):
        """Test assessment when network is healthy."""
        perspective = NetworkPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"auth_state": "valid"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
    
    def _create_evidence(self):
        return ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )


class TestJSPerspective(unittest.TestCase):
    """Test JSPerspective."""
    
    def test_assess_no_event_handlers(self):
        """Test assessment when element has no event handlers."""
        perspective = JSPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"has_event_handlers": False}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertIn("no event handlers", assessment.reason)
    
    def test_assess_js_error(self):
        """Test assessment when JS error is present."""
        perspective = JSPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"js_error": "TypeError: undefined is not a function"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertIn("TypeError", assessment.reason)
    
    def test_assess_loading_state(self):
        """Test assessment when element is loading."""
        perspective = JSPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"is_loading": True}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertIn("loading", assessment.reason)
    
    def test_assess_stable_js(self):
        """Test assessment when JS state is stable."""
        perspective = JSPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"has_event_handlers": True, "is_loading": False}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
    
    def _create_evidence(self):
        return ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )


class TestSafetyPerspective(unittest.TestCase):
    """Test SafetyPerspective."""
    
    def test_assess_payment_risk(self):
        """Test assessment for payment action (acceptance criteria scenario)."""
        perspective = SafetyPerspective()
        action = ClickAction(action_id="act-001", target_ref="#pay-button")
        evidence = self._create_evidence()
        context = {"is_payment": True, "payment_amount": "$99.99"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("payment", assessment.reason.lower())
        self.assertIn("$99.99", assessment.reason)
        self.assertTrue(assessment.evidence["is_payment"])
    
    def test_assess_critical_risk(self):
        """Test assessment for critical risk action."""
        perspective = SafetyPerspective()
        action = ClickAction(action_id="act-001", target_ref="#delete-all")
        evidence = self._create_evidence()
        context = {"risk_level": "critical", "action_category": "data_deletion"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("critical", assessment.reason.lower())
    
    def test_assess_high_risk(self):
        """Test assessment for high risk action."""
        perspective = SafetyPerspective()
        action = ClickAction(action_id="act-001", target_ref="#submit")
        evidence = self._create_evidence()
        context = {"risk_level": "high"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertIn("confirmation", assessment.reason.lower())
    
    def test_assess_low_risk(self):
        """Test assessment for low risk action."""
        perspective = SafetyPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"risk_level": "low"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
    
    def _create_evidence(self):
        return ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )


class TestHistoryPerspective(unittest.TestCase):
    """Test HistoryPerspective."""
    
    def test_assess_repeated_failures(self):
        """Test assessment when action has failed multiple times."""
        perspective = HistoryPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"past_failures": 3}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("3 times", assessment.reason)
    
    def test_assess_success_pattern(self):
        """Test assessment when action matches successful pattern."""
        perspective = HistoryPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"known_pattern": "success"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.HIGH)
        self.assertIn("successful pattern", assessment.reason)
    
    def test_assess_failure_pattern(self):
        """Test assessment when action matches failed pattern."""
        perspective = HistoryPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"known_pattern": "failure"}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertFalse(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.MEDIUM)
        self.assertIn("failed pattern", assessment.reason)
    
    def test_assess_no_history(self):
        """Test assessment when no history is available."""
        perspective = HistoryPerspective()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {}
        
        assessment = perspective.assess(action, evidence, context)
        
        self.assertTrue(assessment.safe)
        self.assertEqual(assessment.confidence, Confidence.LOW)
        self.assertIn("No historical data", assessment.reason)
    
    def _create_evidence(self):
        return ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )


class TestPerspectiveEngine(unittest.TestCase):
    """Test PerspectiveEngine integration."""
    
    def test_all_perspectives_safe(self):
        """Test resolution when all perspectives agree action is safe."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {
            "user_goal": "Click the button",
            "auth_state": "valid",
            "risk_level": "low",
            "is_obscured": False,
            "has_event_handlers": True,
            "is_loading": False,
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        self.assertEqual(resolution.strategy, ResolutionStrategy.ACTION)
        self.assertIn("All perspectives agree", resolution.reason)
        self.assertEqual(len(resolution.assessments), 7)
    
    def test_all_perspectives_unsafe_with_high_risk(self):
        """Test resolution when all perspectives are unsafe with high risk level.
        
        High-risk safety assessment triggers ASK (confirmation required) before
        general unsafe handling. This is correct: high risk means 'confirm with user',
        not 'refuse entirely'.
        """
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=False,
            visible=False,
            enabled=False,
            editable=False,
            stable=False,
            pointer_events=False,
            observed_at=datetime.now(),
        )
        context = {
            "auth_state": "expired",
            "risk_level": "high",
            "is_hidden": True,
            "js_error": "Error",
            "has_event_handlers": False,
            "past_failures": 3,
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        # Safety perspective high-risk triggers ASK before general unsafe handling
        self.assertEqual(resolution.strategy, ResolutionStrategy.ASK)
        self.assertIn("Confirmation required", resolution.reason)
    
    def test_all_perspectives_unsafe_critical_aborts(self):
        """Test that all-unsafe with critical risk still aborts."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=False,
            visible=False,
            enabled=False,
            editable=False,
            stable=False,
            pointer_events=False,
            observed_at=datetime.now(),
        )
        context = {
            "auth_state": "expired",
            "risk_level": "critical",
            "action_category": "data_deletion",
            "is_hidden": True,
            "js_error": "Error",
            "has_event_handlers": False,
            "past_failures": 3,
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        # Critical safety veto takes precedence
        self.assertEqual(resolution.strategy, ResolutionStrategy.ABORT)
        self.assertIn("Safety veto", resolution.reason)
    
    def test_all_perspectives_unsafe_no_safety_risk(self):
        """Test that mixed-unsafe with no safety risk aborts on non-recoverable issues.
        
        Safety returns safe=True (low risk), but DOM/Visual/Network/JS/History
        all return unsafe. The first high-confidence unsafe assessment is
        History (past failures), which is not network or visual → ABORT.
        """
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=False,
            visible=False,
            enabled=False,
            editable=False,
            stable=False,
            pointer_events=False,
            observed_at=datetime.now(),
        )
        context = {
            "auth_state": "missing",
            "risk_level": "low",
            "is_hidden": True,
            "js_error": "Error",
            "has_event_handlers": False,
            "past_failures": 3,
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        # History perspective (past failures) is primary concern → ABORT
        self.assertEqual(resolution.strategy, ResolutionStrategy.ABORT)
    
    def test_safety_veto_critical(self):
        """Test that critical safety risk vetoes all other perspectives."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#delete-all")
        evidence = self._create_evidence()
        context = {
            "user_goal": "Delete all data",
            "auth_state": "valid",
            "risk_level": "critical",
            "action_category": "data_deletion",
            "is_obscured": False,
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        self.assertEqual(resolution.strategy, ResolutionStrategy.ABORT)
        self.assertIn("Safety veto", resolution.reason)
    
    def test_high_risk_requires_confirmation(self):
        """Regression test: high-risk actions require ASK, not ABORT.
        
        Before fix, risk_level=="high" in SafetyPerspective returned safe=False
        but the conflict resolver only checked for "critical" risk and "payment"
        text, causing high-risk to fall through to general unsafe handling → ABORT.
        After fix, high-risk correctly produces ASK (user confirmation).
        """
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#confirm-btn")
        evidence = self._create_evidence()
        context = {
            "user_goal": "Confirm account change",
            "auth_state": "valid",
            "risk_level": "high",
            "is_obscured": False,
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        self.assertEqual(resolution.strategy, ResolutionStrategy.ASK)
        self.assertIn("Confirmation required", resolution.reason)
        # Verify safety perspective flagged the risk
        safety_assessment = next(
            (a for a in resolution.assessments if a.perspective == PerspectiveType.SAFETY),
            None
        )
        self.assertIsNotNone(safety_assessment)
        self.assertFalse(safety_assessment.safe)
        self.assertEqual(safety_assessment.evidence.get("risk_level"), "high")
    
    def test_high_risk_with_mixed_technical_issues(self):
        """Test that high-risk ASK fires even with some technical issues.
        
        When safety says high-risk and other perspectives have minor issues,
        the safety confirmation requirement should still trigger ASK.
        """
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#confirm-btn")
        evidence = self._create_evidence()
        context = {
            "user_goal": "Confirm action",
            "auth_state": "valid",
            "risk_level": "high",
            "is_obscured": False,
            "has_event_handlers": False,  # JS perspective flags this
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        # Safety high-risk ASK should take precedence over JS low-confidence concern
        self.assertEqual(resolution.strategy, ResolutionStrategy.ASK)
    
    def test_payment_requires_confirmation(self):
        """Test that payment actions require user confirmation (acceptance criteria)."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#pay-button")
        evidence = self._create_evidence()
        context = {
            "user_goal": "Complete purchase",
            "auth_state": "valid",
            "is_payment": True,
            "payment_amount": "$99.99",
            "is_obscured": False,
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        self.assertEqual(resolution.strategy, ResolutionStrategy.ASK)
        self.assertIn("payment", resolution.reason.lower())
        self.assertIn("confirmation", resolution.reason.lower())
    
    def test_hidden_button_scenario(self):
        """Test hidden button scenario (acceptance criteria)."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#hidden-button")
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#hidden-button",
            phase=Phase.PRE,
            attached=True,
            visible=False,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        context = {
            "user_goal": "Click the button",
            "is_hidden": True,
            "auth_state": "valid",
            "risk_level": "low",
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        # Should abort or recover due to visibility issue
        self.assertIn(resolution.strategy, [ResolutionStrategy.ABORT, ResolutionStrategy.RECOVER])
        
        # Check that visual perspective flagged the issue
        visual_assessment = next(
            (a for a in resolution.assessments if a.perspective == PerspectiveType.VISUAL),
            None
        )
        self.assertIsNotNone(visual_assessment)
        self.assertFalse(visual_assessment.safe)
    
    def test_expired_auth_scenario(self):
        """Test expired auth scenario (acceptance criteria)."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#api-button")
        evidence = self._create_evidence()
        context = {
            "user_goal": "Call API",
            "auth_state": "expired",
            "risk_level": "low",
            "is_obscured": False,
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        # Should suggest recovery (re-authentication)
        self.assertEqual(resolution.strategy, ResolutionStrategy.RECOVER)
        self.assertIn("expired", resolution.reason.lower())
        self.assertIsNotNone(resolution.suggested_action)
        self.assertIn("auth", resolution.suggested_action.lower())
    
    def test_network_recovery_suggestion(self):
        """Test that network issues suggest recovery."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {
            "auth_state": "expired",
            "risk_level": "low",
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        self.assertEqual(resolution.strategy, ResolutionStrategy.RECOVER)
        self.assertIsNotNone(resolution.suggested_action)
    
    def test_visual_recovery_suggestion(self):
        """Test that visual issues suggest recovery."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=True,
            visible=False,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        context = {
            "is_hidden": True,
            "auth_state": "valid",
            "risk_level": "low",
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        self.assertEqual(resolution.strategy, ResolutionStrategy.RECOVER)
        self.assertIn("wait_for_visibility", resolution.suggested_action)
    
    def test_mixed_assessments_ask(self):
        """Test that low-confidence conflicts result in ASK."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {
            "user_goal": "Click button",
            "auth_state": "valid",
            "risk_level": "low",
            "has_event_handlers": False,  # JS perspective will be unsafe
        }
        
        resolution = engine.analyze(action, evidence, context)
        
        # Should ask for clarification due to mixed signals
        self.assertEqual(resolution.strategy, ResolutionStrategy.ASK)
        self.assertIn("Conflicting", resolution.reason)
    
    def test_selective_perspectives(self):
        """Test analyzing with only selected perspectives."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"risk_level": "low"}
        
        # Only analyze safety and DOM perspectives
        enabled = {PerspectiveType.SAFETY, PerspectiveType.DOM}
        resolution = engine.analyze(action, evidence, context, enabled_perspectives=enabled)
        
        self.assertEqual(len(resolution.assessments), 2)
        perspectives = {a.perspective for a in resolution.assessments}
        self.assertEqual(perspectives, enabled)
    
    def test_resolution_serialization(self):
        """Test that resolution can be serialized to dict."""
        engine = PerspectiveEngine()
        action = ClickAction(action_id="act-001", target_ref="#button")
        evidence = self._create_evidence()
        context = {"risk_level": "low"}
        
        resolution = engine.analyze(action, evidence, context)
        data = resolution.to_dict()
        
        self.assertIn("strategy", data)
        self.assertIn("assessments", data)
        self.assertIn("reason", data)
        self.assertEqual(data["strategy"], resolution.strategy.value)
        self.assertEqual(len(data["assessments"]), len(resolution.assessments))
    
    def _create_evidence(self):
        return ActionabilityEvidence(
            action_id="act-001",
            target_ref="#button",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )


if __name__ == "__main__":
    unittest.main()
