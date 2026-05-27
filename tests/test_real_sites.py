"""NW-033: Real-Site Golden Snapshot Tests.

Integration tests using 3 golden snapshots (static blog, e-commerce SPA,
complex dashboard). Tests parse fixture data → build SceneGraph → validate
structure matches golden expectations. Network trace replay validates
graph_query results. Regression detection alerts on structural changes.

All tests use mocked browser (no real Chromium/network).
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    StorageState,
)
from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    WebSceneGraph,
)
from netweaver.scene_graph_builder import (
    BuilderConfig,
    BuilderResult,
    SceneGraphBuilder,
    build_scene_graph,
)
from netweaver.graph_query import (
    IntentType,
    QueryMatch,
    find_actionable_nodes,
    resolve_target,
)


# ---------------------------------------------------------------------------
# Fixture loading helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "golden"


def _load_golden(name: str) -> Dict[str, Any]:
    """Load a golden snapshot fixture by name."""
    path = FIXTURES_DIR / name
    assert path.exists(), f"Golden fixture missing: {path}"
    with open(path, "r") as f:
        return json.load(f)


def _elements_from_fixture(data: Dict) -> List[InteractiveElement]:
    """Convert fixture JSON interactive_elements to InteractiveElement objects."""
    elements = []
    for el_data in data.get("interactive_elements", []):
        elements.append(InteractiveElement(
            selector=el_data["selector"],
            tag=el_data["tag"],
            type=el_data.get("type"),
            text=el_data.get("text"),
            aria_label=el_data.get("aria_label"),
            actionability=el_data.get("actionability"),
        ))
    return elements


def _network_from_fixture(data: Dict) -> NetworkActivity:
    """Convert fixture JSON network entries to NetworkActivity."""
    net_entries = data.get("network", [])
    resource_types: Dict[str, int] = {}
    failed = 0
    for entry in net_entries:
        rtype = entry.get("type", "other")
        resource_types[rtype] = resource_types.get(rtype, 0) + 1
        status = entry.get("status", 200)
        if status >= 400:
            failed += 1
    return NetworkActivity(
        requests_count=len(net_entries),
        responses_count=len(net_entries),
        failed_count=failed,
        resource_types=resource_types,
    )


def _observation_from_fixture(data: Dict) -> PageObservation:
    """Convert a golden fixture dict to a PageObservation."""
    elements = _elements_from_fixture(data)
    network = _network_from_fixture(data)
    actionability_summary = {
        "total_elements": len(elements),
        "actionable_elements": len([
            e for e in elements
            if e.actionability and e.actionability.get("enabled")
        ]),
        "checks_performed": ["attached", "visible", "enabled", "editable", "stable", "pointer_events"],
    }
    return PageObservation(
        url=data["url"],
        title=data["title"],
        interactive_elements=elements,
        actionability=actionability_summary,
        network=network,
        observed_at=datetime.now(),
        storage=StorageState(
            local_storage={"theme": "dark"},
            session_storage={"session_id": "golden-test"},
            cookies=[],
        ),
    )


def _build_from_golden(name: str) -> tuple:
    """Load golden fixture, build graph, return (data, result)."""
    data = _load_golden(name)
    obs = _observation_from_fixture(data)
    result = build_scene_graph(obs)
    return data, result


# ===========================================================================
# 1. STATIC BLOG — Basic golden snapshot validation
# ===========================================================================

class TestStaticBlogGolden:
    """Golden snapshot: static blog with navigation, comments, social links."""

    def test_blog_loads_fixture(self):
        """Verify fixture loads and has required structure."""
        data = _load_golden("static_blog.json")
        assert data["url"] == "https://blog.example.com/post/getting-started-with-web-automation"
        assert "expected_graph" in data
        assert len(data["interactive_elements"]) == 14

    def test_blog_observation_conversion(self):
        """Fixture JSON converts to valid PageObservation."""
        data = _load_golden("static_blog.json")
        obs = _observation_from_fixture(data)
        assert obs.url == data["url"]
        assert obs.title == data["title"]
        assert len(obs.interactive_elements) == 14
        assert obs.network.requests_count == 2
        assert obs.network.failed_count == 0

    def test_blog_builds_graph_successfully(self):
        """Blog fixture produces a valid SceneGraph."""
        data, result = _build_from_golden("static_blog.json")
        assert isinstance(result, BuilderResult)
        assert isinstance(result.graph, WebSceneGraph)
        assert result.graph.url == data["url"]
        assert result.graph.title == data["title"]
        assert result.evidence_report is not None
        assert len(result.warnings) == 0

    def test_blog_node_counts_match_golden(self):
        """Scene graph node counts match golden expectations."""
        data, result = _build_from_golden("static_blog.json")
        expected = data["expected_graph"]
        stats = result.stats

        assert stats["dom_nodes"] >= expected["min_dom_nodes"], (
            f"DOM nodes: {stats['dom_nodes']} < {expected['min_dom_nodes']}"
        )
        assert stats["a11y_nodes"] >= expected["min_a11y_nodes"]
        assert stats["visual_nodes"] >= expected["min_visual_nodes"]
        assert stats["intent_nodes"] >= expected["min_intent_nodes"]
        assert stats["network_nodes"] >= expected["min_network_nodes"]
        assert stats["total_nodes"] >= expected["min_total_nodes"]

    def test_blog_edge_counts_match_golden(self):
        """Edge counts meet golden minimums."""
        data, result = _build_from_golden("static_blog.json")
        expected = data["expected_graph"]
        graph = result.graph

        containment = graph.get_edges_by_type(EdgeType.CONTAINMENT)
        evidence = graph.get_edges_by_type(EdgeType.EVIDENCE)
        dependency = graph.get_edges_by_type(EdgeType.DEPENDENCY)

        assert len(containment) >= expected["min_containment_edges"]
        assert len(evidence) >= expected["min_evidence_edges"]
        assert len(dependency) >= expected["min_dependency_edges"]


# ===========================================================================
# 2. E-COMMERCE SPA — Hidden elements, selectables, toggleables
# ===========================================================================

class TestEcommerceSpaGolden:
    """Golden snapshot: e-commerce product page with cart, reviews, filters."""

    def test_ecommerce_observation_conversion(self):
        """E-commerce fixture converts correctly."""
        data = _load_golden("ecommerce_spa.json")
        obs = _observation_from_fixture(data)
        assert len(obs.interactive_elements) == 20
        assert obs.network.requests_count == 6
        assert obs.network.failed_count == 0

    def test_ecommerce_builds_graph(self):
        """E-commerce fixture produces valid graph with correct URL."""
        data, result = _build_from_golden("ecommerce_spa.json")
        assert result.graph.url == data["url"]
        assert result.evidence_report is not None

    def test_ecommerce_node_counts(self):
        """E-commerce graph has sufficient node counts for 20 elements."""
        data, result = _build_from_golden("ecommerce_spa.json")
        expected = data["expected_graph"]
        stats = result.stats

        assert stats["dom_nodes"] >= expected["min_dom_nodes"]
        assert stats["a11y_nodes"] >= expected["min_a11y_nodes"]
        assert stats["visual_nodes"] >= expected["min_visual_nodes"]
        assert stats["intent_nodes"] >= expected["min_intent_nodes"]
        assert stats["total_nodes"] >= expected["min_total_nodes"]

    def test_ecommerce_hidden_elements_no_intent_nodes(self):
        """Hidden elements (visible=false) should NOT get intent nodes.

        The builder only creates intent nodes for visible+enabled elements.
        The e-commerce fixture has 3 hidden elements (review-text, review-rating,
        submit-review). Intent count should be element_count - hidden_count.
        """
        data, result = _build_from_golden("ecommerce_spa.json")
        expected = data["expected_graph"]
        stats = result.stats

        # 20 elements - 3 hidden = 17 max visible, but only visible+enabled get intent
        # All visible elements are enabled, so 17 intent nodes expected
        hidden = expected["hidden_elements"]
        total_elements = expected["element_count"]
        max_intent = total_elements - hidden
        assert stats["intent_nodes"] <= max_intent, (
            f"Intent nodes {stats['intent_nodes']} should be <= {max_intent} "
            f"({total_elements} elements - {hidden} hidden)"
        )

    def test_ecommerce_selectable_nodes_exist(self):
        """Select elements should produce 'selectable' intent nodes."""
        _, result = _build_from_golden("ecommerce_spa.json")
        graph = result.graph

        intent_nodes = graph.get_nodes_by_type(NodeType.INTENT)
        affordances = [n.properties.get("affordance") for n in intent_nodes]

        # 3 selects: variant-select, sort-by, review-rating (hidden, no intent)
        # So only 2 visible selects should produce selectable affordances
        selectable_count = affordances.count("selectable")
        assert selectable_count >= 2, (
            f"Expected ≥2 selectable affordances, got {selectable_count}: {affordances}"
        )

    def test_ecommerce_toggleable_checkboxes(self):
        """Checkbox inputs should produce 'toggleable' intent nodes."""
        _, result = _build_from_golden("ecommerce_spa.json")
        graph = result.graph

        intent_nodes = graph.get_nodes_by_type(NodeType.INTENT)
        affordances = [n.properties.get("affordance") for n in intent_nodes]

        # 2 visible checkboxes: filter-prime, filter-sale
        toggleable = affordances.count("toggleable")
        assert toggleable >= 2, f"Expected ≥2 toggleable, got {toggleable}"


# ===========================================================================
# 3. COMPLEX DASHBOARD — Disabled states, iframes, network failures
# ===========================================================================

class TestComplexDashboardGolden:
    """Golden snapshot: admin dashboard with widgets, tables, notifications."""

    def test_dashboard_observation_conversion(self):
        """Dashboard fixture converts with correct network failure detection."""
        data = _load_golden("complex_dashboard.json")
        obs = _observation_from_fixture(data)
        assert len(obs.interactive_elements) == 21
        assert obs.network.requests_count == 8
        # Status 429 on last entry → 1 failed
        assert obs.network.failed_count == 1

    def test_dashboard_builds_graph(self):
        """Dashboard fixture produces valid graph."""
        data, result = _build_from_golden("complex_dashboard.json")
        assert result.graph.url == data["url"]
        assert result.evidence_report is not None

    def test_dashboard_node_counts(self):
        """Dashboard graph meets minimum node thresholds."""
        data, result = _build_from_golden("complex_dashboard.json")
        expected = data["expected_graph"]
        stats = result.stats

        assert stats["dom_nodes"] >= expected["min_dom_nodes"]
        assert stats["a11y_nodes"] >= expected["min_a11y_nodes"]
        assert stats["visual_nodes"] >= expected["min_visual_nodes"]
        assert stats["intent_nodes"] >= expected["min_intent_nodes"]
        assert stats["total_nodes"] >= expected["min_total_nodes"]

    def test_dashboard_disabled_elements_no_intent(self):
        """Disabled elements should NOT get intent nodes.

        The dashboard has 2 disabled elements: widget-disabled-btn, table-prev.
        """
        data, result = _build_from_golden("complex_dashboard.json")
        expected = data["expected_graph"]
        stats = result.stats

        disabled = expected["disabled_elements"]
        total_elements = expected["element_count"]
        max_intent = total_elements - disabled
        assert stats["intent_nodes"] <= max_intent, (
            f"Intent nodes {stats['intent_nodes']} should be ≤ {max_intent}"
        )

    def test_dashboard_network_node_healthy_false(self):
        """Network node should report healthy=False due to 429 response."""
        _, result = _build_from_golden("complex_dashboard.json")
        graph = result.graph

        net_nodes = graph.get_nodes_by_type(NodeType.NETWORK)
        assert len(net_nodes) >= 1
        net_node = net_nodes[0]
        assert net_node.properties.get("healthy") is False
        assert net_node.properties.get("failed_count") >= 1


# ===========================================================================
# 4. GRAPH QUERY VALIDATION — find_actionable_nodes & resolve_target
# ===========================================================================

class TestGraphQueryOnGoldenSnapshots:
    """Validate graph_query functions against golden snapshot graphs."""

    def test_find_clickable_on_blog(self):
        """find_actionable_nodes(CLICK) on blog finds buttons."""
        _, result = _build_from_golden("static_blog.json")
        matches = find_actionable_nodes(result.graph, IntentType.CLICK)
        # Blog has 4 buttons (share-twitter, share-linkedin, submit-comment + any buttons)
        selectors = [m.node.properties.get("selector", "") for m in matches]
        assert len(matches) >= 3, f"Expected ≥3 clickable, got {len(matches)}: {selectors}"

    def test_find_navigable_on_blog(self):
        """find_actionable_nodes(NAVIGATE) on blog finds links."""
        _, result = _build_from_golden("static_blog.json")
        matches = find_actionable_nodes(result.graph, IntentType.NAVIGATE)
        # Blog has 8 links
        assert len(matches) >= 6, f"Expected ≥6 navigable, got {len(matches)}"

    def test_find_fillable_on_blog(self):
        """find_actionable_nodes(FILL) on blog finds input/textarea."""
        _, result = _build_from_golden("static_blog.json")
        matches = find_actionable_nodes(result.graph, IntentType.FILL)
        # Blog has 4 fillable: nav-search, comment-body, comment-name, comment-email
        assert len(matches) >= 3, f"Expected ≥3 fillable, got {len(matches)}"

    def test_resolve_target_login_button_on_ecommerce(self):
        """resolve_target finds 'add to cart' button on e-commerce page."""
        _, result = _build_from_golden("ecommerce_spa.json")
        match = resolve_target(result.graph, "add to cart button")
        assert match is not None, "Should resolve 'add to cart button'"
        assert "add-to-cart" in match.node.properties.get("selector", "")

    def test_resolve_target_search_on_dashboard(self):
        """resolve_target finds 'filter table' search on dashboard."""
        _, result = _build_from_golden("complex_dashboard.json")
        match = resolve_target(result.graph, "filter table search")
        assert match is not None, "Should resolve filter table search input"

    def test_find_selectable_on_dashboard(self):
        """find_actionable_nodes(SELECT) on dashboard finds selects."""
        _, result = _build_from_golden("complex_dashboard.json")
        matches = find_actionable_nodes(result.graph, IntentType.SELECT)
        # Dashboard has 2 visible selects: widget-revenue-range, table-page-size
        assert len(matches) >= 2, f"Expected ≥2 selectable, got {len(matches)}"

    def test_find_toggleable_on_ecommerce(self):
        """find_actionable_nodes(TOGGLE) on e-commerce finds checkboxes."""
        _, result = _build_from_golden("ecommerce_spa.json")
        matches = find_actionable_nodes(result.graph, IntentType.TOGGLE)
        # 2 checkboxes: filter-prime, filter-sale
        assert len(matches) >= 2, f"Expected ≥2 toggleable, got {len(matches)}"


# ===========================================================================
# 5. NETWORK TRACE REPLAY — Validate XHR/fetch patterns in graph
# ===========================================================================

class TestNetworkTraceReplay:
    """Replay network traces from golden fixtures, validate graph state."""

    def test_blog_network_trace_all_200(self):
        """Blog network trace: all requests succeeded (200)."""
        data = _load_golden("static_blog.json")
        net_entries = data["network"]
        assert all(e["status"] == 200 for e in net_entries)

        obs = _observation_from_fixture(data)
        assert obs.network.failed_count == 0
        assert obs.network.requests_count == 2

    def test_ecommerce_network_trace_multiple_types(self):
        """E-commerce trace: fetch, image, beacon resource types."""
        data = _load_golden("ecommerce_spa.json")
        obs = _observation_from_fixture(data)

        types = set(obs.network.resource_types.keys())
        assert "fetch" in types
        assert "image" in types
        assert "beacon" in types

    def test_dashboard_network_trace_has_failure(self):
        """Dashboard trace: 429 rate limit detected in network node."""
        _, result = _build_from_golden("complex_dashboard.json")
        graph = result.graph

        net_nodes = graph.get_nodes_by_type(NodeType.NETWORK)
        assert len(net_nodes) >= 1
        props = net_nodes[0].properties
        assert props["failed_count"] >= 1
        assert props["requests_count"] == 8
        assert props["healthy"] is False

    def test_dashboard_network_trace_websocket(self):
        """Dashboard trace includes websocket connection type."""
        data = _load_golden("complex_dashboard.json")
        ws_entries = [e for e in data["network"] if e["type"] == "websocket"]
        assert len(ws_entries) >= 1, "Dashboard should have websocket entries"


# ===========================================================================
# 6. REGRESSION DETECTION — Detect structural changes in builder output
# ===========================================================================

# Baseline stats captured from initial golden run
GOLDEN_BASELINES = {
    "static_blog.json": {
        "element_count": 14,
        "min_total_nodes": 40,
    },
    "ecommerce_spa.json": {
        "element_count": 20,
        "min_total_nodes": 60,
    },
    "complex_dashboard.json": {
        "element_count": 21,
        "min_total_nodes": 70,
    },
}


class TestRegressionDetection:
    """Detect if SceneGraph structure changes after code modifications.

    Compares current builder output against captured baselines. If node/edge
    counts deviate significantly from golden expectations, the test alerts
    that a regression may have occurred.
    """

    @pytest.mark.parametrize("fixture_name", list(GOLDEN_BASELINES.keys()))
    def test_graph_structure_matches_baseline(self, fixture_name):
        """Graph structure hasn't regressed from golden baseline."""
        data, result = _build_from_golden(fixture_name)
        baseline = GOLDEN_BASELINES[fixture_name]
        expected = data["expected_graph"]

        # Element count must match exactly
        assert len(data["interactive_elements"]) == baseline["element_count"], (
            f"Element count mismatch for {fixture_name}"
        )

        # Total nodes must meet minimum threshold
        assert result.stats["total_nodes"] >= baseline["min_total_nodes"], (
            f"REGRESSION: {fixture_name} total_nodes={result.stats['total_nodes']} "
            f"< baseline {baseline['min_total_nodes']}. Builder may have changed."
        )

    @pytest.mark.parametrize("fixture_name", list(GOLDEN_BASELINES.keys()))
    def test_graph_deterministic_structure(self, fixture_name):
        """Building the same fixture twice produces identical structural stats."""
        obs = _observation_from_fixture(_load_golden(fixture_name))
        result1 = build_scene_graph(obs)
        result2 = build_scene_graph(obs)

        # Stats should be identical (same input → same output)
        for key in ("dom_nodes", "a11y_nodes", "visual_nodes", "intent_nodes", "network_nodes"):
            assert result1.stats[key] == result2.stats[key], (
                f"REGRESSION: {fixture_name} {key} differs between builds: "
                f"{result1.stats[key]} vs {result2.stats[key]}"
            )

    def test_regression_alert_on_node_count_change(self):
        """Simulate regression: if a builder config changes, stats differ."""
        data = _load_golden("static_blog.json")
        obs = _observation_from_fixture(data)

        # Normal build
        result_normal = build_scene_graph(obs)

        # Build with a11y nodes disabled (simulates config regression)
        config_no_a11y = BuilderConfig(include_a11y_nodes=False)
        result_no_a11y = build_scene_graph(obs, config=config_no_a11y)

        # a11y count should differ — this is the "regression detection"
        assert result_normal.stats["a11y_nodes"] > result_no_a11y.stats["a11y_nodes"], (
            "Regression detection: disabling a11y should reduce a11y_nodes"
        )
        assert result_normal.stats["total_nodes"] > result_no_a11y.stats["total_nodes"]


# ===========================================================================
# 7. CROSS-FIXTURE INVARIANTS
# ===========================================================================

class TestCrossFixtureInvariants:
    """Invariants that must hold across all golden snapshots."""

    @pytest.mark.parametrize("fixture_name", list(GOLDEN_BASELINES.keys()))
    def test_every_dom_node_has_evidence(self, fixture_name):
        """Every DOM element node should have at least one observation linked."""
        _, result = _build_from_golden(fixture_name)
        graph = result.graph

        dom_nodes = graph.get_nodes_by_type(NodeType.DOM)
        # Skip page root and observation proxies
        element_nodes = [
            n for n in dom_nodes
            if not n.properties.get("is_root", False)
            and not n.properties.get("is_observation_proxy", False)
        ]
        nodes_with_evidence = [n for n in element_nodes if n.has_evidence()]
        assert len(nodes_with_evidence) == len(element_nodes), (
            f"{fixture_name}: {len(element_nodes) - len(nodes_with_evidence)} "
            f"DOM nodes lack evidence backing"
        )

    @pytest.mark.parametrize("fixture_name", list(GOLDEN_BASELINES.keys()))
    def test_graph_url_and_title_preserved(self, fixture_name):
        """Graph metadata matches fixture URL and title."""
        data, result = _build_from_golden(fixture_name)
        assert result.graph.url == data["url"]
        assert result.graph.title == data["title"]

    @pytest.mark.parametrize("fixture_name", list(GOLDEN_BASELINES.keys()))
    def test_evidence_report_has_observations(self, fixture_name):
        """EvidenceReport contains observations for all elements."""
        data, result = _build_from_golden(fixture_name)
        # At minimum: 1 obs per element (dom) + 1 per element (actionability) + 1 network
        min_obs = len(data["interactive_elements"]) * 2 + 1
        assert len(result.evidence_report.observations) >= min_obs, (
            f"{fixture_name}: expected ≥{min_obs} observations, "
            f"got {len(result.evidence_report.observations)}"
        )

    @pytest.mark.parametrize("fixture_name", list(GOLDEN_BASELINES.keys()))
    def test_evidence_report_has_claims(self, fixture_name):
        """EvidenceReport contains claims derived from observations."""
        _, result = _build_from_golden(fixture_name)
        assert len(result.evidence_report.claims) > 0, (
            f"{fixture_name}: no claims in evidence report"
        )

    @pytest.mark.parametrize("fixture_name", list(GOLDEN_BASELINES.keys()))
    def test_no_browser_imports(self, fixture_name):
        """Test module has no browser/Playwright/vendor imports."""
        # Verify no actual playwright imports in this test file
        source_file = Path(__file__)
        source = source_file.read_text()
        # Check actual import statements, not docstring mentions
        for line in source.splitlines():
            stripped = line.strip()
            # Skip comments and docstrings
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            assert "import playwright" not in stripped, f"Browser import found: {stripped}"
            assert "from playwright" not in stripped, f"Browser import found: {stripped}"
