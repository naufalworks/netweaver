"""NetWeaver SceneGraph Builder — Observer → SceneGraph pipeline.

This is the critical novelty-bridging module that connects NetWeaver's
standalone components into an executable pipeline:

1. **Input**: PageObservation from observer.py
2. **Transform**: observer_evidence_adapter.py → EvidenceReport → SceneGraph nodes/edges
3. **Enrich**: perspective.py analysis adds INTENT/SAFETY metadata
4. **Output**: populated WebSceneGraph representing browser-native world state

The scene graph is NOT a DOM tree or a11y tree — it's a multi-perspective
evidence-linked directed graph that captures causality, intent, and safety
constraints. Once this builder exists, the executor can query the graph to
find safe action targets instead of operating on raw selectors.

Pipeline:
  PageObservation → EvidenceReport → DOM/Network/Visual/A11y nodes
                                → CONTAINMENT/EVIDENCE/CAUSALITY edges
                                → optional PerspectiveEngine enrichment
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
)
from netweaver.evidence import (
    Claim,
    EvidenceReport,
    EvidenceType,
    Observation,
)
from netweaver.observer_evidence_adapter import (
    observation_to_report,
    element_to_dom_observation,
    element_to_actionability_observation,
    network_to_observation,
)
from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    SceneEdge,
    SceneNode,
    WebSceneGraph,
    create_edge,
    create_node,
    create_scene_graph,
)


# ---------------------------------------------------------------------------
# Builder configuration
# ---------------------------------------------------------------------------

@dataclass
class BuilderConfig:
    """Configuration for the SceneGraphBuilder.

    Attributes:
        include_a11y_nodes: Generate ACCESSIBILITY nodes from aria_label data.
        include_visual_nodes: Generate VISUAL nodes from visibility data.
        include_network_nodes: Generate NETWORK nodes from NetworkActivity.
        include_intent_nodes: Generate INTENT nodes for actionable elements.
        include_containment_edges: Create CONTAINMENT edges (page → element).
        include_evidence_edges: Create EVIDENCE edges (node → observation).
        run_perspective_enrichment: Run PerspectiveEngine and add SAFETY nodes.
        node_id_prefix: Prefix for generated node IDs.
    """
    include_a11y_nodes: bool = True
    include_visual_nodes: bool = True
    include_network_nodes: bool = True
    include_intent_nodes: bool = True
    include_containment_edges: bool = True
    include_evidence_edges: bool = True
    run_perspective_enrichment: bool = False
    node_id_prefix: str = "sgb"


# ---------------------------------------------------------------------------
# Builder result
# ---------------------------------------------------------------------------

@dataclass
class BuilderResult:
    """Result of building a scene graph from a PageObservation.

    Attributes:
        graph: The populated WebSceneGraph.
        evidence_report: The EvidenceReport used to build the graph.
        stats: Build statistics.
        warnings: Non-fatal issues encountered during build.
    """
    graph: WebSceneGraph
    evidence_report: EvidenceReport
    stats: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SceneGraphBuilder
# ---------------------------------------------------------------------------

class SceneGraphBuilder:
    """Builds a WebSceneGraph from a PageObservation.

    The builder orchestrates the full pipeline:
      1. Convert PageObservation → EvidenceReport via the adapter.
      2. Create DOM nodes for each interactive element.
      3. Create ACCESSIBILITY nodes from ARIA labels.
      4. Create VISUAL nodes from visibility/actionability data.
      5. Create NETWORK nodes from NetworkActivity.
      6. Create INTENT nodes for actionable elements (affordances).
      7. Create CONTAINMENT edges (page root → elements).
      8. Create EVIDENCE edges linking nodes to observation IDs.
      9. Optionally run PerspectiveEngine enrichment for SAFETY nodes.
    """

    def __init__(self, config: Optional[BuilderConfig] = None):
        self.config = config or BuilderConfig()
        self._warnings: List[str] = []

    def _make_id(self, prefix: str) -> str:
        """Generate a unique ID with the configured prefix."""
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    # --- Node builders ---

    def _build_dom_node(
        self,
        element: InteractiveElement,
        dom_obs: Observation,
        act_obs: Optional[Observation],
    ) -> SceneNode:
        """Create a DOM node from an interactive element."""
        props: Dict[str, Any] = {
            "selector": element.selector,
            "tag": element.tag,
            "type": element.type,
            "text": element.text,
        }
        obs_ids = [dom_obs.observation_id]
        if act_obs:
            obs_ids.append(act_obs.observation_id)

        return create_node(
            node_type=NodeType.DOM,
            label=f"{element.tag}#{element.selector.split('#')[-1].split(':')[0]}",
            properties=props,
            observation_ids=obs_ids,
            metadata={"source": "observer"},
        )

    def _build_a11y_node(
        self,
        element: InteractiveElement,
        parent_dom_id: str,
        act_obs: Optional[Observation],
    ) -> Optional[SceneNode]:
        """Create an ACCESSIBILITY node from ARIA label data."""
        if not element.aria_label:
            return None

        props: Dict[str, Any] = {
            "aria_label": element.aria_label,
            "role": element.type or element.tag,
            "selector": element.selector,
        }
        obs_ids: List[str] = []
        if act_obs:
            obs_ids.append(act_obs.observation_id)

        return create_node(
            node_type=NodeType.ACCESSIBILITY,
            label=f"a11y:{element.aria_label[:30]}",
            properties=props,
            observation_ids=obs_ids,
            metadata={"source": "observer", "parent_dom_id": parent_dom_id},
        )

    def _build_visual_node(
        self,
        element: InteractiveElement,
        parent_dom_id: str,
        act_obs: Optional[Observation],
    ) -> Optional[SceneNode]:
        """Create a VISUAL node from actionability visibility data."""
        if not element.actionability:
            return None

        visible = element.actionability.get("visible", False)
        props: Dict[str, Any] = {
            "selector": element.selector,
            "visible": visible,
            "enabled": element.actionability.get("enabled", False),
            "editable": element.actionability.get("editable", False),
            "pointer_events": element.actionability.get("pointer_events", False),
        }
        obs_ids: List[str] = []
        if act_obs:
            obs_ids.append(act_obs.observation_id)

        return create_node(
            node_type=NodeType.VISUAL,
            label=f"vis:{element.selector}({'v' if visible else 'h'})",
            properties=props,
            observation_ids=obs_ids,
            metadata={"source": "observer", "parent_dom_id": parent_dom_id},
        )

    def _build_network_node(
        self,
        network: NetworkActivity,
        net_obs: Observation,
    ) -> SceneNode:
        """Create a NETWORK node from network activity."""
        props: Dict[str, Any] = {
            "requests_count": network.requests_count,
            "responses_count": network.responses_count,
            "failed_count": network.failed_count,
            "resource_types": network.resource_types,
            "healthy": network.failed_count == 0,
        }

        return create_node(
            node_type=NodeType.NETWORK,
            label=f"net:{network.requests_count}req/{network.failed_count}fail",
            properties=props,
            observation_ids=[net_obs.observation_id],
            metadata={"source": "observer"},
        )

    def _build_intent_node(
        self,
        element: InteractiveElement,
        parent_dom_id: str,
        act_obs: Optional[Observation],
    ) -> Optional[SceneNode]:
        """Create an INTENT node representing element affordance.

        Intent nodes capture what actions the element affords:
        - clickable (buttons, links)
        - fillable (inputs, textareas)
        - selectable (select elements)
        """
        if not element.actionability:
            return None

        # Only create intent for actionable elements
        visible = element.actionability.get("visible", False)
        enabled = element.actionability.get("enabled", False)
        if not (visible and enabled):
            return None

        # Determine affordance type
        affordance = self._classify_affordance(element)

        props: Dict[str, Any] = {
            "selector": element.selector,
            "affordance": affordance,
            "tag": element.tag,
            "text": element.text,
            "aria_label": element.aria_label,
        }
        obs_ids: List[str] = []
        if act_obs:
            obs_ids.append(act_obs.observation_id)

        return create_node(
            node_type=NodeType.INTENT,
            label=f"intent:{affordance}({element.selector})",
            properties=props,
            observation_ids=obs_ids,
            metadata={
                "source": "inferred",
                "parent_dom_id": parent_dom_id,
            },
        )

    def _classify_affordance(self, element: InteractiveElement) -> str:
        """Classify what action an element affords."""
        tag = element.tag.lower()
        elem_type = (element.type or "").lower()

        if tag == "button" or elem_type == "submit":
            return "clickable"
        elif tag == "a":
            return "navigable"
        elif tag in ("input", "textarea"):
            if elem_type in ("checkbox", "radio"):
                return "toggleable"
            elif elem_type == "submit":
                return "clickable"
            else:
                return "fillable"
        elif tag == "select":
            return "selectable"
        else:
            return "interactable"

    # --- Edge builders ---

    def _build_containment_edge(
        self,
        parent_id: str,
        child_id: str,
    ) -> SceneEdge:
        """Create a CONTAINMENT edge (parent → child)."""
        return create_edge(
            source_id=parent_id,
            target_id=child_id,
            edge_type=EdgeType.CONTAINMENT,
            properties={"relationship": "contains"},
        )

    def _build_evidence_edge(
        self,
        node_id: str,
        observation_id: str,
    ) -> SceneEdge:
        """Create an EVIDENCE edge (node → observation ID as proxy)."""
        return create_edge(
            source_id=node_id,
            target_id=observation_id,
            edge_type=EdgeType.EVIDENCE,
            weight=1.0,
            properties={"observation_linked": True},
        )

    def _build_dependency_edge(
        self,
        source_id: str,
        target_id: str,
        dep_type: str = "enriches",
    ) -> SceneEdge:
        """Create a DEPENDENCY edge between complementary nodes."""
        return create_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=EdgeType.DEPENDENCY,
            properties={"dep_type": dep_type},
        )

    # --- Main build pipeline ---

    def build(
        self,
        page_obs: PageObservation,
        perspective_engine: Any = None,
    ) -> BuilderResult:
        """Build a WebSceneGraph from a PageObservation.

        Full pipeline:
          1. Convert observation → EvidenceReport
          2. Create page root node
          3. Create per-element nodes (DOM, A11Y, Visual, Intent)
          4. Create network node
          5. Create containment edges
          6. Create evidence edges
          7. Optionally enrich with perspective analysis

        Args:
            page_obs: Page observation from the observer.
            perspective_engine: Optional PerspectiveEngine for enrichment.
                Must have an `analyze()` method. Only used if
                config.run_perspective_enrichment is True.

        Returns:
            BuilderResult with the populated graph, evidence report, and stats.
        """
        self._warnings = []

        # Step 1: PageObservation → EvidenceReport
        evidence_report = observation_to_report(page_obs)

        # Step 2: Create the scene graph
        graph = create_scene_graph(
            url=page_obs.url,
            title=page_obs.title,
            metadata={
                "source": "scene_graph_builder",
                "element_count": len(page_obs.interactive_elements),
                "builder_config": {
                    "a11y": self.config.include_a11y_nodes,
                    "visual": self.config.include_visual_nodes,
                    "network": self.config.include_network_nodes,
                    "intent": self.config.include_intent_nodes,
                },
            },
        )

        # Create page root node
        page_root = create_node(
            node_type=NodeType.DOM,
            label=f"page:{page_obs.url[:50]}",
            properties={
                "url": page_obs.url,
                "title": page_obs.title,
                "is_root": True,
            },
            metadata={"source": "observer"},
        )
        graph.add_node(page_root)

        # Step 3: Create per-element nodes
        dom_node_ids: List[str] = []
        a11y_node_map: Dict[str, str] = {}  # dom_node_id -> a11y_node_id
        visual_node_map: Dict[str, str] = {}  # dom_node_id -> visual_node_id
        intent_node_map: Dict[str, str] = {}  # dom_node_id -> intent_node_id

        for i, element in enumerate(page_obs.interactive_elements):
            # Get observations for this element from the report
            dom_obs = element_to_dom_observation(element)
            act_obs = element_to_actionability_observation(element)

            # DOM node (always created)
            dom_node = self._build_dom_node(element, dom_obs, act_obs)
            graph.add_node(dom_node)
            dom_node_ids.append(dom_node.node_id)

            # Containment: page_root → dom_node
            if self.config.include_containment_edges:
                cont_edge = self._build_containment_edge(page_root.node_id, dom_node.node_id)
                graph.add_edge(cont_edge)

            # Evidence edge: dom_node → observation proxy
            if self.config.include_evidence_edges:
                # Create a lightweight proxy node for the observation
                obs_proxy = create_node(
                    node_type=NodeType.DOM,
                    label=f"obs:{dom_obs.observation_id[:20]}",
                    properties={"is_observation_proxy": True},
                    observation_ids=[dom_obs.observation_id],
                    metadata={"source": "evidence_adapter"},
                )
                graph.add_node(obs_proxy)
                ev_edge = self._build_evidence_edge(
                    dom_node.node_id, obs_proxy.node_id
                )
                graph.add_edge(ev_edge)

            # Accessibility node
            if self.config.include_a11y_nodes:
                a11y_node = self._build_a11y_node(element, dom_node.node_id, act_obs)
                if a11y_node:
                    graph.add_node(a11y_node)
                    a11y_node_map[dom_node.node_id] = a11y_node.node_id
                    if self.config.include_containment_edges:
                        graph.add_edge(self._build_containment_edge(
                            dom_node.node_id, a11y_node.node_id
                        ))
                    if self.config.include_evidence_edges:
                        graph.add_edge(self._build_dependency_edge(
                            a11y_node.node_id, dom_node.node_id, "enriches"
                        ))

            # Visual node
            if self.config.include_visual_nodes:
                vis_node = self._build_visual_node(element, dom_node.node_id, act_obs)
                if vis_node:
                    graph.add_node(vis_node)
                    visual_node_map[dom_node.node_id] = vis_node.node_id
                    if self.config.include_containment_edges:
                        graph.add_edge(self._build_containment_edge(
                            dom_node.node_id, vis_node.node_id
                        ))
                    if self.config.include_evidence_edges:
                        graph.add_edge(self._build_dependency_edge(
                            vis_node.node_id, dom_node.node_id, "enriches"
                        ))

            # Intent node
            if self.config.include_intent_nodes:
                intent_node = self._build_intent_node(
                    element, dom_node.node_id, act_obs
                )
                if intent_node:
                    graph.add_node(intent_node)
                    intent_node_map[dom_node.node_id] = intent_node.node_id
                    if self.config.include_containment_edges:
                        graph.add_edge(self._build_containment_edge(
                            dom_node.node_id, intent_node.node_id
                        ))
                    if self.config.include_evidence_edges:
                        graph.add_edge(self._build_dependency_edge(
                            intent_node.node_id, dom_node.node_id, "affords"
                        ))

        # Step 4: Network node
        net_node_id: Optional[str] = None
        if self.config.include_network_nodes:
            net_obs = network_to_observation(page_obs.network)
            net_node = self._build_network_node(page_obs.network, net_obs)
            graph.add_node(net_node)
            net_node_id = net_node.node_id
            if self.config.include_containment_edges:
                graph.add_edge(self._build_containment_edge(
                    page_root.node_id, net_node.node_id
                ))

        # Step 5: Build stats
        stats = {
            "dom_nodes": len(dom_node_ids),
            "a11y_nodes": len(a11y_node_map),
            "visual_nodes": len(visual_node_map),
            "intent_nodes": len(intent_node_map),
            "network_nodes": 1 if net_node_id else 0,
            "total_nodes": graph.node_count(),
            "total_edges": graph.edge_count(),
            "evidence_observations": len(evidence_report.observations),
            "evidence_claims": len(evidence_report.claims),
        }

        # Step 6: Optional perspective enrichment
        if self.config.run_perspective_enrichment and perspective_engine is not None:
            self._enrich_with_perspectives(
                graph, page_obs, evidence_report, dom_node_ids, perspective_engine
            )
            stats["perspective_enriched"] = True
            stats["total_nodes_after_enrichment"] = graph.node_count()
            stats["total_edges_after_enrichment"] = graph.edge_count()

        return BuilderResult(
            graph=graph,
            evidence_report=evidence_report,
            stats=stats,
            warnings=self._warnings,
        )

    def _enrich_with_perspectives(
        self,
        graph: WebSceneGraph,
        page_obs: PageObservation,
        evidence_report: EvidenceReport,
        dom_node_ids: List[str],
        perspective_engine: Any,
    ) -> None:
        """Enrich the graph with perspective analysis results.

        For each actionable element, runs the perspective engine and adds
        SAFETY nodes when risks are detected.
        """
        try:
            from netweaver.wnal import ActionabilityEvidence, TypedAction
        except ImportError:
            self._warnings.append("WNAL module not available for perspective enrichment")
            return

        for i, element in enumerate(page_obs.interactive_elements):
            if not element.actionability:
                continue

            # Build WNAL types for perspective engine
            try:
                action = TypedAction(
                    action_id=f"perspective-check-{i}",
                    action_type="click",
                    selector=element.selector,
                )
                evidence = ActionabilityEvidence(
                    action_id=f"perspective-evidence-{i}",
                    selector=element.selector,
                    attached=element.actionability.get("attached", False),
                    visible=element.actionability.get("visible", False),
                    enabled=element.actionability.get("enabled", False),
                    editable=element.actionability.get("editable", False),
                    stable=element.actionability.get("stable", True),
                    pointer_events=element.actionability.get("pointer_events", True),
                )
                context: Dict[str, Any] = {
                    "user_goal": "inspect",
                    "risk_level": "low",
                }
                resolution = perspective_engine.analyze(action, evidence, context)

                # Add SAFETY node only for non-ACTION resolutions
                if resolution.strategy.value != "action":
                    safety_node = create_node(
                        node_type=NodeType.INTENT,
                        label=f"safety:{resolution.strategy.value}:{element.selector}",
                        properties={
                            "strategy": resolution.strategy.value,
                            "reason": resolution.reason,
                            "selector": element.selector,
                            "is_safety_enrichment": True,
                        },
                        metadata={"source": "perspective_engine"},
                    )
                    graph.add_node(safety_node)

                    if dom_node_ids and i < len(dom_node_ids):
                        graph.add_edge(self._build_dependency_edge(
                            safety_node.node_id,
                            dom_node_ids[i],
                            "safety_assessment",
                        ))
            except Exception as e:
                self._warnings.append(
                    f"Perspective enrichment failed for element {i}: {e}"
                )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def build_scene_graph(
    page_obs: PageObservation,
    config: Optional[BuilderConfig] = None,
    perspective_engine: Any = None,
) -> BuilderResult:
    """Build a WebSceneGraph from a PageObservation.

    Convenience function that creates a builder and runs the pipeline.

    Args:
        page_obs: Page observation from the observer.
        config: Optional builder configuration.
        perspective_engine: Optional PerspectiveEngine for enrichment.

    Returns:
        BuilderResult with the populated graph, evidence report, and stats.
    """
    builder = SceneGraphBuilder(config)
    return builder.build(page_obs, perspective_engine)
