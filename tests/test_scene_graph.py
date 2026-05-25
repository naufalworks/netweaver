"""Tests for NetWeaver WebSceneGraph — node/edge/graph schema and serialization.

Validates:
- SceneNode creation for all 7 node types (DOM, Accessibility, Visual, Network, JS, Storage, Intent)
- SceneEdge creation for all 4 edge types (Containment, Evidence, Causality, Dependency)
- WebSceneGraph add/remove/query operations
- JSON round-trip serialization (to_dict/from_dict, to_json/from_json)
- Evidence-linked nodes and edges
- Empty graph edge cases
- Factory helpers
"""

import json
import pytest
from datetime import datetime

from netweaver.scene_graph import (
    NodeType, EdgeType,
    SceneNode, SceneEdge, WebSceneGraph,
    create_node, create_edge, create_scene_graph,
)


# ---------------------------------------------------------------------------
# NodeType / EdgeType enums
# ---------------------------------------------------------------------------

class TestNodeType:
    def test_all_seven_types(self):
        expected = {"dom", "accessibility", "visual", "network", "js", "storage", "intent"}
        actual = {nt.value for nt in NodeType}
        assert actual == expected

    def test_enum_identity(self):
        assert NodeType.DOM == NodeType("dom")
        assert NodeType.NETWORK != NodeType.JS


class TestEdgeType:
    def test_all_four_types(self):
        expected = {"containment", "evidence", "causality", "dependency"}
        actual = {et.value for et in EdgeType}
        assert actual == expected

    def test_enum_identity(self):
        assert EdgeType.CONTAINMENT == EdgeType("containment")
        assert EdgeType.CAUSALITY != EdgeType.DEPENDENCY


# ---------------------------------------------------------------------------
# SceneNode
# ---------------------------------------------------------------------------

class TestSceneNode:
    def test_create_dom_node(self):
        node = SceneNode(
            node_id="n1",
            node_type=NodeType.DOM,
            label="button#submit",
            properties={"tag": "button", "text": "Submit"},
        )
        assert node.node_id == "n1"
        assert node.node_type == NodeType.DOM
        assert node.label == "button#submit"
        assert node.properties["tag"] == "button"
        assert node.timestamp is not None

    def test_create_all_node_types(self):
        types_and_labels = [
            (NodeType.DOM, "div.container"),
            (NodeType.ACCESSIBILITY, "role=button, label=Submit"),
            (NodeType.VISUAL, "viewport(0,0,100,50)"),
            (NodeType.NETWORK, "GET /api/data"),
            (NodeType.JS, "console.log('ready')"),
            (NodeType.STORAGE, "localStorage[user_token]"),
            (NodeType.INTENT, "user wants to submit form"),
        ]
        for ntype, label in types_and_labels:
            node = SceneNode(node_id=f"n-{ntype.value}", node_type=ntype, label=label)
            assert node.node_type == ntype
            assert node.label == label

    def test_add_observation(self):
        node = SceneNode(node_id="n1", node_type=NodeType.DOM, label="btn")
        assert not node.has_evidence()
        node.add_observation("obs-001")
        assert node.has_evidence()
        assert "obs-001" in node.observation_ids

    def test_add_observation_no_duplicates(self):
        node = SceneNode(node_id="n1", node_type=NodeType.DOM, label="btn")
        node.add_observation("obs-001")
        node.add_observation("obs-001")
        assert len(node.observation_ids) == 1

    def test_serialization_round_trip(self):
        node = SceneNode(
            node_id="n1",
            node_type=NodeType.NETWORK,
            label="POST /api/submit",
            properties={"status": 200, "method": "POST"},
            observation_ids=["obs-001", "obs-002"],
            metadata={"source": "network_monitor"},
        )
        d = node.to_dict()
        restored = SceneNode.from_dict(d)
        assert restored.node_id == "n1"
        assert restored.node_type == NodeType.NETWORK
        assert restored.label == "POST /api/submit"
        assert restored.properties == {"status": 200, "method": "POST"}
        assert restored.observation_ids == ["obs-001", "obs-002"]
        assert restored.metadata == {"source": "network_monitor"}

    def test_json_round_trip(self):
        node = SceneNode(
            node_id="n2",
            node_type=NodeType.JS,
            label="window.userData",
            properties={"type": "object"},
        )
        json_str = node.to_json()
        parsed = json.loads(json_str)
        assert parsed["node_id"] == "n2"
        assert parsed["node_type"] == "js"

    def test_default_values(self):
        node = SceneNode(node_id="n3", node_type=NodeType.STORAGE, label="cookie")
        assert node.properties == {}
        assert node.observation_ids == []
        assert node.metadata == {}
        assert node.timestamp is not None

    def test_explicit_timestamp(self):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        node = SceneNode(
            node_id="n4", node_type=NodeType.INTENT, label="goal", timestamp=ts,
        )
        d = node.to_dict()
        assert d["timestamp"] == "2026-01-15T12:00:00"
        restored = SceneNode.from_dict(d)
        assert restored.timestamp == ts


# ---------------------------------------------------------------------------
# SceneEdge
# ---------------------------------------------------------------------------

class TestSceneEdge:
    def test_create_containment_edge(self):
        edge = SceneEdge(
            edge_id="e1",
            source_id="parent",
            target_id="child",
            edge_type=EdgeType.CONTAINMENT,
        )
        assert edge.edge_type == EdgeType.CONTAINMENT
        assert edge.source_id == "parent"
        assert edge.target_id == "child"
        assert edge.weight == 1.0

    def test_create_all_edge_types(self):
        types = [
            EdgeType.CONTAINMENT,
            EdgeType.EVIDENCE,
            EdgeType.CAUSALITY,
            EdgeType.DEPENDENCY,
        ]
        for etype in types:
            edge = SceneEdge(
                edge_id=f"e-{etype.value}",
                source_id="a",
                target_id="b",
                edge_type=etype,
            )
            assert edge.edge_type == etype

    def test_add_observation(self):
        edge = SceneEdge(
            edge_id="e1", source_id="a", target_id="b", edge_type=EdgeType.CAUSALITY,
        )
        assert not edge.has_evidence()
        edge.add_observation("obs-100")
        assert edge.has_evidence()

    def test_add_observation_no_duplicates(self):
        edge = SceneEdge(
            edge_id="e1", source_id="a", target_id="b", edge_type=EdgeType.EVIDENCE,
        )
        edge.add_observation("obs-100")
        edge.add_observation("obs-100")
        assert len(edge.observation_ids) == 1

    def test_serialization_round_trip(self):
        edge = SceneEdge(
            edge_id="e1",
            source_id="js-node",
            target_id="dom-node",
            edge_type=EdgeType.CAUSALITY,
            weight=0.85,
            properties={"mutation_type": "attribute_change"},
            observation_ids=["obs-10"],
        )
        d = edge.to_dict()
        restored = SceneEdge.from_dict(d)
        assert restored.edge_id == "e1"
        assert restored.source_id == "js-node"
        assert restored.target_id == "dom-node"
        assert restored.edge_type == EdgeType.CAUSALITY
        assert restored.weight == 0.85
        assert restored.properties == {"mutation_type": "attribute_change"}
        assert restored.observation_ids == ["obs-10"]

    def test_weight_default(self):
        edge = SceneEdge(
            edge_id="e1", source_id="a", target_id="b", edge_type=EdgeType.DEPENDENCY,
        )
        assert edge.weight == 1.0


# ---------------------------------------------------------------------------
# WebSceneGraph — basic operations
# ---------------------------------------------------------------------------

class TestWebSceneGraphAddRemove:
    def _make_graph(self):
        sg = WebSceneGraph(graph_id="sg-test", url="https://example.com", title="Test")
        n1 = SceneNode(node_id="n1", node_type=NodeType.DOM, label="div")
        n2 = SceneNode(node_id="n2", node_type=NodeType.DOM, label="button")
        n3 = SceneNode(node_id="n3", node_type=NodeType.NETWORK, label="GET /api")
        sg.add_node(n1)
        sg.add_node(n2)
        sg.add_node(n3)
        return sg

    def test_add_node(self):
        sg = self._make_graph()
        assert sg.node_count() == 3
        assert sg.get_node("n1") is not None

    def test_add_edge(self):
        sg = self._make_graph()
        edge = SceneEdge(edge_id="e1", source_id="n1", target_id="n2", edge_type=EdgeType.CONTAINMENT)
        assert sg.add_edge(edge) is True
        assert sg.edge_count() == 1

    def test_add_edge_missing_node(self):
        sg = self._make_graph()
        edge = SceneEdge(edge_id="e1", source_id="n1", target_id="n99", edge_type=EdgeType.CONTAINMENT)
        assert sg.add_edge(edge) is False
        assert sg.edge_count() == 0

    def test_remove_node_cascades_edges(self):
        sg = self._make_graph()
        sg.add_edge(SceneEdge(edge_id="e1", source_id="n1", target_id="n2", edge_type=EdgeType.CONTAINMENT))
        sg.add_edge(SceneEdge(edge_id="e2", source_id="n1", target_id="n3", edge_type=EdgeType.DEPENDENCY))
        assert sg.edge_count() == 2
        sg.remove_node("n1")
        assert sg.node_count() == 2
        assert sg.edge_count() == 0

    def test_remove_edge(self):
        sg = self._make_graph()
        sg.add_edge(SceneEdge(edge_id="e1", source_id="n1", target_id="n2", edge_type=EdgeType.CONTAINMENT))
        assert sg.remove_edge("e1") is True
        assert sg.edge_count() == 0

    def test_remove_nonexistent(self):
        sg = self._make_graph()
        assert sg.remove_node("n99") is False
        assert sg.remove_edge("e99") is False


# ---------------------------------------------------------------------------
# WebSceneGraph — queries
# ---------------------------------------------------------------------------

class TestWebSceneGraphQueries:
    def _make_graph(self):
        sg = WebSceneGraph(graph_id="sg-q", url="https://example.com")

        # DOM hierarchy
        root = SceneNode(node_id="root", node_type=NodeType.DOM, label="html")
        body = SceneNode(node_id="body", node_type=NodeType.DOM, label="body")
        btn = SceneNode(node_id="btn", node_type=NodeType.DOM, label="button#submit")
        btn.add_observation("obs-btn")

        # Accessibility
        a11y = SceneNode(node_id="a11y-btn", node_type=NodeType.ACCESSIBILITY, label="role=button")
        a11y.add_observation("obs-a11y")

        # Network
        xhr = SceneNode(node_id="xhr", node_type=NodeType.NETWORK, label="POST /api")
        xhr.add_observation("obs-xhr")

        # JS
        js_err = SceneNode(node_id="js-err", node_type=NodeType.JS, label="TypeError")

        # Intent
        intent = SceneNode(node_id="intent1", node_type=NodeType.INTENT, label="submit form")

        for n in [root, body, btn, a11y, xhr, js_err, intent]:
            sg.add_node(n)

        # Containment: root → body → btn
        sg.add_edge(SceneEdge(edge_id="e-root-body", source_id="root", target_id="body", edge_type=EdgeType.CONTAINMENT))
        sg.add_edge(SceneEdge(edge_id="e-body-btn", source_id="body", target_id="btn", edge_type=EdgeType.CONTAINMENT))

        # Evidence: btn → a11y
        sg.add_edge(SceneEdge(edge_id="e-evidence", source_id="btn", target_id="a11y-btn", edge_type=EdgeType.EVIDENCE))

        # Causality: btn click → xhr
        sg.add_edge(SceneEdge(edge_id="e-cause", source_id="btn", target_id="xhr", edge_type=EdgeType.CAUSALITY))

        # Dependency: xhr → js_err (XHR failure caused JS error)
        sg.add_edge(SceneEdge(edge_id="e-dep", source_id="xhr", target_id="js-err", edge_type=EdgeType.DEPENDENCY))

        return sg

    def test_get_nodes_by_type(self):
        sg = self._make_graph()
        dom_nodes = sg.get_nodes_by_type(NodeType.DOM)
        assert len(dom_nodes) == 3
        net_nodes = sg.get_nodes_by_type(NodeType.NETWORK)
        assert len(net_nodes) == 1

    def test_get_edges_by_type(self):
        sg = self._make_graph()
        containment = sg.get_edges_by_type(EdgeType.CONTAINMENT)
        assert len(containment) == 2
        causality = sg.get_edges_by_type(EdgeType.CAUSALITY)
        assert len(causality) == 1

    def test_get_neighbors(self):
        sg = self._make_graph()
        neighbors = sg.get_neighbors("btn")
        assert set(neighbors) == {"body", "a11y-btn", "xhr"}

    def test_get_children(self):
        sg = self._make_graph()
        children = sg.get_children("root")
        assert children == ["body"]

    def test_get_parent(self):
        sg = self._make_graph()
        parent = sg.get_parent("btn")
        assert parent == "body"

    def test_get_parent_root(self):
        sg = self._make_graph()
        parent = sg.get_parent("root")
        assert parent is None

    def test_get_causes(self):
        sg = self._make_graph()
        causes = sg.get_causes("xhr")
        assert causes == ["btn"]

    def test_get_effects(self):
        sg = self._make_graph()
        effects = sg.get_effects("btn")
        assert "xhr" in effects

    def test_outgoing_edges(self):
        sg = self._make_graph()
        out = sg.get_outgoing_edges("btn")
        assert len(out) == 2  # evidence + causality

    def test_incoming_edges(self):
        sg = self._make_graph()
        inc = sg.get_incoming_edges("btn")
        assert len(inc) == 1  # containment from body

    def test_evidence_coverage(self):
        sg = self._make_graph()
        coverage = sg.evidence_coverage()
        # 7 nodes, 3 with evidence (btn, a11y, xhr)
        assert coverage["nodes"] == pytest.approx(3 / 7)
        # 5 edges, 0 with observation_ids
        assert coverage["edges"] == 0.0

    def test_summary(self):
        sg = self._make_graph()
        s = sg.summary()
        assert s["graph_id"] == "sg-q"
        assert s["node_count"] == 7
        assert s["edge_count"] == 5
        assert s["nodes_by_type"]["dom"] == 3
        assert s["edges_by_type"]["containment"] == 2


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestWebSceneGraphSerialization:
    def _make_populated_graph(self):
        sg = WebSceneGraph(
            graph_id="sg-serial",
            url="https://example.com/form",
            title="Contact Form",
            metadata={"observer_version": "1.0"},
        )
        dom_root = SceneNode(node_id="n1", node_type=NodeType.DOM, label="form#contact")
        dom_input = SceneNode(
            node_id="n2", node_type=NodeType.DOM, label="input#email",
            properties={"type": "email", "required": True},
            observation_ids=["obs-email"],
        )
        a11y_label = SceneNode(
            node_id="n3", node_type=NodeType.ACCESSIBILITY, label="label for email",
        )
        net_submit = SceneNode(
            node_id="n4", node_type=NodeType.NETWORK, label="POST /api/contact",
            observation_ids=["obs-submit"],
        )

        for n in [dom_root, dom_input, a11y_label, net_submit]:
            sg.add_node(n)

        sg.add_edge(SceneEdge(
            edge_id="e1", source_id="n1", target_id="n2", edge_type=EdgeType.CONTAINMENT,
        ))
        sg.add_edge(SceneEdge(
            edge_id="e2", source_id="n2", target_id="n3", edge_type=EdgeType.EVIDENCE,
            observation_ids=["obs-a11y-link"],
        ))
        sg.add_edge(SceneEdge(
            edge_id="e3", source_id="n2", target_id="n4", edge_type=EdgeType.CAUSALITY,
            properties={"action": "form_submit"},
        ))

        return sg

    def test_to_dict_from_dict_round_trip(self):
        sg = self._make_populated_graph()
        d = sg.to_dict()

        # Verify structure
        assert d["graph_id"] == "sg-serial"
        assert d["url"] == "https://example.com/form"
        assert len(d["nodes"]) == 4
        assert len(d["edges"]) == 3

        # Round-trip
        restored = WebSceneGraph.from_dict(d)
        assert restored.graph_id == sg.graph_id
        assert restored.url == sg.url
        assert restored.title == sg.title
        assert restored.node_count() == 4
        assert restored.edge_count() == 3
        assert restored.metadata == {"observer_version": "1.0"}

        # Check node fidelity
        original_input = sg.get_node("n2")
        restored_input = restored.get_node("n2")
        assert restored_input.node_type == NodeType.DOM
        assert restored_input.properties["type"] == "email"
        assert restored_input.observation_ids == ["obs-email"]

        # Check edge fidelity
        original_cause = sg.get_edge("e3")
        restored_cause = restored.get_edge("e3")
        assert restored_cause.edge_type == EdgeType.CAUSALITY
        assert restored_cause.properties["action"] == "form_submit"

    def test_to_json_from_json_round_trip(self):
        sg = self._make_populated_graph()
        json_str = sg.to_json()

        # Valid JSON
        parsed = json.loads(json_str)
        assert parsed["graph_id"] == "sg-serial"

        # Round-trip
        restored = WebSceneGraph.from_json(json_str)
        assert restored.graph_id == sg.graph_id
        assert restored.node_count() == sg.node_count()
        assert restored.edge_count() == sg.edge_count()

    def test_empty_graph_serialization(self):
        sg = WebSceneGraph(graph_id="sg-empty", url="https://blank.com")
        d = sg.to_dict()
        restored = WebSceneGraph.from_dict(d)
        assert restored.node_count() == 0
        assert restored.edge_count() == 0
        assert restored.url == "https://blank.com"

    def test_evidence_coverage_serialization(self):
        sg = self._make_populated_graph()
        d = sg.to_dict()
        restored = WebSceneGraph.from_dict(d)
        coverage = restored.evidence_coverage()
        # 4 nodes, 2 with evidence
        assert coverage["nodes"] == pytest.approx(0.5)
        # 3 edges, 1 with evidence
        assert coverage["edges"] == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

class TestFactoryHelpers:
    def test_create_node_auto_id(self):
        node = create_node(NodeType.DOM, "div.container")
        assert node.node_id.startswith("node-")
        assert node.node_type == NodeType.DOM
        assert node.label == "div.container"

    def test_create_node_with_evidence(self):
        node = create_node(
            NodeType.NETWORK, "GET /api",
            observation_ids=["obs-1", "obs-2"],
        )
        assert node.has_evidence()
        assert len(node.observation_ids) == 2

    def test_create_edge_auto_id(self):
        edge = create_edge("a", "b", EdgeType.CONTAINMENT)
        assert edge.edge_id.startswith("edge-")
        assert edge.source_id == "a"
        assert edge.target_id == "b"

    def test_create_scene_graph_auto_id(self):
        sg = create_scene_graph("https://example.com", title="Test")
        assert sg.graph_id.startswith("sg-")
        assert sg.url == "https://example.com"
        assert sg.title == "Test"

    def test_unique_auto_ids(self):
        nodes = [create_node(NodeType.DOM, "x") for _ in range(10)]
        ids = {n.node_id for n in nodes}
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_graph_queries(self):
        sg = WebSceneGraph(graph_id="sg-empty", url="about:blank")
        assert sg.get_nodes_by_type(NodeType.DOM) == []
        assert sg.get_edges_by_type(EdgeType.CONTAINMENT) == []
        assert sg.get_neighbors("nonexistent") == []
        assert sg.get_children("nonexistent") == []
        assert sg.get_parent("nonexistent") is None
        assert sg.get_outgoing_edges("nonexistent") == []
        assert sg.get_incoming_edges("nonexistent") == []
        assert sg.get_causes("nonexistent") == []
        assert sg.get_effects("nonexistent") == []
        coverage = sg.evidence_coverage()
        assert coverage["nodes"] == 0.0
        assert coverage["edges"] == 0.0

    def test_self_loop_edge(self):
        sg = WebSceneGraph(graph_id="sg-loop", url="https://example.com")
        n = SceneNode(node_id="n1", node_type=NodeType.JS, label="recursive")
        sg.add_node(n)
        edge = SceneEdge(edge_id="e1", source_id="n1", target_id="n1", edge_type=EdgeType.CAUSALITY)
        assert sg.add_edge(edge) is True
        neighbors = sg.get_neighbors("n1")
        assert "n1" in neighbors

    def test_multiple_edges_same_nodes(self):
        sg = WebSceneGraph(graph_id="sg-multi", url="https://example.com")
        sg.add_node(SceneNode(node_id="a", node_type=NodeType.DOM, label="A"))
        sg.add_node(SceneNode(node_id="b", node_type=NodeType.DOM, label="B"))
        sg.add_edge(SceneEdge(edge_id="e1", source_id="a", target_id="b", edge_type=EdgeType.CONTAINMENT))
        sg.add_edge(SceneEdge(edge_id="e2", source_id="a", target_id="b", edge_type=EdgeType.EVIDENCE))
        assert sg.edge_count() == 2

    def test_add_node_overwrite(self):
        sg = WebSceneGraph(graph_id="sg-overwrite", url="https://example.com")
        sg.add_node(SceneNode(node_id="n1", node_type=NodeType.DOM, label="original"))
        sg.add_node(SceneNode(node_id="n1", node_type=NodeType.INTENT, label="replacement"))
        assert sg.get_node("n1").label == "replacement"
        assert sg.get_node("n1").node_type == NodeType.INTENT

    def test_large_graph_performance(self):
        """Stress test with 1000 nodes and edges."""
        sg = create_scene_graph("https://big.com")
        nodes = [create_node(NodeType.DOM, f"element-{i}") for i in range(1000)]
        for n in nodes:
            sg.add_node(n)

        # Chain edges
        for i in range(999):
            create_edge(nodes[i].node_id, nodes[i + 1].node_id, EdgeType.CONTAINMENT)
            sg.add_edge(create_edge(
                nodes[i].node_id, nodes[i + 1].node_id, EdgeType.CONTAINMENT,
            ))

        assert sg.node_count() == 1000
        assert sg.edge_count() == 999

        # Serialization round-trip
        d = sg.to_dict()
        restored = WebSceneGraph.from_dict(d)
        assert restored.node_count() == 1000
        assert restored.edge_count() == 999
