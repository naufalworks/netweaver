"""Tests for CloakBrowser Bridge module.

All tests use mock CloakBrowser SDK responses — no real browser required.
"""

from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
)
from netweaver.cloak_bridge import (
    ACTIONABILITY_CHECKS,
    INTERACTIVE_SELECTORS,
    MAX_ELEMENTS_PER_SELECTOR,
    CloakBrowserBridge,
    CloakBrowserError,
    CloakBrowserLaunchError,
    CloakBrowserNavigationError,
    NetworkTracker,
)


# ---------------------------------------------------------------------------
# Helpers: mock CloakBrowser SDK objects
# ---------------------------------------------------------------------------

def _make_mock_locator(tag="button", text="Click", type_=None, aria_label=None,
                       visible=True, enabled=True, editable=False):
    """Create a mock locator that behaves like CloakBrowser SDK locator."""
    loc = MagicMock()
    loc.evaluate.return_value = tag
    loc.get_attribute.side_effect = lambda attr: {
        "type": type_,
        "aria-label": aria_label,
    }.get(attr)
    loc.inner_text.return_value = text
    loc.is_visible.return_value = visible
    loc.is_enabled.return_value = enabled
    loc.is_editable.return_value = editable
    return loc


def _make_mock_page(title="Test Page", url="https://example.com",
                    locators=None):
    """Create a mock page object."""
    page = MagicMock()
    page.title.return_value = title
    page.url = url

    if locators is None:
        locators = {
            "button": [_make_mock_locator()],
            "a[href": [_make_mock_locator(tag="a", text="Link", type_=None)],
        }

    def locator_side_effect(selector):
        mock_loc = MagicMock()
        mock_loc.all.return_value = locators.get(selector, [])
        return mock_loc

    page.locator.side_effect = locator_side_effect
    return page


def _make_mock_browser(page=None):
    """Create a mock browser object."""
    if page is None:
        page = _make_mock_page()
    browser = MagicMock()
    browser.new_page.return_value = page
    return browser


def _make_mock_request(resource_type="document"):
    req = MagicMock()
    req.resource_type = resource_type
    return req


def _make_mock_response(ok=True):
    resp = MagicMock()
    resp.ok = ok
    return resp


# ---------------------------------------------------------------------------
# NetworkTracker
# ---------------------------------------------------------------------------

class TestNetworkTracker:
    """Test NetworkTracker callback handler."""

    def test_initial_state(self):
        tracker = NetworkTracker()
        assert tracker.requests_count == 0
        assert tracker.responses_count == 0
        assert tracker.failed_count == 0
        assert tracker.resource_types == {}

    def test_on_request_counts(self):
        tracker = NetworkTracker()
        tracker.on_request(_make_mock_request("document"))
        tracker.on_request(_make_mock_request("script"))
        tracker.on_request(_make_mock_request("script"))

        assert tracker.requests_count == 3
        assert tracker.resource_types == {"document": 1, "script": 2}

    def test_on_response_ok(self):
        tracker = NetworkTracker()
        tracker.on_response(_make_mock_response(ok=True))
        assert tracker.responses_count == 1
        assert tracker.failed_count == 0

    def test_on_response_failed(self):
        tracker = NetworkTracker()
        tracker.on_response(_make_mock_response(ok=False))
        assert tracker.responses_count == 1
        assert tracker.failed_count == 1

    def test_to_activity(self):
        tracker = NetworkTracker()
        tracker.on_request(_make_mock_request("xhr"))
        tracker.on_request(_make_mock_request("image"))
        tracker.on_response(_make_mock_response(ok=True))
        tracker.on_response(_make_mock_response(ok=False))

        activity = tracker.to_activity()
        assert isinstance(activity, NetworkActivity)
        assert activity.requests_count == 2
        assert activity.responses_count == 2
        assert activity.failed_count == 1
        assert activity.resource_types == {"xhr": 1, "image": 1}

    def test_to_activity_returns_copy(self):
        tracker = NetworkTracker()
        tracker.on_request(_make_mock_request("script"))
        a1 = tracker.to_activity()
        a2 = tracker.to_activity()
        assert a1.resource_types is not a2.resource_types

    def test_on_request_missing_resource_type(self):
        tracker = NetworkTracker()
        req = MagicMock(spec=[])  # No resource_type attr
        req.resource_type = "other"
        # Simulate getattr fallback
        tracker.on_request(req)
        assert tracker.requests_count == 1


# ---------------------------------------------------------------------------
# CloakBrowserBridge
# ---------------------------------------------------------------------------

class TestCloakBrowserBridgeObserve:
    """Test bridge.observe() with mock browser."""

    def test_observe_returns_page_observation(self):
        page = _make_mock_page(title="My Page", url="https://example.com")
        browser = _make_mock_browser(page)

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        obs = bridge.observe("https://example.com")

        assert isinstance(obs, PageObservation)
        assert obs.url == "https://example.com"
        assert obs.title == "My Page"
        assert isinstance(obs.network, NetworkActivity)
        assert isinstance(obs.observed_at, datetime)

    def test_observe_extracts_interactive_elements(self):
        btn = _make_mock_locator(tag="button", text="Submit")
        inp = _make_mock_locator(tag="input", text=None, type_="email",
                                 aria_label="Email")
        page = _make_mock_page(locators={
            "button": [btn],
            "input": [inp],
        })
        browser = _make_mock_browser(page)

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        obs = bridge.observe("https://example.com")

        assert len(obs.interactive_elements) == 2
        tags = {e.tag for e in obs.interactive_elements}
        assert "button" in tags
        assert "input" in tags

    def test_observe_element_actionability(self):
        btn = _make_mock_locator(tag="button", text="Go", visible=True, enabled=True)
        page = _make_mock_page(locators={"button": [btn]})
        browser = _make_mock_browser(page)

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        obs = bridge.observe("https://example.com")

        elem = obs.interactive_elements[0]
        assert elem.actionability is not None
        assert elem.actionability["attached"] is True
        assert elem.actionability["visible"] is True
        assert elem.actionability["enabled"] is True
        assert elem.actionability["editable"] is False
        assert elem.actionability["stable"] is True
        assert elem.actionability["pointer_events"] is True

    def test_observe_network_tracking(self):
        page = _make_mock_page()
        browser = _make_mock_browser(page)

        # Capture the request/response callbacks
        callbacks = {}
        original_on = page.on
        def capture_on(event, cb):
            callbacks[event] = cb
        page.on.side_effect = capture_on

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        obs = bridge.observe("https://example.com")

        # Simulate network events before observe completes
        # (callbacks are registered during observe, we verify they were registered)
        assert "request" in callbacks
        assert "response" in callbacks

    def test_observe_actionability_summary(self):
        btn_visible = _make_mock_locator(visible=True, enabled=True)
        btn_hidden = _make_mock_locator(visible=False, enabled=True)
        btn_disabled = _make_mock_locator(visible=True, enabled=False)
        page = _make_mock_page(locators={"button": [btn_visible, btn_hidden, btn_disabled]})
        browser = _make_mock_browser(page)

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        obs = bridge.observe("https://example.com")

        assert obs.actionability["total_elements"] == 3
        assert obs.actionability["actionable_elements"] == 1  # Only visible+enabled
        assert obs.actionability["checks_performed"] == ACTIONABILITY_CHECKS

    def test_observe_closes_browser_on_success(self):
        browser = _make_mock_browser()
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        bridge.observe("https://example.com")
        browser.close.assert_called_once()

    def test_observe_closes_browser_on_error(self):
        browser = _make_mock_browser()
        browser.new_page.return_value.goto.side_effect = Exception("timeout")

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        with pytest.raises(CloakBrowserNavigationError):
            bridge.observe("https://example.com")

        browser.close.assert_called_once()

    def test_observe_launch_error(self):
        def failing_factory(**kwargs):
            raise CloakBrowserLaunchError("Cannot launch")

        bridge = CloakBrowserBridge(browser_factory=failing_factory)
        with pytest.raises(CloakBrowserLaunchError):
            bridge.observe("https://example.com")

    def test_observe_navigation_error(self):
        page = _make_mock_page()
        page.goto.side_effect = Exception("net::ERR_CONNECTION_REFUSED")
        browser = _make_mock_browser(page)

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        with pytest.raises(CloakBrowserNavigationError) as exc_info:
            bridge.observe("https://unreachable.example.com")

        assert "unreachable.example.com" in str(exc_info.value)

    def test_observe_passes_headless_and_timeout(self):
        factory = MagicMock(return_value=_make_mock_browser())
        bridge = CloakBrowserBridge(browser_factory=factory)
        bridge.observe("https://example.com", headless=True, timeout=15.0)

        factory.assert_called_once_with(headless=True)


class TestCloakBrowserBridgeExtractElement:
    """Test _extract_element static method."""

    def test_extracts_button(self):
        loc = _make_mock_locator(tag="button", text="Submit")
        elem = CloakBrowserBridge._extract_element(loc, "button", 0)

        assert elem is not None
        assert elem.tag == "button"
        assert elem.text == "Submit"
        assert elem.selector == "button:nth-of-type(1)"
        assert elem.type is None

    def test_extracts_input_with_type(self):
        loc = _make_mock_locator(tag="input", text=None, type_="email",
                                 aria_label="Email address")
        elem = CloakBrowserBridge._extract_element(loc, "input", 2)

        assert elem is not None
        assert elem.tag == "input"
        assert elem.type == "email"
        assert elem.text is None
        assert elem.aria_label == "Email address"
        assert elem.selector == "input:nth-of-type(3)"

    def test_truncates_long_text(self):
        loc = _make_mock_locator(text="A" * 200)
        elem = CloakBrowserBridge._extract_element(loc, "button", 0)
        assert len(elem.text) == 50

    def test_returns_none_on_error(self):
        loc = MagicMock()
        loc.evaluate.side_effect = Exception("detached")
        elem = CloakBrowserBridge._extract_element(loc, "button", 0)
        assert elem is None

    def test_editable_input(self):
        loc = _make_mock_locator(tag="input", type_="text", editable=True)
        elem = CloakBrowserBridge._extract_element(loc, "input", 0)
        assert elem.actionability["editable"] is True


class TestCloakBrowserBridgeExtractElements:
    """Test _extract_interactive_elements method."""

    def test_skips_failed_selector(self):
        page = MagicMock()

        def locator_side_effect(selector):
            mock_loc = MagicMock()
            if selector == "button":
                mock_loc.all.return_value = [_make_mock_locator()]
            elif selector == "a[href]":
                raise Exception("selector error")
            else:
                mock_loc.all.return_value = []
            return mock_loc

        page.locator.side_effect = locator_side_effect

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: _make_mock_browser(page))
        elements = bridge._extract_interactive_elements(page)

        assert len(elements) == 1
        assert elements[0].tag == "button"

    def test_limits_elements_per_selector(self):
        locators = [_make_mock_locator() for _ in range(15)]
        page = MagicMock()
        loc = MagicMock()
        loc.all.return_value = locators
        page.locator.return_value = loc

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: _make_mock_browser(page))
        elements = bridge._extract_interactive_elements(page)

        # Should be capped at MAX_ELEMENTS_PER_SELECTOR per selector
        assert len(elements) <= MAX_ELEMENTS_PER_SELECTOR * len(INTERACTIVE_SELECTORS)


class TestCloakBrowserBridgeBuildSummary:
    """Test _build_actionability_summary static method."""

    def test_empty_elements(self):
        summary = CloakBrowserBridge._build_actionability_summary([])
        assert summary["total_elements"] == 0
        assert summary["actionable_elements"] == 0
        assert summary["checks_performed"] == ACTIONABILITY_CHECKS

    def test_mixed_actionability(self):
        elements = [
            InteractiveElement(selector="a", tag="button",
                               actionability={"enabled": True, "visible": True}),
            InteractiveElement(selector="b", tag="button",
                               actionability={"enabled": False, "visible": True}),
            InteractiveElement(selector="c", tag="button",
                               actionability={"enabled": True, "visible": False}),
            InteractiveElement(selector="d", tag="button",
                               actionability=None),
        ]
        summary = CloakBrowserBridge._build_actionability_summary(elements)
        assert summary["total_elements"] == 4
        assert summary["actionable_elements"] == 1

    def test_checks_performed_constant(self):
        assert ACTIONABILITY_CHECKS == [
            "attached", "visible", "enabled", "editable", "stable", "pointer_events"
        ]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class TestCloakBrowserErrors:
    """Test error class hierarchy."""

    def test_launch_error_is_cloak_error(self):
        assert issubclass(CloakBrowserLaunchError, CloakBrowserError)

    def test_navigation_error_is_cloak_error(self):
        assert issubclass(CloakBrowserNavigationError, CloakBrowserError)

    def test_cloak_error_is_exception(self):
        assert issubclass(CloakBrowserError, Exception)


# ---------------------------------------------------------------------------
# Integration: observer.observe_page_cloak delegates to bridge
# ---------------------------------------------------------------------------

class TestObserverCloakDelegation:
    """Test that observer.observe_page_cloak delegates to CloakBrowserBridge."""

    def test_observe_page_cloak_uses_bridge(self):
        """observe_page_cloak should create a bridge and call bridge.observe()."""
        from netweaver.observer import observe_page_cloak

        mock_obs = PageObservation(
            url="https://example.com",
            title="Mock",
            interactive_elements=[],
            actionability={},
            network=NetworkActivity(),
            observed_at=datetime.now(),
        )

        with patch("netweaver.cloak_bridge.CloakBrowserBridge") as MockBridge:
            instance = MockBridge.return_value
            instance.observe.return_value = mock_obs

            result = observe_page_cloak("https://example.com")

            assert result is mock_obs
            MockBridge.assert_called_once()
            instance.observe.assert_called_once_with(
                "https://example.com", headless=True, timeout=30.0
            )

    def test_observe_page_cloak_launch_error_becomes_runtime_error(self):
        from netweaver.observer import observe_page_cloak

        with patch("netweaver.cloak_bridge.CloakBrowserBridge") as MockBridge:
            instance = MockBridge.return_value
            instance.observe.side_effect = CloakBrowserLaunchError("no install")

            with pytest.raises(RuntimeError, match="no install"):
                observe_page_cloak("https://example.com")

    def test_observe_page_cloak_nav_error_becomes_runtime_error(self):
        from netweaver.observer import observe_page_cloak

        with patch("netweaver.cloak_bridge.CloakBrowserBridge") as MockBridge:
            instance = MockBridge.return_value
            instance.observe.side_effect = CloakBrowserNavigationError("timeout")

            with pytest.raises(RuntimeError, match="timeout"):
                observe_page_cloak("https://example.com")

    def test_observe_page_mock_unchanged(self):
        """Mock mode should still work identically (backward compat)."""
        from netweaver.observer import observe_page_mock

        obs = observe_page_mock("https://example.com")
        assert isinstance(obs, PageObservation)
        assert obs.url == "https://example.com"
        assert len(obs.interactive_elements) == 3


# ---------------------------------------------------------------------------
# Contract: PageObservation shape unchanged
# ---------------------------------------------------------------------------

class TestPageObservationContract:
    """Verify bridge produces identical PageObservation shape as mock mode."""

    def test_bridge_observation_has_same_fields_as_mock(self):
        from netweaver.observer import observe_page_mock

        mock_obs = observe_page_mock("https://example.com")

        # Build a bridge observation from mocks
        btn = _make_mock_locator(tag="button", text="Submit")
        page = _make_mock_page(locators={"button": [btn]})
        browser = _make_mock_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        bridge_obs = bridge.observe("https://example.com")

        # Same top-level keys
        mock_dict = mock_obs.to_dict()
        bridge_dict = bridge_obs.to_dict()
        assert set(mock_dict.keys()) == set(bridge_dict.keys())

        # Same element keys
        if mock_dict["interactive_elements"] and bridge_dict["interactive_elements"]:
            mock_el_keys = set(mock_dict["interactive_elements"][0].keys())
            bridge_el_keys = set(bridge_dict["interactive_elements"][0].keys())
            assert mock_el_keys == bridge_el_keys

        # Same network keys
        assert set(mock_dict["network"].keys()) == set(bridge_dict["network"].keys())
