"""WNAL (Web Native Action Language) - Typed action schema and verifier contracts.

This module defines the typed action schema for browser automation with
actionability evidence envelopes that serve as verifier input.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set


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
    """Actionability evidence envelope from CloakBrowser checks.
    
    This envelope captures the state of a target element before (pre) or
    after (post) an action is executed. The verifier uses this evidence
    to validate preconditions and postconditions.
    
    Field semantics (from ADR-001):
    - attached: target remains connected to DOM/actionability tree
    - visible: target has visible box/rendered affordance
    - enabled: target is not disabled for activation
    - editable: target can accept text input
    - stable: target geometry/state is stable for humanized interaction
    - pointer_events: target can receive pointer input
    """
    action_id: str
    target_ref: str
    phase: Phase
    attached: bool
    visible: bool
    enabled: bool
    editable: bool
    stable: bool
    pointer_events: bool
    observed_at: datetime
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "action_id": self.action_id,
            "target_ref": self.target_ref,
            "phase": self.phase.value,
            "attached": self.attached,
            "visible": self.visible,
            "enabled": self.enabled,
            "editable": self.editable,
            "stable": self.stable,
            "pointer_events": self.pointer_events,
            "observed_at": self.observed_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ActionabilityEvidence":
        """Create from dict."""
        return cls(
            action_id=data["action_id"],
            target_ref=data["target_ref"],
            phase=Phase(data["phase"]),
            attached=data["attached"],
            visible=data["visible"],
            enabled=data["enabled"],
            editable=data["editable"],
            stable=data["stable"],
            pointer_events=data["pointer_events"],
            observed_at=datetime.fromisoformat(data["observed_at"]),
        )


@dataclass
class ActionPreconditions:
    """Required preconditions for an action type.
    
    Maps actionability evidence fields to required boolean values.
    """
    required_fields: Set[str]
    
    def validate(self, evidence: ActionabilityEvidence) -> bool:
        """Check if evidence satisfies all required preconditions."""
        for field_name in self.required_fields:
            if not getattr(evidence, field_name):
                return False
        return True
    
    def missing_preconditions(self, evidence: ActionabilityEvidence) -> List[str]:
        """Return list of unsatisfied preconditions."""
        missing = []
        for field_name in self.required_fields:
            if not getattr(evidence, field_name):
                missing.append(field_name)
        return missing


# Precondition mappings for each action type (from ADR-001)
CLICK_PRECONDITIONS = ActionPreconditions(
    required_fields={"attached", "visible", "enabled", "stable", "pointer_events"}
)

FILL_PRECONDITIONS = ActionPreconditions(
    required_fields={"attached", "visible", "enabled", "editable", "stable", "pointer_events"}
)

WAIT_PRECONDITIONS = ActionPreconditions(
    required_fields={"attached"}  # Wait only requires target existence
)


def get_preconditions(action_type: ActionType) -> ActionPreconditions:
    """Get precondition requirements for an action type."""
    mapping = {
        ActionType.CLICK: CLICK_PRECONDITIONS,
        ActionType.FILL: FILL_PRECONDITIONS,
        ActionType.WAIT: WAIT_PRECONDITIONS,
    }
    return mapping[action_type]


@dataclass
class TypedAction:
    """A typed WNAL action with target and parameters."""
    action_id: str
    action_type: ActionType
    target_ref: str
    parameters: Dict = field(default_factory=dict)
    
    def get_preconditions(self) -> ActionPreconditions:
        """Get required preconditions for this action."""
        return get_preconditions(self.action_type)
    
    def validate_preconditions(self, evidence: ActionabilityEvidence) -> bool:
        """Validate that evidence satisfies preconditions."""
        if evidence.action_id != self.action_id:
            raise ValueError(f"Evidence action_id mismatch: {evidence.action_id} != {self.action_id}")
        if evidence.target_ref != self.target_ref:
            raise ValueError(f"Evidence target_ref mismatch: {evidence.target_ref} != {self.target_ref}")
        if evidence.phase != Phase.PRE:
            raise ValueError(f"Precondition validation requires PRE phase evidence, got {evidence.phase}")
        
        preconditions = self.get_preconditions()
        return preconditions.validate(evidence)
    
    def missing_preconditions(self, evidence: ActionabilityEvidence) -> List[str]:
        """Get list of unsatisfied preconditions."""
        preconditions = self.get_preconditions()
        return preconditions.missing_preconditions(evidence)
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "target_ref": self.target_ref,
            "parameters": self.parameters,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TypedAction":
        """Create from dict."""
        return cls(
            action_id=data["action_id"],
            action_type=ActionType(data["action_type"]),
            target_ref=data["target_ref"],
            parameters=data.get("parameters", {}),
        )


@dataclass
class ClickAction(TypedAction):
    """Click action on a target element."""
    
    def __init__(self, action_id: str, target_ref: str, button: str = "left"):
        super().__init__(
            action_id=action_id,
            action_type=ActionType.CLICK,
            target_ref=target_ref,
            parameters={"button": button}
        )


@dataclass
class FillAction(TypedAction):
    """Fill action to input text into a target element."""
    
    def __init__(self, action_id: str, target_ref: str, text: str):
        super().__init__(
            action_id=action_id,
            action_type=ActionType.FILL,
            target_ref=target_ref,
            parameters={"text": text}
        )


@dataclass
class WaitAction(TypedAction):
    """Wait action for a target element to reach a state."""
    
    def __init__(self, action_id: str, target_ref: str, condition: str = "attached", timeout_ms: int = 5000):
        super().__init__(
            action_id=action_id,
            action_type=ActionType.WAIT,
            target_ref=target_ref,
            parameters={"condition": condition, "timeout_ms": timeout_ms}
        )


@dataclass
class VerificationResult:
    """Result of precondition or postcondition verification."""
    action_id: str
    passed: bool
    missing_conditions: List[str] = field(default_factory=list)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "action_id": self.action_id,
            "passed": self.passed,
            "missing_conditions": self.missing_conditions,
            "error": self.error,
        }
