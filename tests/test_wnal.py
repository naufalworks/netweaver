"""Tests for WNAL typed action schema and verifier contracts.

Validates:
- ActionabilityEvidence creation, serialization, round-trip
- ActionType/Phase enums
- Precondition maps for click/fill/wait
- ActionPreconditions validation
- VerificationResult pass/fail semantics
- TypedAction dataclasses (ClickAction, FillAction, WaitAction)
- action_from_dict deserialization
- Schema shape correctness
"""

import json
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
    action_from_dict,
    CLICK_PRECONDITIONS,
    FILL_PRECONDITIONS,
    WAIT_PRECONDITIONS,
    PRECONDITION_MAP,
)


class TestEnums(unittest.TestCase):
    """Test ActionType and Phase enums."""

    def test_action_types(self):
        self.assertEqual(ActionType.CLICK.value, "click")
        self.assertEqual(ActionType.FILL.value, "fill")
        self.assertEqual(ActionType.WAIT.value, "wait")

    def test_phases(self):
        self.assertEqual(Phase.PRE.value, "pre")
        self.assertEqual(Phase.POST.value, "post")

    def test_action_type_from_string(self):
        self.assertEqual(ActionType("click"), ActionType.CLICK)
        self.assertEqual(ActionType("fill"), ActionType.FILL)
        self.assertEqual(ActionType("wait"), ActionType.WAIT)


class TestActionabilityEvidence(unittest.TestCase):
    """Test ActionabilityEvidence envelope."""

    def test_create_evidence_with_defaults(self):
        evidence = ActionabilityEvidence(
            action_id="act-001",
            selector="#btn",
            phase=Phase.PRE,
        )
        self.assertEqual(evidence.action_id, "act-001")
        self.assertEqual(evidence.selector, "#btn")
        self.assertEqual(evidence.phase, Phase.PRE)
        self.assertTrue(evidence.visible)
        self.assertTrue(evidence.enabled)
        self.assertTrue(evidence.attached)
        self.assertTrue(evidence.stable)
        self.assertTrue(evidence.pointer_events)
        self.assertIsNone(evidence.editable)
        self.assertIsNotNone(evidence.timestamp)
        self.assertEqual(evidence.metadata, {})

    def test_create_evidence_with_all_fields(self):
        now = datetime.utcnow()
        evidence = ActionabilityEvidence(
            action_id="act-002",
            selector="input[name='email']",
            phase=Phase.POST,
            visible=False,
            enabled=True,
            attached=True,
            stable=True,
            pointer_events=True,
            editable=True,
            timestamp=now,
            metadata={"rect": {"x": 10, "y": 20}},
        )
        self.assertFalse(evidence.visible)
        self.assertTrue(evidence.editable)
        self.assertEqual(evidence.metadata["rect"]["x"], 10)

    def test_evidence_to_dict(self):
        evidence = ActionabilityEvidence(
            action_id="act-003",
            selector="button.submit",
            phase=Phase.PRE,
            visible=True,
            enabled=False,
        )
        d = evidence.to_dict()
        self.assertEqual(d["action_id"], "act-003")
        self.assertEqual(d["phase"], "pre")
        self.assertTrue(d["visible"])
        self.assertFalse(d["enabled"])
        self.assertIn("timestamp", d)

    def test_evidence_round_trip(self):
        original = ActionabilityEvidence(
            action_id="act-rt",
            selector="#round-trip",
            phase=Phase.POST,
            visible=True,
            enabled=True,
            editable=True,
            metadata={"tag": "input"},
        )
        serialized = original.to_dict()
        restored = ActionabilityEvidence.from_dict(serialized)
        self.assertEqual(restored.action_id, original.action_id)
        self.assertEqual(restored.selector, original.selector)
        self.assertEqual(restored.phase, original.phase)
        self.assertEqual(restored.visible, original.visible)
        self.assertEqual(restored.editable, original.editable)
        self.assertEqual(restored.metadata, original.metadata)

    def test_evidence_to_json(self):
        evidence = ActionabilityEvidence(
            action_id="act-json",
            selector="a.link",
            phase=Phase.PRE,
        )
        j = evidence.to_json()
        parsed = json.loads(j)
        self.assertEqual(parsed["action_id"], "act-json")
        self.assertEqual(parsed["selector"], "a.link")


class TestPreconditions(unittest.TestCase):
    """Test precondition maps and get_preconditions."""

    def test_click_preconditions(self):
        expected = {"visible", "enabled", "attached", "stable", "pointer_events"}
        self.assertEqual(CLICK_PRECONDITIONS, expected)

    def test_fill_preconditions(self):
        expected = {"visible", "enabled", "attached", "editable"}
        self.assertEqual(FILL_PRECONDITIONS, expected)

    def test_wait_preconditions(self):
        expected = {"attached"}
        self.assertEqual(WAIT_PRECONDITIONS, expected)

    def test_get_preconditions_click(self):
        preconds = get_preconditions(ActionType.CLICK)
        self.assertIn("visible", preconds)
        self.assertIn("enabled", preconds)
        self.assertIn("stable", preconds)

    def test_get_preconditions_fill(self):
        preconds = get_preconditions(ActionType.FILL)
        self.assertIn("editable", preconds)
        self.assertNotIn("stable", preconds)

    def test_get_preconditions_wait(self):
        preconds = get_preconditions(ActionType.WAIT)
        self.assertEqual(preconds, {"attached"})

    def test_precondition_map_complete(self):
        for atype in ActionType:
            self.assertIn(atype, PRECONDITION_MAP)
            self.assertTrue(len(PRECONDITION_MAP[atype]) > 0)


class TestActionPreconditions(unittest.TestCase):
    """Test ActionPreconditions validation."""

    def test_all_click_preconditions_met(self):
        evidence = ActionabilityEvidence(
            action_id="act-ok",
            selector="#btn",
            phase=Phase.PRE,
            visible=True,
            enabled=True,
            attached=True,
            stable=True,
            pointer_events=True,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        self.assertTrue(preconds.all_met)
        self.assertEqual(preconds.failed_checks(), [])

    def test_click_precondition_not_visible(self):
        evidence = ActionabilityEvidence(
            action_id="act-hidden",
            selector="#hidden-btn",
            phase=Phase.PRE,
            visible=False,
            enabled=True,
            attached=True,
            stable=True,
            pointer_events=True,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        self.assertFalse(preconds.all_met)
        self.assertIn("visible", preconds.failed_checks())

    def test_fill_missing_editable(self):
        evidence = ActionabilityEvidence(
            action_id="act-noedit",
            selector="div.notinput",
            phase=Phase.PRE,
            visible=True,
            enabled=True,
            attached=True,
            editable=None,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.FILL,
            evidence=evidence,
        )
        self.assertFalse(preconds.all_met)
        self.assertIn("editable", preconds.failed_checks())

    def test_fill_editable_false(self):
        evidence = ActionabilityEvidence(
            action_id="act-false",
            selector="span",
            phase=Phase.PRE,
            visible=True,
            enabled=True,
            attached=True,
            editable=False,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.FILL,
            evidence=evidence,
        )
        self.assertFalse(preconds.all_met)
        self.assertIn("editable", preconds.failed_checks())

    def test_wait_only_needs_attached(self):
        evidence = ActionabilityEvidence(
            action_id="act-wait",
            selector="#spinner",
            phase=Phase.PRE,
            visible=False,
            enabled=False,
            attached=True,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.WAIT,
            evidence=evidence,
        )
        self.assertTrue(preconds.all_met)

    def test_preconditions_to_dict(self):
        evidence = ActionabilityEvidence(
            action_id="act-dict",
            selector="#btn",
            phase=Phase.PRE,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        d = preconds.to_dict()
        self.assertEqual(d["action_type"], "click")
        self.assertIn("evidence", d)
        self.assertIn("checks", d)
        self.assertTrue(d["all_met"])

    def test_multiple_failures(self):
        evidence = ActionabilityEvidence(
            action_id="act-multi",
            selector="#broken",
            phase=Phase.PRE,
            visible=False,
            enabled=False,
            attached=False,
            stable=True,
            pointer_events=True,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        self.assertFalse(preconds.all_met)
        failed = preconds.failed_checks()
        self.assertIn("visible", failed)
        self.assertIn("enabled", failed)
        self.assertIn("attached", failed)


class TestVerificationResult(unittest.TestCase):
    """Test VerificationResult pass/fail semantics."""

    def test_passed_result(self):
        evidence = ActionabilityEvidence(
            action_id="act-pass",
            selector="#btn",
            phase=Phase.PRE,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        result = VerificationResult(
            action_id="act-pass",
            action_type=ActionType.CLICK,
            preconditions=preconds,
            passed=True,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.reason, "All preconditions met")

    def test_failed_result(self):
        evidence = ActionabilityEvidence(
            action_id="act-fail",
            selector="#btn",
            phase=Phase.PRE,
            visible=False,
            enabled=True,
            attached=True,
            stable=True,
            pointer_events=True,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        result = VerificationResult(
            action_id="act-fail",
            action_type=ActionType.CLICK,
            preconditions=preconds,
            passed=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("visible", result.reason)

    def test_custom_reason(self):
        evidence = ActionabilityEvidence(
            action_id="act-custom",
            selector="#btn",
            phase=Phase.PRE,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        result = VerificationResult(
            action_id="act-custom",
            action_type=ActionType.CLICK,
            preconditions=preconds,
            passed=False,
            reason="Element detached during check",
        )
        self.assertEqual(result.reason, "Element detached during check")

    def test_result_to_dict(self):
        evidence = ActionabilityEvidence(
            action_id="act-rd",
            selector="#btn",
            phase=Phase.PRE,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        result = VerificationResult(
            action_id="act-rd",
            action_type=ActionType.CLICK,
            preconditions=preconds,
            passed=True,
        )
        d = result.to_dict()
        self.assertEqual(d["action_id"], "act-rd")
        self.assertEqual(d["action_type"], "click")
        self.assertTrue(d["passed"])
        self.assertIn("preconditions", d)


class TestClickAction(unittest.TestCase):
    """Test ClickAction dataclass."""

    def test_create_click(self):
        action = ClickAction(selector="#submit-btn")
        self.assertEqual(action.action_type, ActionType.CLICK)
        self.assertEqual(action.selector, "#submit-btn")
        self.assertEqual(action.button, "left")
        self.assertEqual(action.click_count, 1)

    def test_click_with_options(self):
        action = ClickAction(
            selector="#ctx-menu",
            button="right",
            click_count=2,
            delay_ms=100,
            description="Double right-click context menu",
        )
        self.assertEqual(action.button, "right")
        self.assertEqual(action.click_count, 2)
        self.assertEqual(action.delay_ms, 100)

    def test_click_to_dict(self):
        action = ClickAction(selector="#btn", action_id="click-1")
        d = action.to_dict()
        self.assertEqual(d["action_type"], "click")
        self.assertEqual(d["selector"], "#btn")
        self.assertEqual(d["button"], "left")
        self.assertIn("click_count", d)
        self.assertIn("delay_ms", d)

    def test_click_to_json(self):
        action = ClickAction(selector="#btn")
        j = action.to_json()
        parsed = json.loads(j)
        self.assertEqual(parsed["action_type"], "click")

    def test_click_validate_preconditions_pass(self):
        action = ClickAction(selector="#btn", action_id="cv-1")
        evidence = ActionabilityEvidence(
            action_id="cv-1",
            selector="#btn",
            phase=Phase.PRE,
            visible=True,
            enabled=True,
            attached=True,
            stable=True,
            pointer_events=True,
        )
        result = action.validate_preconditions(evidence)
        self.assertTrue(result.passed)
        self.assertEqual(action.pre_evidence, evidence)
        self.assertIsNotNone(action.verification)

    def test_click_validate_preconditions_fail(self):
        action = ClickAction(selector="#disabled-btn", action_id="cv-2")
        evidence = ActionabilityEvidence(
            action_id="cv-2",
            selector="#disabled-btn",
            phase=Phase.PRE,
            visible=True,
            enabled=False,
            attached=True,
            stable=True,
            pointer_events=True,
        )
        result = action.validate_preconditions(evidence)
        self.assertFalse(result.passed)
        self.assertIn("enabled", result.reason)


class TestFillAction(unittest.TestCase):
    """Test FillAction dataclass."""

    def test_create_fill(self):
        action = FillAction(selector="input[name='email']", value="test@example.com")
        self.assertEqual(action.action_type, ActionType.FILL)
        self.assertEqual(action.value, "test@example.com")
        self.assertTrue(action.clear_first)

    def test_fill_with_options(self):
        action = FillAction(
            selector="#search",
            value="query",
            clear_first=False,
            press_enter=True,
        )
        self.assertFalse(action.clear_first)
        self.assertTrue(action.press_enter)

    def test_fill_to_dict(self):
        action = FillAction(selector="input", value="hello", action_id="fill-1")
        d = action.to_dict()
        self.assertEqual(d["action_type"], "fill")
        self.assertEqual(d["value"], "hello")
        self.assertIn("clear_first", d)
        self.assertIn("press_enter", d)

    def test_fill_validate_needs_editable(self):
        action = FillAction(selector="input", value="x", action_id="fv-1")
        evidence = ActionabilityEvidence(
            action_id="fv-1",
            selector="input",
            phase=Phase.PRE,
            visible=True,
            enabled=True,
            attached=True,
            editable=True,
        )
        result = action.validate_preconditions(evidence)
        self.assertTrue(result.passed)

    def test_fill_validate_not_editable(self):
        action = FillAction(selector="div", value="x", action_id="fv-2")
        evidence = ActionabilityEvidence(
            action_id="fv-2",
            selector="div",
            phase=Phase.PRE,
            visible=True,
            enabled=True,
            attached=True,
            editable=False,
        )
        result = action.validate_preconditions(evidence)
        self.assertFalse(result.passed)


class TestWaitAction(unittest.TestCase):
    """Test WaitAction dataclass."""

    def test_create_wait(self):
        action = WaitAction(selector="#modal")
        self.assertEqual(action.action_type, ActionType.WAIT)
        self.assertEqual(action.condition, "attached")
        self.assertEqual(action.timeout_ms, 30000)

    def test_wait_with_options(self):
        action = WaitAction(
            selector="#toast",
            condition="visible",
            timeout_ms=5000,
        )
        self.assertEqual(action.condition, "visible")
        self.assertEqual(action.timeout_ms, 5000)

    def test_wait_to_dict(self):
        action = WaitAction(selector="#el", action_id="wait-1")
        d = action.to_dict()
        self.assertEqual(d["action_type"], "wait")
        self.assertIn("condition", d)
        self.assertIn("timeout_ms", d)

    def test_wait_validate_minimal(self):
        action = WaitAction(selector="#el", action_id="wv-1")
        evidence = ActionabilityEvidence(
            action_id="wv-1",
            selector="#el",
            phase=Phase.PRE,
            attached=True,
        )
        result = action.validate_preconditions(evidence)
        self.assertTrue(result.passed)

    def test_wait_validate_not_attached(self):
        action = WaitAction(selector="#gone", action_id="wv-2")
        evidence = ActionabilityEvidence(
            action_id="wv-2",
            selector="#gone",
            phase=Phase.PRE,
            attached=False,
        )
        result = action.validate_preconditions(evidence)
        self.assertFalse(result.passed)


class TestActionFromDict(unittest.TestCase):
    """Test action_from_dict deserialization."""

    def test_deserialize_click(self):
        data = {
            "action_type": "click",
            "selector": "#btn",
            "action_id": "ds-1",
            "button": "right",
            "click_count": 2,
        }
        action = action_from_dict(data)
        self.assertIsInstance(action, ClickAction)
        self.assertEqual(action.selector, "#btn")
        self.assertEqual(action.button, "right")
        self.assertEqual(action.click_count, 2)

    def test_deserialize_fill(self):
        data = {
            "action_type": "fill",
            "selector": "input",
            "value": "hello",
            "clear_first": False,
        }
        action = action_from_dict(data)
        self.assertIsInstance(action, FillAction)
        self.assertEqual(action.value, "hello")
        self.assertFalse(action.clear_first)

    def test_deserialize_wait(self):
        data = {
            "action_type": "wait",
            "selector": "#modal",
            "condition": "visible",
            "timeout_ms": 10000,
        }
        action = action_from_dict(data)
        self.assertIsInstance(action, WaitAction)
        self.assertEqual(action.condition, "visible")
        self.assertEqual(action.timeout_ms, 10000)

    def test_deserialize_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            action_from_dict({"action_type": "unknown", "selector": "#x"})

    def test_deserialize_defaults(self):
        data = {"action_type": "click", "selector": "#btn"}
        action = action_from_dict(data)
        self.assertEqual(action.button, "left")
        self.assertEqual(action.click_count, 1)


class TestSchemaShape(unittest.TestCase):
    """Validate overall schema structure and completeness."""

    def test_all_action_types_have_preconditions(self):
        for atype in ActionType:
            preconds = get_preconditions(atype)
            self.assertTrue(len(preconds) > 0, f"{atype} has no preconditions")

    def test_action_types_are_complete(self):
        self.assertEqual(len(ActionType), 3)

    def test_evidence_has_required_fields(self):
        evidence = ActionabilityEvidence(
            action_id="shape-1",
            selector="#test",
            phase=Phase.PRE,
        )
        d = evidence.to_dict()
        required_keys = [
            "action_id", "selector", "phase",
            "visible", "enabled", "attached",
            "stable", "pointer_events", "editable",
            "timestamp", "metadata",
        ]
        for key in required_keys:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_verification_result_schema(self):
        evidence = ActionabilityEvidence(
            action_id="schema-v",
            selector="#btn",
            phase=Phase.PRE,
        )
        preconds = ActionPreconditions(
            action_type=ActionType.CLICK,
            evidence=evidence,
        )
        result = VerificationResult(
            action_id="schema-v",
            action_type=ActionType.CLICK,
            preconditions=preconds,
            passed=True,
        )
        d = result.to_dict()
        self.assertIn("action_id", d)
        self.assertIn("action_type", d)
        self.assertIn("passed", d)
        self.assertIn("reason", d)
        self.assertIn("preconditions", d)

    def test_typed_action_base_fields(self):
        action = ClickAction(selector="#btn", action_id="base-1")
        d = action.to_dict()
        self.assertIn("action_type", d)
        self.assertIn("selector", d)
        self.assertIn("action_id", d)
        self.assertIn("description", d)

    def test_action_id_uniqueness(self):
        ids = set()
        for _ in range(100):
            action = ClickAction(selector="#btn")
            self.assertNotIn(action.action_id, ids, "Duplicate action_id generated")
            ids.add(action.action_id)


# ---------------------------------------------------------------------------
# Tech debt fix: FillAction credential leak protection
# ---------------------------------------------------------------------------

class TestFillActionSensitive(unittest.TestCase):
    """Test FillAction is_sensitive flag and masked_value property."""

    def test_default_not_sensitive(self):
        action = FillAction(selector="input[name='email']", value="test@example.com")
        self.assertFalse(action.is_sensitive)

    def test_sensitive_flag_set(self):
        action = FillAction(
            selector="input[type='password']",
            value="s3cr3t!",
            is_sensitive=True,
        )
        self.assertTrue(action.is_sensitive)

    def test_masked_value_normal(self):
        action = FillAction(value="hello", is_sensitive=True)
        self.assertEqual(action.masked_value, "h****")

    def test_masked_value_single_char(self):
        action = FillAction(value="x", is_sensitive=True)
        self.assertEqual(action.masked_value, "*")

    def test_masked_value_empty(self):
        action = FillAction(value="", is_sensitive=True)
        self.assertEqual(action.masked_value, "")

    def test_masked_value_long(self):
        action = FillAction(value="supersecret12345", is_sensitive=True)
        self.assertEqual(action.masked_value, "s***************")

    def test_to_dict_masks_sensitive_by_default(self):
        action = FillAction(
            selector="input[type='password']",
            value="mypassword",
            is_sensitive=True,
        )
        d = action.to_dict()
        self.assertEqual(d["value"], "m*********")
        self.assertEqual(d["text"], "m*********")
        self.assertTrue(d["is_sensitive"])

    def test_to_dict_no_mask_when_not_sensitive(self):
        action = FillAction(
            selector="input[name='email']",
            value="user@example.com",
            is_sensitive=False,
        )
        d = action.to_dict()
        self.assertEqual(d["value"], "user@example.com")
        self.assertFalse(d["is_sensitive"])

    def test_to_dict_no_mask_when_mask_disabled(self):
        action = FillAction(
            selector="input[type='password']",
            value="mypassword",
            is_sensitive=True,
        )
        d = action.to_dict(mask_sensitive=False)
        self.assertEqual(d["value"], "mypassword")
        self.assertTrue(d["is_sensitive"])

    def test_sensitive_fill_value_sync(self):
        """text and value sync applies before masking."""
        action = FillAction(
            selector="input[type='password']",
            text="secret",
            is_sensitive=True,
        )
        self.assertEqual(action.value, "secret")
        d = action.to_dict()
        self.assertEqual(d["value"], "s*****")

    def test_non_sensitive_masked_value_still_works(self):
        """masked_value is a property available regardless of is_sensitive."""
        action = FillAction(value="visible", is_sensitive=False)
        self.assertEqual(action.masked_value, "v******")


class TestActionRoundTrip(unittest.TestCase):
    """Test action serialization → deserialization round-trips."""

    def test_fill_sensitive_round_trip(self):
        """is_sensitive must survive serialization → deserialization.
        
        For sensitive actions, to_dict(mask_sensitive=False) must be used
        for serialization that will be deserialized later — masked values
        cannot be restored. This test verifies the full contract.
        """
        original = FillAction(
            selector="input[type='password']",
            value="s3cr3t!",
            is_sensitive=True,
            press_enter=True,
            clear_first=False,
            description="Enter password",
            action_id="rt-1",
        )
        # Round-trip MUST use mask_sensitive=False for faithful restore
        serialized = original.to_dict(mask_sensitive=False)
        restored = action_from_dict(serialized)
        self.assertIsInstance(restored, FillAction)
        self.assertTrue(restored.is_sensitive)
        self.assertEqual(restored.value, "s3cr3t!")
        self.assertTrue(restored.press_enter)
        self.assertFalse(restored.clear_first)
        self.assertEqual(restored.description, "Enter password")
        self.assertEqual(restored.action_id, "rt-1")

    def test_fill_sensitive_default_mask_broke_round_trip(self):
        """Document known behavior: default to_dict() masks value,
        so action_from_dict receives masked value, not original.
        This is by design — masked dicts are for logging, not storage.
        """
        original = FillAction(
            selector="input[type='password']",
            value="s3cr3t!",
            is_sensitive=True,
            action_id="rt-mask",
        )
        masked = original.to_dict()  # default: mask_sensitive=True
        restored = action_from_dict(masked)
        self.assertTrue(restored.is_sensitive)
        # Value is masked — this is expected for logging paths
        self.assertNotEqual(restored.value, "s3cr3t!")
        self.assertEqual(restored.value, "s******")

    def test_fill_unmasked_round_trip(self):
        """Round-trip with mask_sensitive=False preserves raw value."""
        original = FillAction(
            selector="input[type='password']",
            value="secret",
            is_sensitive=True,
            action_id="rt-2",
        )
        serialized = original.to_dict(mask_sensitive=False)
        restored = action_from_dict(serialized)
        self.assertTrue(restored.is_sensitive)
        self.assertEqual(restored.value, "secret")

    def test_fill_non_sensitive_round_trip(self):
        """Non-sensitive FillAction round-trip."""
        original = FillAction(
            selector="input[name='email']",
            value="user@test.com",
            is_sensitive=False,
            action_id="rt-3",
        )
        serialized = original.to_dict()
        restored = action_from_dict(serialized)
        self.assertFalse(restored.is_sensitive)
        self.assertEqual(restored.value, "user@test.com")

    def test_click_round_trip(self):
        original = ClickAction(
            selector="#btn",
            button="right",
            click_count=2,
            delay_ms=50,
            description="Right-click menu",
            action_id="rt-4",
        )
        serialized = original.to_dict()
        restored = action_from_dict(serialized)
        self.assertIsInstance(restored, ClickAction)
        self.assertEqual(restored.button, "right")
        self.assertEqual(restored.click_count, 2)
        self.assertEqual(restored.delay_ms, 50)
        self.assertEqual(restored.description, "Right-click menu")

    def test_wait_round_trip(self):
        original = WaitAction(
            selector="#spinner",
            condition="hidden",
            timeout_ms=5000,
            description="Wait for spinner to disappear",
            action_id="rt-5",
        )
        serialized = original.to_dict()
        restored = action_from_dict(serialized)
        self.assertIsInstance(restored, WaitAction)
        self.assertEqual(restored.condition, "hidden")
        self.assertEqual(restored.timeout_ms, 5000)
        self.assertEqual(restored.description, "Wait for spinner to disappear")

    def test_fill_default_is_sensitive_false(self):
        """Deserializing FillAction without is_sensitive defaults to False."""
        data = {
            "action_type": "fill",
            "selector": "input",
            "value": "hello",
        }
        action = action_from_dict(data)
        self.assertFalse(action.is_sensitive)

    def test_fill_from_dict_preserves_press_enter(self):
        data = {
            "action_type": "fill",
            "selector": "#search",
            "value": "query",
            "press_enter": True,
        }
        action = action_from_dict(data)
        self.assertTrue(action.press_enter)

    def test_target_ref_sync_on_deserialize(self):
        """action_from_dict syncs selector ↔ target_ref."""
        data = {"action_type": "click", "selector": "#btn"}
        action = action_from_dict(data)
        self.assertEqual(action.target_ref, "#btn")
        data2 = {"action_type": "click", "target_ref": "#btn2"}
        action2 = action_from_dict(data2)
        self.assertEqual(action2.selector, "#btn2")


class TestActionEvidenceRoundTrip(unittest.TestCase):
    """Test action_from_dict round-trip with evidence and verification attachments.

    Validates that pre_evidence, post_evidence, and verification are fully
    deserialized — the gap fixed in this WNAL cycle.
    """

    def _make_evidence(self, action_id: str, phase: Phase, **overrides) -> ActionabilityEvidence:
        """Helper: build a non-trivial evidence envelope."""
        defaults = {
            "selector": "#target",
            "target_ref": "#target",
            "visible": True,
            "enabled": True,
            "attached": True,
            "stable": True,
            "pointer_events": True,
            "editable": True,
            "metadata": {"rect": {"x": 10, "y": 20}},
        }
        defaults.update(overrides)
        return ActionabilityEvidence(action_id=action_id, phase=phase, **defaults)

    def test_click_with_pre_evidence_round_trip(self):
        """ClickAction with pre_evidence round-trips fully."""
        ev = self._make_evidence("cl-1", Phase.PRE)
        original = ClickAction(selector="#btn", action_id="cl-1")
        result = original.validate_preconditions(ev)
        self.assertTrue(result.passed)

        serialized = original.to_dict()
        self.assertIn("pre_evidence", serialized)
        self.assertIn("verification", serialized)

        restored = action_from_dict(serialized)
        self.assertIsInstance(restored, ClickAction)
        self.assertIsNotNone(restored.pre_evidence)
        self.assertEqual(restored.pre_evidence.action_id, "cl-1")
        self.assertEqual(restored.pre_evidence.phase, Phase.PRE)
        self.assertTrue(restored.pre_evidence.visible)
        self.assertTrue(restored.pre_evidence.enabled)
        self.assertIsNotNone(restored.verification)
        self.assertTrue(restored.verification.passed)

    def test_click_with_post_evidence_round_trip(self):
        """ClickAction with both pre and post evidence round-trips."""
        pre = self._make_evidence("cl-2", Phase.PRE)
        post = self._make_evidence("cl-2", Phase.POST, visible=False)
        original = ClickAction(selector="#btn", action_id="cl-2")
        original.validate_preconditions(pre)
        original.post_evidence = post

        serialized = original.to_dict()
        restored = action_from_dict(serialized)

        self.assertIsNotNone(restored.pre_evidence)
        self.assertEqual(restored.pre_evidence.phase, Phase.PRE)
        self.assertIsNotNone(restored.post_evidence)
        self.assertEqual(restored.post_evidence.phase, Phase.POST)
        self.assertFalse(restored.post_evidence.visible)

    def test_fill_with_evidence_round_trip(self):
        """FillAction with evidence round-trips (non-sensitive)."""
        ev = self._make_evidence("fl-1", Phase.PRE)
        original = FillAction(
            selector="input[name='q']",
            value="search term",
            action_id="fl-1",
            clear_first=True,
            press_enter=True,
        )
        original.validate_preconditions(ev)

        serialized = original.to_dict()
        restored = action_from_dict(serialized)

        self.assertIsInstance(restored, FillAction)
        self.assertEqual(restored.value, "search term")
        self.assertTrue(restored.press_enter)
        self.assertIsNotNone(restored.pre_evidence)
        self.assertTrue(restored.verification.passed)

    def test_wait_with_evidence_round_trip(self):
        """WaitAction with evidence round-trips."""
        ev = self._make_evidence("wt-1", Phase.PRE)
        original = WaitAction(
            selector="#spinner",
            condition="hidden",
            timeout_ms=5000,
            action_id="wt-1",
        )
        original.validate_preconditions(ev)

        serialized = original.to_dict()
        restored = action_from_dict(serialized)

        self.assertIsInstance(restored, WaitAction)
        self.assertEqual(restored.condition, "hidden")
        self.assertEqual(restored.timeout_ms, 5000)
        self.assertIsNotNone(restored.pre_evidence)
        self.assertIsNotNone(restored.verification)

    def test_action_without_evidence_still_works(self):
        """Actions without evidence deserialize with None attachments."""
        original = ClickAction(selector="#btn", action_id="noev-1")
        serialized = original.to_dict()
        self.assertNotIn("pre_evidence", serialized)
        self.assertNotIn("post_evidence", serialized)
        self.assertNotIn("verification", serialized)

        restored = action_from_dict(serialized)
        self.assertIsNone(restored.pre_evidence)
        self.assertIsNone(restored.post_evidence)
        self.assertIsNone(restored.verification)

    def test_verification_failed_round_trip(self):
        """VerificationResult with failed preconditions round-trips."""
        ev = ActionabilityEvidence(
            action_id="fail-1",
            selector="#btn",
            phase=Phase.PRE,
            visible=False,
            enabled=True,
            attached=True,
            stable=False,
            pointer_events=True,
        )
        original = ClickAction(selector="#btn", action_id="fail-1")
        result = original.validate_preconditions(ev)
        self.assertFalse(result.passed)

        serialized = original.to_dict()
        restored = action_from_dict(serialized)

        self.assertIsNotNone(restored.verification)
        self.assertFalse(restored.verification.passed)
        self.assertIn("visible", restored.verification.preconditions.failed_checks())
        self.assertIn("stable", restored.verification.preconditions.failed_checks())

    def test_evidence_metadata_round_trip(self):
        """Evidence metadata dict survives round-trip."""
        ev = ActionabilityEvidence(
            action_id="meta-1",
            selector="#el",
            phase=Phase.PRE,
            metadata={"rect": {"x": 100, "y": 200}, "styles": {"color": "red"}},
        )
        original = ClickAction(selector="#el", action_id="meta-1")
        original.validate_preconditions(ev)

        serialized = original.to_dict()
        restored = action_from_dict(serialized)

        self.assertEqual(
            restored.pre_evidence.metadata["rect"],
            {"x": 100, "y": 200},
        )
        self.assertEqual(restored.pre_evidence.metadata["styles"]["color"], "red")

    def test_evidence_timestamp_round_trip(self):
        """Evidence timestamps survive round-trip."""
        ts = datetime(2026, 5, 24, 12, 0, 0)
        ev = ActionabilityEvidence(
            action_id="ts-1",
            selector="#el",
            phase=Phase.PRE,
            timestamp=ts,
            observed_at=ts,
        )
        original = ClickAction(selector="#el", action_id="ts-1")
        original.validate_preconditions(ev)

        serialized = original.to_dict()
        restored = action_from_dict(serialized)

        self.assertEqual(restored.pre_evidence.timestamp, ts)
        self.assertEqual(restored.pre_evidence.observed_at, ts)

    def test_full_evidence_chain_round_trip(self):
        """Complete observe→verify→execute→verify chain round-trips."""
        pre = self._make_evidence("chain-1", Phase.PRE)
        post = self._make_evidence("chain-1", Phase.POST, visible=False, stable=False)
        original = ClickAction(selector="#btn", action_id="chain-1")
        original.validate_preconditions(pre)
        original.post_evidence = post

        serialized = original.to_dict()
        restored = action_from_dict(serialized)

        # Pre-evidence: all good
        self.assertTrue(restored.pre_evidence.visible)
        self.assertTrue(restored.pre_evidence.stable)
        self.assertTrue(restored.verification.passed)

        # Post-evidence: element changed
        self.assertFalse(restored.post_evidence.visible)
        self.assertFalse(restored.post_evidence.stable)
        self.assertEqual(restored.post_evidence.phase, Phase.POST)


if __name__ == "__main__":
    unittest.main()
