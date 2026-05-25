"""Tests for netweaver/scene_graph_builder.py — Observer→SceneGraph pipeline.

Validates the critical novelty-bridging module that connects:
  PageObservation → EvidenceReport → WebSceneGraph with DOM/A11Y/Visual/Network/Intent nodes.
"""

import json
import pytest
from datetime import datetime
from typing import Dict

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    observe_page_mock,
)
from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    SceneEdge,
    SceneNode,
    WebSceneGraph,
)
from netweaver.scene_graph_builder import (
    BuilderConfig,
    BuilderResult,
    SceneGraphBuilder,
    build_scene_graph,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_element(
    selector: str = "button#submit",
    tag: str = "button",
    elem_type: str = "submit",
    text: str = "Submit",
    aria_label: str = "Submit form",
    visible: bool = True,
    enabled: bool = True,
    editable: bool = False,
    attached: bool = True,
    stable: bool = True,
    pointer_events: bool = True,
) -> InteractiveElement:
    """Helper to create an InteractiveElement with defaults."""
    return InteractiveElement(
        selector=selector,
        tag=tag,
        type=elem_type,
        text=text,
        aria_label=aria_label,
        actionability={
            "attached": attached,
            "visible": visible,
            "enabled": enabled,
            "editable": editable,
            "stable": stable,
            "pointer_events": pointer_events,
        },
    )


def _make_observation(
    elements=None,
    url: str = "https://example.com",
    title: str = "Test Page",
) -> PageObservation:
    """Helper to create a PageObservation with defaults."""
    if elements is None:
        elements = [
            _make_element(
                selector="button#submit",
                tag="button",
                elem_type="submit",
                text="Submit",
                aria_label="Submit form",
            ),
            _make_element(
                selector="input#email",
                tag="input",
                elem_type="email",
                text=None,
                aria_label="Email address",
                editable=True,
            ),
        ]
    return PageObservation(
        url=url,
        title=title,
        interactive_elements=elements,
        actionability={
            "total_elements": len(elements),
            "actionable_elements": len([e for e in elements if e.actionability and e.actionability.get("enabled")]),
            "checks_performed": ["attached", "visible", "enabled"],
        },
        network=NetworkActivity(
            requests_count=5,
            responses_count=5,
            failed_count=0,
            resource_types={"document": 1, "script": 2, "image": 2},
        ),
        observed_at=datetime.now(),
    )


# ===========================================================================
# Basic builder tests
# ===========================================================================

class TestSceneGraphBuilderBasic:
    """Basic builder creation and configuration tests."""

    def test_builder_creates_with_default_config(self):
        builder = SceneGraphBuilder()
        assert builder.config is not None
        assert builder.config.include_a11y_nodes is True
        assert builder.config.include_visual_nodes is True

    def test_builder_creates_with_custom_config(self):
        config = BuilderConfig(include_network_nodes=False)
        builder = SceneGraphBuilder(config)
        assert builder.config.include_network_nodes is False

    def test_build_returns_builder_result(self):
        result = build_scene_graph(_make_observation())
        assert isinstance(result, BuilderResult)
        assert isinstance(result.graph, WebSceneGraph)
        assert isinstance(result.evidence_report, object)
        assert isinstance(result.stats, dict)
        assert isinstance(result.warnings, list)

    def test_build_graph_has_url_and_title(self):
        obs = _make_observation(url="https://test.com", title="Test")
        result = build_scene_graph(obs)
        assert result.graph.url == "https://test.com"
        assert result.graph.title == "Test"


# ===========================================================================
# DOM node tests
# ===========================================================================

class TestDOMNodes:
    """Tests for DOM node creation from interactive elements."""

    def test_creates_dom_nodes_for_each_element(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        # 2 elements + 1 page root + observation proxies + other node types
        dom_nodes = result.graph.get_nodes_by_type(NodeType.DOM)
        assert len(dom_nodes) >= 3  # root + 2 elements

    def test_dom_node_has_selector_property(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        dom_nodes = [
            n for n in result.graph.get_nodes_by_type(NodeType.DOM)
            if not n.properties.get("is_root") and not n.properties.get("is_observation_proxy")
        ]
        assert len(dom_nodes) == 2
        selectors = [n.properties["selector"] for n in dom_nodes]
        assert "button#submit" in selectors
        assert "input#email" in selectors

    def test_dom_node_has_tag_property(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        dom_nodes = [
            n for n in result.graph.get_nodes_by_type(NodeType.DOM)
            if not n.properties.get("is_root") and not n.properties.get("is_observation_proxy")
        ]
        tags = {n.properties["tag"] for n in dom_nodes}
        assert "button" in tags
        assert "input" in tags

    def test_dom_node_has_observation_ids(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        dom_nodes = [
            n for n in result.graph.get_nodes_by_type(NodeType.DOM)
            if not n.properties.get("is_root") and not n.properties.get("is_observation_proxy")
        ]
        for node in dom_nodes:
            assert len(node.observation_ids) > 0


# ===========================================================================
# Page root node tests
# ===========================================================================

class TestPageRootNode:
    """Tests for the page root node."""

    def test_page_root_exists(self):
        result = build_scene_graph(_make_observation())
        page_root = [
            n for n in result.graph.nodes.values()
            if n.properties.get("is_root")
        ]
        assert len(page_root) == 1

    def test_page_root_has_url(self):
        result = build_scene_graph(_make_observation(url="https://root.test"))
        page_root = [
            n for n in result.graph.nodes.values()
            if n.properties.get("is_root")
        ]
        assert page_root[0].properties["url"] == "https://root.test"

    def test_page_root_has_title(self):
        result = build_scene_graph(_make_observation(title="Root Title"))
        page_root = [
            n for n in result.graph.nodes.values()
            if n.properties.get("is_root")
        ]
        assert page_root[0].properties["title"] == "Root Title"


# ===========================================================================
# Accessibility node tests
# ===========================================================================

class TestA11yNodes:
    """Tests for ACCESSIBILITY node creation."""

    def test_creates_a11y_nodes_for_elements_with_aria_labels(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        a11y_nodes = result.graph.get_nodes_by_type(NodeType.ACCESSIBILITY)
        assert len(a11y_nodes) >= 2  # both elements have aria_labels

    def test_a11y_node_has_aria_label(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        a11y_nodes = result.graph.get_nodes_by_type(NodeType.ACCESSIBILITY)
        labels = [n.properties.get("aria_label") for n in a11y_nodes]
        assert any(l == "Submit form" for l in labels)
        assert any(l == "Email address" for l in labels)

    def test_no_a11y_node_without_aria_label(self):
        elements = [
            InteractiveElement(
                selector="div.plain",
                tag="div",
                type=None,
                text="Plain div",
                aria_label=None,
                actionability={"attached": True, "visible": True, "enabled": True},
            ),
        ]
        obs = _make_observation(elements=elements)
        result = build_scene_graph(obs)
        a11y_nodes = result.graph.get_nodes_by_type(NodeType.ACCESSIBILITY)
        assert len(a11y_nodes) == 0

    def test_disable_a11y_nodes(self):
        config = BuilderConfig(include_a11y_nodes=False)
        result = build_scene_graph(_make_observation(), config=config)
        a11y_nodes = result.graph.get_nodes_by_type(NodeType.ACCESSIBILITY)
        assert len(a11y_nodes) == 0


# ===========================================================================
# Visual node tests
# ===========================================================================

class TestVisualNodes:
    """Tests for VISUAL node creation."""

    def test_creates_visual_nodes_for_elements_with_actionability(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        vis_nodes = result.graph.get_nodes_by_type(NodeType.VISUAL)
        assert len(vis_nodes) >= 2

    def test_visual_node_has_visibility_data(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        vis_nodes = result.graph.get_nodes_by_type(NodeType.VISUAL)
        assert any(n.properties.get("visible") for n in vis_nodes)

    def test_visual_node_label_reflects_visibility(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        vis_nodes = result.graph.get_nodes_by_type(NodeType.VISUAL)
        # Visible elements have '(v)' in label
        assert any("(v)" in n.label for n in vis_nodes)

    def test_disable_visual_nodes(self):
        config = BuilderConfig(include_visual_nodes=False)
        result = build_scene_graph(_make_observation(), config=config)
        vis_nodes = result.graph.get_nodes_by_type(NodeType.VISUAL)
        assert len(vis_nodes) == 0


# ===========================================================================
# Network node tests
# ===========================================================================

class TestNetworkNodes:
    """Tests for NETWORK node creation."""

    def test_creates_network_node(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        net_nodes = result.graph.get_nodes_by_type(NodeType.NETWORK)
        assert len(net_nodes) == 1

    def test_network_node_has_request_counts(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        net_nodes = result.graph.get_nodes_by_type(NodeType.NETWORK)
        assert net_nodes[0].properties["requests_count"] == 5
        assert net_nodes[0].properties["responses_count"] == 5
        assert net_nodes[0].properties["failed_count"] == 0

    def test_network_node_healthy_when_no_failures(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        net_nodes = result.graph.get_nodes_by_type(NodeType.NETWORK)
        assert net_nodes[0].properties["healthy"] is True

    def test_network_node_unhealthy_with_failures(self):
        elements = [_make_element()]
        obs = _make_observation(elements=elements)
        obs.network.failed_count = 2
        result = build_scene_graph(obs)
        net_nodes = result.graph.get_nodes_by_type(NodeType.NETWORK)
        assert net_nodes[0].properties["healthy"] is False

    def test_disable_network_nodes(self):
        config = BuilderConfig(include_network_nodes=False)
        result = build_scene_graph(_make_observation(), config=config)
        net_nodes = result.graph.get_nodes_by_type(NodeType.NETWORK)
        assert len(net_nodes) == 0


# ===========================================================================
# Intent node tests
# ===========================================================================

class TestIntentNodes:
    """Tests for INTENT node creation (element affordances)."""

    def test_creates_intent_nodes_for_actionable_elements(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        # Both elements are visible + enabled, so intent nodes should exist
        assert len(intent_nodes) >= 2

    def test_button_affordance_is_clickable(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        clickables = [
            n for n in intent_nodes
            if n.properties.get("affordance") == "clickable"
        ]
        assert len(clickables) >= 1

    def test_input_affordance_is_fillable(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        fillables = [
            n for n in intent_nodes
            if n.properties.get("affordance") == "fillable"
        ]
        assert len(fillables) >= 1

    def test_no_intent_node_for_hidden_element(self):
        elements = [
            _make_element(selector="button#hidden", visible=False, enabled=True),
        ]
        obs = _make_observation(elements=elements)
        result = build_scene_graph(obs)
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        assert len(intent_nodes) == 0

    def test_no_intent_node_for_disabled_element(self):
        elements = [
            _make_element(selector="button#disabled", visible=True, enabled=False),
        ]
        obs = _make_observation(elements=elements)
        result = build_scene_graph(obs)
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        assert len(intent_nodes) == 0

    def test_link_affordance_is_navigable(self):
        elements = [
            InteractiveElement(
                selector="a.home",
                tag="a",
                type=None,
                text="Home",
                aria_label="Go home",
                actionability={
                    "attached": True, "visible": True, "enabled": True,
                    "editable": False, "stable": True, "pointer_events": True,
                },
            ),
        ]
        obs = _make_observation(elements=elements)
        result = build_scene_graph(obs)
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        assert len(intent_nodes) == 1
        assert intent_nodes[0].properties["affordance"] == "navigable"

    def test_select_affordance_is_selectable(self):
        elements = [
            InteractiveElement(
                selector="select.country",
                tag="select",
                type=None,
                text=None,
                aria_label="Country",
                actionability={
                    "attached": True, "visible": True, "enabled": True,
                    "editable": False, "stable": True, "pointer_events": True,
                },
            ),
        ]
        obs = _make_observation(elements=elements)
        result = build_scene_graph(obs)
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        assert len(intent_nodes) == 1
        assert intent_nodes[0].properties["affordance"] == "selectable"

    def test_disable_intent_nodes(self):
        config = BuilderConfig(include_intent_nodes=False)
        result = build_scene_graph(_make_observation(), config=config)
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        assert len(intent_nodes) == 0


# ===========================================================================
# Edge tests
# ===========================================================================

class TestEdges:
    """Tests for edge creation (containment, evidence, dependency)."""

    def test_containment_edges_from_page_root(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        page_root_id = [
            nid for nid, n in result.graph.nodes.items()
            if n.properties.get("is_root")
        ][0]
        children = result.graph.get_children(page_root_id)
        # Should have 2 DOM element children + 1 network node
        assert len(children) >= 3

    def test_containment_edges_dom_to_a11y(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        a11y_nodes = result.graph.get_nodes_by_type(NodeType.ACCESSIBILITY)
        for a11y_node in a11y_nodes:
            parent_id = result.graph.get_parent(a11y_node.node_id)
            assert parent_id is not None
            parent = result.graph.get_node(parent_id)
            assert parent.node_type == NodeType.DOM

    def test_dependency_edges_enrichment(self):
        obs = _make_observation()
        result = build_scene_graph(obs)
        dep_edges = result.graph.get_edges_by_type(EdgeType.DEPENDENCY)
        assert len(dep_edges) > 0

    def test_disable_containment_edges(self):
        config = BuilderConfig(include_containment_edges=False)
        result = build_scene_graph(_make_observation(), config=config)
        cont_edges = result.graph.get_edges_by_type(EdgeType.CONTAINMENT)
        assert len(cont_edges) == 0


# ===========================================================================
# Evidence report integration tests
# ===========================================================================

class TestEvidenceIntegration:
    """Tests for evidence report integration with scene graph."""

    def test_evidence_report_created(self):
        result = build_scene_graph(_make_observation())
        report = result.evidence_report
        assert report is not None
        assert len(report.observations) > 0
        assert len(report.claims) > 0

    def test_stats_include_evidence_counts(self):
        result = build_scene_graph(_make_observation())
        assert "evidence_observations" in result.stats
        assert "evidence_claims" in result.stats
        assert result.stats["evidence_observations"] > 0
        assert result.stats["evidence_claims"] > 0

    def test_dom_nodes_have_linked_observations(self):
        result = build_scene_graph(_make_observation())
        dom_nodes = [
            n for n in result.graph.get_nodes_by_type(NodeType.DOM)
            if not n.properties.get("is_root") and not n.properties.get("is_observation_proxy")
        ]
        for node in dom_nodes:
            assert node.has_evidence()


# ===========================================================================
# Stats tests
# ===========================================================================

class TestStats:
    """Tests for build statistics."""

    def test_stats_include_dom_node_count(self):
        result = build_scene_graph(_make_observation())
        assert result.stats["dom_nodes"] == 2

    def test_stats_include_total_counts(self):
        result = build_scene_graph(_make_observation())
        assert result.stats["total_nodes"] > 0
        assert result.stats["total_edges"] > 0

    def test_stats_network_node_count(self):
        result = build_scene_graph(_make_observation())
        assert result.stats["network_nodes"] == 1

    def test_stats_zero_when_disabled(self):
        config = BuilderConfig(
            include_a11y_nodes=False,
            include_visual_nodes=False,
            include_network_nodes=False,
            include_intent_nodes=False,
        )
        result = build_scene_graph(_make_observation(), config=config)
        assert result.stats["a11y_nodes"] == 0
        assert result.stats["visual_nodes"] == 0
        assert result.stats["network_nodes"] == 0
        assert result.stats["intent_nodes"] == 0


# ===========================================================================
# Full pipeline test with mock observer
# ===========================================================================

class TestFullPipeline:
    """Integration tests using the mock observer."""

    def test_mock_observer_to_scene_graph(self):
        """Full pipeline: mock observer → evidence report → scene graph."""
        obs = observe_page_mock("https://example.com")
        result = build_scene_graph(obs)
        assert result.graph.node_count() > 0
        assert result.graph.edge_count() > 0
        assert result.graph.url == "https://example.com"

    def test_graph_serialization_round_trip(self):
        obs = observe_page_mock("https://example.com")
        result = build_scene_graph(obs)
        json_str = result.graph.to_json()
        reconstructed = WebSceneGraph.from_json(json_str)
        assert reconstructed.url == result.graph.url
        assert reconstructed.title == result.graph.title
        assert reconstructed.node_count() == result.graph.node_count()
        assert reconstructed.edge_count() == result.graph.edge_count()

    def test_graph_summary(self):
        obs = observe_page_mock("https://example.com")
        result = build_scene_graph(obs)
        summary = result.graph.summary()
        assert "graph_id" in summary
        assert "url" in summary
        assert "node_count" in summary
        assert "edge_count" in summary
        assert "nodes_by_type" in summary

    def test_no_browser_required(self):
        """Ensure the full pipeline runs without a browser."""
        obs = observe_page_mock("https://test.no-browser.com")
        result = build_scene_graph(obs)
        assert result.graph.node_count() > 0
        assert len(result.warnings) == 0

    def test_empty_elements(self):
        """Handle observation with no interactive elements."""
        obs = _make_observation(elements=[])
        result = build_scene_graph(obs)
        assert result.graph.node_count() >= 2  # root + network
        assert result.stats["dom_nodes"] == 0
        assert result.stats["a11y_nodes"] == 0

    def test_many_elements(self):
        """Handle observation with many elements."""
        elements = [
            _make_element(selector=f"button#{i}", tag="button", text=f"Btn {i}")
            for i in range(20)
        ]
        obs = _make_observation(elements=elements)
        result = build_scene_graph(obs)
        assert result.stats["dom_nodes"] == 20
        assert result.stats["intent_nodes"] == 20

    def test_element_without_actionability(self):
        """Handle element with no actionability data."""
        elements = [
            InteractiveElement(
                selector="div.no-act",
                tag="div",
                type=None,
                text="No actionability",
                aria_label=None,
                actionability=None,
            ),
        ]
        obs = _make_observation(elements=elements)
        result = build_scene_graph(obs)
        assert result.stats["dom_nodes"] == 1
        assert result.stats["visual_nodes"] == 0  # no actionability → no visual node
        assert result.stats["intent_nodes"] == 0


# ===========================================================================
# Perspective enrichment tests
# ===========================================================================

class TestPerspectiveEnrichment:
    """Tests for optional perspective engine enrichment."""

    def test_enrichment_disabled_by_default(self):
        result = build_scene_graph(_make_observation())
        assert "perspective_enriched" not in result.stats

    def test_enrichment_with_mock_engine(self):
        """Test enrichment with a mock perspective engine."""
        config = BuilderConfig(run_perspective_enrichment=True)
        builder = SceneGraphBuilder(config)

        # Create a mock perspective engine
        class MockResolution:
            strategy = type("Strategy", (), {"value": "action"})()
            reason = "Mock: safe"

        class MockEngine:
            def analyze(self, action, evidence, context):
                return MockResolution()

        obs = _make_observation()
        result = builder.build(obs, perspective_engine=MockEngine())
        assert result.stats.get("perspective_enriched") is True

    def test_enrichment_adds_safety_nodes_for_non_action(self):
        """Non-ACTION strategies should add SAFETY nodes."""
        from netweaver.perspective import ResolutionStrategy

        config = BuilderConfig(run_perspective_enrichment=True)
        builder = SceneGraphBuilder(config)

        class AskResolution:
            strategy = ResolutionStrategy.ASK
            reason = "Confirmation required"

        class MockEngine:
            def analyze(self, action, evidence, context):
                return AskResolution()

        obs = _make_observation()
        result = builder.build(obs, perspective_engine=MockEngine())

        # Should have added safety-related intent nodes
        intent_nodes = result.graph.get_nodes_by_type(NodeType.INTENT)
        safety_nodes = [
            n for n in intent_nodes
            if n.properties.get("is_safety_enrichment")
        ]
        assert len(safety_nodes) >= 1

    def test_enrichment_handles_engine_failure(self):
        """Builder should handle exceptions from perspective engine gracefully."""
        config = BuilderConfig(run_perspective_enrichment=True)
        builder = SceneGraphBuilder(config)

        class FailingEngine:
            def analyze(self, action, evidence, context):
                raise RuntimeError("Engine failed")

        obs = _make_observation()
        result = builder.build(obs, perspective_engine=FailingEngine())
        assert len(result.warnings) > 0
        assert "Perspective enrichment failed" in result.warnings[0]


# ===========================================================================
# Edge case tests
# ===========================================================================

class TestEdgeCases:
    """Edge case and robustness tests."""

    def test_single_hidden_element(self):
        elements = [
            _make_element(selector="button#hid", visible=False),
        ]
        obs = _make_observation(elements=elements)
        result = build_scene_graph(obs)
        # Hidden element gets DOM node but no intent node
        assert result.stats["dom_nodes"] == 1
        assert result.stats["intent_nodes"] == 0

    def test_network_with_many_resource_types(self):
        elements = [_make_element()]
        obs = _make_observation(elements=elements)
        obs.network.resource_types = {
            "document": 1, "stylesheet": 5, "script": 10,
            "image": 20, "font": 3, "xhr": 5, "websocket": 1,
        }
        result = build_scene_graph(obs)
        net_nodes = result.graph.get_nodes_by_type(NodeType.NETWORK)
        assert len(net_nodes[0].properties["resource_types"]) == 7

    def test_graph_evidence_coverage(self):
        obs = observe_page_mock("https://example.com")
        result = build_scene_graph(obs)
        coverage = result.graph.evidence_coverage()
        assert "nodes" in coverage
        assert "edges" in coverage
        # Most nodes should have evidence
        assert coverage["nodes"] > 0.0

    def test_no_warnings_on_normal_input(self):
        result = build_scene_graph(_make_observation())
        assert len(result.warnings) == 0
