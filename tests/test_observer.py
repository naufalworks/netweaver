"""Integration tests for netweaver.observer module.

Tests cover:
- Data classes: InteractiveElement, NetworkActivity, StorageState, PageObservation
- Mock observation: observe_page_mock()
- Entry points: observe_page(), observe_page_cloak()
- CLI: main()
- Serialization: to_dict(), to_json()

All tests use mock mode — no real browser launched.
"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    StorageState,
    observe_page,
    observe_page_mock,
)


# ── InteractiveElement ──────────────────────────────────────────────


class TestInteractiveElement:
    def test_creation_full(self):
        el = InteractiveElement(
            selector="button#submit",
            tag="button",
            type="submit",
            text="Submit",
            aria_label="Submit form",
            actionability={"visible": True, "enabled": True},
        )
        assert el.selector == "button#submit"
        assert el.tag == "button"
        assert el.type == "submit"
        assert el.text == "Submit"
        assert el.aria_label == "Submit form"
        assert el.actionability["visible"] is True

    def test_creation_minimal(self):
        el = InteractiveElement(selector="div.x", tag="div")
        assert el.type is None
        assert el.text is None
        assert el.aria_label is None
        assert el.actionability is None

    def test_to_dict_full(self):
        el = InteractiveElement(
            selector="input#email",
            tag="input",
            type="email",
            text=None,
            aria_label="Email",
            actionability={"attached": True},
        )
        d = el.to_dict()
        assert d["selector"] == "input#email"
        assert d["tag"] == "input"
        assert d["type"] == "email"
        assert d["text"] is None
        assert d["aria_label"] == "Email"
        assert d["actionability"] == {"attached": True}

    def test_to_dict_round_trip_json(self):
        el = InteractiveElement(
            selector="a.link", tag="a", text="Home",
            actionability={"visible": True},
        )
        serialized = json.dumps(el.to_dict())
        deserialized = json.loads(serialized)
        assert deserialized["selector"] == "a.link"
        assert deserialized["tag"] == "a"


# ── NetworkActivity ─────────────────────────────────────────────────


class TestNetworkActivity:
    def test_defaults(self):
        na = NetworkActivity()
        assert na.requests_count == 0
        assert na.responses_count == 0
        assert na.failed_count == 0
        assert na.resource_types == {}

    def test_with_values(self):
        na = NetworkActivity(
            requests_count=10,
            responses_count=9,
            failed_count=1,
            resource_types={"script": 5, "image": 3},
        )
        assert na.requests_count == 10
        assert na.failed_count == 1

    def test_to_dict(self):
        na = NetworkActivity(requests_count=3, resource_types={"xhr": 2})
        d = na.to_dict()
        assert d["requests_count"] == 3
        assert d["resource_types"] == {"xhr": 2}
        assert "responses_count" in d
        assert "failed_count" in d

    def test_to_dict_json_serializable(self):
        na = NetworkActivity(requests_count=1)
        serialized = json.dumps(na.to_dict())
        assert '"requests_count": 1' in serialized


# ── StorageState ────────────────────────────────────────────────────


class TestStorageState:
    def test_defaults(self):
        ss = StorageState()
        assert ss.local_storage == {}
        assert ss.session_storage == {}
        assert ss.cookies == []

    def test_with_data(self):
        ss = StorageState(
            local_storage={"theme": "dark"},
            session_storage={"token": "abc"},
            cookies=[{"name": "sid", "value": "x"}],
        )
        assert ss.local_storage["theme"] == "dark"
        assert len(ss.cookies) == 1

    def test_to_dict(self):
        ss = StorageState(
            local_storage={"k": "v"},
            cookies=[{"name": "c"}],
        )
        d = ss.to_dict()
        assert d["local_storage"] == {"k": "v"}
        assert d["session_storage"] == {}
        assert len(d["cookies"]) == 1

    def test_to_dict_round_trip(self):
        ss = StorageState(local_storage={"a": "b"}, session_storage={"c": "d"})
        rt = json.loads(json.dumps(ss.to_dict()))
        assert rt["local_storage"]["a"] == "b"
        assert rt["session_storage"]["c"] == "d"


# ── PageObservation ─────────────────────────────────────────────────


class TestPageObservation:
    @pytest.fixture
    def sample_observation(self):
        return PageObservation(
            url="https://example.com",
            title="Example",
            interactive_elements=[
                InteractiveElement(selector="button#go", tag="button", text="Go"),
            ],
            actionability={"total_elements": 1, "actionable_elements": 1},
            network=NetworkActivity(requests_count=5),
            observed_at=datetime(2026, 1, 1, 12, 0, 0),
        )

    def test_creation(self, sample_observation):
        assert sample_observation.url == "https://example.com"
        assert sample_observation.title == "Example"
        assert len(sample_observation.interactive_elements) == 1
        assert sample_observation.storage is None

    def test_to_dict_no_storage(self, sample_observation):
        d = sample_observation.to_dict()
        assert d["url"] == "https://example.com"
        assert d["title"] == "Example"
        assert len(d["interactive_elements"]) == 1
        assert d["network"]["requests_count"] == 5
        assert "storage" not in d

    def test_to_dict_with_storage(self, sample_observation):
        sample_observation.storage = StorageState(local_storage={"k": "v"})
        d = sample_observation.to_dict()
        assert "storage" in d
        assert d["storage"]["local_storage"] == {"k": "v"}

    def test_to_json_default(self, sample_observation):
        j = sample_observation.to_json()
        parsed = json.loads(j)
        assert parsed["url"] == "https://example.com"

    def test_to_json_pretty(self, sample_observation):
        j = sample_observation.to_json(indent=4)
        assert "\n" in j
        parsed = json.loads(j)
        assert parsed["title"] == "Example"

    def test_observed_at_isoformat(self, sample_observation):
        d = sample_observation.to_dict()
        assert d["observed_at"] == "2026-01-01T12:00:00"


# ── observe_page_mock ───────────────────────────────────────────────


class TestObservePageMock:
    def test_returns_page_observation(self):
        obs = observe_page_mock("https://example.com")
        assert isinstance(obs, PageObservation)

    def test_url_preserved(self):
        obs = observe_page_mock("https://test.org/page")
        assert obs.url == "https://test.org/page"

    def test_title_contains_domain(self):
        obs = observe_page_mock("https://example.com")
        assert "example.com" in obs.title

    def test_title_default_domain(self):
        obs = observe_page_mock("no-scheme")
        assert "example.com" in obs.title

    def test_interactive_elements_count(self):
        obs = observe_page_mock("https://example.com")
        assert len(obs.interactive_elements) == 3

    def test_element_types(self):
        obs = observe_page_mock("https://example.com")
        tags = {el.tag for el in obs.interactive_elements}
        assert "button" in tags
        assert "input" in tags
        assert "a" in tags

    def test_element_actionability(self):
        obs = observe_page_mock("https://example.com")
        for el in obs.interactive_elements:
            assert el.actionability is not None
            assert el.actionability["attached"] is True
            assert el.actionability["visible"] is True
            assert el.actionability["enabled"] is True

    def test_network_activity(self):
        obs = observe_page_mock("https://example.com")
        assert obs.network.requests_count == 12
        assert obs.network.responses_count == 12
        assert obs.network.failed_count == 0
        assert "script" in obs.network.resource_types

    def test_storage_state(self):
        obs = observe_page_mock("https://example.com")
        assert obs.storage is not None
        assert obs.storage.local_storage["theme"] == "dark"
        assert obs.storage.session_storage["session_id"] == "abc123"
        assert len(obs.storage.cookies) == 1

    def test_actionability_summary(self):
        obs = observe_page_mock("https://example.com")
        assert obs.actionability["total_elements"] == 3
        assert obs.actionability["actionable_elements"] == 3
        assert "checks_performed" in obs.actionability

    def test_observed_at_is_recent(self):
        obs = observe_page_mock("https://example.com")
        delta = (datetime.now() - obs.observed_at).total_seconds()
        assert delta < 5

    def test_serialization_round_trip(self):
        obs = observe_page_mock("https://example.com")
        j = obs.to_json()
        parsed = json.loads(j)
        assert parsed["url"] == "https://example.com"
        assert len(parsed["interactive_elements"]) == 3
        assert parsed["network"]["requests_count"] == 12


# ── observe_page entry point ────────────────────────────────────────


class TestObservePage:
    def test_mock_mode(self):
        obs = observe_page("https://example.com", use_cloak=False)
        assert isinstance(obs, PageObservation)
        assert obs.url == "https://example.com"

    @patch("netweaver.observer.observe_page_cloak")
    def test_cloak_mode_delegates(self, mock_cloak):
        mock_cloak.return_value = observe_page_mock("https://example.com")
        obs = observe_page("https://example.com", use_cloak=True)
        mock_cloak.assert_called_once_with(
            "https://example.com", headless=True, timeout=30.0
        )
        assert isinstance(obs, PageObservation)

    @patch("netweaver.observer.observe_page_cloak")
    def test_cloak_passes_params(self, mock_cloak):
        mock_cloak.return_value = observe_page_mock("https://example.com")
        observe_page(
            "https://example.com",
            use_cloak=True,
            headless=False,
            timeout=60.0,
        )
        mock_cloak.assert_called_once_with(
            "https://example.com", headless=False, timeout=60.0
        )


# ── observe_page_cloak fallback ─────────────────────────────────────


class TestObservePageCloakFallback:
    @patch("netweaver.observer.observe_page_cloak")
    def test_cloak_import_error_raises_runtime(self, mock_cloak):
        mock_cloak.side_effect = RuntimeError("browser fail")
        with pytest.raises(RuntimeError, match="browser fail"):
            observe_page("https://example.com", use_cloak=True)


# ── CLI main() ──────────────────────────────────────────────────────


class TestObserverCLI:
    @patch("netweaver.observer.observe_page")
    @patch("sys.argv", ["observer", "https://example.com", "--no-cloak"])
    def test_main_happy_path(self, mock_observe, capsys):
        mock_observe.return_value = observe_page_mock("https://example.com")
        from netweaver.observer import main
        main()
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["url"] == "https://example.com"

    @patch("netweaver.observer.observe_page")
    @patch("sys.argv", ["observer", "https://example.com", "--no-cloak", "--pretty"])
    def test_main_pretty_print(self, mock_observe, capsys):
        mock_observe.return_value = observe_page_mock("https://example.com")
        from netweaver.observer import main
        main()
        captured = capsys.readouterr()
        assert "\n" in captured.out

    @patch("netweaver.observer.observe_page")
    @patch("sys.argv", ["observer", "https://example.com", "--no-cloak"])
    def test_main_error_exits_1(self, mock_observe):
        mock_observe.side_effect = RuntimeError("boom")
        from netweaver.observer import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
