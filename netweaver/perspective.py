"""NetWeaver Perspective Engine - Multi-perspective conflict resolution.

The perspective engine analyzes browser actions from multiple viewpoints:
- User intent perspective: what the user wants to accomplish
- DOM perspective: structural/semantic validity
- Visual perspective: what's actually visible/accessible
- Network perspective: API state, auth, rate limits
- JS perspective: dynamic state, event handlers
- Safety perspective: risk assessment (payments, data loss)
- History perspective: past action outcomes, learned patterns

When perspectives conflict, the engine returns a resolution strategy:
- action: safe to proceed
- ask: ambiguous, needs user clarification
- abort: unsafe, should not proceed
- recover: recoverable error, suggest alternative
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set

from netweaver.wnal import ActionabilityEvidence, TypedAction


class PerspectiveType(Enum):
    """Supported perspective types."""
    USER = "user"
    DOM = "dom"
    VISUAL = "visual"
    NETWORK = "network"
    JS = "js"
    SAFETY = "safety"
    HISTORY = "history"


class ResolutionStrategy(Enum):
    """Conflict resolution strategies."""
    ACTION = "action"  # Safe to proceed
    ASK = "ask"  # Ambiguous, needs clarification
    ABORT = "abort"  # Unsafe, should not proceed
    RECOVER = "recover"  # Recoverable error, suggest alternative


class Confidence(Enum):
    """Confidence levels for perspective assessments."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class PerspectiveAssessment:
    """Assessment from a single perspective."""
    perspective: PerspectiveType
    safe: bool
    confidence: Confidence
    reason: str
    evidence: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "perspective": self.perspective.value,
            "safe": self.safe,
            "confidence": self.confidence.value,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class ConflictResolution:
    """Result of multi-perspective conflict resolution."""
    strategy: ResolutionStrategy
    assessments: List[PerspectiveAssessment]
    reason: str
    suggested_action: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "strategy": self.strategy.value,
            "assessments": [a.to_dict() for a in self.assessments],
            "reason": self.reason,
            "suggested_action": self.suggested_action,
        }


class UserPerspective:
    """User intent perspective - what the user wants to accomplish."""
    
    def assess(self, action: TypedAction, evidence: ActionabilityEvidence, context: Dict) -> PerspectiveAssessment:
        """Assess action from user intent perspective."""
        # Check if action aligns with stated user goal
        user_goal = context.get("user_goal", "")
        
        # For now, assume user intent is valid if goal is stated
        if user_goal:
            return PerspectiveAssessment(
                perspective=PerspectiveType.USER,
                safe=True,
                confidence=Confidence.HIGH,
                reason=f"Action aligns with user goal: {user_goal}",
                evidence={"user_goal": user_goal}
            )
        
        return PerspectiveAssessment(
            perspective=PerspectiveType.USER,
            safe=True,
            confidence=Confidence.LOW,
            reason="No explicit user goal provided",
            evidence={}
        )


class DOMPerspective:
    """DOM perspective - structural/semantic validity."""
    
    def assess(self, action: TypedAction, evidence: ActionabilityEvidence, context: Dict) -> PerspectiveAssessment:
        """Assess action from DOM perspective."""
        # Check if element is attached and structurally valid
        if not evidence.attached:
            return PerspectiveAssessment(
                perspective=PerspectiveType.DOM,
                safe=False,
                confidence=Confidence.HIGH,
                reason="Target element is not attached to DOM",
                evidence={"attached": False}
            )
        
        # Check semantic validity from context
        element_role = context.get("element_role", "")
        if element_role == "presentation":
            return PerspectiveAssessment(
                perspective=PerspectiveType.DOM,
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Target has presentation role, not interactive",
                evidence={"element_role": element_role}
            )
        
        return PerspectiveAssessment(
            perspective=PerspectiveType.DOM,
            safe=True,
            confidence=Confidence.HIGH,
            reason="Element is attached and semantically valid",
            evidence={"attached": True}
        )


class VisualPerspective:
    """Visual perspective - what's actually visible/accessible."""
    
    def assess(self, action: TypedAction, evidence: ActionabilityEvidence, context: Dict) -> PerspectiveAssessment:
        """Assess action from visual perspective."""
        # Check visibility and visual accessibility
        if not evidence.visible:
            # Check if element is intentionally hidden
            is_hidden = context.get("is_hidden", False)
            if is_hidden:
                return PerspectiveAssessment(
                    perspective=PerspectiveType.VISUAL,
                    safe=False,
                    confidence=Confidence.HIGH,
                    reason="Target element is hidden (display:none or visibility:hidden)",
                    evidence={"visible": False, "is_hidden": True}
                )
            
            return PerspectiveAssessment(
                perspective=PerspectiveType.VISUAL,
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Target element is not visible",
                evidence={"visible": False}
            )
        
        # Check if element is obscured
        is_obscured = context.get("is_obscured", False)
        if is_obscured:
            return PerspectiveAssessment(
                perspective=PerspectiveType.VISUAL,
                safe=False,
                confidence=Confidence.HIGH,
                reason="Target element is obscured by another element",
                evidence={"visible": True, "is_obscured": True}
            )
        
        return PerspectiveAssessment(
            perspective=PerspectiveType.VISUAL,
            safe=True,
            confidence=Confidence.HIGH,
            reason="Element is visible and not obscured",
            evidence={"visible": True, "is_obscured": False}
        )


class NetworkPerspective:
    """Network perspective - API state, auth, rate limits."""
    
    def assess(self, action: TypedAction, evidence: ActionabilityEvidence, context: Dict) -> PerspectiveAssessment:
        """Assess action from network perspective."""
        # Check authentication state
        auth_state = context.get("auth_state", "unknown")
        if auth_state == "expired":
            return PerspectiveAssessment(
                perspective=PerspectiveType.NETWORK,
                safe=False,
                confidence=Confidence.HIGH,
                reason="Authentication token has expired",
                evidence={"auth_state": "expired"}
            )
        
        if auth_state == "missing":
            return PerspectiveAssessment(
                perspective=PerspectiveType.NETWORK,
                safe=False,
                confidence=Confidence.HIGH,
                reason="No authentication token present",
                evidence={"auth_state": "missing"}
            )
        
        # Check rate limiting
        rate_limit_remaining = context.get("rate_limit_remaining", None)
        if rate_limit_remaining is not None and rate_limit_remaining <= 0:
            return PerspectiveAssessment(
                perspective=PerspectiveType.NETWORK,
                safe=False,
                confidence=Confidence.HIGH,
                reason="API rate limit exceeded",
                evidence={"rate_limit_remaining": 0}
            )
        
        # Check network connectivity
        network_error = context.get("network_error", None)
        if network_error:
            return PerspectiveAssessment(
                perspective=PerspectiveType.NETWORK,
                safe=False,
                confidence=Confidence.HIGH,
                reason=f"Network error detected: {network_error}",
                evidence={"network_error": network_error}
            )
        
        return PerspectiveAssessment(
            perspective=PerspectiveType.NETWORK,
            safe=True,
            confidence=Confidence.HIGH if auth_state == "valid" else Confidence.MEDIUM,
            reason="Network state is healthy",
            evidence={"auth_state": auth_state}
        )


class JSPerspective:
    """JS perspective - dynamic state, event handlers."""
    
    def assess(self, action: TypedAction, evidence: ActionabilityEvidence, context: Dict) -> PerspectiveAssessment:
        """Assess action from JavaScript perspective."""
        # Check if element has event handlers
        has_handlers = context.get("has_event_handlers", True)
        if not has_handlers:
            return PerspectiveAssessment(
                perspective=PerspectiveType.JS,
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Target element has no event handlers",
                evidence={"has_event_handlers": False}
            )
        
        # Check if JS is in error state
        js_error = context.get("js_error", None)
        if js_error:
            return PerspectiveAssessment(
                perspective=PerspectiveType.JS,
                safe=False,
                confidence=Confidence.HIGH,
                reason=f"JavaScript error detected: {js_error}",
                evidence={"js_error": js_error}
            )
        
        # Check if element is in loading state
        is_loading = context.get("is_loading", False)
        if is_loading:
            return PerspectiveAssessment(
                perspective=PerspectiveType.JS,
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Element or page is in loading state",
                evidence={"is_loading": True}
            )
        
        return PerspectiveAssessment(
            perspective=PerspectiveType.JS,
            safe=True,
            confidence=Confidence.HIGH,
            reason="JavaScript state is stable",
            evidence={"has_event_handlers": True, "is_loading": False}
        )


class SafetyPerspective:
    """Safety perspective - risk assessment (payments, data loss)."""
    
    def assess(self, action: TypedAction, evidence: ActionabilityEvidence, context: Dict) -> PerspectiveAssessment:
        """Assess action from safety perspective."""
        # Check for high-risk actions
        risk_level = context.get("risk_level", "low")
        
        if risk_level == "critical":
            # Payment, deletion, or irreversible action
            action_type = context.get("action_category", "")
            return PerspectiveAssessment(
                perspective=PerspectiveType.SAFETY,
                safe=False,
                confidence=Confidence.HIGH,
                reason=f"Critical risk action detected: {action_type}",
                evidence={"risk_level": "critical", "action_category": action_type}
            )
        
        if risk_level == "high":
            # Requires user confirmation
            return PerspectiveAssessment(
                perspective=PerspectiveType.SAFETY,
                safe=False,
                confidence=Confidence.HIGH,
                reason="High-risk action requires user confirmation",
                evidence={"risk_level": "high"}
            )
        
        # Check for payment indicators
        is_payment = context.get("is_payment", False)
        if is_payment:
            payment_amount = context.get("payment_amount", "unknown")
            return PerspectiveAssessment(
                perspective=PerspectiveType.SAFETY,
                safe=False,
                confidence=Confidence.HIGH,
                reason=f"Payment action detected (amount: {payment_amount})",
                evidence={"is_payment": True, "payment_amount": payment_amount}
            )
        
        return PerspectiveAssessment(
            perspective=PerspectiveType.SAFETY,
            safe=True,
            confidence=Confidence.HIGH,
            reason="No safety risks detected",
            evidence={"risk_level": risk_level}
        )


class HistoryPerspective:
    """History perspective - past action outcomes, learned patterns."""
    
    def assess(self, action: TypedAction, evidence: ActionabilityEvidence, context: Dict) -> PerspectiveAssessment:
        """Assess action from history perspective."""
        # Check past action outcomes for this target
        past_failures = context.get("past_failures", 0)
        if past_failures >= 3:
            return PerspectiveAssessment(
                perspective=PerspectiveType.HISTORY,
                safe=False,
                confidence=Confidence.HIGH,
                reason=f"Action has failed {past_failures} times previously",
                evidence={"past_failures": past_failures}
            )
        
        # Check for known patterns
        known_pattern = context.get("known_pattern", None)
        if known_pattern == "success":
            return PerspectiveAssessment(
                perspective=PerspectiveType.HISTORY,
                safe=True,
                confidence=Confidence.HIGH,
                reason="Action matches successful pattern from history",
                evidence={"known_pattern": "success"}
            )
        
        if known_pattern == "failure":
            return PerspectiveAssessment(
                perspective=PerspectiveType.HISTORY,
                safe=False,
                confidence=Confidence.MEDIUM,
                reason="Action matches failed pattern from history",
                evidence={"known_pattern": "failure"}
            )
        
        # No history available
        return PerspectiveAssessment(
            perspective=PerspectiveType.HISTORY,
            safe=True,
            confidence=Confidence.LOW,
            reason="No historical data available for this action",
            evidence={}
        )


class PerspectiveEngine:
    """Multi-perspective conflict resolution engine."""
    
    def __init__(self):
        self.perspectives = {
            PerspectiveType.USER: UserPerspective(),
            PerspectiveType.DOM: DOMPerspective(),
            PerspectiveType.VISUAL: VisualPerspective(),
            PerspectiveType.NETWORK: NetworkPerspective(),
            PerspectiveType.JS: JSPerspective(),
            PerspectiveType.SAFETY: SafetyPerspective(),
            PerspectiveType.HISTORY: HistoryPerspective(),
        }
    
    def analyze(
        self,
        action: TypedAction,
        evidence: ActionabilityEvidence,
        context: Dict,
        enabled_perspectives: Optional[Set[PerspectiveType]] = None
    ) -> ConflictResolution:
        """Analyze action from multiple perspectives and resolve conflicts.
        
        Args:
            action: The typed action to analyze
            evidence: Actionability evidence for the target
            context: Additional context (auth state, risk level, etc.)
            enabled_perspectives: Which perspectives to use (default: all)
        
        Returns:
            ConflictResolution with strategy and reasoning
        """
        if enabled_perspectives is None:
            enabled_perspectives = list(self.perspectives.keys())
        
        # Collect assessments from all enabled perspectives
        assessments = []
        for perspective_type in enabled_perspectives:
            perspective = self.perspectives[perspective_type]
            assessment = perspective.assess(action, evidence, context)
            assessments.append(assessment)
        
        # Resolve conflicts
        return self._resolve_conflicts(assessments, action, context)
    
    def _resolve_conflicts(
        self,
        assessments: List[PerspectiveAssessment],
        action: TypedAction,
        context: Dict
    ) -> ConflictResolution:
        """Resolve conflicts between perspective assessments."""
        # Count safe vs unsafe assessments
        safe_count = sum(1 for a in assessments if a.safe)
        unsafe_count = len(assessments) - safe_count
        
        # Check for critical safety veto
        safety_assessment = next(
            (a for a in assessments if a.perspective == PerspectiveType.SAFETY),
            None
        )
        if safety_assessment and not safety_assessment.safe:
            risk_level = safety_assessment.evidence.get("risk_level", "")
            if risk_level == "critical":
                return ConflictResolution(
                    strategy=ResolutionStrategy.ABORT,
                    assessments=assessments,
                    reason=f"Safety veto: {safety_assessment.reason}",
                )
            elif risk_level == "high" or "payment" in safety_assessment.reason.lower():
                # High-risk and payment actions require user confirmation (ASK)
                return ConflictResolution(
                    strategy=ResolutionStrategy.ASK,
                    assessments=assessments,
                    reason=f"Confirmation required: {safety_assessment.reason}",
                )
        
        # All perspectives agree it's safe
        if unsafe_count == 0:
            return ConflictResolution(
                strategy=ResolutionStrategy.ACTION,
                assessments=assessments,
                reason="All perspectives agree action is safe",
            )
        
        # All perspectives agree it's unsafe
        if safe_count == 0:
            # Count high-confidence unsafe assessments
            high_confidence_unsafe = [
                a for a in assessments
                if not a.safe and a.confidence == Confidence.HIGH
            ]
            
            # If multiple high-confidence issues, abort (too many problems to recover)
            if len(high_confidence_unsafe) > 1:
                return ConflictResolution(
                    strategy=ResolutionStrategy.ABORT,
                    assessments=assessments,
                    reason="Multiple critical issues detected - action is unsafe",
                )
            
            # Single recoverable issue - check if we can suggest recovery
            if len(high_confidence_unsafe) == 1:
                primary_concern = high_confidence_unsafe[0]
                if primary_concern.perspective == PerspectiveType.NETWORK:
                    if "expired" in primary_concern.reason.lower():
                        return ConflictResolution(
                            strategy=ResolutionStrategy.RECOVER,
                            assessments=assessments,
                            reason="Authentication expired - suggest re-authentication",
                            suggested_action="re_authenticate",
                        )
            
            return ConflictResolution(
                strategy=ResolutionStrategy.ABORT,
                assessments=assessments,
                reason="All perspectives agree action is unsafe",
            )
        
        # Mixed assessments - need to analyze conflicts
        high_confidence_unsafe = [
            a for a in assessments
            if not a.safe and a.confidence == Confidence.HIGH
        ]
        
        # Check if safe assessments are only low-confidence
        high_confidence_safe = [
            a for a in assessments
            if a.safe and a.confidence == Confidence.HIGH
        ]
        
        # If we have multiple high-confidence unsafe but no high-confidence safe,
        # treat as effectively "all unsafe" - abort
        if len(high_confidence_unsafe) > 1 and len(high_confidence_safe) == 0:
            return ConflictResolution(
                strategy=ResolutionStrategy.ABORT,
                assessments=assessments,
                reason="Multiple critical technical issues detected - action is unsafe",
            )
        
        if high_confidence_unsafe:
            # High-confidence unsafe assessment takes precedence
            primary_concern = high_confidence_unsafe[0]
            
            # Check if recoverable
            if primary_concern.perspective == PerspectiveType.NETWORK:
                return ConflictResolution(
                    strategy=ResolutionStrategy.RECOVER,
                    assessments=assessments,
                    reason=f"Network issue detected: {primary_concern.reason}",
                    suggested_action="retry_with_auth" if "auth" in primary_concern.reason.lower() else "retry",
                )
            
            if primary_concern.perspective == PerspectiveType.VISUAL:
                return ConflictResolution(
                    strategy=ResolutionStrategy.RECOVER,
                    assessments=assessments,
                    reason=f"Visual issue detected: {primary_concern.reason}",
                    suggested_action="wait_for_visibility",
                )
            
            return ConflictResolution(
                strategy=ResolutionStrategy.ABORT,
                assessments=assessments,
                reason=f"High-confidence concern: {primary_concern.reason}",
            )
        
        # Low-confidence conflicts - ask for clarification
        return ConflictResolution(
            strategy=ResolutionStrategy.ASK,
            assessments=assessments,
            reason=f"Conflicting assessments ({safe_count} safe, {unsafe_count} unsafe) - need clarification",
        )
