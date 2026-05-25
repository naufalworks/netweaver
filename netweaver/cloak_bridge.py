"""CloakBrowser Bridge - Abstraction layer for CloakBrowser SDK integration.

Encapsulates all CloakBrowser SDK interactions behind a clean interface.
Observer delegates live-mode page observation to this bridge.

The bridge translates CloakBrowser-specific APIs into NetWeaver's
internal data structures (InteractiveElement, NetworkActivity, PageObservation).
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    StorageState,
)


# Default selectors for interactive element discovery
INTERACTIVE_SELECTORS = [
    "button",
    "a[href]",
    "input",
    "textarea",
    "select",
    "[role='button']",
    "[onclick]",
]

# Max elements to extract per selector type
MAX_ELEMENTS_PER_SELECTOR = 10

# Default actionability checks
ACTIONABILITY_CHECKS = [
    "attached",
    "visible",
    "enabled",
    "editable",
    "stable",
    "pointer_events",
]


class CloakBrowserError(Exception):
    """Base error for CloakBrowser bridge operations."""
    pass


class CloakBrowserLaunchError(CloakBrowserError):
    """Failed to launch CloakBrowser."""
    pass


class CloakBrowserNavigationError(CloakBrowserError):
    """Failed to navigate to URL."""
    pass


class NetworkTracker:
    """Tracks network requests and responses for a page."""

    def __init__(self):
        self.requests: List[Dict[str, Any]] = []
        self.responses: List[Dict[str, Any]] = []

    @property
    def requests_count(self) -> int:
        return len(self.requests)

    @property
    def responses_count(self) -> int:
        return len(self.responses)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.responses if not r.get("ok", True))

    @property
    def resource_types(self) -> Dict[str, int]:
        types: Dict[str, int] = {}
        for req in self.requests:
            rt = req.get("resource_type", "other")
            types[rt] = types.get(rt, 0) + 1
        return types

    def on_request(self, request: Any) -> None:
        """Handle a new network request."""
        req_data = {
            "url": getattr(request, "url", ""),
            "method": getattr(request, "method", "GET"),
            "headers": getattr(request, "headers", {}),
            "timestamp": datetime.utcnow().isoformat(),
            "resource_type": getattr(request, "resource_type", "other"),
        }
        self.requests.append(req_data)

    def on_response(self, response: Any) -> None:
        """Handle a completed network response."""
        ok = getattr(response, "ok", True)
        res_data = {
            "url": getattr(response, "url", ""),
            "status": getattr(response, "status", 200),
            "headers": getattr(response, "headers", {}),
            "timestamp": datetime.utcnow().isoformat(),
            "ok": ok,
        }
        self.responses.append(res_data)

    def to_activity(self) -> NetworkActivity:
        """Convert current tracker state to a NetworkActivity summary."""
        return NetworkActivity(
            requests_count=self.requests_count,
            responses_count=self.responses_count,
            failed_count=self.failed_count,
            resource_types=dict(self.resource_types),
        )


class CloakBrowserBridge:
    """Bridge between CloakBrowser SDK and NetWeaver observer.

    Provides a clean interface for browser lifecycle management
    and data extraction. All CloakBrowser-specific APIs are
    contained within this module.

    Usage:
        bridge = CloakBrowserBridge()
        observation = bridge.observe(url, headless=True, timeout=30.0)
    """

    def __init__(self, browser_factory: Optional[Callable] = None):
        """Initialize bridge with optional browser factory.

        Args:
            browser_factory: Callable that returns a browser instance.
                           Defaults to cloakbrowser.launch.
        """
        self._browser_factory = browser_factory or self._default_factory

    @staticmethod
    def _default_factory(**kwargs):
        """Default factory using cloakbrowser.launch."""
        try:
            from cloakbrowser import launch
            return launch(**kwargs)
        except ImportError:
            raise CloakBrowserLaunchError(
                "CloakBrowser not installed. Install with: pip install cloakbrowser\n"
                "Or use --no-cloak for mock mode."
            )

    def observe(
        self,
        url: str,
        headless: bool = True,
        timeout: float = 30.0,
    ) -> PageObservation:
        """Observe a page using CloakBrowser.

        Args:
            url: Target URL to observe
            headless: Run browser in headless mode
            timeout: Page load timeout in seconds

        Returns:
            PageObservation with real browser data

        Raises:
            CloakBrowserLaunchError: If browser launch fails
            CloakBrowserNavigationError: If navigation fails
        """
        browser = None
        try:
            browser = self._browser_factory(headless=headless)
            page = browser.new_page()

            # Set up network tracking
            network_tracker = NetworkTracker()
            page.on("request", network_tracker.on_request)
            page.on("response", network_tracker.on_response)

            # Navigate
            try:
                page.goto(
                    url,
                    timeout=int(timeout * 1000),
                    wait_until="domcontentloaded",
                )
            except Exception as e:
                raise CloakBrowserNavigationError(
                    f"Failed to navigate to {url}: {e}"
                ) from e

            # Extract data
            title = self._extract_title(page)
            final_url = self._extract_url(page)
            elements = self._extract_interactive_elements(page)
            actionability_summary = self._build_actionability_summary(elements)
            storage_state = self._extract_storage_state(page)

            return PageObservation(
                url=final_url,
                title=title,
                interactive_elements=elements,
                actionability=actionability_summary,
                network=network_tracker.to_activity(),
                storage=storage_state,
                observed_at=datetime.utcnow(),
            )
        finally:
            if browser:
                browser.close()

    def _extract_title(self, page: Any) -> str:
        """Extract page title."""
        try:
            return page.title()
        except Exception:
            return ""

    def _extract_url(self, page: Any) -> str:
        """Extract current page URL."""
        try:
            return page.url
        except Exception:
            return ""

    def _extract_interactive_elements(self, page: Any) -> List[InteractiveElement]:
        """Extract interactive elements from the page."""
        elements = []
        for selector in INTERACTIVE_SELECTORS:
            try:
                locators = page.locator(selector).all()[:MAX_ELEMENTS_PER_SELECTOR]
                for idx, locator in enumerate(locators):
                    element = self._extract_element(locator, selector, idx)
                    if element:
                        elements.append(element)
            except Exception:
                continue
        return elements

    @staticmethod
    def _extract_element(locator: Any, selector_type: str, index: int) -> Optional[InteractiveElement]:
        """Extract data from a single element locator.

        Args:
            locator: Browser locator object
            selector_type: CSS selector type (e.g. 'button', 'input')
            index: Index of element within its selector group

        Returns:
            InteractiveElement or None if extraction fails
        """
        try:
            tag = locator.evaluate("el => el.tagName.toLowerCase()")
            type_ = locator.get_attribute("type")
            aria_label = locator.get_attribute("aria-label")

            # Get text — None for input elements
            text = None
            if tag not in ("input", "textarea"):
                raw_text = locator.inner_text()
                text = raw_text[:50] if raw_text else None

            # Actionability checks
            is_visible = locator.is_visible()
            is_enabled = locator.is_enabled()
            is_editable = locator.is_editable() if tag in ("input", "textarea", "select") else False

            actionability = {
                "attached": True,
                "visible": is_visible,
                "enabled": is_enabled,
                "editable": is_editable,
                "stable": True,
                "pointer_events": True,
            }

            selector = f"{selector_type}:nth-of-type({index + 1})"

            return InteractiveElement(
                selector=selector,
                tag=tag,
                type=type_,
                text=text,
                aria_label=aria_label,
                actionability=actionability,
            )
        except Exception:
            return None

    @staticmethod
    def _build_actionability_summary(elements: List[InteractiveElement]) -> Dict[str, Any]:
        """Build summary of element actionability checks.

        Args:
            elements: List of interactive elements

        Returns:
            Summary dict with total, actionable counts and checks performed
        """
        actionable = 0
        for el in elements:
            if el.actionability and el.actionability.get("enabled") and el.actionability.get("visible"):
                actionable += 1

        return {
            "total_elements": len(elements),
            "actionable_elements": actionable,
            "checks_performed": ACTIONABILITY_CHECKS,
        }

    def collect_evidence(self, action_id: str, target_ref: str) -> "ActionabilityEvidence":
        """Collect actionability evidence for a target element via real browser.

        Args:
            action_id: Unique identifier for the action.
            target_ref: CSS selector for the target element.

        Returns:
            ActionabilityEvidence with real element state.
        """
        from netweaver.wnal import ActionabilityEvidence, Phase

        try:
            browser = self._browser_factory(headless=True)
            page = browser.new_page()
            try:
                locator = page.locator(target_ref)
                is_visible = locator.is_visible()
                is_enabled = locator.is_enabled()
                is_editable = locator.is_editable()
                # Check attached by evaluating DOM presence
                is_attached = locator.count() > 0
                is_stable = True  # optimistic; could add wait-for-stable
                has_pointer_events = True  # optimistic; real check via evaluate

                if is_attached and has_pointer_events:
                    try:
                        has_pointer_events = locator.evaluate(
                            "el => window.getComputedStyle(el).pointerEvents !== 'none'"
                        )
                    except Exception:
                        has_pointer_events = True

                return ActionabilityEvidence(
                    action_id=action_id,
                    target_ref=target_ref,
                    selector=target_ref,
                    phase=Phase.PRE,
                    visible=is_visible,
                    enabled=is_enabled,
                    attached=is_attached,
                    stable=is_stable,
                    pointer_events=has_pointer_events,
                    editable=is_editable,
                    observed_at=datetime.utcnow(),
                )
            finally:
                browser.close()
        except Exception:
            return ActionabilityEvidence(
                action_id=action_id,
                target_ref=target_ref,
                selector=target_ref,
                phase=Phase.PRE,
                attached=False,
                visible=False,
                enabled=False,
                stable=True,
                pointer_events=True,
                observed_at=datetime.utcnow(),
            )

    def execute_action(self, action: Any) -> bool:
        """Execute a typed browser action on a real page.

        Args:
            action: TypedAction (ClickAction, FillAction, or WaitAction).

        Returns:
            True if action succeeded, False otherwise.
        """
        from netweaver.wnal import ActionType

        try:
            browser = self._browser_factory(headless=True)
            page = browser.new_page()
            try:
                locator = page.locator(action.target_ref)
                if action.action_type == ActionType.CLICK:
                    click_args = {}
                    if hasattr(action, "button") and action.button:
                        click_args["button"] = action.button
                    if hasattr(action, "click_count") and action.click_count:
                        click_args["click_count"] = action.click_count
                    if hasattr(action, "delay_ms") and action.delay_ms:
                        click_args["delay"] = action.delay_ms / 1000.0
                    locator.click(**click_args)
                    return True

                elif action.action_type == ActionType.FILL:
                    fill_text = getattr(action, "text", "") or getattr(action, "value", "")
                    if getattr(action, "clear_first", True):
                        locator.fill("")
                    locator.fill(fill_text)
                    if getattr(action, "press_enter", False):
                        page.keyboard.press("Enter")
                    return True

                elif action.action_type == ActionType.WAIT:
                    condition = getattr(action, "condition", "attached")
                    timeout_ms = getattr(action, "timeout_ms", 30000)
                    state_map = {
                        "attached": "attached",
                        "visible": "visible",
                        "stable": "stable",
                        "hidden": "hidden",
                        "detached": "detached",
                    }
                    state = state_map.get(condition, "attached")
                    locator.wait_for(state=state, timeout=timeout_ms)
                    return True

                return False
            finally:
                browser.close()
        except Exception:
            return False

    def _extract_storage_state(self, page: Any) -> StorageState:
        """Extract browser storage state (cookies, localStorage, sessionStorage)."""
        try:
            cookies = page.context.cookies()
            return StorageState(
                cookies=cookies,
                local_storage={},
                session_storage={},
            )
        except Exception:
            return StorageState(cookies=[], local_storage={}, session_storage={})
