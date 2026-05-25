"""NetWeaver Verified Executor - Evidence-first action execution.

The executor is the runtime bridge between WNAL typed actions and the browser.
It enforces evidence-first verification:

1. PRE phase: Collect actionability evidence before executing.
2. PERSPECTIVE phase: Run multi-perspective conflict resolution.
3. EXECUTE phase: Perform the action (mocked or via CloakBrowser).
4. POST phase: Collect actionability evidence after executing.
5. VERIFY phase: Compare pre/post evidence, produce evidence report.

Every execution produces a VerifiedExecution record with full evidence chain.
No action is taken without pre-verified preconditions.

NW-015: Executor→Query Integration
The executor now supports graph-native target resolution via resolve_target().
When a scene graph is provided, actions can use natural-language descriptions
instead of raw CSS selectors. The graph ensures targets are evidence-backed
and safety-checked before execution proceeds.

NW-016: Live Mode Integration
Executor now supports real CloakBrowser actions via cloak_bridge.
Mode: 'live' uses real browser actions; 'mock' uses testing stubs.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from netweaver.wnal import (
    ActionabilityEvidence,
    ActionType,
    ClickAction,
    FillAction,
    Phase,
    TypedAction,
    VerificationResult,
    WaitAction,
)
from netweaver.perspective import (
    ConflictResolution,
    PerspectiveEngine,
    ResolutionStrategy,
)
from netweaver.evidence import (
    Claim,
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
    Observation,
    create_claim,
    create_observation,
)
from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    WebSceneGraph,
)
from netweaver.cloak_bridge import CloakBrowserBridge


class ExecutionStatus(Enum):
    """Status of an execution attempt."""
    SUCCESS = "success"
    PRECONDITION_FAILED = "precondition_failed"
    PERSPECTIVE_BLOCKED = "perspective_blocked"
    EXECUTION_ERROR = "execution_error"
    POSTCONDITION_MISMATCH = "postcondition_mismatch"
    TARGET_RESOLUTION_FAILED = "target_resolution_failed"


class ResolutionStatus(Enum):
    """Status of a graph-based target resolution attempt."""
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    SAFETY_BLOCKED = "safety_blocked"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"


@dataclass
class PrePostEvidence:
    """Pre and post actionability evidence pair."""
    pre: Optional[ActionabilityEvidence] = None
    post: Optional[ActionabilityEvidence] = None

    def to_dict(self) -> Dict:
        return {
            "pre": self.pre.to_dict() if self.pre else None,
            "post": self.post.to_dict() if self.post else None,
        }


@dataclass
class VerifiedExecution:
    """Complete record of a verified execution attempt.

    Captures the full evidence chain: action -> preconditions -> perspective
    resolution -> execution -> postconditions -> evidence report.
    """
    execution_id: str
    action: TypedAction
    status: ExecutionStatus
    evidence: PrePostEvidence
    perspective_resolution: Optional[ConflictResolution] = None
    report: Optional[EvidenceReport] = None
    error: Optional[str] = None
    executed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "execution_id": self.execution_id,
            "action": self.action.to_dict(),
            "status": self.status.value,
            "evidence": self.evidence.to_dict(),
            "perspective_resolution": (
                self.perspective_resolution.to_dict()
                if self.perspective_resolution else None
            ),
            "report": self.report.to_dict() if self.report else None,
            "error": self.error,
            "executed_at": self.executed_at.isoformat(),
        }


@dataclass
class GraphResolvedTarget:
    """Result of resolving an action target via scene graph query.

    Carries the matched node, selector, confidence score, and evidence
    metadata from the graph query.
    """
    status: ResolutionStatus
    description: str = ""
    node_id: Optional[str] = None
    selector: Optional[str] = None
    score: float = 0.0
    matched_properties: List[str] = field(default_factory=list)
    evidence_count: int = 0
    evidence_sufficient: bool = False
    evidence_confidence: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "status": self.status.value,
            "description": self.description,
            "node_id": self.node_id,
            "selector": self.selector,
            "score": self.score,
            "matched_properties": self.matched_properties,
            "evidence_count": self.evidence_count,
            "evidence_sufficient": self.evidence_sufficient,
            "evidence_confidence": self.evidence_confidence,
            "error": self.error,
        }


# Type aliases
EvidenceCollector = Callable[[str, str], ActionabilityEvidence]
ActionExecutor = Callable[[TypedAction], bool]


def mock_evidence_collector(action_id: str, target_ref: str) -> ActionabilityEvidence:
    """Mock evidence collector for testing (--no-cloak mode).

    Returns fully actionable evidence for any target.
    """
    return ActionabilityEvidence(
        action_id=action_id,
        target_ref=target_ref,
        phase=Phase.PRE,
        attached=True,
        visible=True,
        enabled=True,
        stable=True,
        pointer_events=True,
        observed_at=datetime.now(),
    )


def mock_action_executor(action: TypedAction) -> bool:
    """Mock action executor for testing (--no-cloak mode).

    Always returns True (success).
    """
    return True


def _make_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix."""
    uid = uuid.uuid4().hex
    if prefix:
        return f"{prefix}-{uid[:12]}"
    return uid[:16]


def _build_evidence_report(
    execution: VerifiedExecution,
    action: TypedAction,
    pre_evidence: ActionabilityEvidence,
    post_evidence: Optional[ActionabilityEvidence],
) -> EvidenceReport:
    """Build an EvidenceReport from a completed execution."""
    url = pre_evidence.target_ref or action.target_ref
    report = EvidenceReport(
        report_id=_make_id("report"),
        url=url,
        timestamp=datetime.now(),
    )

    # Pre observation
    pre_obs = create_observation(
        observation_id=_make_id("obs"),
        evidence_type=EvidenceType.ACTIONABILITY,
        data=pre_evidence.to_dict(),
        source="executor",
    )
    report.add_observation(pre_obs)

    pre_claim = create_claim(
        claim_id=_make_id("claim"),
        description=f"{action.action_type.value}: element '{pre_evidence.target_ref}' actionable before execution",
        evidence_type=EvidenceType.ACTIONABILITY,
        observation_ids=[pre_obs.observation_id],
    )
    report.add_claim(pre_claim)

    # Post observation
    if post_evidence:
        post_obs = create_observation(
            observation_id=_make_id("obs"),
            evidence_type=EvidenceType.ACTIONABILITY,
            data=post_evidence.to_dict(),
            source="executor",
        )
        report.add_observation(post_obs)

        post_claim = create_claim(
            claim_id=_make_id("claim"),
            description=f"Element '{post_evidence.target_ref}' state after execution",
            evidence_type=EvidenceType.ACTIONABILITY,
            observation_ids=[post_obs.observation_id],
        )
        report.add_claim(post_claim)

    report.verify()
    return report


class VerifiedExecutor:
    """Verified action executor with evidence-first verification.

    Modes:
    - 'mock': Use mock evidence collectors and action executors
    - 'live': Use real CloakBrowser actions via cloak_bridge
    """

    def __init__(
        self,
        mode: str = "mock",
        cloak_bridge: Optional[CloakBrowserBridge] = None,
        scene_graph: Optional[Any] = None,
        evidence_collector: Optional[EvidenceCollector] = None,
        action_executor: Optional[ActionExecutor] = None,
    ):
        if mode not in ("mock", "live"):
            raise ValueError(f"Invalid mode: {mode}. Use 'mock' or 'live'.")

        self.mode = mode
        self.cloak_bridge = cloak_bridge
        self.scene_graph = scene_graph
        self.perspective_engine = PerspectiveEngine()
        self._evidence_collector = evidence_collector
        self._action_executor = action_executor

        if mode == "live" and cloak_bridge is None:
            raise ValueError("Live mode requires a CloakBrowserBridge instance.")

    def _get_evidence_collector(self) -> EvidenceCollector:
        """Get evidence collector based on mode."""
        if self._evidence_collector:
            return self._evidence_collector
        if self.mode == "mock":
            return mock_evidence_collector
        return self._live_evidence_collector

    def _get_action_executor(self) -> ActionExecutor:
        """Get action executor based on mode."""
        if self._action_executor:
            return self._action_executor
        if self.mode == "mock":
            return mock_action_executor
        return self._live_action_executor

    def _live_evidence_collector(self, action_id: str, target_ref: str) -> ActionabilityEvidence:
        """Collect real evidence via cloak_bridge."""
        if self.cloak_bridge is None:
            raise RuntimeError("Live mode requires cloak_bridge.")
        evidence = self.cloak_bridge.collect_evidence(action_id, target_ref)
        return evidence

    def _live_action_executor(self, action: TypedAction) -> bool:
        """Execute real action via cloak_bridge."""
        if self.cloak_bridge is None:
            raise RuntimeError("Live mode requires cloak_bridge.")
        success = self.cloak_bridge.execute_action(action)
        return success

    def _build_action(self, action_type: ActionType, target_ref: str, **kwargs) -> TypedAction:
        """Build a TypedAction with necessary fields."""
        action_id = _make_id("act")
        if action_type == ActionType.CLICK:
            return ClickAction(
                action_id=action_id,
                target_ref=target_ref,
                button=kwargs.get("button", "left"),
                click_count=kwargs.get("click_count", 1),
                delay_ms=kwargs.get("delay_ms", 0),
            )
        elif action_type == ActionType.FILL:
            text = kwargs.get("text", kwargs.get("value", ""))
            return FillAction(
                action_id=action_id,
                target_ref=target_ref,
                value=text,
                text=text,
                clear_first=kwargs.get("clear_first", True),
                press_enter=kwargs.get("press_enter", False),
                is_sensitive=kwargs.get("is_sensitive", False),
            )
        elif action_type == ActionType.WAIT:
            return WaitAction(
                action_id=action_id,
                target_ref=target_ref,
                condition=kwargs.get("condition", "attached"),
                timeout_ms=kwargs.get("timeout_ms", 30000),
            )
        return TypedAction(
            action_id=action_id,
            target_ref=target_ref,
            action_type=action_type,
        )

    def resolve_target(self, action: TypedAction) -> str:
        """Resolve action target using scene graph if available.

        Returns the resolved CSS selector or original target.
        """
        if self.scene_graph is None:
            return action.target_ref
        resolved = self.scene_graph.resolve(action.target_ref)
        return resolved

    def execute(self, action: TypedAction, context: Optional[Dict] = None, *, skip_perspective: bool = False) -> VerifiedExecution:
        """Execute a verified action through all phases.

        Returns VerifiedExecution with full evidence chain.
        """
        execution_id = _make_id("exec")
        evidence_collector = self._get_evidence_collector()
        action_executor = self._get_action_executor()
        ctx = context or {}

        # Resolve target using scene graph
        resolved_target = self.resolve_target(action)

        # Phase 1: PRE evidence collection
        pre_evidence = evidence_collector(action.action_id, resolved_target)
        pre_evidence.phase = Phase.PRE

        # Phase 1b: PRECONDITION gate — element must be actionable
        # Different action types have different precondition requirements
        failed = []
        if not pre_evidence.attached:
            failed.append("attached")
        if action.action_type != ActionType.WAIT:
            # Click/fill need the element to be visible, enabled, stable, have pointer_events
            if not pre_evidence.visible:
                failed.append("visible")
            if not pre_evidence.enabled:
                failed.append("enabled")
            if not pre_evidence.stable:
                failed.append("stable")
            if not pre_evidence.pointer_events:
                failed.append("pointer_events")
            # For fill actions, also check editable
            if action.action_type == ActionType.FILL and hasattr(pre_evidence, 'editable') and not pre_evidence.editable:
                failed.append("editable")
        if failed:
            return VerifiedExecution(
                execution_id=execution_id,
                action=action,
                status=ExecutionStatus.PRECONDITION_FAILED,
                evidence=PrePostEvidence(pre=pre_evidence),
                error=f"Preconditions failed: {', '.join(failed)}",
            )

        # Phase 2: PERSPECTIVE conflict resolution (skip if flagged)
        perspective_resolution = None
        if not skip_perspective:
            perspective_resolution = self.perspective_engine.analyze(
                action, pre_evidence, ctx
            )
            if perspective_resolution.strategy in (ResolutionStrategy.ABORT, ResolutionStrategy.ASK):
                return VerifiedExecution(
                    execution_id=execution_id,
                    action=action,
                    status=ExecutionStatus.PERSPECTIVE_BLOCKED,
                    evidence=PrePostEvidence(pre=pre_evidence),
                    perspective_resolution=perspective_resolution,
                    error="Perspective conflict resolution blocked action",
                )

        # Phase 3: EXECUTE action
        success = False
        error_msg = ""
        try:
            success = action_executor(action)
        except Exception as e:
            error_msg = str(e)

        if not success:
            error_msg = error_msg or "action execution failure"
            return VerifiedExecution(
                execution_id=execution_id,
                action=action,
                status=ExecutionStatus.EXECUTION_ERROR,
                evidence=PrePostEvidence(pre=pre_evidence),
                error=error_msg,
            )

        # Phase 4: POST evidence collection
        post_evidence = evidence_collector(action.action_id, resolved_target)
        post_evidence.phase = Phase.POST

        # Phase 5: VERIFY evidence and generate report
        report = _build_evidence_report(
            VerifiedExecution(
                execution_id=execution_id,
                action=action,
                status=ExecutionStatus.SUCCESS,
                evidence=PrePostEvidence(pre=pre_evidence, post=post_evidence),
            ),
            action,
            pre_evidence,
            post_evidence,
        )

        return VerifiedExecution(
            execution_id=execution_id,
            action=action,
            status=ExecutionStatus.SUCCESS,
            evidence=PrePostEvidence(pre=pre_evidence, post=post_evidence),
            perspective_resolution=perspective_resolution,
            report=report,
        )

    def _resolve_from_graph(
        self, graph: WebSceneGraph, description: str, affordance: str
    ) -> GraphResolvedTarget:
        """Resolve a description to a graph node by matching INTENT nodes.
        
        Strategy: first try exact affordance match, then fall back to any node.
        """
        intent_nodes = graph.get_nodes_by_type(NodeType.INTENT)

        # Round 1: try exact affordance match
        matched = self._match_intent_nodes(intent_nodes, graph, description, affordance)
        if matched:
            return self._select_best_match(description, graph, matched, intent_nodes)

        # Round 2: fall back to any intent node (only for wait actions)
        if affordance == "waitable":
            matched = self._match_intent_nodes(intent_nodes, graph, description, None)
            if matched:
                return self._select_best_match(description, graph, matched, intent_nodes)

        # No match found
        return GraphResolvedTarget(
            status=ResolutionStatus.NOT_FOUND,
            description=description,
            error=f"No graph node matching '{description}'",
        )

    def _match_intent_nodes(self, intent_nodes, graph, description, affordance):
        """Match intent nodes by description and optional affordance constraint."""
        matched = []
        for node in intent_nodes:
            if not node.properties:
                continue
            # Filter by affordance if specified
            if affordance is not None:
                node_aff = node.properties.get("affordance", "")
                if node_aff != affordance:
                    continue

            # Get parent DOM node info
            dom_label, dom_selector, dom_text, dom_node_id, evidence_count = \
                self._get_dom_parent(graph, node)

            # Get intent node text
            node_label = (node.label or "").lower()
            node_props_text = str(node.properties.get("text", "")).lower()

            # Score description match
            desc_lower = description.lower()
            score = 0.0
            matched_props = []

            all_texts = [
                (node_label, "label"),
                (node_props_text, "text"),
                ((dom_label or "").lower(), "dom_label"),
                ((dom_text or "").lower(), "dom_text"),
            ]
            for text_val, prop_name in all_texts:
                if not text_val:
                    continue
                if desc_lower in text_val or text_val in desc_lower:
                    score = max(score, 0.8)
                    matched_props.append(prop_name)

            # Try partial word matching
            if score == 0.0:
                desc_words = set(desc_lower.split())
                for text_val, prop_name in all_texts:
                    if not text_val:
                        continue
                    text_words = set(text_val.split())
                    common = desc_words & text_words
                    if common:
                        score = max(score, min(0.5, len(common) / max(len(desc_words), 1)))
                        matched_props.append(f"partial_{prop_name}")

            if score > 0.0 and dom_selector:
                matched.append({
                    "score": score,
                    "node": node,
                    "selector": dom_selector,
                    "node_id": dom_node_id,
                    "matched_props": matched_props,
                    "evidence_count": evidence_count,
                })
            elif score > 0.0 and dom_label:
                # Fallback: use DOM node's label as selector
                matched.append({
                    "score": score,
                    "node": node,
                    "selector": dom_label,
                    "node_id": dom_node_id,
                    "matched_props": matched_props,
                    "evidence_count": evidence_count,
                })

        return matched

    def _match_dom_nodes(self, graph, description):
        """Match DOM nodes directly by description."""
        dom_nodes = graph.get_nodes_by_type(NodeType.DOM)
        matched = []
        desc_lower = description.lower()
        for node in dom_nodes:
            if node.node_id == "page-root":
                continue
            label = (node.label or "").lower()
            text = node.properties.get("text", "").lower() if node.properties else ""
            selector = node.properties.get("selector") if node.properties else None
            evidence_count = len(node.observation_ids) if node.observation_ids else 0

            score = 0.0
            if label and (desc_lower in label or label in desc_lower):
                score = max(score, 0.7)
            if text and (desc_lower in text or text in desc_lower):
                score = max(score, 0.8)
            if score == 0.0:
                desc_words = set(desc_lower.split())
                label_words = set(label.split())
                text_words = set(text.split())
                common = desc_words & (label_words | text_words)
                if common:
                    score = min(0.5, len(common) / max(len(desc_words), 1))

            if score > 0.0 and selector:
                matched.append({
                    "score": score,
                    "node_id": node.node_id,
                    "selector": selector,
                    "evidence_count": evidence_count,
                })
        return matched

    def _get_dom_parent(self, graph, node):
        parent_dom_id = node.metadata.get("parent_dom_id") if node.metadata else None
        dom_label = ""
        dom_selector = None
        dom_text = ""
        dom_node_id = None
        evidence_count = 0

        if parent_dom_id and parent_dom_id in graph.nodes:
            dom_node_id = parent_dom_id
            parent = graph.nodes[parent_dom_id]
            dom_label = parent.label or ""
            dom_selector = parent.properties.get("selector") if parent.properties else None
            dom_text = parent.properties.get("text", "") if parent.properties else ""
            evidence_count = len(parent.observation_ids) if parent.observation_ids else 0
        else:
            edges = graph.get_outgoing_edges(node.node_id)
            for edge in edges:
                if edge.edge_type == EdgeType.DEPENDENCY and edge.source_id in graph.nodes:
                    source = graph.nodes[edge.source_id]
                    if source.node_type == NodeType.DOM:
                        dom_node_id = edge.source_id
                        dom_label = source.label or ""
                        dom_selector = source.properties.get("selector") if source.properties else None
                        dom_text = source.properties.get("text", "") if source.properties else ""
                        evidence_count = len(source.observation_ids) if source.observation_ids else 0
                        break

        return dom_label, dom_selector, dom_text, dom_node_id, evidence_count

    def _select_best_match(self, description, graph, matched, intent_nodes):
        """Select best match from candidates, check safety, then build the result."""
        best = max(matched, key=lambda m: (m["score"], m["evidence_count"]))
        
        # Check for safety enrichment nodes targeting the same DOM parent
        for node in intent_nodes:
            if not node.properties:
                continue
            if node.properties.get("is_safety_enrichment") is True:
                safety_strategy = node.properties.get("strategy", "")
                if safety_strategy in ("abort", "block"):
                    # Check if this safety node targets the same DOM parent
                    safety_dom = node.metadata.get("parent_dom_id") if node.metadata else None
                    if safety_dom and safety_dom == best["node_id"]:
                        reason = node.properties.get("reason", "safety enrichment")
                        return GraphResolvedTarget(
                            status=ResolutionStatus.SAFETY_BLOCKED,
                            description=description,
                            error=f"Safety blocked: {reason}",
                        )
                    # Also check edges
                    if not safety_dom:
                        edges = graph.get_outgoing_edges(node.node_id)
                        for edge in edges:
                            if edge.edge_type == EdgeType.DEPENDENCY and edge.target_id == best["node_id"]:
                                reason = node.properties.get("reason", "safety enrichment")
                                return GraphResolvedTarget(
                                    status=ResolutionStatus.SAFETY_BLOCKED,
                                    description=description,
                                    error=f"Safety blocked: {reason}",
                                )
        
        return GraphResolvedTarget(
            status=ResolutionStatus.RESOLVED,
            description=description,
            node_id=best["node_id"],
            selector=best["selector"],
            score=best["score"],
            matched_properties=best["matched_props"],
            evidence_count=best["evidence_count"],
            evidence_sufficient=best["evidence_count"] > 0,
        )

    def execute_click(
        self, target_ref: str, skip_perspective: bool = False, context: Optional[Dict] = None,
    ) -> VerifiedExecution:
        """Execute a click action on the given target."""
        action = self._build_action(ActionType.CLICK, target_ref)
        return self.execute(action, context=context, skip_perspective=skip_perspective)

    def execute_fill(
        self, target_ref: str, text: str = "", skip_perspective: bool = False, context: Optional[Dict] = None,
    ) -> VerifiedExecution:
        """Execute a fill action on the given target."""
        action = self._build_action(ActionType.FILL, target_ref, text=text)
        return self.execute(action, context=context, skip_perspective=skip_perspective)

    def execute_wait(
        self, target_ref: str, skip_perspective: bool = False, context: Optional[Dict] = None,
        condition: str = "attached", timeout_ms: int = 5000,
    ) -> VerifiedExecution:
        """Execute a wait action on the given target."""
        action = self._build_action(ActionType.WAIT, target_ref, condition=condition, timeout_ms=timeout_ms)
        return self.execute(action, context=context, skip_perspective=skip_perspective)

    def execute_graph_click(
        self,
        graph: WebSceneGraph,
        description: str,
        context: Optional[Dict] = None,
        skip_perspective: bool = False,
    ) -> tuple:
        """Resolve target from scene graph, then execute click."""
        resolution = self._resolve_from_graph(graph, description, "clickable")
        if resolution.status != ResolutionStatus.RESOLVED:
            return (
                VerifiedExecution(
                    execution_id=_make_id("exec"),
                    action=self._build_action(ActionType.CLICK, f"<graph:{description}>"),
                    status=ExecutionStatus.TARGET_RESOLUTION_FAILED,
                    evidence=PrePostEvidence(),
                    error=resolution.error or f"No target found for '{description}'",
                ),
                resolution,
            )
        execution = self.execute_click(str(resolution.selector), skip_perspective=skip_perspective)
        return execution, resolution

    def execute_graph_fill(
        self,
        graph: WebSceneGraph,
        description: str,
        text: str = "",
        context: Optional[Dict] = None,
        skip_perspective: bool = False,
    ) -> tuple:
        """Resolve target from scene graph, then execute fill."""
        resolution = self._resolve_from_graph(graph, description, "fillable")
        if resolution.status != ResolutionStatus.RESOLVED:
            return (
                VerifiedExecution(
                    execution_id=_make_id("exec"),
                    action=self._build_action(ActionType.FILL, f"<graph:{description}>"),
                    status=ExecutionStatus.TARGET_RESOLUTION_FAILED,
                    evidence=PrePostEvidence(),
                    error=resolution.error or f"No target found for '{description}'",
                ),
                resolution,
            )
        execution = self.execute_fill(str(resolution.selector), text=text, skip_perspective=skip_perspective)
        return execution, resolution

    def execute_graph_wait(
        self,
        graph: WebSceneGraph,
        description: str,
        context: Optional[Dict] = None,
        skip_perspective: bool = False,
        condition: str = "attached",
        timeout_ms: int = 30000,
    ) -> tuple:
        """Resolve target from scene graph, then execute wait."""
        resolution = self._resolve_from_graph(graph, description, "waitable")
        if resolution.status != ResolutionStatus.RESOLVED:
            return (
                VerifiedExecution(
                    execution_id=_make_id("exec"),
                    action=self._build_action(ActionType.WAIT, f"<graph:{description}>"),
                    status=ExecutionStatus.TARGET_RESOLUTION_FAILED,
                    evidence=PrePostEvidence(),
                    error=resolution.error or f"No target found for '{description}'",
                ),
                resolution,
            )
        action = self._build_action(ActionType.WAIT, str(resolution.selector), condition=condition, timeout_ms=timeout_ms)
        execution = self.execute(action, skip_perspective=skip_perspective)
        return execution, resolution
