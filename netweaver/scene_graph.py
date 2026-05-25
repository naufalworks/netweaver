"""NetWeaver WebSceneGraph — Browser-native world model.

A scene graph is a directed graph that represents the complete state of a web
page as observed by NetWeaver. Unlike a DOM tree or accessibility tree, the
WebSceneGraph integrates multiple evidence domains into a unified model:

- DOM nodes: element structure, attributes, text content
- Accessibility nodes: ARIA roles, labels, states
- Visual nodes: layout, viewport position, visibility
- Network nodes: requests, responses, resource timing
- JS nodes: console output, errors, global state
- Storage nodes: localStorage, sessionStorage, cookies
- Intent nodes: user goals, page purpose, action affordances

Edges represent relationships between nodes:
- CONTAINMENT: parent-child DOM hierarchy
- EVIDENCE: node backed by an EvidenceReport observation
- CAUSALITY: one node caused another (e.g., JS→DOM mutation)
- DEPENDENCY: one node depends on another (e.g., network→resource)

Each node links to EvidenceReport observations from evidence.py, providing
verifiable provenance for every fact in the world model.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

class NodeType(Enum):
    """Type of node in the WebSceneGraph."""
    DOM = "dom"
    ACCESSIBILITY = "accessibility"
    VISUAL = "visual"
    NETWORK = "network"
    JS = "js"
    STORAGE = "storage"
    INTENT = "intent"


class EdgeType(Enum):
    """Type of edge between scene graph nodes."""
    CONTAINMENT = "containment"
    EVIDENCE = "evidence"
    CAUSALITY = "causality"
    DEPENDENCY = "dependency"


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

@dataclass
class SceneNode:
    """A node in the WebSceneGraph.

    Each node represents a fact about the page state, backed by evidence
    from an EvidenceReport observation. Nodes are typed by domain (DOM,
    accessibility, visual, network, JS, storage, intent).

    Attributes:
        node_id: Unique identifier for this node.
        node_type: Domain type of this node.
        label: Human-readable label (e.g., "button#submit", "XHR /api/data").
        properties: Typed dict of node-specific properties.
        observation_ids: IDs of EvidenceReport observations backing this node.
        timestamp: When this node was created/observed.
        metadata: Additional untyped context.
    """
    node_id: str
    node_type: NodeType
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)
    observation_ids: List[str] = field(default_factory=list)
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def add_observation(self, observation_id: str) -> None:
        """Link an EvidenceReport observation to this node."""
        if observation_id not in self.observation_ids:
            self.observation_ids.append(observation_id)

    def has_evidence(self) -> bool:
        """Check if this node is backed by at least one observation."""
        return len(self.observation_ids) > 0

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "label": self.label,
            "properties": self.properties,
            "observation_ids": self.observation_ids,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SceneNode":
        return cls(
            node_id=data["node_id"],
            node_type=NodeType(data["node_type"]),
            label=data["label"],
            properties=data.get("properties", {}),
            observation_ids=data.get("observation_ids", []),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else None,
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class SceneEdge:
    """A directed edge between two SceneNodes.

    Edges represent relationships: containment (DOM hierarchy), evidence
    (observation backing), causality (one node caused another), or
    dependency (one node depends on another).

    Attributes:
        edge_id: Unique identifier for this edge.
        source_id: ID of the source node.
        target_id: ID of the target node.
        edge_type: Type of relationship.
        weight: Optional weight/confidence (0.0 to 1.0).
        properties: Edge-specific properties.
        observation_ids: EvidenceReport observations backing this edge.
    """
    edge_id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    observation_ids: List[str] = field(default_factory=list)

    def add_observation(self, observation_id: str) -> None:
        """Link an EvidenceReport observation to this edge."""
        if observation_id not in self.observation_ids:
            self.observation_ids.append(observation_id)

    def has_evidence(self) -> bool:
        """Check if this edge is backed by at least one observation."""
        return len(self.observation_ids) > 0

    def to_dict(self) -> Dict:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "weight": self.weight,
            "properties": self.properties,
            "observation_ids": self.observation_ids,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SceneEdge":
        return cls(
            edge_id=data["edge_id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            edge_type=EdgeType(data["edge_type"]),
            weight=data.get("weight", 1.0),
            properties=data.get("properties", {}),
            observation_ids=data.get("observation_ids", []),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Scene Graph
# ---------------------------------------------------------------------------

@dataclass
class WebSceneGraph:
    """Directed graph representing the complete state of a web page.

    The WebSceneGraph is the unified world model that integrates all evidence
    domains (DOM, accessibility, visual, network, JS, storage, intent) into
    a single queryable structure. Nodes represent facts; edges represent
    relationships between those facts.

    This is the schema bridge from observer/evidence/perspective into a
    browser-native world model that can drive verified execution.

    Attributes:
        graph_id: Unique identifier for this scene graph.
        url: The page URL this graph represents.
        title: Page title at time of observation.
        nodes: All nodes in the graph.
        edges: All edges in the graph.
        created_at: When this graph was created.
        metadata: Additional context (observer version, etc.).
    """
    graph_id: str
    url: str
    title: str = ""
    nodes: Dict[str, SceneNode] = field(default_factory=dict)
    edges: Dict[str, SceneEdge] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    # --- Node operations ---

    def add_node(self, node: SceneNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.node_id] = node

    def get_node(self, node_id: str) -> Optional[SceneNode]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all edges connected to it."""
        if node_id not in self.nodes:
            return False
        # Remove connected edges
        edge_ids_to_remove = [
            eid for eid, edge in self.edges.items()
            if edge.source_id == node_id or edge.target_id == node_id
        ]
        for eid in edge_ids_to_remove:
            del self.edges[eid]
        del self.nodes[node_id]
        return True

    # --- Edge operations ---

    def add_edge(self, edge: SceneEdge) -> bool:
        """Add an edge to the graph.

        Returns False if source or target node doesn't exist.
        """
        if edge.source_id not in self.nodes or edge.target_id not in self.nodes:
            return False
        self.edges[edge.edge_id] = edge
        return True

    def get_edge(self, edge_id: str) -> Optional[SceneEdge]:
        """Get an edge by ID."""
        return self.edges.get(edge_id)

    def remove_edge(self, edge_id: str) -> bool:
        """Remove an edge from the graph."""
        if edge_id not in self.edges:
            return False
        del self.edges[edge_id]
        return True

    # --- Query operations ---

    def get_nodes_by_type(self, node_type: NodeType) -> List[SceneNode]:
        """Filter nodes by type."""
        return [n for n in self.nodes.values() if n.node_type == node_type]

    def get_edges_by_type(self, edge_type: EdgeType) -> List[SceneEdge]:
        """Filter edges by type."""
        return [e for e in self.edges.values() if e.edge_type == edge_type]

    def get_neighbors(self, node_id: str) -> List[str]:
        """Get IDs of all nodes connected to a given node (both directions)."""
        neighbor_ids: Set[str] = set()
        for edge in self.edges.values():
            if edge.source_id == node_id:
                neighbor_ids.add(edge.target_id)
            elif edge.target_id == node_id:
                neighbor_ids.add(edge.source_id)
        return list(neighbor_ids)

    def get_outgoing_edges(self, node_id: str) -> List[SceneEdge]:
        """Get all edges where node_id is the source."""
        return [e for e in self.edges.values() if e.source_id == node_id]

    def get_incoming_edges(self, node_id: str) -> List[SceneEdge]:
        """Get all edges where node_id is the target."""
        return [e for e in self.edges.values() if e.target_id == node_id]

    def get_children(self, node_id: str) -> List[str]:
        """Get child node IDs via CONTAINMENT edges."""
        return [
            e.target_id for e in self.edges.values()
            if e.source_id == node_id and e.edge_type == EdgeType.CONTAINMENT
        ]

    def get_parent(self, node_id: str) -> Optional[str]:
        """Get parent node ID via CONTAINMENT edges (assumes single parent)."""
        for edge in self.edges.values():
            if edge.target_id == node_id and edge.edge_type == EdgeType.CONTAINMENT:
                return edge.source_id
        return None

    def get_causes(self, node_id: str) -> List[str]:
        """Get nodes that caused this node (via CAUSALITY edges pointing to it)."""
        return [
            e.source_id for e in self.edges.values()
            if e.target_id == node_id and e.edge_type == EdgeType.CAUSALITY
        ]

    def get_effects(self, node_id: str) -> List[str]:
        """Get nodes caused by this node (via CAUSALITY edges from it)."""
        return [
            e.target_id for e in self.edges.values()
            if e.source_id == node_id and e.edge_type == EdgeType.CAUSALITY
        ]

    # --- Statistics ---

    def node_count(self) -> int:
        return len(self.nodes)

    def edge_count(self) -> int:
        return len(self.edges)

    def evidence_coverage(self) -> Dict[str, float]:
        """Fraction of nodes/edges with at least one observation, by type."""
        nodes_with_evidence = sum(1 for n in self.nodes.values() if n.has_evidence())
        edges_with_evidence = sum(1 for e in self.edges.values() if e.has_evidence())
        return {
            "nodes": nodes_with_evidence / len(self.nodes) if self.nodes else 0.0,
            "edges": edges_with_evidence / len(self.edges) if self.edges else 0.0,
        }

    def summary(self) -> Dict[str, Any]:
        """Generate a summary of the scene graph."""
        coverage = self.evidence_coverage()
        return {
            "graph_id": self.graph_id,
            "url": self.url,
            "title": self.title,
            "node_count": self.node_count(),
            "edge_count": self.edge_count(),
            "nodes_by_type": {
                nt.value: len(self.get_nodes_by_type(nt)) for nt in NodeType
            },
            "edges_by_type": {
                et.value: len(self.get_edges_by_type(et)) for et in EdgeType
            },
            "evidence_coverage": coverage,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    # --- Serialization ---

    def to_dict(self) -> Dict:
        return {
            "graph_id": self.graph_id,
            "url": self.url,
            "title": self.title,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": {eid: e.to_dict() for eid, e in self.edges.items()},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "WebSceneGraph":
        return cls(
            graph_id=data["graph_id"],
            url=data["url"],
            title=data.get("title", ""),
            nodes={
                nid: SceneNode.from_dict(n) for nid, n in data.get("nodes", {}).items()
            },
            edges={
                eid: SceneEdge.from_dict(e) for eid, e in data.get("edges", {}).items()
            },
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "WebSceneGraph":
        return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_node(
    node_type: NodeType,
    label: str,
    properties: Optional[Dict[str, Any]] = None,
    observation_ids: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SceneNode:
    """Factory helper to create a SceneNode with auto-generated ID."""
    return SceneNode(
        node_id=f"node-{uuid.uuid4().hex[:12]}",
        node_type=node_type,
        label=label,
        properties=properties or {},
        observation_ids=observation_ids or [],
        metadata=metadata or {},
    )


def create_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType,
    weight: float = 1.0,
    properties: Optional[Dict[str, Any]] = None,
    observation_ids: Optional[List[str]] = None,
) -> SceneEdge:
    """Factory helper to create a SceneEdge with auto-generated ID."""
    return SceneEdge(
        edge_id=f"edge-{uuid.uuid4().hex[:12]}",
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        weight=weight,
        properties=properties or {},
        observation_ids=observation_ids or [],
    )


def create_scene_graph(
    url: str,
    title: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> WebSceneGraph:
    """Factory helper to create a WebSceneGraph with auto-generated ID."""
    return WebSceneGraph(
        graph_id=f"sg-{uuid.uuid4().hex[:12]}",
        url=url,
        title=title,
        metadata=metadata or {},
    )
