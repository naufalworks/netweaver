"""Tests for netweaver.graph_query — SceneGraph Query Layer.

Covers all 4 core query functions plus helpers:
- find_actionable_nodes: intent-based node search
- resolve_target: natural-language element resolution
- find_safe_path: BFS pathfinding with safety exclusion
- check_evidence_chain: evidence verification
"""

import pytest

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
from netweaver.graph_query import (
    EvidenceStatus,
    IntentType,
    PathResult,
    QueryMatch,
    check_evidence_chain,
    find_actionable_nodes,
    find_safe_path,
    resolve_target,
    _is_safety_blocked,
    _get_safety_blocked_ids,
    _normalize_text,
    _text_similarity,
)


# ---------------------------------------------------------------------------
# Helpers: graph construction for tests
# ---------------------------------------------------------------------------

def _make_simple_graph() -> WebSceneGraph:
    """Create a graph with a page root, 3 DOM elements, and intent nodes."""
    g = create_scene_graph(url="https://example.com", title="Test Page")

    # Page root
    root = create_node(NodeType.DOM, "page:root", properties={"is_root": True})
    g.add_node(root)

    # DOM nodes
    login_btn = create_node(
        NodeType.DOM, "button#login",
        properties={"selector": "#login-btn", "tag": "button", "text": "Login"},
        observation_ids=["obs-1", "obs-2"],
    )
    email_input = create_node(
        NodeType.DOM, "input#email",
        properties={"selector": "#email", "tag": "input", "text": "", "type": "email"},
        observation_ids=["obs-3"],
    )
    link = create_node(
        NodeType.DOM, "a#help",
        properties={"selector": "#help-link", "tag": "a", "text": "Help Center"},
        observation_ids=["obs-4"],
    )
    g.add_node(login_btn)
    g.add_node(email_input)
    g.add_node(link)

    # Containment edges
    for node in [login_btn, email_input, link]:
        g.add_edge(create_edge(root.node_id, node.node_id, EdgeType.CONTAINMENT))

    # Intent nodes
    login_intent = create_node(
        NodeType.INTENT, "intent:clickable(#login-btn)",
        properties={"affordance": "clickable", "selector": "#login-btn", "text": "Login"},
        metadata={"parent_dom_id": login_btn.node_id},
    )
    email_intent = create_node(
        NodeType.INTENT, "intent:fillable(#email)",
        properties={"affordance": "fillable", "selector": "#email"},
        metadata={"parent_dom_id": email_input.node_id},
    )
    nav_intent = create_node(
        NodeType.INTENT, "intent:navigable(#help-link)",
        properties={"affordance": "navigable", "selector": "#help-link"},
        metadata={"parent_dom_id": link.node_id},
    )
    g.add_node(login_intent)
    g.add_node(email_intent)
    g.add_node(nav_intent)

    # Containment: dom → intent
    g.add_edge(create_edge(login_btn.node_id, login_intent.node_id, EdgeType.CONTAINMENT))
    g.add_edge(create_edge(email_input.node_id, email_intent.node_id, EdgeType.CONTAINMENT))
    g.add_edge(create_edge(link.node_id, nav_intent.node_id, EdgeType.CONTAINMENT))

    return g


def _add_safety_block(graph: WebSceneGraph, target_node_id: str) -> SceneNode:
    """Add a SAFETY node blocking a target DOM node."""
    safety = create_node(
        NodeType.INTENT,
        "safety:abort:" + target_node_id,
        properties={
            "is_safety_enrichment": True,
            "strategy": "abort",
            "reason": "dangerous action",
        },
        metadata={"source": "perspective_engine"},
    )
    graph.add_node(safety)
    graph.add_edge(create_edge(
        safety.node_id, target_node_id,
        EdgeType.DEPENDENCY,
        properties={"dep_type": "safety_assessment"},
    ))
    return safety


# ---------------------------------------------------------------------------
# Text matching tests
# ---------------------------------------------------------------------------

class TestTextMatching:
    def test_normalize_lowercase(self):
        assert _normalize_text("Hello World") == "hello world"

    def test_normalize_strip(self):
        assert _normalize_text("  hello  ") == "hello"

    def test_normalize_collapse_whitespace(self):
        assert _normalize_text("hello   world") == "hello world"

    def test_similarity_identical(self):
        assert _text_similarity("login button", "login button") == 1.0

    def test_similarity_partial(self):
        sim = _text_similarity("login", "login button")
        assert 0.5 < sim <= 1.0

    def test_similarity_no_overlap(self):
        assert _text_similarity("foo", "bar") == 0.0

    def test_similarity_empty_query(self):
        assert _text_similarity("", "text") == 0.0

    def test_similarity_empty_target(self):
        assert _text_similarity("text", "") == 0.0


# ---------------------------------------------------------------------------
# find_actionable_nodes tests
# ---------------------------------------------------------------------------

class TestFindActionableNodes:
    def setup_method(self):
        self.graph = _make_simple_graph()

    def test_find_clickable(self):
        results = find_actionable_nodes(self.graph, IntentType.CLICK)
        assert len(results) >= 1
        assert all(m.node.properties.get("tag") == "button" or
                    "clickable" in str(m.matched_properties) for m in results)

    def test_find_fillable(self):
        results = find_actionable_nodes(self.graph, IntentType.FILL)
        assert len(results) >= 1
        assert any("email" in m.node.properties.get("selector", "") for m in results)

    def test_find_navigable(self):
        results = find_actionable_nodes(self.graph, IntentType.NAVIGATE)
        assert len(results) >= 1
        assert any("help" in m.node.properties.get("selector", "") for m in results)

    def test_find_any(self):
        results = find_actionable_nodes(self.graph, IntentType.ANY)
        assert len(results) == 3  # All 3 intent nodes

    def test_results_sorted_by_score(self):
        results = find_actionable_nodes(self.graph, IntentType.ANY)
        scores = [m.score for m in results]
        assert scores == sorted(scores, reverse=True)

    def test_min_evidence_filter(self):
        results = find_actionable_nodes(
            self.graph, IntentType.ANY, min_evidence=2
        )
        # Only login_btn has 2 observations
        assert all(m.evidence_count >= 2 for m in results)

    def test_exclude_blocked(self):
        # Block the login button
        dom_nodes = self.graph.get_nodes_by_type(NodeType.DOM)
        login_btn = [n for n in dom_nodes if n.properties.get("tag") == "button"][0]
        _add_safety_block(self.graph, login_btn.node_id)

        results = find_actionable_nodes(
            self.graph, IntentType.CLICK, exclude_blocked=True
        )
        assert not any(m.node.node_id == login_btn.node_id for m in results)

    def test_include_blocked(self):
        dom_nodes = self.graph.get_nodes_by_type(NodeType.DOM)
        login_btn = [n for n in dom_nodes if n.properties.get("tag") == "button"][0]
        _add_safety_block(self.graph, login_btn.node_id)

        results = find_actionable_nodes(
            self.graph, IntentType.CLICK, exclude_blocked=False
        )
        blocked_matches = [m for m in results if m.node.node_id == login_btn.node_id]
        assert len(blocked_matches) == 1
        assert blocked_matches[0].blocked is True

    def test_no_intent_nodes(self):
        g = create_scene_graph(url="https://empty.com")
        results = find_actionable_nodes(g, IntentType.CLICK)
        assert results == []

    def test_skips_safety_enrichment_nodes(self):
        # Add a safety enrichment node (not blocking, just enrichment)
        safety = create_node(
            NodeType.INTENT, "safety:action:foo",
            properties={"is_safety_enrichment": True, "strategy": "action"},
        )
        self.graph.add_node(safety)
        results = find_actionable_nodes(self.graph, IntentType.ANY)
        assert not any(m.node.node_id == safety.node_id for m in results)


# ---------------------------------------------------------------------------
# resolve_target tests
# ---------------------------------------------------------------------------

class TestResolveTarget:
    def setup_method(self):
        self.graph = _make_simple_graph()

    def test_resolve_by_text(self):
        result = resolve_target(self.graph, "Login")
        assert result is not None
        assert "login" in result.node.properties.get("selector", "").lower() or \
               "login" in result.node.properties.get("text", "").lower()

    def test_resolve_by_aria_label(self):
        # Add accessibility node to login button
        dom_nodes = self.graph.get_nodes_by_type(NodeType.DOM)
        login_btn = [n for n in dom_nodes if n.properties.get("tag") == "button"][0]

        a11y = create_node(
            NodeType.ACCESSIBILITY, "a11y:Sign In",
            properties={"aria_label": "Sign In to your account", "selector": "#login-btn"},
        )
        self.graph.add_node(a11y)
        self.graph.add_edge(create_edge(login_btn.node_id, a11y.node_id, EdgeType.CONTAINMENT))

        result = resolve_target(self.graph, "sign in account")
        assert result is not None
        assert result.node.node_id == login_btn.node_id

    def test_resolve_no_match(self):
        result = resolve_target(self.graph, "xyzzy plugh baz")
        assert result is None

    def test_resolve_with_intent_filter(self):
        result = resolve_target(
            self.graph, "email", intent=IntentType.FILL
        )
        assert result is not None
        # Should match on selector "#email"
        assert "email" in result.node.properties.get("selector", "")

    def test_resolve_intent_filter_excludes_wrong_type(self):
        result = resolve_target(
            self.graph, "help", intent=IntentType.FILL
        )
        # "Help Center" is navigable, not fillable
        assert result is None

    def test_resolve_min_score(self):
        # Very low min_score should still filter truly bad matches
        result = resolve_target(self.graph, "Login", min_score=0.99)
        # "Login" text should still match exactly
        assert result is not None

    def test_resolve_excludes_blocked(self):
        dom_nodes = self.graph.get_nodes_by_type(NodeType.DOM)
        login_btn = [n for n in dom_nodes if n.properties.get("tag") == "button"][0]
        _add_safety_block(self.graph, login_btn.node_id)

        result = resolve_target(self.graph, "Login", exclude_blocked=True)
        assert result is None or result.node.node_id != login_btn.node_id

    def test_resolve_includes_blocked(self):
        dom_nodes = self.graph.get_nodes_by_type(NodeType.DOM)
        login_btn = [n for n in dom_nodes if n.properties.get("tag") == "button"][0]
        _add_safety_block(self.graph, login_btn.node_id)

        result = resolve_target(self.graph, "Login", exclude_blocked=False)
        assert result is not None
        assert result.blocked is True

    def test_resolve_skips_root_node(self):
        result = resolve_target(self.graph, "root")
        assert result is None

    def test_resolve_skips_proxy_nodes(self):
        proxy = create_node(
            NodeType.DOM, "obs:proxy",
            properties={"is_observation_proxy": True},
        )
        self.graph.add_node(proxy)
        result = resolve_target(self.graph, "proxy")
        assert result is None or result.node.node_id != proxy.node_id

    def test_evidence_boosts_score(self):
        # Login has 2 observations, email has 1
        login_result = resolve_target(self.graph, "login")
        # Both should resolve, but check score boosting works
        assert login_result is not None
        assert login_result.score > 0


# ---------------------------------------------------------------------------
# find_safe_path tests
# ---------------------------------------------------------------------------

class TestFindSafePath:
    def setup_method(self):
        self.graph = _make_simple_graph()

    def test_path_to_self(self):
        root = [n for n in self.graph.nodes.values() if n.properties.get("is_root")][0]
        result = find_safe_path(self.graph, root.node_id, root.node_id)
        assert result.path == [root.node_id]
        assert result.length == 0
        assert result.blocked is False

    def test_path_missing_source(self):
        result = find_safe_path(self.graph, "nonexistent", "other")
        assert result.path == []

    def test_path_missing_target(self):
        root = [n for n in self.graph.nodes.values() if n.properties.get("is_root")][0]
        result = find_safe_path(self.graph, root.node_id, "nonexistent")
        assert result.path == []

    def test_path_through_containment(self):
        nodes = list(self.graph.nodes.values())
        root = [n for n in nodes if n.properties.get("is_root")][0]
        login_btn = [n for n in nodes if n.properties.get("tag") == "button"][0]

        result = find_safe_path(self.graph, root.node_id, login_btn.node_id)
        assert len(result.path) >= 2
        assert result.path[0] == root.node_id
        assert result.path[-1] == login_btn.node_id
        assert result.blocked is False

    def test_path_blocked_by_safety(self):
        nodes = list(self.graph.nodes.values())
        root = [n for n in nodes if n.properties.get("is_root")][0]
        login_btn = [n for n in nodes if n.properties.get("tag") == "button"][0]
        _add_safety_block(self.graph, login_btn.node_id)

        result = find_safe_path(self.graph, root.node_id, login_btn.node_id)
        assert result.blocked is True
        assert result.blocked_at == login_btn.node_id

    def test_path_max_depth(self):
        nodes = list(self.graph.nodes.values())
        root = [n for n in nodes if n.properties.get("is_root")][0]
        link = [n for n in nodes if n.properties.get("tag") == "a"][0]

        result = find_safe_path(
            self.graph, root.node_id, link.node_id, max_depth=1
        )
        # Depth 1 should find link (root → link is 1 hop)
        assert result.path[-1] == link.node_id

    def test_path_no_connection(self):
        # Add isolated node
        isolated = create_node(NodeType.DOM, "isolated")
        self.graph.add_node(isolated)

        root = [n for n in self.graph.nodes.values() if n.properties.get("is_root")][0]
        result = find_safe_path(self.graph, root.node_id, isolated.node_id)
        assert result.path == []

    def test_bidirectional_traversal(self):
        nodes = list(self.graph.nodes.values())
        root = [n for n in nodes if n.properties.get("is_root")][0]
        login_btn = [n for n in nodes if n.properties.get("tag") == "button"][0]

        # Reverse direction: login → root (incoming CONTAINMENT edge)
        result = find_safe_path(self.graph, login_btn.node_id, root.node_id)
        assert len(result.path) >= 2


# ---------------------------------------------------------------------------
# check_evidence_chain tests
# ---------------------------------------------------------------------------

class TestCheckEvidenceChain:
    def setup_method(self):
        self.graph = _make_simple_graph()

    def test_node_with_evidence(self):
        login_btn = [n for n in self.graph.nodes.values()
                     if n.properties.get("tag") == "button"][0]
        status = check_evidence_chain(self.graph, login_btn.node_id)
        assert status.has_evidence is True
        assert status.observation_count == 2
        assert status.confidence >= 0.8
        assert status.sufficient is True

    def test_node_without_evidence(self):
        no_ev = create_node(NodeType.DOM, "no-evidence", properties={"tag": "div"})
        self.graph.add_node(no_ev)

        status = check_evidence_chain(self.graph, no_ev.node_id)
        assert status.has_evidence is False
        assert status.observation_count == 0
        assert status.confidence == 0.0

    def test_missing_node(self):
        status = check_evidence_chain(self.graph, "nonexistent")
        assert status.has_evidence is False
        assert status.sufficient is False

    def test_min_observations_threshold(self):
        email = [n for n in self.graph.nodes.values()
                 if n.properties.get("selector") == "#email"][0]
        # email has 1 observation
        status = check_evidence_chain(
            self.graph, email.node_id, min_observations=2
        )
        assert status.observation_count == 1
        assert status.sufficient is False

    def test_evidence_types_dom(self):
        login_btn = [n for n in self.graph.nodes.values()
                     if n.properties.get("tag") == "button"][0]
        status = check_evidence_chain(self.graph, login_btn.node_id)
        assert "dom" in status.evidence_types

    def test_evidence_types_network(self):
        net_node = create_node(
            NodeType.NETWORK, "net:node",
            properties={"healthy": True},
            observation_ids=["obs-net-1"],
        )
        self.graph.add_node(net_node)
        status = check_evidence_chain(self.graph, net_node.node_id)
        assert "network" in status.evidence_types

    def test_evidence_types_visual(self):
        vis_node = create_node(
            NodeType.VISUAL, "vis:node",
            properties={"visible": True},
            observation_ids=["obs-vis-1"],
        )
        self.graph.add_node(vis_node)
        status = check_evidence_chain(self.graph, vis_node.node_id)
        assert "actionability" in status.evidence_types

    def test_evidence_from_edges(self):
        # Node with no direct obs but has EVIDENCE edge to proxy
        node = create_node(NodeType.DOM, "linked-node")
        proxy = create_node(
            NodeType.DOM, "obs-proxy",
            properties={"is_observation_proxy": True},
            observation_ids=["obs-edge-1", "obs-edge-2"],
        )
        self.graph.add_node(node)
        self.graph.add_node(proxy)
        self.graph.add_edge(create_edge(
            node.node_id, proxy.node_id, EdgeType.EVIDENCE
        ))

        status = check_evidence_chain(self.graph, node.node_id)
        assert status.has_evidence is True
        assert status.observation_count == 2

    def test_confidence_levels(self):
        # 0 observations → 0.0
        n0 = create_node(NodeType.DOM, "n0")
        self.graph.add_node(n0)
        s0 = check_evidence_chain(self.graph, n0.node_id)
        assert s0.confidence == 0.0

        # 1 observation → 0.5
        n1 = create_node(NodeType.DOM, "n1", observation_ids=["o1"])
        self.graph.add_node(n1)
        s1 = check_evidence_chain(self.graph, n1.node_id)
        assert s1.confidence == 0.5

        # 2 observations → 0.8
        n2 = create_node(NodeType.DOM, "n2", observation_ids=["o1", "o2"])
        self.graph.add_node(n2)
        s2 = check_evidence_chain(self.graph, n2.node_id)
        assert s2.confidence == 0.8

        # 4+ observations → 1.0
        n4 = create_node(NodeType.DOM, "n4", observation_ids=["o1", "o2", "o3", "o4"])
        self.graph.add_node(n4)
        s4 = check_evidence_chain(self.graph, n4.node_id)
        assert s4.confidence == 1.0


# ---------------------------------------------------------------------------
# Safety helpers tests
# ---------------------------------------------------------------------------

class TestSafetyHelpers:
    def setup_method(self):
        self.graph = _make_simple_graph()

    def test_no_safety_block(self):
        login_btn = [n for n in self.graph.nodes.values()
                     if n.properties.get("tag") == "button"][0]
        blocked, reason = _is_safety_blocked(self.graph, login_btn.node_id)
        assert blocked is False
        assert reason is None

    def test_safety_block_detected(self):
        login_btn = [n for n in self.graph.nodes.values()
                     if n.properties.get("tag") == "button"][0]
        _add_safety_block(self.graph, login_btn.node_id)
        blocked, reason = _is_safety_blocked(self.graph, login_btn.node_id)
        assert blocked is True
        assert "dangerous" in reason

    def test_safety_action_not_blocked(self):
        login_btn = [n for n in self.graph.nodes.values()
                     if n.properties.get("tag") == "button"][0]
        safety = create_node(
            NodeType.INTENT, "safety:action:ok",
            properties={
                "is_safety_enrichment": True,
                "strategy": "action",  # action means proceed
            },
        )
        self.graph.add_node(safety)
        self.graph.add_edge(create_edge(
            safety.node_id, login_btn.node_id, EdgeType.DEPENDENCY,
        ))
        blocked, reason = _is_safety_blocked(self.graph, login_btn.node_id)
        assert blocked is False

    def test_get_all_blocked_ids(self):
        login_btn = [n for n in self.graph.nodes.values()
                     if n.properties.get("tag") == "button"][0]
        email = [n for n in self.graph.nodes.values()
                 if n.properties.get("selector") == "#email"][0]

        _add_safety_block(self.graph, login_btn.node_id)
        _add_safety_block(self.graph, email.node_id)

        blocked = _get_safety_blocked_ids(self.graph)
        assert login_btn.node_id in blocked
        assert email.node_id in blocked
        assert len(blocked) == 2

    def test_non_intent_safety_ignored(self):
        login_btn = [n for n in self.graph.nodes.values()
                     if n.properties.get("tag") == "button"][0]
        # Non-INTENT node with safety-enrichment property
        fake_safety = create_node(
            NodeType.DOM, "fake-safety",
            properties={"is_safety_enrichment": True, "strategy": "abort"},
        )
        self.graph.add_node(fake_safety)
        self.graph.add_edge(create_edge(
            fake_safety.node_id, login_btn.node_id, EdgeType.DEPENDENCY,
        ))
        blocked, _ = _is_safety_blocked(self.graph, login_btn.node_id)
        assert blocked is False  # Only INTENT nodes count as safety blockers


# ---------------------------------------------------------------------------
# Integration: combined queries
# ---------------------------------------------------------------------------

class TestQueryIntegration:
    def test_find_then_verify_evidence(self):
        """Find actionable nodes, then verify their evidence chains."""
        graph = _make_simple_graph()
        matches = find_actionable_nodes(graph, IntentType.CLICK)
        assert len(matches) >= 1

        for match in matches:
            status = check_evidence_chain(graph, match.node.node_id)
            assert status.has_evidence is True

    def test_resolve_then_check_path(self):
        """Resolve a target, then find a safe path to it."""
        graph = _make_simple_graph()
        root = [n for n in graph.nodes.values() if n.properties.get("is_root")][0]

        target = resolve_target(graph, "Login")
        assert target is not None

        path = find_safe_path(graph, root.node_id, target.node.node_id)
        assert path.blocked is False
        assert len(path.path) >= 2

    def test_blocked_path_blocks_resolve(self):
        """Safety-blocked node is excluded from resolution."""
        graph = _make_simple_graph()
        login_btn = [n for n in graph.nodes.values()
                     if n.properties.get("tag") == "button"][0]
        _add_safety_block(graph, login_btn.node_id)

        # resolve_target excludes blocked by default
        result = resolve_target(graph, "Login")
        assert result is None or result.node.node_id != login_btn.node_id

    def test_full_pipeline_with_mock_data(self):
        """Simulate observer → graph → query → evidence verification."""
        graph = _make_simple_graph()

        # Find all actionable nodes
        all_matches = find_actionable_nodes(graph, IntentType.ANY)
        assert len(all_matches) == 3

        # Resolve specific target
        login_match = resolve_target(graph, "Login", intent=IntentType.CLICK)
        assert login_match is not None

        # Verify evidence
        evidence = check_evidence_chain(
            graph, login_match.node.node_id, min_observations=1
        )
        assert evidence.sufficient is True

        # Find path from root
        root = [n for n in graph.nodes.values() if n.properties.get("is_root")][0]
        path = find_safe_path(graph, root.node_id, login_match.node.node_id)
        assert path.blocked is False
        assert login_match.node.node_id in path.path
