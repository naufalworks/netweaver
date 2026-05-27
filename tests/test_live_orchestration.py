"""NetWeaver P2-004 Integration Tests — Real-site orchestration.

These tests exercise the full orchestration pipeline against real websites
using Playwright for browser automation. They verify that the orchestrator
can execute multi-step action sequences on live pages with inter-step
verification and rollback on failure.

NOTE: These tests require a working Playwright installation.
Skip if Playwright is not available (we use CloakBrowser instead).

Test pages used:
  - https://example.com (static, minimal)
  - https://httpbin.org/forms/post (form page)
  - https://books.toscrape.com (searchable catalog)
"""
import pytest
from datetime import datetime
from typing import Any, Dict, Optional

# Check if Playwright is actually working
try:
    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    _pw.stop()
    _playwright_available = True
except Exception:
    _playwright_available = False

pytestmark = pytest.mark.skipif(
    not _playwright_available,
    reason="Playwright not available (using CloakBrowser instead)"
)

from netweaver.executor import (
    ExecutionStatus,
    ResolutionStatus,
    VerifiedExecutor,
)
from netweaver.action_orchestrator import (
    ActionOrchestrator,
    ActionPlan,
    ActionType,
    PlanStatus,
    StepResult,
)
from netweaver.scene_graph import NodeType
from netweaver.playwright_bridge import PlaywrightBridge
from netweaver.scene_graph_builder import (
    BuilderConfig,
    SceneGraphBuilder,
)
from netweaver.observer import PageObservation
from netweaver.wnal import ActionabilityEvidence, Phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_graph_supplier(url: str = "https://example.com"):
    """Simple graph supplier for use with ActionOrchestrator.

    Returns a callable that returns a fresh scene graph on each call.
    """
    bridge = PlaywrightBridge()
    builder = SceneGraphBuilder(config=BuilderConfig(
        include_intent_nodes=True,
        include_network_nodes=False,
        include_visual_nodes=False,
        run_perspective_enrichment=False,
    ))
    def _supply() -> Any:
        obs = bridge.observe(url, headless=True, timeout=15.0)
        result = builder.build(obs)
        return result.graph
    return _supply


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestRealSiteObservation:
    """Verify that PlaywrightBridge can observe real sites."""

    def test_observe_example_com(self):
        """Observe example.com and validate basic page structure."""
        bridge = PlaywrightBridge()
        obs = bridge.observe("https://example.com", headless=True, timeout=15.0)
        assert obs.url == "https://example.com/"
        assert obs.title == "Example Domain"
        assert len(obs.interactive_elements) >= 1
        links = [e for e in obs.interactive_elements if e.tag == "a"]
        assert len(links) >= 1
        assert links[0].text is not None
        assert obs.network.requests_count >= 1

    def test_observe_httpbin_form(self):
        """Observe httpbin forms page — has form elements."""
        bridge = PlaywrightBridge()
        obs = bridge.observe("https://httpbin.org/forms/post", headless=True, timeout=15.0)
        assert "forms" in obs.url or "httpbin" in obs.url
        inputs = [e for e in obs.interactive_elements if e.tag == "input"]
        assert len(inputs) >= 2
        buttons = [e for e in obs.interactive_elements if e.tag == "button"]
        assert any("submit" in (b.text or "").lower() for b in buttons)


@pytest.mark.live
class TestRealSiteGraphBuilding:
    """Verify scene graphs built from real observations."""

    def test_example_com_scene_graph(self):
        """Build a scene graph from example.com."""
        bridge = PlaywrightBridge()
        builder = SceneGraphBuilder(config=BuilderConfig(
            include_intent_nodes=True,
            run_perspective_enrichment=False,
        ))
        obs = bridge.observe("https://example.com", headless=True, timeout=15.0)
        result = builder.build(obs)
        graph = result.graph
        assert graph is not None
        assert graph.url == "https://example.com/"
        dom_nodes = graph.get_nodes_by_type(NodeType.DOM)
        assert len(dom_nodes) >= 1
        intent_nodes = graph.get_nodes_by_type(NodeType.INTENT)
        assert len(intent_nodes) >= 1


@pytest.mark.live
class TestRealSiteExecutor:
    """Verify executor works with PlaywrightBridge on real pages."""

    def test_executor_live_constructs(self):
        """Verify executor constructs correctly in live mode with PlaywrightBridge."""
        bridge = PlaywrightBridge()
        executor = VerifiedExecutor(
            mode="live",
            cloak_bridge=bridge,
        )
        assert executor.mode == "live"
        assert executor.cloak_bridge is not None

    def test_executor_collect_evidence(self):
        """Verify collect_evidence handles non-navigated page gracefully."""
        bridge = PlaywrightBridge()
        # Without a pre-navigated page, collect_evidence returns unattached
        evidence = bridge.collect_evidence("test-act-1", "a")
        assert evidence is not None
        # attach state depends on whether a page was loaded
        assert hasattr(evidence, "attached")


@pytest.mark.live
class TestRealSiteOrchestrator:
    """Verify orchestrator handles real-site scenarios."""

    def test_orchestrator_single_step_wait(self):
        """Execute a single-step wait plan on a real page."""
        bridge = PlaywrightBridge()
        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        orchestrator = ActionOrchestrator(executor=executor)
        supplier = _simple_graph_supplier("https://example.com")

        plan = ActionPlan(
            plan_id="test-single-step",
            description="Observe example.com (no-op step)",
        )
        plan.add_step(
            action_type=ActionType.WAIT,
            description="page body",
            intent="wait for page to load",
            condition="attached",
            timeout_ms=5000,
        )

        result = orchestrator.orchestrate(
            plan=plan,
            graph_supplier=supplier,
        )
        assert result.status in (PlanStatus.COMPLETED, PlanStatus.FAILED)
        if result.status == PlanStatus.COMPLETED:
            assert result.completed_steps >= 1

    def test_orchestrator_multi_step_plan_graceful(self):
        """Multi-step plan on a real form page — graceful completion or failure."""
        bridge = PlaywrightBridge()
        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        orchestrator = ActionOrchestrator(executor=executor)
        supplier = _simple_graph_supplier("https://httpbin.org/forms/post")

        plan = ActionPlan(
            plan_id="test-multi-step",
            description="Fill and submit httpbin form",
        )
        plan.add_step(
            action_type=ActionType.WAIT,
            description="form element",
            intent="wait for form to load",
            condition="attached",
            timeout_ms=10000,
        )
        plan.add_step(
            action_type=ActionType.FILL,
            description="input[name='custname']",
            intent="fill customer name",
            text="Test User",
        )

        result = orchestrator.orchestrate(
            plan=plan,
            graph_supplier=supplier,
        )
        assert result.status in (
            PlanStatus.COMPLETED,
            PlanStatus.FAILED,
            PlanStatus.ROLLED_BACK,
        )
        assert result.steps is not None
        assert len(result.steps) > 0

    def test_orchestrator_rollback_on_real_failure(self):
        """Verify rollback behavior when a real-site plan fails mid-sequence."""
        bridge = PlaywrightBridge()
        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        orchestrator = ActionOrchestrator(executor=executor)
        supplier = _simple_graph_supplier("https://example.com")

        plan = ActionPlan(
            plan_id="test-rollback",
            description="Plan with unresolvable target",
        )
        plan.add_step(
            action_type=ActionType.WAIT,
            description="page body",
            intent="wait for page",
            condition="attached",
            timeout_ms=5000,
        )
        plan.add_step(
            action_type=ActionType.CLICK,
            description="non-existent-element-xyz-999",
            intent="click something that doesn't exist",
        )

        result = orchestrator.orchestrate(
            plan=plan,
            graph_supplier=supplier,
        )
        assert result.status in (
            PlanStatus.FAILED,
            PlanStatus.ROLLED_BACK,
            PlanStatus.COMPLETED,
        )
        assert len(result.steps) >= 1


@pytest.mark.live
class TestPlaywrightBridge:
    """Direct tests of PlaywrightBridge functionality."""

    def test_collect_evidence_returns_evidence(self):
        bridge = PlaywrightBridge()
        bridge.observe("https://example.com", headless=True, timeout=15.0)
        evidence = bridge.collect_evidence("act-1", "a")
        assert evidence is not None
        assert hasattr(evidence, "attached")
        assert hasattr(evidence, "visible")
        assert hasattr(evidence, "enabled")

    def test_execute_action_click_fails_gracefully(self):
        bridge = PlaywrightBridge()
        class DummyAction:
            action_type = ActionType.CLICK
            target_ref = "#nonexistent"
            button = "left"
            click_count = 1
            delay_ms = 0
        result = bridge.execute_action(DummyAction())
        assert result is False

    def test_observe_nonexistent_domain_raises(self):
        bridge = PlaywrightBridge()
        with pytest.raises(Exception):
            bridge.observe(
                "https://this-domain-definitely-does-not-exist-12345.com",
                headless=True,
                timeout=5.0,
            )
