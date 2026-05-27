"""Tests for NetWeaver Observer — current API coverage.

Tests the dataclass models and observe_page_mock() function.
"""
from datetime import datetime
from unittest.mock import patch

import pytest

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    StorageState,
    PageObservation,
    observe_page_mock,
)


class TestInteractiveElement:
    """InteractiveElement dataclass."""

    def test_defaults(self):
        el = InteractiveElement(selector="#btn", tag="button")
        assert el.selector == "#btn"
        assert el.tag == "button"
        assert el.type is None
        assert el.text is None
        assert el.aria_label is None
        assert el.actionability is None

    def test_to_dict_full(self):
        el = InteractiveElement(
            selector="input#email",
            tag="input",
            type="email",
            text="Enter email",
            aria_label="Email address",
            actionability={"attached": True, "visible": True},
        )
        d = el.to_dict()
        assert d["selector"] == "input#email"
        assert d["tag"] == "input"
        assert d["type"] == "email"
        assert d["actionability"]["visible"] is True

    def test_to_dict_partial(self):
        el = InteractiveElement(selector="a.link", tag="a")
        d = el.to_dict()
        assert d["selector"] == "a.link"
        assert d["type"] is None
        assert d["actionability"] is None


class TestNetworkActivity:
    """NetworkActivity dataclass."""

    def test_defaults(self):
        na = NetworkActivity()
        assert na.requests_count == 0
        assert na.responses_count == 0
        assert na.failed_count == 0
        assert na.resource_types == {}

    def test_to_dict(self):
        na = NetworkActivity(
            requests_count=10,
            responses_count=8,
            failed_count=2,
            resource_types={"document": 1, "script": 5},
        )
        d = na.to_dict()
        assert d["requests_count"] == 10
        assert d["failed_count"] == 2
        assert d["resource_types"]["script"] == 5


class TestStorageState:
    """StorageState dataclass."""

    def test_defaults(self):
        ss = StorageState()
        assert ss.local_storage == {}
        assert ss.session_storage == {}
        assert ss.cookies == []

    def test_to_dict(self):
        ss = StorageState(
            local_storage={"theme": "dark"},
            session_storage={"session_id": "x"},
            cookies=[{"name": "sid", "value": "x", "domain": "example.com"}],
        )
        d = ss.to_dict()
        assert d["local_storage"]["theme"] == "dark"
        assert len(d["cookies"]) == 1


class TestPageObservation:
    """PageObservation dataclass + serialization."""

    @pytest.fixture
    def sample_observation(self) -> PageObservation:
        return PageObservation(
            url="http://example.com",
            title="Test Page",
            interactive_elements=[
                InteractiveElement(selector="#btn", tag="button"),
            ],
            actionability={"total_elements": 1, "actionable_elements": 1},
            network=NetworkActivity(requests_count=5, responses_count=5),
            observed_at=datetime(2025, 1, 1, 12, 0, 0),
            storage=StorageState(
                local_storage={"key": "val"},
                cookies=[{"name": "c", "value": "v", "domain": "example.com"}],
            ),
        )

    def test_to_dict(self, sample_observation):
        d = sample_observation.to_dict()
        assert d["url"] == "http://example.com"
        assert d["title"] == "Test Page"
        assert len(d["interactive_elements"]) == 1
        assert d["network"]["requests_count"] == 5
        assert d["storage"]["local_storage"]["key"] == "val"

    def test_to_json(self, sample_observation):
        j = sample_observation.to_json()
        assert isinstance(j, str)
        assert "http://example.com" in j
        assert "Test Page" in j

    def test_optional_storage(self):
        obs = PageObservation(
            url="http://example.com",
            title="No Storage",
            interactive_elements=[],
            actionability={},
            network=NetworkActivity(),
            observed_at=datetime.now(),
        )
        d = obs.to_dict()
        # storage key omitted when None — not serialized
        assert "storage" not in d


class TestObservePageMock:
    """observe_page_mock() function."""

    def test_returns_page_observation(self):
        result = observe_page_mock("http://example.com")
        assert isinstance(result, PageObservation)

    def test_url_reflected(self):
        url = "http://test-site.com/page"
        result = observe_page_mock(url)
        assert result.url == url

    def test_title_contains_domain(self):
        result = observe_page_mock("http://mysite.com")
        assert "mysite.com" in result.title

    def test_has_interactive_elements(self):
        result = observe_page_mock("http://example.com")
        assert len(result.interactive_elements) > 0
        # Check known mock elements
        selectors = [el.selector for el in result.interactive_elements]
        assert "button#submit" in selectors
        assert "input#email" in selectors

    def test_all_elements_have_actionability(self):
        result = observe_page_mock("http://example.com")
        for el in result.interactive_elements:
            assert el.actionability is not None
            assert el.actionability.get("attached") is True

    def test_network_activity(self):
        result = observe_page_mock("http://example.com")
        assert result.network.requests_count > 0
        assert result.network.failed_count == 0

    def test_actionability_summary(self):
        result = observe_page_mock("http://example.com")
        assert result.actionability["total_elements"] > 0
        assert result.actionability["actionable_elements"] > 0

    def test_storage_state(self):
        result = observe_page_mock("http://example.com")
        assert result.storage is not None
        assert "theme" in result.storage.local_storage
        assert len(result.storage.cookies) > 0

    def test_observed_at_timestamp(self):
        result = observe_page_mock("http://example.com")
        assert isinstance(result.observed_at, datetime)
        # Should be recent (within last minute)
        delta = datetime.now() - result.observed_at
        assert delta.total_seconds() < 60


class TestObservePageMockEdgeCases:
    """Edge cases for observe_page_mock."""

    def test_empty_url(self):
        result = observe_page_mock("")
        assert result is not None
        domain_in_title = "example.com" in result.title
        # With empty URL, domain parsing yields empty string
        assert isinstance(result.url, str)

    def test_url_with_query_params(self):
        result = observe_page_mock("http://example.com/path?a=1&b=2")
        assert result.url == "http://example.com/path?a=1&b=2"

    def test_https_url(self):
        result = observe_page_mock("https://secure-site.com")
        assert "secure-site.com" in result.title
        assert result.url.startswith("https://")

    def test_ip_address_url(self):
        result = observe_page_mock("http://192.168.1.1/admin")
        assert "192.168.1.1" in result.title

    def test_many_elements_actionability(self):
        """All returned elements should have complete actionability checks."""
        result = observe_page_mock("http://example.com")
        required_checks = {"attached", "visible", "enabled", "editable", "stable", "pointer_events"}
        for el in result.interactive_elements:
            assert el.actionability is not None
            assert required_checks.issubset(el.actionability.keys())
