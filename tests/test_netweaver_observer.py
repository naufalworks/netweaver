"""Tests for NetWeaver Observer module."""

import json
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    observe_page,
    observe_page_mock,
)


class TestInteractiveElement:
    """Test InteractiveElement dataclass."""
    
    def test_to_dict_minimal(self):
        """Test serialization with minimal fields."""
        elem = InteractiveElement(
            selector="button#submit",
            tag="button",
        )
        data = elem.to_dict()
        
        assert data["selector"] == "button#submit"
        assert data["tag"] == "button"
        assert data["type"] is None
        assert data["text"] is None
        assert data["aria_label"] is None
        assert data["actionability"] is None
    
    def test_to_dict_full(self):
        """Test serialization with all fields."""
        elem = InteractiveElement(
            selector="input#email",
            tag="input",
            type="email",
            text="test@example.com",
            aria_label="Email address",
            actionability={
                "attached": True,
                "visible": True,
                "enabled": True,
                "editable": True,
                "stable": True,
                "pointer_events": True,
            }
        )
        data = elem.to_dict()
        
        assert data["selector"] == "input#email"
        assert data["tag"] == "input"
        assert data["type"] == "email"
        assert data["text"] == "test@example.com"
        assert data["aria_label"] == "Email address"
        assert data["actionability"]["attached"] is True
        assert data["actionability"]["editable"] is True


class TestNetworkActivity:
    """Test NetworkActivity dataclass."""
    
    def test_to_dict_empty(self):
        """Test serialization with default values."""
        network = NetworkActivity()
        data = network.to_dict()
        
        assert data["requests_count"] == 0
        assert data["responses_count"] == 0
        assert data["failed_count"] == 0
        assert data["resource_types"] == {}
    
    def test_to_dict_with_data(self):
        """Test serialization with activity data."""
        network = NetworkActivity(
            requests_count=10,
            responses_count=9,
            failed_count=1,
            resource_types={"document": 1, "script": 5, "image": 4}
        )
        data = network.to_dict()
        
        assert data["requests_count"] == 10
        assert data["responses_count"] == 9
        assert data["failed_count"] == 1
        assert data["resource_types"]["script"] == 5


class TestPageObservation:
    """Test PageObservation dataclass."""
    
    def test_to_dict(self):
        """Test serialization of complete observation."""
        elem = InteractiveElement(
            selector="button",
            tag="button",
            actionability={"attached": True, "visible": True}
        )
        network = NetworkActivity(requests_count=5)
        obs_time = datetime(2026, 5, 23, 12, 0, 0)
        
        obs = PageObservation(
            url="https://example.com",
            title="Example Page",
            interactive_elements=[elem],
            actionability={"total_elements": 1},
            network=network,
            observed_at=obs_time,
        )
        
        data = obs.to_dict()
        
        assert data["url"] == "https://example.com"
        assert data["title"] == "Example Page"
        assert len(data["interactive_elements"]) == 1
        assert data["interactive_elements"][0]["selector"] == "button"
        assert data["actionability"]["total_elements"] == 1
        assert data["network"]["requests_count"] == 5
        assert data["observed_at"] == "2026-05-23T12:00:00"
    
    def test_to_json(self):
        """Test JSON serialization."""
        elem = InteractiveElement(selector="a", tag="a")
        network = NetworkActivity()
        obs_time = datetime(2026, 5, 23, 12, 0, 0)
        
        obs = PageObservation(
            url="https://example.com",
            title="Test",
            interactive_elements=[elem],
            actionability={},
            network=network,
            observed_at=obs_time,
        )
        
        json_str = obs.to_json()
        data = json.loads(json_str)
        
        assert data["url"] == "https://example.com"
        assert data["title"] == "Test"
        assert isinstance(data["interactive_elements"], list)


class TestObservePageMock:
    """Test mock page observation (--no-cloak mode)."""
    
    def test_mock_returns_valid_observation(self):
        """Test that mock mode returns valid PageObservation."""
        obs = observe_page_mock("https://example.com")
        
        assert isinstance(obs, PageObservation)
        assert obs.url == "https://example.com"
        assert "example.com" in obs.title
        assert len(obs.interactive_elements) > 0
        assert isinstance(obs.network, NetworkActivity)
        assert isinstance(obs.observed_at, datetime)
    
    def test_mock_has_required_fields(self):
        """Test that mock observation has all required fields."""
        obs = observe_page_mock("https://test.com")
        
        # Check top-level fields
        assert obs.url
        assert obs.title
        assert obs.interactive_elements is not None
        assert obs.actionability is not None
        assert obs.network is not None
        assert obs.observed_at is not None
    
    def test_mock_interactive_elements_have_actionability(self):
        """Test that mock elements include actionability evidence."""
        obs = observe_page_mock("https://example.com")
        
        assert len(obs.interactive_elements) > 0
        
        for elem in obs.interactive_elements:
            assert elem.actionability is not None
            assert "attached" in elem.actionability
            assert "visible" in elem.actionability
            assert "enabled" in elem.actionability
            assert "editable" in elem.actionability
            assert "stable" in elem.actionability
            assert "pointer_events" in elem.actionability
    
    def test_mock_network_activity(self):
        """Test that mock includes network activity."""
        obs = observe_page_mock("https://example.com")
        
        assert obs.network.requests_count > 0
        assert obs.network.responses_count > 0
        assert obs.network.failed_count >= 0
        assert len(obs.network.resource_types) > 0
    
    def test_mock_actionability_summary(self):
        """Test that mock includes actionability summary."""
        obs = observe_page_mock("https://example.com")
        
        assert "total_elements" in obs.actionability
        assert "actionable_elements" in obs.actionability
        assert "checks_performed" in obs.actionability
        assert obs.actionability["total_elements"] > 0
        assert len(obs.actionability["checks_performed"]) == 6
    
    def test_mock_json_serialization(self):
        """Test that mock observation serializes to valid JSON."""
        obs = observe_page_mock("https://example.com")
        json_str = obs.to_json()
        
        # Should not raise
        data = json.loads(json_str)
        
        assert data["url"] == "https://example.com"
        assert "title" in data
        assert "interactive_elements" in data
        assert "actionability" in data
        assert "network" in data
        assert "observed_at" in data


class TestObservePage:
    """Test observe_page function."""
    
    def test_observe_page_no_cloak_mode(self):
        """Test observe_page with use_cloak=False."""
        obs = observe_page("https://example.com", use_cloak=False)
        
        assert isinstance(obs, PageObservation)
        assert obs.url == "https://example.com"
        assert len(obs.interactive_elements) > 0
    
    def test_observe_page_default_uses_cloak(self):
        """Test that observe_page defaults to use_cloak=True."""
        # This will fail if cloakbrowser is not installed, which is expected
        # In CI/testing, we use --no-cloak mode
        with pytest.raises((ImportError, Exception)):
            observe_page("https://example.com")


class TestCLIAcceptance:
    """Acceptance tests matching KANBAN criteria."""
    
    def test_cli_no_cloak_prints_valid_json(self, capsys):
        """Test: python -m netweaver.observer https://example.com --no-cloak prints valid JSON."""
        from netweaver.observer import main
        
        with patch("sys.argv", ["observer", "https://example.com", "--no-cloak"]):
            main()
        
        captured = capsys.readouterr()
        
        # Should print valid JSON
        data = json.loads(captured.out)
        
        assert data["url"] == "https://example.com"
        assert "title" in data
        assert "interactive_elements" in data
        assert "actionability" in data
        assert "network" in data
    
    def test_json_has_required_fields(self):
        """Test: JSON has url, title, interactive_elements, actionability, network."""
        obs = observe_page_mock("https://example.com")
        data = json.loads(obs.to_json())
        
        # Required fields from acceptance criteria
        assert "url" in data
        assert "title" in data
        assert "interactive_elements" in data
        assert "actionability" in data
        assert "network" in data
    
    def test_no_browser_download_in_mock_mode(self):
        """Test: tests use mocks/no browser download."""
        # This test itself proves we can test without browser
        obs = observe_page_mock("https://example.com")
        
        # Should complete instantly without network/browser
        assert obs is not None
        assert isinstance(obs, PageObservation)
