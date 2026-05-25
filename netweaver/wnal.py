"""WNAL (Web Native Action Language) — Typed action schema and verifier contracts.

Defines click/fill/wait action types with actionability evidence envelopes
that map preconditions to verifiable evidence. This is the typed action
layer that sits between observer evidence and the verified executor.

Key design:
- ActionType enum: CLICK, FILL, WAIT
- ActionabilityEvidence: captures element state (visible/enabled/attached/stable/pointer_events)
- ActionPreconditions: per-action-type required preconditions
- TypedAction dataclasses: ClickAction, FillAction, WaitAction
- VerificationResult: precondition check outcome linked to evidence
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set
import json
import uuid


class ActionType(Enum):
    """Supported WNAL action types."""
    CLICK = "click"
    FILL = "fill"
    WAIT = "wait"


class Phase(Enum):
    """Evidence collection phase."""
    PRE = "pre"
    POST = "post"


@dataclass
class ActionabilityEvidence:
    """Actionability evidence envelope from element checks.

    Captures the state of a target element before (pre) or after (post)
    action execution. Used as verifier input for the evidence-first pipeline.

    Attributes:
        action_id: Unique identifier for the action this evidence belongs to.
        selector: CSS/XPath selector targeting the element.
        phase: PRE or POST collection phase.
        visible: Whether element is visible in viewport.
        enabled: Whether element is interactive (not disabled).
        attached: Whether element is in the DOM.
        stable: Whether element is not animating/transitioning.
        pointer_events: Whether element accepts pointer events.
        editable: Whether element is editable (input/textarea/contenteditable).
        timestamp: Evidence collection timestamp.
        metadata: Additional context (rect, styles, etc.).
    """
    action_id: str
    selector: str = ""
    phase: Phase = Phase.PRE
    target_ref: str = ""
    visible: bool = True
    enabled: bool = True
    attached: bool = True
    stable: bool = True
    pointer_events: bool = True
    editable: Optional[bool] = None
    timestamp: Optional[datetime] = None
    observed_at: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp is None and self.observed_at is not None:
            self.timestamp = self.observed_at
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.observed_at is None:
            self.observed_at = self.timestamp
        if not self.selector and self.target_ref:
            self.selector = self.target_ref
        if not self.target_ref and self.selector:
            self.target_ref = self.selector

    def to_dict(self) -> Dict:
        return {
            "action_id": self.action_id,
            "selector": self.selector,
            "target_ref": self.target_ref,
            "phase": self.phase.value,
            "visible": self.visible,
            "enabled": self.enabled,
            "attached": self.attached,
            "stable": self.stable,
            "pointer_events": self.pointer_events,
            "editable": self.editable,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ActionabilityEvidence":
        d = dict(data)
        if "phase" in d and isinstance(d["phase"], str):
            d["phase"] = Phase(d["phase"])
        if "timestamp" in d and isinstance(d["timestamp"], str):
            d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        if "observed_at" in d and isinstance(d["observed_at"], str):
            d["observed_at"] = datetime.fromisoformat(d["observed_at"])
        return cls(**d)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# --- Preconditions per action type ---

CLICK_PRECONDITIONS: Set[str] = {"visible", "enabled", "attached", "stable", "pointer_events"}
FILL_PRECONDITIONS: Set[str] = {"visible", "enabled", "attached", "editable"}
WAIT_PRECONDITIONS: Set[str] = {"attached"}

PRECONDITION_MAP: Dict[ActionType, Set[str]] = {
    ActionType.CLICK: CLICK_PRECONDITIONS,
    ActionType.FILL: FILL_PRECONDITIONS,
    ActionType.WAIT: WAIT_PRECONDITIONS,
}


def get_preconditions(action_type: ActionType) -> Set[str]:
    """Return the required preconditions for an action type."""
    return PRECONDITION_MAP.get(action_type, set())


@dataclass
class ActionPreconditions:
    """Validated preconditions for a specific action.

    Maps each required precondition to its evidence value and pass/fail status.
    """
    action_type: ActionType
    evidence: ActionabilityEvidence
    checks: Dict[str, bool] = field(default_factory=dict)
    all_met: bool = False

    def __post_init__(self):
        required = get_preconditions(self.action_type)
        self.checks = {}
        for precond in required:
            value = getattr(self.evidence, precond, None)
            if value is None:
                self.checks[precond] = False
            else:
                self.checks[precond] = bool(value)
        self.all_met = all(self.checks.values()) if self.checks else False

    def failed_checks(self) -> List[str]:
        return [k for k, v in self.checks.items() if not v]

    def to_dict(self) -> Dict:
        return {
            "action_type": self.action_type.value,
            "evidence": self.evidence.to_dict(),
            "checks": self.checks,
            "all_met": self.all_met,
        }


@dataclass
class VerificationResult:
    """Result of verifying action preconditions against evidence.

    Links the action, its precondition check, and pass/fail outcome
    so the executor can decide whether to proceed.
    """
    action_id: str
    action_type: ActionType
    preconditions: ActionPreconditions
    passed: bool
    reason: str = ""

    def __post_init__(self):
        if not self.reason:
            if self.passed:
                self.reason = "All preconditions met"
            else:
                failed = self.preconditions.failed_checks()
                self.reason = f"Failed preconditions: {', '.join(failed)}"

    def to_dict(self) -> Dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "passed": self.passed,
            "reason": self.reason,
            "preconditions": self.preconditions.to_dict(),
        }


# --- Typed Action Dataclasses ---

@dataclass
class TypedAction:
    """Base typed action with common fields."""
    action_type: ActionType = field(default=None)
    selector: str = ""
    target_ref: str = ""
    action_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    pre_evidence: Optional[ActionabilityEvidence] = None
    post_evidence: Optional[ActionabilityEvidence] = None
    verification: Optional[VerificationResult] = None

    def __post_init__(self):
        if not self.selector and self.target_ref:
            self.selector = self.target_ref
        if not self.target_ref and self.selector:
            self.target_ref = self.selector

    def to_dict(self) -> Dict:
        d = {
            "action_type": self.action_type.value,
            "selector": self.selector,
            "target_ref": self.target_ref,
            "action_id": self.action_id,
            "description": self.description,
        }
        if self.pre_evidence:
            d["pre_evidence"] = self.pre_evidence.to_dict()
        if self.post_evidence:
            d["post_evidence"] = self.post_evidence.to_dict()
        if self.verification:
            d["verification"] = self.verification.to_dict()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def validate_preconditions(self, evidence: ActionabilityEvidence) -> VerificationResult:
        """Validate preconditions for this action against evidence."""
        preconds = ActionPreconditions(
            action_type=self.action_type,
            evidence=evidence,
        )
        result = VerificationResult(
            action_id=self.action_id,
            action_type=self.action_type,
            preconditions=preconds,
            passed=preconds.all_met,
        )
        self.pre_evidence = evidence
        self.verification = result
        return result


@dataclass
class ClickAction(TypedAction):
    """Typed click action."""
    button: str = "left"  # left, right, middle
    click_count: int = 1
    delay_ms: int = 0

    def __post_init__(self):
        super().__post_init__()
        self.action_type = ActionType.CLICK

    def to_dict(self) -> Dict:
        d = super().to_dict()
        d.update({
            "button": self.button,
            "click_count": self.click_count,
            "delay_ms": self.delay_ms,
        })
        return d


@dataclass
class FillAction(TypedAction):
    """Typed fill/typing action.

    Security note: set is_sensitive=True for password/credential fields.
    When is_sensitive=True, to_dict() masks the value and text fields,
    and the masked_value property returns a redacted string.
    """
    value: str = ""
    text: str = ""
    clear_first: bool = True
    press_enter: bool = False
    is_sensitive: bool = False

    def __post_init__(self):
        super().__post_init__()
        self.action_type = ActionType.FILL
        if not self.value and self.text:
            self.value = self.text
        if not self.text and self.value:
            self.text = self.value

    @property
    def masked_value(self) -> str:
        """Return masked representation of the value for logging/display.

        Shows first char + asterisks for length, or empty string if no value.
        Example: 's' → 's***', 'supersecret' → 's**********', '' → ''
        """
        if not self.value:
            return ""
        if len(self.value) == 1:
            return "*"
        return self.value[0] + "*" * (len(self.value) - 1)

    def to_dict(self, mask_sensitive: bool = True) -> Dict:
        d = super().to_dict()
        if self.is_sensitive and mask_sensitive:
            d.update({
                "value": self.masked_value,
                "text": self.masked_value,
                "clear_first": self.clear_first,
                "press_enter": self.press_enter,
                "is_sensitive": True,
            })
        else:
            d.update({
                "value": self.value,
                "text": self.text,
                "clear_first": self.clear_first,
                "press_enter": self.press_enter,
                "is_sensitive": self.is_sensitive,
            })
        return d


@dataclass
class WaitAction(TypedAction):
    """Typed wait action — wait for element condition."""
    condition: str = "attached"  # attached, visible, visible_text, hidden, detached
    timeout_ms: int = 30000

    def __post_init__(self):
        super().__post_init__()
        self.action_type = ActionType.WAIT

    def to_dict(self) -> Dict:
        d = super().to_dict()
        d.update({
            "condition": self.condition,
            "timeout_ms": self.timeout_ms,
        })
        return d


def _deserialize_evidence(data: Optional[Dict]) -> Optional[ActionabilityEvidence]:
    """Deserialize an ActionabilityEvidence dict, or return None."""
    if data is None:
        return None
    return ActionabilityEvidence.from_dict(data)


def _deserialize_verification(data: Optional[Dict]) -> Optional[VerificationResult]:
    """Deserialize a VerificationResult dict, or return None."""
    if data is None:
        return None
    preconds_data = data.get("preconditions", {})
    evidence = _deserialize_evidence(preconds_data.get("evidence"))
    preconds = ActionPreconditions(
        action_type=ActionType(preconds_data.get("action_type", data.get("action_type", "click"))),
        evidence=evidence or ActionabilityEvidence(action_id=data.get("action_id", "")),
    )
    # Override computed fields with serialized values for exact round-trip
    preconds.checks = preconds_data.get("checks", preconds.checks)
    preconds.all_met = preconds_data.get("all_met", preconds.all_met)
    return VerificationResult(
        action_id=data.get("action_id", ""),
        action_type=ActionType(data.get("action_type", "click")),
        preconditions=preconds,
        passed=data.get("passed", False),
        reason=data.get("reason", ""),
    )


def action_from_dict(data: Dict) -> TypedAction:
    """Deserialize a typed action from a dict.

    Round-trip complete: serializes pre_evidence, post_evidence, and
    verification via to_dict() and restores them here.
    """
    atype = ActionType(data["action_type"])
    pre_evidence = _deserialize_evidence(data.get("pre_evidence"))
    post_evidence = _deserialize_evidence(data.get("post_evidence"))
    verification = _deserialize_verification(data.get("verification"))

    if atype == ActionType.CLICK:
        action = ClickAction(
            selector=data.get("selector", data.get("target_ref", "")),
            target_ref=data.get("target_ref", data.get("selector", "")),
            action_id=data.get("action_id", str(uuid.uuid4())[:8]),
            description=data.get("description", ""),
            button=data.get("button", "left"),
            click_count=data.get("click_count", 1),
            delay_ms=data.get("delay_ms", 0),
        )
    elif atype == ActionType.FILL:
        action = FillAction(
            selector=data.get("selector", data.get("target_ref", "")),
            target_ref=data.get("target_ref", data.get("selector", "")),
            action_id=data.get("action_id", str(uuid.uuid4())[:8]),
            description=data.get("description", ""),
            value=data.get("value", data.get("text", "")),
            text=data.get("text", data.get("value", "")),
            clear_first=data.get("clear_first", True),
            press_enter=data.get("press_enter", False),
            is_sensitive=data.get("is_sensitive", False),
        )
    elif atype == ActionType.WAIT:
        action = WaitAction(
            selector=data.get("selector", data.get("target_ref", "")),
            target_ref=data.get("target_ref", data.get("selector", "")),
            action_id=data.get("action_id", str(uuid.uuid4())[:8]),
            description=data.get("description", ""),
            condition=data.get("condition", "attached"),
            timeout_ms=data.get("timeout_ms", 30000),
        )
    else:
        raise ValueError(f"Unknown action type: {atype}")

    # Restore evidence and verification attachments
    action.pre_evidence = pre_evidence
    action.post_evidence = post_evidence
    action.verification = verification
    return action
