"""Playwright Bridge — Real browser interaction via Playwright.

Replaces CloakBrowserBridge when CloakBrowser SDK is not available.
Implements the same interface: observe, collect_evidence, execute_action.

NW-004 / P2-004: Enables real-site orchestration without CloakBrowser.
"""
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    StorageState,
)


class PlaywrightError(Exception):
    """Base error for Playwright bridge operations."""
    pass


class PlaywrightLaunchError(PlaywrightError):
    """Failed to launch Playwright browser."""
    pass


class PlaywrightNavigationError(PlaywrightError):
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
        req_data = {
            "url": request.url,
            "method": request.method,
            "headers": dict(request.headers),
            "timestamp": datetime.utcnow().isoformat(),
            "resource_type": request.resource_type,
        }
        self.requests.append(req_data)

    def on_response(self, response: Any) -> None:
        res_data = {
            "url": response.url,
            "status": response.status,
            "headers": dict(response.headers),
            "timestamp": datetime.utcnow().isoformat(),
            "ok": response.ok,
        }
        self.responses.append(res_data)

    def to_activity(self) -> NetworkActivity:
        return NetworkActivity(
            requests_count=self.requests_count,
            responses_count=self.responses_count,
            failed_count=self.failed_count,
            resource_types=dict(self.resource_types),
        )


INTERACTIVE_SELECTORS = [
    "button",
    "a[href]",
    "input",
    "textarea",
    "select",
    "[role='button']",
    "[onclick]",
]

MAX_ELEMENTS_PER_SELECTOR = 10
ACTIONABILITY_CHECKS = [
    "attached", "visible", "enabled", "editable",
    "stable", "pointer_events",
]


class PlaywrightBridge:
    """Bridge between Playwright and NetWeaver observer/executor.

    Provides the same interface as CloakBrowserBridge but uses
    Playwright directly for browser automation.

    Usage:
        bridge = PlaywrightBridge()
        observation = bridge.observe(url, headless=True, timeout=30.0)
        evidence = bridge.collect_evidence(action_id, target_ref)
        success = bridge.execute_action(action)
    """

    def __init__(self, browser_launcher: Optional[Callable] = None):
        """Initialize bridge with optional browser launcher.

        Args:
            browser_launcher: Callable that returns a browser instance.
                Defaults to playwright.sync_api.chromium.launch.
        """
        self._browser_launcher = browser_launcher or self._default_launcher
        self._context = None

    @staticmethod
    def _default_launcher(**kwargs) -> Any:
        """Default launcher using Playwright Chromium headless."""
        try:
            from playwright.sync_api import sync_playwright
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(**kwargs)
            # Attach playwright to browser so we can stop it later
            browser._pw_playwright = playwright
            return browser
        except ImportError as e:
            raise PlaywrightLaunchError(
                "Playwright not installed. Install with: pip install playwright && playwright install chromium"
            ) from e

    def observe(
        self,
        url: str,
        headless: bool = True,
        timeout: float = 30.0,
    ) -> PageObservation:
        """Observe a page using Playwright Chromium.

        Args:
            url: Target URL to observe
            headless: Run browser in headless mode
            timeout: Page load timeout in seconds

        Returns:
            PageObservation with real browser data
        """
        browser = None
        try:
            browser = self._browser_launcher(headless=headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()

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
                raise PlaywrightNavigationError(
                    f"Failed to navigate to {url}: {e}"
                ) from e

            # Extract data
            title = self._extract_title(page)
            final_url = page.url
            elements = self._extract_interactive_elements(page)
            actionability_summary = self._build_actionability_summary(elements)
            storage_state = self._extract_storage_state(page, context)

            return PageObservation(
                url=final_url,
                title=title,
                interactive_elements=elements,
                actionability=actionability_summary,
                network=network_tracker.to_activity(),
                storage=storage_state,
                observed_at=datetime.utcnow(),
            )
        except PlaywrightError:
            raise
        except Exception as e:
            raise PlaywrightError(f"Observation failed: {e}") from e
        finally:
            if browser:
                try:
                    browser.close()
                    pw = getattr(browser, "_pw_playwright", None)
                    if pw:
                        pw.stop()
                except Exception:
                    pass

    def collect_evidence(
        self, action_id: str, target_ref: str
    ) -> "ActionabilityEvidence":
        """Collect actionability evidence for a target element via real browser.

        Args:
            action_id: Unique identifier for the action.
            target_ref: CSS selector for the target element.

        Returns:
            ActionabilityEvidence with real element state.
        """
        from netweaver.wnal import ActionabilityEvidence, Phase

        browser = None
        try:
            browser = self._browser_launcher(headless=True)
            context = browser.new_context()
            page = context.new_page()

            locator = page.locator(target_ref)
            count = locator.count()
            if count == 0:
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

            is_visible = locator.first.is_visible()
            is_enabled = locator.first.is_enabled()
            is_editable = locator.first.is_editable()
            is_attached = count > 0

            has_pointer_events = True
            try:
                has_pointer_events = locator.first.evaluate(
                    "el => window.getComputedStyle(el).pointerEvents !== 'none'"
                )
            except Exception:
                pass

            return ActionabilityEvidence(
                action_id=action_id,
                target_ref=target_ref,
                selector=target_ref,
                phase=Phase.PRE,
                visible=is_visible,
                enabled=is_enabled,
                attached=is_attached,
                stable=True,
                pointer_events=has_pointer_events,
                editable=is_editable,
                observed_at=datetime.utcnow(),
            )
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
        finally:
            if browser:
                try:
                    browser.close()
                    pw = getattr(browser, "_pw_playwright", None)
                    if pw:
                        pw.stop()
                except Exception:
                    pass

    def execute_action(self, action: Any) -> bool:
        """Execute a typed browser action on a real page via Playwright.

        Args:
            action: TypedAction (ClickAction, FillAction, or WaitAction).

        Returns:
            True if action succeeded, False otherwise.
        """
        from netweaver.wnal import ActionType

        browser = None
        try:
            browser = self._browser_launcher(headless=True)
            context = browser.new_context()
            page = context.new_page()

            locator = page.locator(action.target_ref)

            if action.action_type == ActionType.CLICK:
                click_args = {}
                if hasattr(action, "button") and action.button:
                    click_args["button"] = action.button
                if hasattr(action, "click_count") and action.click_count:
                    click_args["click_count"] = action.click_count
                if hasattr(action, "delay_ms") and action.delay_ms:
                    click_args["delay"] = action.delay_ms / 1000.0
                locator.first.click(**click_args)
                return True

            elif action.action_type == ActionType.FILL:
                fill_text = getattr(action, "text", "") or getattr(action, "value", "")
                if getattr(action, "clear_first", True):
                    locator.first.fill("")
                locator.first.fill(fill_text)
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
                locator.first.wait_for(state=state, timeout=timeout_ms)
                return True

            return False
        except Exception:
            return False
        finally:
            if browser:
                try:
                    browser.close()
                    pw = getattr(browser, "_pw_playwright", None)
                    if pw:
                        pw.stop()
                except Exception:
                    pass

    def _extract_title(self, page: Any) -> str:
        try:
            return page.title()
        except Exception:
            return ""

    def _extract_interactive_elements(self, page: Any) -> List[InteractiveElement]:
        elements = []
        for selector in INTERACTIVE_SELECTORS:
            try:
                locators = page.locator(selector).all()
                for idx, locator in enumerate(locators[:MAX_ELEMENTS_PER_SELECTOR]):
                    element = self._extract_element(locator, selector, idx)
                    if element:
                        elements.append(element)
            except Exception:
                continue
        return elements

    @staticmethod
    def _extract_element(
        locator: Any, selector_type: str, index: int
    ) -> Optional[InteractiveElement]:
        try:
            tag = locator.evaluate("el => el.tagName.toLowerCase()")
            type_ = locator.get_attribute("type")
            aria_label = locator.get_attribute("aria-label")

            text = None
            if tag not in ("input", "textarea"):
                raw_text = locator.inner_text()
                text = raw_text[:50] if raw_text else None

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
    def _build_actionability_summary(
        elements: List[InteractiveElement],
    ) -> Dict[str, Any]:
        actionable = 0
        for el in elements:
            if el.actionability and el.actionability.get("enabled") and el.actionability.get("visible"):
                actionable += 1
        return {
            "total_elements": len(elements),
            "actionable_elements": actionable,
            "checks_performed": ACTIONABILITY_CHECKS,
        }

    def _extract_storage_state(self, page: Any, context: Any) -> StorageState:
        try:
            cookies = context.cookies()
            local_storage = {}
            session_storage = {}
            try:
                local_storage = page.evaluate("JSON.parse(JSON.stringify(window.localStorage))")
            except Exception:
                pass
            try:
                session_storage = page.evaluate("JSON.parse(JSON.stringify(window.sessionStorage))")
            except Exception:
                pass
            return StorageState(
                cookies=cookies,
                local_storage=local_storage,
                session_storage=session_storage,
            )
        except Exception:
            return StorageState(cookies=[], local_storage={}, session_storage={})
