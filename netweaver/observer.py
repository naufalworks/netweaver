"""NetWeaver Observer - Browser page inspection with actionability evidence.

This module provides page observation capabilities that extract:
- Basic page metadata (url, title)
- Interactive elements with actionability evidence
- Network activity summary
- Visual/DOM state

Supports both real CloakBrowser execution and --no-cloak mock mode for testing.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


@dataclass
class InteractiveElement:
    """An interactive element discovered on the page."""
    selector: str
    tag: str
    type: Optional[str] = None
    text: Optional[str] = None
    aria_label: Optional[str] = None
    actionability: Optional[Dict[str, bool]] = None
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "selector": self.selector,
            "tag": self.tag,
            "type": self.type,
            "text": self.text,
            "aria_label": self.aria_label,
            "actionability": self.actionability,
        }


@dataclass
class NetworkActivity:
    """Network activity summary."""
    requests_count: int = 0
    responses_count: int = 0
    failed_count: int = 0
    resource_types: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "requests_count": self.requests_count,
            "responses_count": self.responses_count,
            "failed_count": self.failed_count,
            "resource_types": self.resource_types,
        }


@dataclass
class StorageState:
    """Browser storage state snapshot."""
    local_storage: Dict[str, str] = field(default_factory=dict)
    session_storage: Dict[str, str] = field(default_factory=dict)
    cookies: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "local_storage": self.local_storage,
            "session_storage": self.session_storage,
            "cookies": self.cookies,
        }


@dataclass
class PageObservation:
    """Complete page observation result."""
    url: str
    title: str
    interactive_elements: List[InteractiveElement]
    actionability: Dict[str, Any]
    network: NetworkActivity
    observed_at: datetime
    storage: Optional[StorageState] = None

    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        d = {
            "url": self.url,
            "title": self.title,
            "interactive_elements": [el.to_dict() for el in self.interactive_elements],
            "actionability": self.actionability,
            "network": self.network.to_dict(),
            "observed_at": self.observed_at.isoformat(),
        }
        if self.storage is not None:
            d["storage"] = self.storage.to_dict()
        return d

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


def observe_page_mock(url: str) -> PageObservation:
    """Mock page observation for testing (--no-cloak mode).
    
    Returns synthetic data without launching a real browser.
    """
    parsed = urlparse(url)
    domain = parsed.netloc or "example.com"
    
    # Create mock interactive elements
    elements = [
        InteractiveElement(
            selector="button#submit",
            tag="button",
            type="submit",
            text="Submit",
            aria_label="Submit form",
            actionability={
                "attached": True,
                "visible": True,
                "enabled": True,
                "editable": False,
                "stable": True,
                "pointer_events": True,
            }
        ),
        InteractiveElement(
            selector="input#email",
            tag="input",
            type="email",
            text=None,
            aria_label="Email address",
            actionability={
                "attached": True,
                "visible": True,
                "enabled": True,
                "editable": True,
                "stable": True,
                "pointer_events": True,
            }
        ),
        InteractiveElement(
            selector="a.nav-link",
            tag="a",
            type=None,
            text="Home",
            aria_label=None,
            actionability={
                "attached": True,
                "visible": True,
                "enabled": True,
                "editable": False,
                "stable": True,
                "pointer_events": True,
            }
        ),
    ]
    
    # Mock network activity
    network = NetworkActivity(
        requests_count=12,
        responses_count=12,
        failed_count=0,
        resource_types={
            "document": 1,
            "stylesheet": 3,
            "script": 5,
            "image": 2,
            "xhr": 1,
        }
    )
    
    # Mock actionability summary
    actionability_summary = {
        "total_elements": len(elements),
        "actionable_elements": len([e for e in elements if e.actionability and e.actionability.get("enabled")]),
        "checks_performed": ["attached", "visible", "enabled", "editable", "stable", "pointer_events"],
    }
    
    # Mock storage state
    storage = StorageState(
        local_storage={"theme": "dark", "lang": "en"},
        session_storage={"session_id": "abc123"},
        cookies=[{"name": "sid", "value": "x", "domain": domain}],
    )

    return PageObservation(
        url=url,
        title=f"Mock Page - {domain}",
        interactive_elements=elements,
        actionability=actionability_summary,
        network=network,
        observed_at=datetime.now(),
        storage=storage,
    )


def observe_page_cloak(url: str, headless: bool = True, timeout: float = 30.0) -> PageObservation:
    """Observe page using real browser (CloakBrowser or Playwright fallback).
    
    Uses CloakBrowser if installed; falls back to Playwright otherwise.
    
    Args:
        url: Target URL to observe
        headless: Run browser in headless mode
        timeout: Page load timeout in seconds
        
    Returns:
        PageObservation with real browser data
        
    Raises:
        RuntimeError: If browser launch or page load fails
    """
    try:
        from netweaver.cloak_bridge import CloakBrowserBridge
        bridge = CloakBrowserBridge()
        return bridge.observe(url, headless=headless, timeout=timeout)
    except ImportError:
        pass
    
    # Fallback: Playwright
    from netweaver.playwright_bridge import PlaywrightBridge, PlaywrightError
    bridge = PlaywrightBridge()
    try:
        return bridge.observe(url, headless=headless, timeout=timeout)
    except PlaywrightError as e:
        raise RuntimeError(str(e)) from e


def observe_page(url: str, use_cloak: bool = True, headless: bool = True, timeout: float = 30.0) -> PageObservation:
    """Observe a web page and extract actionability evidence.
    
    Args:
        url: Target URL to observe
        use_cloak: Use real CloakBrowser (True) or mock mode (False)
        headless: Run browser in headless mode (only for use_cloak=True)
        timeout: Page load timeout in seconds
        
    Returns:
        PageObservation with page metadata and actionability evidence
    """
    if use_cloak:
        return observe_page_cloak(url, headless=headless, timeout=timeout)
    else:
        return observe_page_mock(url)


def main():
    """CLI entry point for observer."""
    parser = argparse.ArgumentParser(
        description="NetWeaver Observer - Inspect web pages with actionability evidence"
    )
    parser.add_argument("url", help="URL to observe")
    parser.add_argument(
        "--no-cloak",
        action="store_true",
        help="Use mock mode instead of real browser (for testing)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Page load timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output"
    )
    
    args = parser.parse_args()
    
    try:
        observation = observe_page(
            url=args.url,
            use_cloak=not args.no_cloak,
            headless=args.headless,
            timeout=args.timeout,
        )
        
        indent = 2 if args.pretty else None
        print(observation.to_json(indent=indent))
        
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
