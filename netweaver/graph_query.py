"""NetWeaver SceneGraph Query Layer — Evidence-native target resolution.

This is the semantic bridge that makes the executor graph-native. Instead of
operating on raw CSS selectors, the executor can query the scene graph for
safe, evidence-backed targets using high-level intent descriptions.

Core functions:
  - find_actionable_nodes: Find nodes matching an intent (click/fill/navigate)
  - resolve_target: Natural-language element description → best graph match
  - find_safe_path: BFS through safe edges, excluding SAFETY-blocked nodes
  - check_evidence_chain: Verify a node has sufficient observation backing

Design principles:
  - All queries are read-only (no graph mutation)
  - Safety nodes can block traversal
  - Evidence backing is required for high-confidence results
  - Fuzzy text matching for natural-language target resolution
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    SceneEdge,
    SceneNode,
    WebSceneGraph,
)


# ---------------------------------------------------------------------------
# Query types
# ---------------------------------------------------------------------------

class IntentType(Enum):
    """Action intent for node queries."""
    CLICK = "click"
    FILL = "fill"
    NAVIGATE = "navigate"
    SELECT = "select"
    TOGGLE = "toggle"
    ANY = "any"


# Affordance → Intent mapping (from scene_graph_builder affordances)
_AFFORDANCE_TO_INTENT: Dict[str, IntentType] = {
    "clickable": IntentType.CLICK,
    "fillable": IntentType.FILL,
    "navigable": IntentType.NAVIGATE,
    "selectable": IntentType.SELECT,
    "toggleable": IntentType.TOGGLE,
    "interactable": IntentType.ANY,
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class QueryMatch:
    """A single node match from a graph query.

    Attributes:
        node: The matched SceneNode.
        score: Confidence score (0.0-1.0). Higher is better.
        matched_properties: Which properties contributed to the match.
        blocked: Whether the node is blocked by a SAFETY assessment.
        block_reason: Why the node is blocked (if blocked).
        evidence_count: Number of backing observations.
    """
    node: SceneNode
    score: float = 1.0
    matched_properties: List[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None
    evidence_count: int = 0


@dataclass
class PathResult:
    """Result of a path search through the scene graph.

    Attributes:
        path: Ordered list of node IDs from source to target.
        edges: Ordered list of edge IDs traversed.
        length: Number of hops.
        blocked: Whether the path encounters a safety block.
        blocked_at: Node ID where the path is blocked (if blocked).
    """
    path: List[str] = field(default_factory=list)
    edges: List[str] = field(default_factory=list)
    length: int = 0
    blocked: bool = False
    blocked_at: Optional[str] = None


@dataclass
class EvidenceStatus:
    """Evidence chain verification result.

    Attributes:
        node_id: The node that was checked.
        has_evidence: Whether the node has any backing observations.
        observation_count: Number of observation IDs linked.
        evidence_types: Set of evidence domains present.
        confidence: 0.0-1.0 confidence based on observation count.
        sufficient: Whether evidence meets the minimum threshold.
    """
    node_id: str
    has_evidence: bool
    observation_count: int
    evidence_types: Set[str] = field(default_factory=set)
    confidence: float = 0.0
    sufficient: bool = False


# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------

def _is_safety_blocked(graph: WebSceneGraph, node_id: str) -> Tuple[bool, Optional[str]]:
    """Check if a node is blocked by a safety assessment node.

    A node is safety-blocked if any INTENT node with is_safety_enrichment=True
    has a DEPENDENCY edge pointing to it with strategy != "action".
    """
    incoming = graph.get_incoming_edges(node_id)
    for edge in incoming:
        if edge.edge_type != EdgeType.DEPENDENCY:
            continue
        source = graph.get_node(edge.source_id)
        if source is None:
            continue
        if (source.node_type == NodeType.INTENT and
                source.properties.get("is_safety_enrichment", False)):
            strategy = source.properties.get("strategy", "action")
            if strategy != "action":
                return True, source.properties.get("reason", "safety assessment")
    return False, None


def _get_safety_blocked_ids(graph: WebSceneGraph) -> Set[str]:
    """Get all node IDs that are blocked by safety assessments."""
    blocked: Set[str] = set()
    for node in graph.nodes.values():
        is_blocked, _ = _is_safety_blocked(graph, node.node_id)
        if is_blocked:
            blocked.add(node.node_id)
    return blocked


# ---------------------------------------------------------------------------
# Text matching helpers
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching: lowercase, strip, collapse whitespace."""
    # Strip CSS selector prefixes (# . :) for matching
    text = re.sub(r'[#.:]', ' ', text)
    return " ".join(text.lower().split())


def _text_similarity(query: str, target: str) -> float:
    """Simple token-overlap similarity between two strings.

    Returns a score from 0.0 to 1.0 based on how many query tokens
    appear in the target string.
    """
    q_tokens = set(_normalize_text(query).split())
    t_tokens = set(_normalize_text(target).split())
    if not q_tokens:
        return 0.0
    if not t_tokens:
        return 0.0
    overlap = q_tokens & t_tokens
    return len(overlap) / len(q_tokens)


# ---------------------------------------------------------------------------
# Core query functions
# ---------------------------------------------------------------------------

def find_actionable_nodes(
    graph: WebSceneGraph,
    intent: IntentType,
    *,
    min_evidence: int = 1,
    exclude_blocked: bool = True,
) -> List[QueryMatch]:
    """Find nodes matching an action intent.

    Searches INTENT nodes for matching affordance, then resolves
    back to their parent DOM nodes. Only returns nodes that are:
    - Not safety-blocked (unless exclude_blocked=False)
    - Backed by at least min_evidence observations

    Args:
        graph: The scene graph to query.
        intent: The desired action intent.
        min_evidence: Minimum observation count for a match.
        exclude_blocked: Whether to filter out safety-blocked nodes.

    Returns:
        List of QueryMatch sorted by score (highest first).
    """
    results: List[QueryMatch] = []

    # Get all INTENT nodes
    intent_nodes = graph.get_nodes_by_type(NodeType.INTENT)

    for intent_node in intent_nodes:
        # Skip safety enrichment nodes
        if intent_node.properties.get("is_safety_enrichment", False):
            continue

        affordance = intent_node.properties.get("affordance", "")
        node_intent = _AFFORDANCE_TO_INTENT.get(affordance, IntentType.ANY)

        # Check intent match
        if intent != IntentType.ANY and node_intent != intent and node_intent != IntentType.ANY:
            continue

        # Find parent DOM node
        parent_id = intent_node.metadata.get("parent_dom_id")
        parent = graph.get_node(parent_id) if parent_id else None
        target_node = parent if parent else intent_node

        # Check safety
        blocked, block_reason = _is_safety_blocked(graph, target_node.node_id)
        if exclude_blocked and blocked:
            continue

        # Check evidence
        evidence_count = len(target_node.observation_ids)

        # Skip if evidence below threshold
        if evidence_count < min_evidence:
            continue

        # Compute score
        score = 1.0
        if evidence_count == 0:
            score = 0.3
        if node_intent == IntentType.ANY:
            score *= 0.8  # Slight penalty for generic match

        results.append(QueryMatch(
            node=target_node,
            score=score,
            matched_properties=["affordance", "intent"],
            blocked=blocked,
            block_reason=block_reason,
            evidence_count=evidence_count,
        ))

    # Sort by score descending
    results.sort(key=lambda m: m.score, reverse=True)
    return results


def resolve_target(
    graph: WebSceneGraph,
    description: str,
    *,
    intent: Optional[IntentType] = None,
    min_score: float = 0.3,
    exclude_blocked: bool = True,
) -> Optional[QueryMatch]:
    """Resolve a natural-language element description to a graph node.

    Searches DOM and INTENT nodes for the best match based on:
    - Text content similarity
    - ARIA label match
    - Selector/class match
    - Intent affordance match

    Args:
        graph: The scene graph to query.
        description: Natural-language element description (e.g., "login button").
        intent: Optional intent filter to narrow candidates.
        min_score: Minimum similarity score for a match.
        exclude_blocked: Whether to exclude safety-blocked nodes.

    Returns:
        Best QueryMatch if found above min_score, else None.
    """
    candidates: List[QueryMatch] = []

    # Get candidate nodes: DOM nodes with properties
    dom_nodes = graph.get_nodes_by_type(NodeType.DOM)
    intent_nodes = graph.get_nodes_by_type(NodeType.INTENT)

    # Build a map of dom_node_id -> intent_node for cross-referencing
    dom_to_intent: Dict[str, SceneNode] = {}
    for inode in intent_nodes:
        if inode.properties.get("is_safety_enrichment", False):
            continue
        parent_id = inode.metadata.get("parent_dom_id")
        if parent_id:
            dom_to_intent[parent_id] = inode

    for dom_node in dom_nodes:
        # Skip root and proxy nodes
        if dom_node.properties.get("is_root", False):
            continue
        if dom_node.properties.get("is_observation_proxy", False):
            continue

        # Check safety
        blocked, block_reason = _is_safety_blocked(graph, dom_node.node_id)
        if exclude_blocked and blocked:
            continue

        # Check intent filter
        if intent is not None:
            matching_intent = dom_to_intent.get(dom_node.node_id)
            if matching_intent:
                affordance = matching_intent.properties.get("affordance", "")
                node_intent = _AFFORDANCE_TO_INTENT.get(affordance, IntentType.ANY)
                if (intent != IntentType.ANY and
                        node_intent != intent and
                        node_intent != IntentType.ANY):
                    continue
            elif intent != IntentType.ANY:
                continue  # No intent node, can't verify intent

        # Compute text similarity across multiple properties
        best_sim = 0.0
        matched_props: List[str] = []

        # Text content
        text = dom_node.properties.get("text", "")
        if text:
            sim = _text_similarity(description, text)
            if sim > best_sim:
                best_sim = sim
                matched_props = ["text"]

        # Label
        label = dom_node.label
        if label:
            sim = _text_similarity(description, label)
            if sim > best_sim:
                best_sim = sim
                matched_props = ["label"]

        # Selector
        selector = dom_node.properties.get("selector", "")
        if selector:
            sim = _text_similarity(description, selector)
            if sim > best_sim:
                best_sim = sim
                matched_props = ["selector"]

        # Check ARIA labels from linked accessibility nodes
        children = graph.get_children(dom_node.node_id)
        for child_id in children:
            child = graph.get_node(child_id)
            if child and child.node_type == NodeType.ACCESSIBILITY:
                aria = child.properties.get("aria_label", "")
                if aria:
                    sim = _text_similarity(description, aria)
                    if sim > best_sim:
                        best_sim = sim
                        matched_props = ["aria_label"]

        if best_sim < min_score:
            continue

        # Boost score for evidence backing
        evidence_count = len(dom_node.observation_ids)
        evidence_boost = min(0.2, evidence_count * 0.05)
        final_score = min(1.0, best_sim + evidence_boost)

        candidates.append(QueryMatch(
            node=dom_node,
            score=final_score,
            matched_properties=matched_props,
            blocked=blocked,
            block_reason=block_reason,
            evidence_count=evidence_count,
        ))

    if not candidates:
        return None

    candidates.sort(key=lambda m: m.score, reverse=True)
    return candidates[0]


def find_safe_path(
    graph: WebSceneGraph,
    source_id: str,
    target_id: str,
    *,
    allowed_edge_types: Optional[FrozenSet[EdgeType]] = None,
    max_depth: int = 20,
) -> PathResult:
    """Find a safe path between two nodes using BFS.

    Traverses through CONTAINMENT and EVIDENCE edges by default,
    excluding nodes that are blocked by SAFETY assessments.

    Args:
        graph: The scene graph to search.
        source_id: Starting node ID.
        target_id: Destination node ID.
        allowed_edge_types: Edge types to traverse (default: CONTAINMENT, EVIDENCE).
        max_depth: Maximum BFS depth.

    Returns:
        PathResult with the path, or a blocked/empty result.
    """
    if source_id not in graph.nodes or target_id not in graph.nodes:
        return PathResult()

    if source_id == target_id:
        return PathResult(path=[source_id], length=0)

    if allowed_edge_types is None:
        allowed_edge_types = frozenset({EdgeType.CONTAINMENT, EdgeType.EVIDENCE, EdgeType.DEPENDENCY})

    # Pre-compute safety-blocked nodes
    blocked_ids = _get_safety_blocked_ids(graph)

    # BFS
    visited: Set[str] = {source_id}
    queue: List[Tuple[str, List[str], List[str]]] = [(source_id, [source_id], [])]

    while queue:
        current_id, path, edge_path = queue.pop(0)

        if len(path) > max_depth:
            continue

        for edge in graph.get_outgoing_edges(current_id):
            if edge.edge_type not in allowed_edge_types:
                continue

            next_id = edge.target_id
            if next_id in visited:
                continue

            new_path = path + [next_id]
            new_edges = edge_path + [edge.edge_id]

            # Check if target is reached (check safety on target too)
            if next_id == target_id:
                is_blocked, block_reason = _is_safety_blocked(graph, next_id)
                if is_blocked:
                    return PathResult(
                        path=new_path,
                        edges=new_edges,
                        length=len(new_edges),
                        blocked=True,
                        blocked_at=next_id,
                    )
                return PathResult(
                    path=new_path,
                    edges=new_edges,
                    length=len(new_edges),
                    blocked=False,
                )

            # Check if blocked (intermediate)
            if next_id in blocked_ids:
                # Return partial result showing where block occurs
                return PathResult(
                    path=new_path,
                    edges=new_edges,
                    length=len(new_edges),
                    blocked=True,
                    blocked_at=next_id,
                )

            visited.add(next_id)
            queue.append((next_id, new_path, new_edges))

        # Also check incoming edges for bidirectional traversal
        for edge in graph.get_incoming_edges(current_id):
            if edge.edge_type not in allowed_edge_types:
                continue

            next_id = edge.source_id
            if next_id in visited:
                continue

            new_path = path + [next_id]
            new_edges = edge_path + [edge.edge_id]

            if next_id == target_id:
                is_blocked, _ = _is_safety_blocked(graph, next_id)
                if is_blocked:
                    return PathResult(
                        path=new_path,
                        edges=new_edges,
                        length=len(new_edges),
                        blocked=True,
                        blocked_at=next_id,
                    )
                return PathResult(
                    path=new_path,
                    edges=new_edges,
                    length=len(new_edges),
                    blocked=False,
                )

            if next_id in blocked_ids:
                return PathResult(
                    path=new_path,
                    edges=new_edges,
                    length=len(new_edges),
                    blocked=True,
                    blocked_at=next_id,
                )

            visited.add(next_id)
            queue.append((next_id, new_path, new_edges))

    # No path found
    return PathResult()


def check_evidence_chain(
    graph: WebSceneGraph,
    node_id: str,
    *,
    min_observations: int = 1,
    required_types: Optional[Set[str]] = None,
) -> EvidenceStatus:
    """Verify a node has sufficient evidence backing.

    Checks both the node's direct observation_ids and any EVIDENCE
    edges linking it to observation proxy nodes.

    Args:
        graph: The scene graph to check.
        node_id: The node to verify.
        min_observations: Minimum required observations.
        required_types: Optional set of required evidence types
            (inferred from node properties).

    Returns:
        EvidenceStatus with verification details.
    """
    node = graph.get_node(node_id)
    if node is None:
        return EvidenceStatus(
            node_id=node_id,
            has_evidence=False,
            observation_count=0,
            confidence=0.0,
            sufficient=False,
        )

    # Collect all observation IDs
    obs_ids: Set[str] = set(node.observation_ids)

    # Also collect from EVIDENCE edges
    evidence_edges = [
        e for e in graph.get_outgoing_edges(node_id)
        if e.edge_type == EdgeType.EVIDENCE
    ]
    for edge in evidence_edges:
        target = graph.get_node(edge.target_id)
        if target:
            obs_ids.update(target.observation_ids)

    # Infer evidence types from node properties
    evidence_types: Set[str] = set()
    if node.node_type == NodeType.DOM:
        evidence_types.add("dom")
    if node.node_type == NodeType.VISUAL:
        evidence_types.add("actionability")
    if node.node_type == NodeType.NETWORK:
        evidence_types.add("network")
    if node.node_type == NodeType.ACCESSIBILITY:
        evidence_types.add("dom")

    # Check for actionability evidence via linked visual nodes
    children = graph.get_children(node_id)
    for child_id in children:
        child = graph.get_node(child_id)
        if child and child.node_type == NodeType.VISUAL:
            evidence_types.add("actionability")
        if child and child.node_type == NodeType.ACCESSIBILITY:
            evidence_types.add("dom")

    # Compute confidence
    count = len(obs_ids)
    if count == 0:
        confidence = 0.0
    elif count == 1:
        confidence = 0.5
    elif count <= 3:
        confidence = 0.8
    else:
        confidence = 1.0

    # Check sufficiency
    sufficient = count >= min_observations
    if required_types:
        sufficient = sufficient and required_types.issubset(evidence_types)

    return EvidenceStatus(
        node_id=node_id,
        has_evidence=count > 0,
        observation_count=count,
        evidence_types=evidence_types,
        confidence=confidence,
        sufficient=sufficient,
    )
