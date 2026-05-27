"""Tests for WNAL typed action schema and verifier contracts."""

import unittest
from datetime import datetime

from netweaver.wnal import (
    ActionType,
    ActionabilityEvidence,
    ActionPreconditions,
    ClickAction,
    FillAction,
    WaitAction,
    TypedAction,
    Phase,
    VerificationResult,
    get_preconditions,
    CLICK_PRECONDITIONS,
    FILL_PRECONDITIONS,
    WAIT_PRECONDITIONS,
)


class TestActionabilityEvidence(unittest.TestCase):
    """Test ActionabilityEvidence envelope."""
    
    def test_create_evidence(self):
        """Test creating evidence with all fields."""
        now = datetime.now()
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#submit-btn",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=now,
        )
        
        self.assertEqual(evidence.action_id, "act-001")
        self.assertEqual(evidence.target_ref, "#submit-btn")
        self.assertEqual(evidence.phase, Phase.PRE)
        self.assertTrue(evidence.attached)
        self.assertTrue(evidence.visible)
        self.assertTrue(evidence.enabled)
        self.assertFalse(evidence.editable)
        self.assertTrue(evidence.stable)
        self.assertTrue(evidence.pointer_events)
        self.assertEqual(evidence.observed_at, now)
    
    def test_to_dict(self):
        """Test serialization to dict."""
        now = datetime(2026, 5, 23, 12, 0, 0)
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#submit-btn",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=now,
        )
        
        data = evidence.to_dict()
        
        self.assertEqual(data["action_id"], "act-001")
        self.assertEqual(data["target_ref"], "#submit-btn")
        self.assertEqual(data["phase"], "pre")
        self.assertTrue(data["attached"])
        self.assertTrue(data["visible"])
        self.assertTrue(data["enabled"])
        self.assertFalse(data["editable"])
        self.assertTrue(data["stable"])
        self.assertTrue(data["pointer_events"])
        self.assertEqual(data["observed_at"], "2026-05-23T12:00:00")
    
    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "action_id": "act-001",
            "target_ref": "#submit-btn",
            "phase": "post",
            "attached": True,
            "visible": True,
            "enabled": False,
            "editable": False,
            "stable": True,
            "pointer_events": True,
            "observed_at": "2026-05-23T12:00:00",
        }
        
        evidence = ActionabilityEvidence.from_dict(data)
        
        self.assertEqual(evidence.action_id, "act-001")
        self.assertEqual(evidence.target_ref, "#submit-btn")
        self.assertEqual(evidence.phase, Phase.POST)
        self.assertTrue(evidence.attached)
        self.assertTrue(evidence.visible)
        self.assertFalse(evidence.enabled)
        self.assertFalse(evidence.editable)
        self.assertTrue(evidence.stable)
        self.assertTrue(evidence.pointer_events)

    def test_serialization_round_trip(self):
        """Test full round-trip serialization."""
        now = datetime(2026, 5, 23, 14, 30, 0)
        original = ActionabilityEvidence(
            action_id="act-round",
            target_ref="#elem",
            phase=Phase.PRE,
            attached=True,
            visible=False,
            enabled=True,
            editable=True,
            stable=False,
            pointer_events=True,
            observed_at=now,
        )
        
        data = original.to_dict()
        restored = ActionabilityEvidence.from_dict(data)
        
        self.assertEqual(restored.action_id, original.action_id)
        self.assertEqual(restored.target_ref, original.target_ref)
        self.assertEqual(restored.phase, original.phase)
        self.assertEqual(restored.attached, original.attached)
        self.assertEqual(restored.visible, original.visible)
        self.assertEqual(restored.enabled, original.enabled)
        self.assertEqual(restored.editable, original.editable)
        self.assertEqual(restored.stable, original.stable)
        self.assertEqual(restored.pointer_events, original.pointer_events)


class TestActionPreconditions(unittest.TestCase):
    """Test ActionPreconditions validation."""
    
    def test_validate_all_satisfied(self):
        """Test validation when all preconditions are satisfied."""
        preconditions = ActionPreconditions(
            required_fields={"attached", "visible", "enabled"}
        )
        
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#btn",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        
        self.assertTrue(preconditions.validate(evidence))
        self.assertEqual(preconditions.missing_preconditions(evidence), [])
    
    def test_validate_missing_precondition(self):
        """Test validation when a precondition is not satisfied."""
        preconditions = ActionPreconditions(
            required_fields={"attached", "visible", "enabled"}
        )
        
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#btn",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=False,  # Not satisfied
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        
        self.assertFalse(preconditions.validate(evidence))
        self.assertEqual(preconditions.missing_preconditions(evidence), ["enabled"])
    
    def test_validate_multiple_missing(self):
        """Test validation with multiple missing preconditions."""
        preconditions = ActionPreconditions(
            required_fields={"attached", "visible", "enabled", "stable"}
        )
        
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#btn",
            phase=Phase.PRE,
            attached=True,
            visible=False,  # Not satisfied
            enabled=False,  # Not satisfied
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        
        self.assertFalse(preconditions.validate(evidence))
        missing = preconditions.missing_preconditions(evidence)
        self.assertIn("visible", missing)
        self.assertIn("enabled", missing)
        self.assertEqual(len(missing), 2)


class TestPreconditionMappings(unittest.TestCase):
    """Test precondition mappings for each action type."""
    
    def test_click_preconditions(self):
        """Test CLICK requires attached, visible, enabled, stable, pointer_events."""
        required = CLICK_PRECONDITIONS.required_fields
        self.assertEqual(required, {"attached", "visible", "enabled", "stable", "pointer_events"})
    
    def test_fill_preconditions(self):
        """Test FILL requires all CLICK fields plus editable."""
        required = FILL_PRECONDITIONS.required_fields
        self.assertEqual(
            required,
            {"attached", "visible", "enabled", "editable", "stable", "pointer_events"}
        )
    
    def test_wait_preconditions(self):
        """Test WAIT only requires attached."""
        required = WAIT_PRECONDITIONS.required_fields
        self.assertEqual(required, {"attached"})
    
    def test_get_preconditions(self):
        """Test get_preconditions returns correct mapping."""
        self.assertEqual(get_preconditions(ActionType.CLICK), CLICK_PRECONDITIONS)
        self.assertEqual(get_preconditions(ActionType.FILL), FILL_PRECONDITIONS)
        self.assertEqual(get_preconditions(ActionType.WAIT), WAIT_PRECONDITIONS)


class TestTypedAction(unittest.TestCase):
    """Test TypedAction base class."""
    
    def test_create_typed_action(self):
        """Test creating a typed action."""
        action = TypedAction(
            action_id="act-001",
            action_type=ActionType.CLICK,
            target_ref="#submit-btn",
            parameters={"button": "left"}
        )
        
        self.assertEqual(action.action_id, "act-001")
        self.assertEqual(action.action_type, ActionType.CLICK)
        self.assertEqual(action.target_ref, "#submit-btn")
        self.assertEqual(action.parameters, {"button": "left"})
    
    def test_get_preconditions(self):
        """Test getting preconditions for an action."""
        action = TypedAction(
            action_id="act-001",
            action_type=ActionType.FILL,
            target_ref="#email",
        )
        
        preconditions = action.get_preconditions()
        self.assertEqual(preconditions, FILL_PRECONDITIONS)
    
    def test_validate_preconditions_success(self):
        """Test successful precondition validation."""
        action = TypedAction(
            action_id="act-001",
            action_type=ActionType.CLICK,
            target_ref="#btn",
        )
        
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#btn",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        
        self.assertTrue(action.validate_preconditions(evidence))
        self.assertEqual(action.missing_preconditions(evidence), [])
    
    def test_validate_preconditions_failure(self):
        """Test failed precondition validation."""
        action = TypedAction(
            action_id="act-001",
            action_type=ActionType.CLICK,
            target_ref="#btn",
        )
        
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#btn",
            phase=Phase.PRE,
            attached=True,
            visible=False,  # Missing
            enabled=True,
            editable=False,
            stable=False,  # Missing
            pointer_events=True,
            observed_at=datetime.now(),
        )
        
        self.assertFalse(action.validate_preconditions(evidence))
        missing = action.missing_preconditions(evidence)
        self.assertIn("visible", missing)
        self.assertIn("stable", missing)
    
    def test_validate_action_id_mismatch(self):
        """Test validation raises on action_id mismatch."""
        action = TypedAction(
            action_id="act-001",
            action_type=ActionType.CLICK,
            target_ref="#btn",
        )
        
        evidence = ActionabilityEvidence(
            action_id="act-002",  # Mismatch
            target_ref="#btn",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        
        with self.assertRaises(ValueError) as ctx:
            action.validate_preconditions(evidence)
        self.assertIn("action_id mismatch", str(ctx.exception))
    
    def test_validate_target_ref_mismatch(self):
        """Test validation raises on target_ref mismatch."""
        action = TypedAction(
            action_id="act-001",
            action_type=ActionType.CLICK,
            target_ref="#btn1",
        )
        
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#btn2",  # Mismatch
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        
        with self.assertRaises(ValueError) as ctx:
            action.validate_preconditions(evidence)
        self.assertIn("target_ref mismatch", str(ctx.exception))
    
    def test_validate_wrong_phase(self):
        """Test validation raises on POST phase evidence."""
        action = TypedAction(
            action_id="act-001",
            action_type=ActionType.CLICK,
            target_ref="#btn",
        )
        
        evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="#btn",
            phase=Phase.POST,  # Wrong phase
            attached=True,
            visible=True,
            enabled=True,
            editable=False,
            stable=True,
            pointer_events=True,
            observed_at=datetime.now(),
        )
        
        with self.assertRaises(ValueError) as ctx:
            action.validate_preconditions(evidence)
        self.assertIn("PRE phase evidence", str(ctx.exception))
    
    def test_to_dict(self):
        """Test serialization to dict."""
        action = TypedAction(
            action_id="act-001",
            action_type=ActionType.FILL,
            target_ref="#email",
            parameters={"text": "test@example.com"}
        )
        
        data = action.to_dict()
        
        self.assertEqual(data["action_id"], "act-001")
        self.assertEqual(data["action_type"], "fill")
        self.assertEqual(data["target_ref"], "#email")
        self.assertEqual(data["parameters"], {"text": "test@example.com"})
    
    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "action_id": "act-001",
            "action_type": "wait",
            "target_ref": "#loading",
            "parameters": {"timeout_ms": 3000}
        }
        
        action = TypedAction.from_dict(data)
        
        self.assertEqual(action.action_id, "act-001")
        self.assertEqual(action.action_type, ActionType.WAIT)
        self.assertEqual(action.target_ref, "#loading")
        self.assertEqual(action.parameters, {"timeout_ms": 3000})

    def test_serialization_round_trip(self):
        """Test action round-trip serialization."""
        original = TypedAction(
            action_id="act-rt",
            action_type=ActionType.CLICK,
            target_ref="#btn",
            parameters={"button": "right"}
        )
        
        data = original.to_dict()
        restored = TypedAction.from_dict(data)
        
        self.assertEqual(restored.action_id, original.action_id)
        self.assertEqual(restored.action_type, original.action_type)
        self.assertEqual(restored.target_ref, original.target_ref)
        self.assertEqual(restored.parameters, original.parameters)


class TestClickAction(unittest.TestCase):
    """Test ClickAction specialized class."""
    
    def test_create_click_action(self):
        """Test creating a click action."""
        action = ClickAction(action_id="act-001", target_ref="#submit-btn")
        
        self.assertEqual(action.action_id, "act-001")
        self.assertEqual(action.action_type, ActionType.CLICK)
        self.assertEqual(action.target_ref, "#submit-btn")
        self.assertEqual(action.parameters, {"button": "left"})
    
    def test_create_click_action_with_button(self):
        """Test creating a click action with custom button."""
        action = ClickAction(action_id="act-001", target_ref="#menu", button="right")
        
        self.assertEqual(action.parameters, {"button": "right"})
    
    def test_click_preconditions(self):
        """Test click action uses correct preconditions."""
        action = ClickAction(action_id="act-001", target_ref="#btn")
        preconditions = action.get_preconditions()
        
        self.assertEqual(preconditions.required_fields, {
            "attached", "visible", "enabled", "stable", "pointer_events"
        })


class TestFillAction(unittest.TestCase):
    """Test FillAction specialized class."""
    
    def test_create_fill_action(self):
        """Test creating a fill action."""
        action = FillAction(
            action_id="act-002",
            target_ref="#email-input",
            text="user@example.com"
        )
        
        self.assertEqual(action.action_id, "act-002")
        self.assertEqual(action.action_type, ActionType.FILL)
        self.assertEqual(action.target_ref, "#email-input")
        self.assertEqual(action.parameters, {"text": "user@example.com"})
    
    def test_fill_preconditions(self):
        """Test fill action uses correct preconditions."""
        action = FillAction(action_id="act-002", target_ref="#input", text="test")
        preconditions = action.get_preconditions()
        
        self.assertEqual(preconditions.required_fields, {
            "attached", "visible", "enabled", "editable", "stable", "pointer_events"
        })


class TestWaitAction(unittest.TestCase):
    """Test WaitAction specialized class."""
    
    def test_create_wait_action(self):
        """Test creating a wait action with defaults."""
        action = WaitAction(action_id="act-003", target_ref="#loading-spinner")
        
        self.assertEqual(action.action_id, "act-003")
        self.assertEqual(action.action_type, ActionType.WAIT)
        self.assertEqual(action.target_ref, "#loading-spinner")
        self.assertEqual(action.parameters, {"condition": "attached", "timeout_ms": 5000})
    
    def test_create_wait_action_custom(self):
        """Test creating a wait action with custom parameters."""
        action = WaitAction(
            action_id="act-003",
            target_ref="#result",
            condition="visible",
            timeout_ms=10000
        )
        
        self.assertEqual(action.parameters, {"condition": "visible", "timeout_ms": 10000})
    
    def test_wait_preconditions(self):
        """Test wait action uses correct preconditions."""
        action = WaitAction(action_id="act-003", target_ref="#elem")
        preconditions = action.get_preconditions()
        
        self.assertEqual(preconditions.required_fields, {"attached"})


class TestVerificationResult(unittest.TestCase):
    """Test VerificationResult."""
    
    def test_create_success_result(self):
        """Test creating a successful verification result."""
        result = VerificationResult(
            action_id="act-001",
            passed=True,
        )
        
        self.assertEqual(result.action_id, "act-001")
        self.assertTrue(result.passed)
        self.assertEqual(result.missing_conditions, [])
        self.assertIsNone(result.error)
    
    def test_create_failure_result(self):
        """Test creating a failed verification result."""
        result = VerificationResult(
            action_id="act-001",
            passed=False,
            missing_conditions=["visible", "enabled"],
            error="Element not interactable",
        )
        
        self.assertEqual(result.action_id, "act-001")
        self.assertFalse(result.passed)
        self.assertEqual(result.missing_conditions, ["visible", "enabled"])
        self.assertEqual(result.error, "Element not interactable")
    
    def test_result_serialization(self):
        """Test VerificationResult serialization."""
        result = VerificationResult(
            action_id="act-001",
            passed=False,
            missing_conditions=["stable"],
            error="Element not stable",
        )
        
        data = result.to_dict()
        
        self.assertEqual(data["action_id"], "act-001")
        self.assertFalse(data["passed"])
        self.assertEqual(data["missing_conditions"], ["stable"])
        self.assertEqual(data["error"], "Element not stable")


if __name__ == "__main__":
    unittest.main()
