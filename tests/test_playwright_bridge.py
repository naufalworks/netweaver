"""Integration tests for netweaver.playwright_bridge module.

Tests cover:
- Error hierarchy: PlaywrightError, PlaywrightLaunchError, PlaywrightNavigationError
- NetworkTracker: request/response tracking, failure counting, resource types
- PlaywrightBridge: observe, collect_evidence, execute_action with mocked browser
- Internal helpers: _extract_title, _extract_interactive_elements, _build_actionability_summary, _extract_storage_state
- Constants: INTERACTIVE_SELECTORS, MAX_ELEMENTS_PER_SELECTOR, ACTIONABILITY_CHECKS

All tests use mocked browser — no real Chromium launched.
"""
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    StorageState,
)
from netweaver.playwright_bridge import (
    ACTIONABILITY_CHECKS,
    INTERACTIVE_SELECTORS,
    MAX_ELEMENTS_PER_SELECTOR,
    NetworkTracker,
    PlaywrightBridge,
    PlaywrightError,
    PlaywrightLaunchError,
    PlaywrightNavigationError,
)


# ── Error Hierarchy ─────────────────────────────────────────────────


class TestErrorHierarchy:
    def test_playwright_error_is_exception(self):
        assert issubclass(PlaywrightError, Exception)

    def test_launch_error_is_playwright_error(self):
        assert issubclass(PlaywrightLaunchError, PlaywrightError)

    def test_navigation_error_is_playwright_error(self):
        assert issubclass(PlaywrightNavigationError, PlaywrightError)

    def test_error_messages(self):
        e = PlaywrightLaunchError("no browser")
        assert str(e) == "no browser"
        e2 = PlaywrightNavigationError("timeout")
        assert str(e2) == "timeout"


# ── Constants ───────────────────────────────────────────────────────


class TestConstants:
    def test_interactive_selectors_contains_button(self):
        assert "button" in INTERACTIVE_SELECTORS

    def test_interactive_selectors_contains_input(self):
        assert "input" in INTERACTIVE_SELECTORS

    def test_interactive_selectors_contains_links(self):
        assert "a[href]" in INTERACTIVE_SELECTORS

    def test_max_elements_per_selector(self):
        assert MAX_ELEMENTS_PER_SELECTOR == 10

    def test_actionability_checks(self):
        expected = ["attached", "visible", "enabled", "editable", "stable", "pointer_events"]
        assert ACTIONABILITY_CHECKS == expected


# ── NetworkTracker ──────────────────────────────────────────────────


class TestNetworkTracker:
    def test_init_empty(self):
        nt = NetworkTracker()
        assert nt.requests_count == 0
        assert nt.responses_count == 0
        assert nt.failed_count == 0
        assert nt.resource_types == {}

    def test_on_request(self):
        nt = NetworkTracker()
        req = MagicMock()
        req.url = "https://example.com/script.js"
        req.method = "GET"
        req.headers = {"accept": "*/*"}
        req.resource_type = "script"
        nt.on_request(req)
        assert nt.requests_count == 1
        assert nt.requests[0]["url"] == "https://example.com/script.js"
        assert nt.requests[0]["method"] == "GET"
        assert nt.requests[0]["resource_type"] == "script"

    def test_on_response_ok(self):
        nt = NetworkTracker()
        resp = MagicMock()
        resp.url = "https://example.com/api"
        resp.status = 200
        resp.headers = {"content-type": "application/json"}
        resp.ok = True
        nt.on_response(resp)
        assert nt.responses_count == 1
        assert nt.responses[0]["status"] == 200
        assert nt.responses[0]["ok"] is True

    def test_on_response_failed(self):
        nt = NetworkTracker()
        resp = MagicMock()
        resp.url = "https://example.com/missing"
        resp.status = 404
        resp.headers = {}
        resp.ok = False
        nt.on_response(resp)
        assert nt.failed_count == 1

    def test_failed_count_mixed(self):
        nt = NetworkTracker()
        for ok_val in [True, True, False, True, False]:
            resp = MagicMock()
            resp.url = "https://example.com"
            resp.status = 200 if ok_val else 500
            resp.headers = {}
            resp.ok = ok_val
            nt.on_response(resp)
        assert nt.failed_count == 2
        assert nt.responses_count == 5

    def test_resource_types(self):
        nt = NetworkTracker()
        for rt in ["script", "script", "image", "xhr"]:
            req = MagicMock()
            req.url = "https://example.com"
            req.method = "GET"
            req.headers = {}
            req.resource_type = rt
            nt.on_request(req)
        assert nt.resource_types == {"script": 2, "image": 1, "xhr": 1}

    def test_to_activity(self):
        nt = NetworkTracker()
        req = MagicMock()
        req.url = "https://example.com"
        req.method = "GET"
        req.headers = {}
        req.resource_type = "document"
        nt.on_request(req)

        resp = MagicMock()
        resp.url = "https://example.com"
        resp.status = 200
        resp.headers = {}
        resp.ok = True
        nt.on_response(resp)

        activity = nt.to_activity()
        assert isinstance(activity, NetworkActivity)
        assert activity.requests_count == 1
        assert activity.responses_count == 1
        assert activity.failed_count == 0
        assert activity.resource_types == {"document": 1}


# ── PlaywrightBridge — Init & Browser Lifecycle ─────────────────────


class TestPlaywrightBridgeInit:
    def test_default_launcher(self):
        bridge = PlaywrightBridge()
        assert bridge._browser_launcher == PlaywrightBridge._default_launcher

    def test_custom_launcher(self):
        custom = MagicMock()
        bridge = PlaywrightBridge(browser_launcher=custom)
        assert bridge._browser_launcher is custom

    def test_close_browser_none(self):
        # Should not raise
        PlaywrightBridge._close_browser(None)

    def test_close_browser_with_mock(self):
        browser = MagicMock()
        browser._pw = MagicMock()
        PlaywrightBridge._close_browser(browser)
        browser.close.assert_called_once()
        browser._pw.stop.assert_called_once()

    def test_close_browser_no_pw(self):
        browser = MagicMock(spec=[])  # no _pw attr
        browser.close = MagicMock()
        PlaywrightBridge._close_browser(browser)
        browser.close.assert_called_once()

    def test_close_browser_swallows_exception(self):
        browser = MagicMock()
        browser.close.side_effect = RuntimeError("already closed")
        # Should not raise
        PlaywrightBridge._close_browser(browser)


# ── PlaywrightBridge — observe() ────────────────────────────────────


def _make_mock_page():
    """Create a mock page with typical behavior."""
    page = MagicMock()
    page.url = "https://example.com"
    page.title.return_value = "Example Page"
    page.evaluate.return_value = {}

    # Mock locator chain
    mock_locator = MagicMock()
    mock_locator.all.return_value = []
    page.locator.return_value = mock_locator

    return page


def _make_mock_context(page=None):
    """Create a mock browser context."""
    ctx = MagicMock()
    if page is None:
        page = _make_mock_page()
    ctx.new_page.return_value = page
    ctx.cookies.return_value = [{"name": "sid", "value": "abc"}]
    return ctx, page


def _make_mock_browser(page=None):
    """Create a mock browser."""
    browser = MagicMock()
    ctx, page = _make_mock_context(page)
    browser.new_context.return_value = ctx
    return browser, ctx, page


class TestPlaywrightBridgeObserve:
    def test_observe_returns_page_observation(self):
        browser, ctx, page = _make_mock_browser()
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        obs = bridge.observe("https://example.com")
        assert obs.url == "https://example.com"
        assert obs.title == "Example Page"

    def test_observe_calls_launcher_with_headless(self):
        browser, _, _ = _make_mock_browser()
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        bridge.observe("https://example.com", headless=False)
        launcher.assert_called_once_with(headless=False)

    def test_observe_navigates_to_url(self):
        browser, _, page = _make_mock_browser()
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        bridge.observe("https://example.com", timeout=10.0)
        page.goto.assert_called_once_with(
            "https://example.com",
            timeout=10000,
            wait_until="domcontentloaded",
        )

    def test_observe_navigation_error(self):
        browser, _, page = _make_mock_browser()
        page.goto.side_effect = TimeoutError("page load timeout")
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        with pytest.raises(PlaywrightNavigationError, match="Failed to navigate"):
            bridge.observe("https://example.com")

    def test_observe_generic_error_wraps(self):
        browser = MagicMock()
        browser.new_context.side_effect = RuntimeError("context fail")
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        with pytest.raises(PlaywrightError, match="Observation failed"):
            bridge.observe("https://example.com")

    def test_observe_closes_browser_on_success(self):
        browser, _, _ = _make_mock_browser()
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        bridge.observe("https://example.com")
        browser.close.assert_called_once()

    def test_observe_closes_browser_on_error(self):
        browser, _, page = _make_mock_browser()
        page.goto.side_effect = RuntimeError("fail")
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        with pytest.raises(PlaywrightError):
            bridge.observe("https://example.com")
        browser.close.assert_called_once()

    def test_observe_network_tracking(self):
        browser, _, page = _make_mock_browser()
        # Simulate network events by capturing the on() callbacks
        event_handlers = {}

        def capture_on(event, handler):
            event_handlers[event] = handler

        page.on = capture_on
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        obs = bridge.observe("https://example.com")
        assert isinstance(obs.network, NetworkActivity)

    def test_observe_storage_state(self):
        browser, ctx, page = _make_mock_browser()
        page.evaluate.side_effect = [
            {"theme": "dark"},   # localStorage
            {"sess": "abc123"},  # sessionStorage
        ]
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        obs = bridge.observe("https://example.com")
        assert obs.storage is not None
        assert isinstance(obs.storage, StorageState)

    def test_observe_storage_extraction_failure(self):
        browser, ctx, page = _make_mock_browser()
        page.evaluate.side_effect = RuntimeError("eval fail")
        ctx.cookies.side_effect = RuntimeError("cookie fail")
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        obs = bridge.observe("https://example.com")
        assert obs.storage is not None
        assert obs.storage.cookies == []
        assert obs.storage.local_storage == {}


# ── PlaywrightBridge — Internal Helpers ─────────────────────────────


class TestPlaywrightBridgeHelpers:
    def test_extract_title_success(self):
        page = MagicMock()
        page.title.return_value = "My Page"
        bridge = PlaywrightBridge()
        assert bridge._extract_title(page) == "My Page"

    def test_extract_title_failure(self):
        page = MagicMock()
        page.title.side_effect = RuntimeError("no title")
        bridge = PlaywrightBridge()
        assert bridge._extract_title(page) == ""

    def test_build_actionability_summary_all_actionable(self):
        elements = [
            InteractiveElement(
                selector="button", tag="button",
                actionability={"visible": True, "enabled": True},
            ),
            InteractiveElement(
                selector="input", tag="input",
                actionability={"visible": True, "enabled": True},
            ),
        ]
        summary = PlaywrightBridge._build_actionability_summary(elements)
        assert summary["total_elements"] == 2
        assert summary["actionable_elements"] == 2
        assert summary["checks_performed"] == ACTIONABILITY_CHECKS

    def test_build_actionability_summary_some_hidden(self):
        elements = [
            InteractiveElement(
                selector="button", tag="button",
                actionability={"visible": True, "enabled": True},
            ),
            InteractiveElement(
                selector="div.hidden", tag="div",
                actionability={"visible": False, "enabled": True},
            ),
        ]
        summary = PlaywrightBridge._build_actionability_summary(elements)
        assert summary["actionable_elements"] == 1

    def test_build_actionability_summary_empty(self):
        summary = PlaywrightBridge._build_actionability_summary([])
        assert summary["total_elements"] == 0
        assert summary["actionable_elements"] == 0

    def test_extract_interactive_elements(self):
        page = MagicMock()
        # Return empty locators for all selectors
        mock_locator = MagicMock()
        mock_locator.all.return_value = []
        page.locator.return_value = mock_locator

        bridge = PlaywrightBridge()
        elements = bridge._extract_interactive_elements(page)
        assert isinstance(elements, list)

    def test_extract_interactive_elements_handles_error(self):
        page = MagicMock()
        page.locator.side_effect = RuntimeError("DOM error")
        bridge = PlaywrightBridge()
        elements = bridge._extract_interactive_elements(page)
        assert elements == []

    def test_extract_element_returns_none_on_error(self):
        locator = MagicMock()
        locator.evaluate.side_effect = RuntimeError("detached")
        result = PlaywrightBridge._extract_element(locator, "button", 0)
        assert result is None


# ── PlaywrightBridge — execute_action() ─────────────────────────────


class TestPlaywrightBridgeExecuteAction:
    def _make_action(self, action_type, **kwargs):
        action = MagicMock()
        action.action_type = action_type
        action.target_ref = kwargs.get("target_ref", "button#submit")
        for k, v in kwargs.items():
            if k != "target_ref":
                setattr(action, k, v)
        return action

    def test_execute_click(self):
        from netweaver.wnal import ActionType
        browser, _, page = _make_mock_browser()
        locator = MagicMock()
        locator.first = MagicMock()
        page.locator.return_value = locator
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        action = self._make_action(ActionType.CLICK)
        result = bridge.execute_action(action)
        assert result is True
        locator.first.click.assert_called_once()

    def test_execute_fill(self):
        from netweaver.wnal import ActionType
        browser, _, page = _make_mock_browser()
        locator = MagicMock()
        locator.first = MagicMock()
        page.locator.return_value = locator
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        action = self._make_action(ActionType.FILL, text="hello", clear_first=True)
        result = bridge.execute_action(action)
        assert result is True

    def test_execute_wait(self):
        from netweaver.wnal import ActionType
        browser, _, page = _make_mock_browser()
        locator = MagicMock()
        locator.first = MagicMock()
        page.locator.return_value = locator
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        action = self._make_action(
            ActionType.WAIT, condition="visible", timeout_ms=5000
        )
        result = bridge.execute_action(action)
        assert result is True

    def test_execute_unknown_type_returns_false(self):
        browser, _, page = _make_mock_browser()
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        action = MagicMock()
        action.action_type = "UNKNOWN"
        action.target_ref = "div.x"
        result = bridge.execute_action(action)
        assert result is False

    def test_execute_error_returns_false(self):
        from netweaver.wnal import ActionType
        browser = MagicMock()
        browser.new_context.side_effect = RuntimeError("fail")
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        action = self._make_action(ActionType.CLICK)
        result = bridge.execute_action(action)
        assert result is False


# ── PlaywrightBridge — collect_evidence() ───────────────────────────


class TestPlaywrightBridgeCollectEvidence:
    def test_collect_evidence_element_not_found(self):
        browser, _, page = _make_mock_browser()
        locator = MagicMock()
        locator.count.return_value = 0
        page.locator.return_value = locator
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        evidence = bridge.collect_evidence("act-1", "button#missing")
        assert evidence.attached is False
        assert evidence.visible is False

    def test_collect_evidence_element_found(self):
        browser, _, page = _make_mock_browser()
        locator = MagicMock()
        locator.count.return_value = 1
        locator.first.is_visible.return_value = True
        locator.first.is_enabled.return_value = True
        locator.first.is_editable.return_value = False
        locator.first.evaluate.return_value = True
        page.locator.return_value = locator
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        evidence = bridge.collect_evidence("act-2", "button#submit")
        assert evidence.attached is True
        assert evidence.visible is True
        assert evidence.enabled is True

    def test_collect_evidence_error_returns_detached(self):
        browser = MagicMock()
        browser.new_context.side_effect = RuntimeError("fail")
        launcher = MagicMock(return_value=browser)
        bridge = PlaywrightBridge(browser_launcher=launcher)

        evidence = bridge.collect_evidence("act-3", "button#x")
        assert evidence.attached is False
        assert evidence.visible is False


# ── PlaywrightBridge — Default Launcher ─────────────────────────────


class TestDefaultLauncher:
    @patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None})
    def test_default_launcher_import_error(self):
        with pytest.raises(PlaywrightLaunchError, match="Playwright not installed"):
            PlaywrightBridge._default_launcher(headless=True)
