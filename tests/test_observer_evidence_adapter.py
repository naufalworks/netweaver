"""Tests for observer → evidence adapter.

Validates that PageObservation output from the observer is correctly
converted into EvidenceReport with proper observations, claims, and
verification. All tests use mocked observer output — no browser required.

P2-003: Added bridge→adapter integration tests and evidence chain
integrity tests using CloakBrowserBridge with mock SDK.
"""

import json
from datetime import datetime
from unittest.mock import MagicMock

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    StorageState,
    observe_page_mock,
)
from netweaver.evidence import (
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
)
from netweaver.observer_evidence_adapter import (
    element_to_actionability_observation,
    element_to_dom_observation,
    get_actionable_selectors,
    get_network_health,
    network_to_observation,
    observation_to_report,
    storage_to_observation,
)
from netweaver.cloak_bridge import CloakBrowserBridge


# --- Fixtures ---

def _make_element(
    selector="button#submit",
    tag="button",
    type_="submit",
    text="Submit",
    aria_label="Submit form",
    actionability=None,
) -> InteractiveElement:
    """Helper to create test interactive elements."""
    if actionability is None:
        actionability = {
            "attached": True,
            "visible": True,
            "enabled": True,
            "editable": False,
            "stable": True,
            "pointer_events": True,
        }
    return InteractiveElement(
        selector=selector,
        tag=tag,
        type=type_,
        text=text,
        aria_label=aria_label,
        actionability=actionability,
    )


def _make_network(
    requests=12,
    responses=12,
    failed=0,
    resource_types=None,
) -> NetworkActivity:
    """Helper to create test network activity."""
    if resource_types is None:
        resource_types = {"document": 1, "script": 5, "image": 2}
    return NetworkActivity(
        requests_count=requests,
        responses_count=responses,
        failed_count=failed,
        resource_types=resource_types,
    )


def _make_observation(elements=None, network=None, url="https://example.com"):
    """Helper to create a test PageObservation."""
    if elements is None:
        elements = [_make_element()]
    if network is None:
        network = _make_network()
    return PageObservation(
        url=url,
        title="Test Page",
        interactive_elements=elements,
        actionability={"total_elements": len(elements)},
        network=network,
        observed_at=datetime.now(),
    )


# --- Unit tests: element converters ---

class TestElementToDomObservation:
    def test_creates_dom_observation(self):
        el = _make_element()
        obs = element_to_dom_observation(el)
        assert obs.evidence_type == EvidenceType.DOM
        assert obs.data["selector"] == "button#submit"
        assert obs.data["tag"] == "button"
        assert obs.data["type"] == "submit"
        assert obs.data["text"] == "Submit"
        assert obs.data["aria_label"] == "Submit form"
        assert obs.source == "observer"

    def test_unique_observation_ids(self):
        el = _make_element()
        obs1 = element_to_dom_observation(el)
        obs2 = element_to_dom_observation(el)
        assert obs1.observation_id != obs2.observation_id

    def test_custom_source(self):
        el = _make_element()
        obs = element_to_dom_observation(el, source="custom")
        assert obs.source == "custom"

    def test_optional_fields_none(self):
        el = InteractiveElement(selector="div.box", tag="div")
        obs = element_to_dom_observation(el)
        assert obs.data["type"] is None
        assert obs.data["text"] is None
        assert obs.data["aria_label"] is None


class TestElementToActionabilityObservation:
    def test_creates_actionability_observation(self):
        el = _make_element()
        obs = element_to_actionability_observation(el)
        assert obs.evidence_type == EvidenceType.ACTIONABILITY
        assert obs.data["selector"] == "button#submit"
        assert obs.data["attached"] is True
        assert obs.data["visible"] is True
        assert obs.data["enabled"] is True

    def test_no_actionability_data(self):
        el = InteractiveElement(selector="div.box", tag="div")
        obs = element_to_actionability_observation(el)
        assert obs.evidence_type == EvidenceType.ACTIONABILITY
        assert obs.data["selector"] == "div.box"
        # Should have empty dict spread
        assert "attached" not in obs.data

    def test_partial_actionability(self):
        el = _make_element(
            actionability={"attached": True, "visible": False}
        )
        obs = element_to_actionability_observation(el)
        assert obs.data["attached"] is True
        assert obs.data["visible"] is False
        assert "enabled" not in obs.data


class TestNetworkToObservation:
    def test_creates_network_observation(self):
        net = _make_network()
        obs = network_to_observation(net)
        assert obs.evidence_type == EvidenceType.NETWORK
        assert obs.data["requests_count"] == 12
        assert obs.data["responses_count"] == 12
        assert obs.data["failed_count"] == 0
        assert obs.data["resource_types"] == {"document": 1, "script": 5, "image": 2}

    def test_network_with_failures(self):
        net = _make_network(failed=3)
        obs = network_to_observation(net)
        assert obs.data["failed_count"] == 3


# --- Integration tests: full report conversion ---

class TestObservationToReport:
    def test_basic_report_creation(self):
        page_obs = _make_observation()
        report = observation_to_report(page_obs)
        assert isinstance(report, EvidenceReport)
        assert report.url == "https://example.com"
        assert len(report.observations) > 0
        assert len(report.claims) > 0

    def test_report_verifies_successfully(self):
        page_obs = _make_observation()
        report = observation_to_report(page_obs)
        assert report.verify() is True

    def test_custom_report_id(self):
        page_obs = _make_observation()
        report = observation_to_report(page_obs, report_id="my-report")
        assert report.report_id == "my-report"

    def test_auto_report_id(self):
        page_obs = _make_observation()
        report = observation_to_report(page_obs)
        assert report.report_id.startswith("rpt-")

    def test_single_element_creates_correct_observations(self):
        page_obs = _make_observation(elements=[_make_element()])
        report = observation_to_report(page_obs)
        # 1 element → 1 DOM obs + 1 actionability obs + 1 network obs = 3
        assert len(report.observations) == 3
        dom_obs = report.get_observations_by_type(EvidenceType.DOM)
        act_obs = report.get_observations_by_type(EvidenceType.ACTIONABILITY)
        net_obs = report.get_observations_by_type(EvidenceType.NETWORK)
        assert len(dom_obs) == 1
        assert len(act_obs) == 1
        assert len(net_obs) == 1

    def test_multiple_elements(self):
        elements = [
            _make_element(selector=f"button#{i}", text=f"Btn {i}")
            for i in range(5)
        ]
        page_obs = _make_observation(elements=elements)
        report = observation_to_report(page_obs)
        # 5 elements × 2 (DOM + act) + 1 network = 11 observations
        assert len(report.observations) == 11
        assert len(report.get_observations_by_type(EvidenceType.DOM)) == 5
        assert len(report.get_observations_by_type(EvidenceType.ACTIONABILITY)) == 5

    def test_claims_link_to_observations(self):
        page_obs = _make_observation()
        report = observation_to_report(page_obs)
        obs_ids = {obs.observation_id for obs in report.observations}
        for claim in report.claims:
            for oid in claim.observation_ids:
                assert oid in obs_ids, f"Claim {claim.claim_id} references missing obs {oid}"

    def test_element_exists_claims(self):
        page_obs = _make_observation(elements=[_make_element(selector="input#email")])
        report = observation_to_report(page_obs)
        exists_claims = [c for c in report.claims if "exists in DOM" in c.description]
        assert len(exists_claims) == 1
        assert "input#email" in exists_claims[0].description

    def test_actionability_claims(self):
        page_obs = _make_observation(elements=[_make_element(selector="button#go")])
        report = observation_to_report(page_obs)
        act_claims = [c for c in report.claims if "actionable" in c.description.lower()]
        assert len(act_claims) == 1
        assert "actionable" in act_claims[0].description.lower()

    def test_not_actionable_claim(self):
        el = _make_element(
            selector="button#disabled",
            actionability={"attached": True, "visible": True, "enabled": False, "stable": True},
        )
        page_obs = _make_observation(elements=[el])
        report = observation_to_report(page_obs)
        act_claims = [c for c in report.claims if "actionable" in c.description.lower()]
        assert len(act_claims) == 1
        assert "not actionable" in act_claims[0].description.lower()

    def test_network_health_claim_healthy(self):
        page_obs = _make_observation(network=_make_network(failed=0))
        report = observation_to_report(page_obs)
        net_claims = [c for c in report.claims if "Network" in c.description]
        assert len(net_claims) == 1
        assert "healthy" in net_claims[0].description

    def test_network_health_claim_degraded(self):
        page_obs = _make_observation(network=_make_network(failed=3))
        report = observation_to_report(page_obs)
        net_claims = [c for c in report.claims if "Network" in c.description]
        assert len(net_claims) == 1
        assert "degraded" in net_claims[0].description

    def test_page_level_claim_with_elements(self):
        page_obs = _make_observation()
        report = observation_to_report(page_obs)
        page_claims = [c for c in report.claims if "Page" in c.description]
        assert len(page_claims) == 1
        assert "Test Page" in page_claims[0].description

    def test_no_page_level_claim_without_elements(self):
        page_obs = _make_observation(elements=[])
        report = observation_to_report(page_obs)
        page_claims = [c for c in report.claims if "Page" in c.description]
        assert len(page_claims) == 0

    def test_element_without_actionability_no_act_claim(self):
        el = InteractiveElement(selector="div.box", tag="div")
        page_obs = _make_observation(elements=[el])
        report = observation_to_report(page_obs)
        act_claims = [c for c in report.claims if "actionable" in c.description.lower()]
        assert len(act_claims) == 0

    def test_serialization_roundtrip(self):
        page_obs = _make_observation()
        report = observation_to_report(page_obs)
        data = report.to_dict()
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        restored = EvidenceReport.from_dict(parsed)
        assert restored.report_id == report.report_id
        assert restored.url == report.url
        assert len(restored.observations) == len(report.observations)
        assert len(restored.claims) == len(report.claims)


# --- Tests with mock observer ---

class TestWithMockObserver:
    def test_mock_observer_to_report(self):
        """Full pipeline: mock observer → evidence report."""
        page_obs = observe_page_mock("https://example.com")
        report = observation_to_report(page_obs)
        assert report.verify() is True
        assert report.url == "https://example.com"
        # Mock returns 3 elements
        assert len(page_obs.interactive_elements) == 3
        # 3 DOM + 3 actionability + 1 network + 1 storage = 8 observations
        assert len(report.observations) == 8

    def test_mock_observer_claim_count(self):
        page_obs = observe_page_mock("https://example.com")
        report = observation_to_report(page_obs)
        # 3 elements × 2 (exists + actionable) + 1 network + 1 storage + 1 page = 9
        assert len(report.claims) == 9

    def test_mock_observer_all_claims_supported(self):
        page_obs = observe_page_mock("https://example.com")
        report = observation_to_report(page_obs)
        unsupported = report.get_unsupported_claims()
        assert len(unsupported) == 0


# --- Utility function tests ---

class TestGetActionableSelectors:
    def test_returns_actionable_selectors(self):
        page_obs = _make_observation(elements=[
            _make_element(selector="button#ok"),
            _make_element(selector="input#name"),
        ])
        report = observation_to_report(page_obs)
        selectors = get_actionable_selectors(report)
        assert "button#ok" in selectors
        assert "input#name" in selectors

    def test_excludes_disabled(self):
        el = _make_element(
            selector="button#disabled",
            actionability={"attached": True, "visible": True, "enabled": False, "stable": True},
        )
        page_obs = _make_observation(elements=[el])
        report = observation_to_report(page_obs)
        selectors = get_actionable_selectors(report)
        assert "button#disabled" not in selectors

    def test_excludes_invisible(self):
        el = _make_element(
            selector="button#hidden",
            actionability={"attached": True, "visible": False, "enabled": True, "stable": True},
        )
        page_obs = _make_observation(elements=[el])
        report = observation_to_report(page_obs)
        selectors = get_actionable_selectors(report)
        assert "button#hidden" not in selectors

    def test_empty_report(self):
        page_obs = _make_observation(elements=[])
        report = observation_to_report(page_obs)
        selectors = get_actionable_selectors(report)
        assert selectors == []


class TestGetNetworkHealth:
    def test_healthy_network(self):
        page_obs = _make_observation(network=_make_network(failed=0))
        report = observation_to_report(page_obs)
        health = get_network_health(report)
        assert health["healthy"] is True
        assert health["requests_count"] == 12
        assert health["failed_count"] == 0

    def test_degraded_network(self):
        page_obs = _make_observation(network=_make_network(failed=2))
        report = observation_to_report(page_obs)
        health = get_network_health(report)
        assert health["healthy"] is False
        assert health["failed_count"] == 2

    def test_no_network_observations(self):
        report = EvidenceReport(
            report_id="test",
            url="https://example.com",
            timestamp=datetime.now(),
        )
        health = get_network_health(report)
        assert health["healthy"] is False
        assert "error" in health


# --- P2-003: Storage observation tests ---

class TestStorageToObservation:
    """Test storage_to_observation converter."""

    def test_creates_storage_observation(self):
        storage = StorageState(
            local_storage={"theme": "dark"},
            session_storage={"sid": "abc"},
            cookies=[{"name": "c1", "value": "v1"}],
        )
        obs = storage_to_observation(storage)
        assert obs.evidence_type == EvidenceType.STORAGE
        assert obs.data["local_storage"] == {"theme": "dark"}
        assert obs.data["session_storage"] == {"sid": "abc"}
        assert obs.data["cookies"] == [{"name": "c1", "value": "v1"}]
        assert obs.data["local_keys"] == ["theme"]
        assert obs.data["session_keys"] == ["sid"]
        assert obs.data["cookie_count"] == 1

    def test_empty_storage(self):
        storage = StorageState()
        obs = storage_to_observation(storage)
        assert obs.evidence_type == EvidenceType.STORAGE
        assert obs.data["local_keys"] == []
        assert obs.data["cookie_count"] == 0

    def test_custom_source(self):
        storage = StorageState()
        obs = storage_to_observation(storage, source="real-browser")
        assert obs.source == "real-browser"


class TestObservationToReportWithStorage:
    """Test that observation_to_report handles storage evidence."""

    def test_with_storage_data(self):
        storage = StorageState(
            local_storage={"key": "val"},
            session_storage={},
            cookies=[{"name": "c", "value": "v"}],
        )
        page_obs = _make_observation()
        page_obs.storage = storage
        report = observation_to_report(page_obs)

        store_obs = report.get_observations_by_type(EvidenceType.STORAGE)
        assert len(store_obs) == 1
        store_claims = report.get_claims_by_type(EvidenceType.STORAGE)
        assert len(store_claims) == 1
        assert "localStorage keys" in store_claims[0].description

    def test_without_storage_backward_compat(self):
        """PageObservation without storage (backward compat) still works."""
        page_obs = _make_observation()
        page_obs.storage = None
        report = observation_to_report(page_obs)
        store_obs = report.get_observations_by_type(EvidenceType.STORAGE)
        assert len(store_obs) == 0
        assert report.verify() is True


# --- P2-003: Bridge → Adapter integration tests ---

class _MockBrowserFactory:
    """Helper to create mock CloakBrowser SDK objects for bridge tests."""

    @staticmethod
    def make_locator(tag="button", text="Click", type_=None, aria_label=None,
                     visible=True, enabled=True, editable=False):
        loc = MagicMock()
        loc.evaluate.return_value = tag
        loc.get_attribute.side_effect = lambda attr: {
            "type": type_, "aria-label": aria_label,
        }.get(attr)
        loc.inner_text.return_value = text
        loc.is_visible.return_value = visible
        loc.is_enabled.return_value = enabled
        loc.is_editable.return_value = editable
        return loc

    @staticmethod
    def make_page(title="Test Page", url="https://example.com",
                  locators=None, local_storage=None, session_storage=None,
                  cookies=""):
        page = MagicMock()
        page.title.return_value = title
        page.url = url

        if locators is None:
            locators = {
                "button": [_MockBrowserFactory.make_locator()],
                "a[href]": [_MockBrowserFactory.make_locator(
                    tag="a", text="Link", type_=None)],
                "input": [_MockBrowserFactory.make_locator(
                    tag="input", text=None, type_="email",
                    aria_label="Email", editable=True)],
            }

        def locator_side_effect(selector):
            mock_loc = MagicMock()
            mock_loc.all.return_value = locators.get(selector, [])
            return mock_loc

        page.locator.side_effect = locator_side_effect

        _ls = local_storage if local_storage is not None else {"theme": "dark", "lang": "en"}
        _ss = session_storage if session_storage is not None else {"sid": "abc123"}
        _cookies = cookies if cookies is not None else "session=x; user=test"

        def evaluate_side_effect(script):
            if "localStorage" in script:
                return _ls
            elif "sessionStorage" in script:
                return _ss
            elif "document.cookie" in script:
                return _cookies
            return None

        page.evaluate.side_effect = evaluate_side_effect
        return page

    @staticmethod
    def make_browser(page=None):
        if page is None:
            page = _MockBrowserFactory.make_page()
        browser = MagicMock()
        browser.new_page.return_value = page
        return browser


class TestBridgeToAdapter:
    """Integration: CloakBrowserBridge → observation_to_report pipeline.

    Uses mock SDK (P2-001 pattern) to produce a PageObservation via the
    bridge, then pipes it through the adapter to produce an EvidenceReport.
    This is the exact pipeline a real observation would follow.
    """

    def test_bridge_observation_produces_verified_report(self):
        """Bridge output → adapter → verified EvidenceReport."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        assert isinstance(report, EvidenceReport)
        assert report.verify() is True
        assert len(report.get_unsupported_claims()) == 0

    def test_bridge_report_has_all_evidence_types(self):
        """Report from bridge observation has DOM, actionability, network, storage."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        dom_obs = report.get_observations_by_type(EvidenceType.DOM)
        act_obs = report.get_observations_by_type(EvidenceType.ACTIONABILITY)
        net_obs = report.get_observations_by_type(EvidenceType.NETWORK)
        store_obs = report.get_observations_by_type(EvidenceType.STORAGE)

        assert len(dom_obs) == 3  # button, a, input
        assert len(act_obs) == 3
        assert len(net_obs) == 1
        assert len(store_obs) == 1

    def test_bridge_report_element_claims(self):
        """Each element gets an exists claim + actionability claim."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        exists_claims = [c for c in report.claims if "exists in DOM" in c.description]
        act_claims = [c for c in report.claims if "actionable" in c.description.lower()
                      and "exists" not in c.description.lower()]
        assert len(exists_claims) == 3
        assert len(act_claims) == 3

    def test_bridge_report_network_claim(self):
        """Network observation produces a health claim."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        net_claims = [c for c in report.claims if "Network" in c.description]
        assert len(net_claims) == 1

    def test_bridge_report_storage_claim(self):
        """Storage observation produces a storage snapshot claim."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        store_claims = [c for c in report.claims
                        if "storage snapshot" in c.description.lower()]
        assert len(store_claims) == 1
        assert "localStorage" in store_claims[0].description

    def test_bridge_report_page_claim(self):
        """Page-level claim references title and URL."""
        page = _MockBrowserFactory.make_page(title="My App", url="https://app.com")
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://app.com")
        report = observation_to_report(obs)

        page_claims = [c for c in report.claims if "Page" in c.description]
        assert len(page_claims) == 1
        assert "My App" in page_claims[0].description

    def test_bridge_report_actionable_selectors(self):
        """get_actionable_selectors works on bridge output."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)
        selectors = get_actionable_selectors(report)

        assert len(selectors) == 3  # all visible+enabled

    def test_bridge_report_serialization_roundtrip(self):
        """Report from bridge output survives serialization."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        data = report.to_dict()
        restored = EvidenceReport.from_dict(data)
        assert restored.report_id == report.report_id
        assert len(restored.observations) == len(report.observations)
        assert len(restored.claims) == len(report.claims)

    def test_bridge_with_disabled_element(self):
        """Disabled element → 'not actionable' claim."""
        locators = {
            "button": [
                _MockBrowserFactory.make_locator(tag="button", text="OK", visible=True, enabled=True),
                _MockBrowserFactory.make_locator(tag="button", text="Disabled", visible=True, enabled=False),
            ],
        }
        page = _MockBrowserFactory.make_page(locators=locators)
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        not_act = [c for c in report.claims if "not actionable" in c.description.lower()]
        assert len(not_act) == 1
        assert "Disabled" not in not_act[0].description  # selector, not text

    def test_bridge_with_no_elements(self):
        """Empty page → no element claims, but network/storage claims remain."""
        page = _MockBrowserFactory.make_page(locators={})
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://empty.example.com")
        report = observation_to_report(obs)

        assert report.verify() is True
        exists_claims = [c for c in report.claims if "exists in DOM" in c.description]
        assert len(exists_claims) == 0
        net_claims = [c for c in report.claims if "Network" in c.description]
        assert len(net_claims) == 1


# --- P2-003: Evidence chain integrity tests ---

class TestEvidenceChainIntegrity:
    """Verify evidence chain integrity: every claim backed by observations.

    These tests use real-browser-shaped data (from bridge mock SDK) to ensure
    the evidence chain holds under realistic conditions.
    """

    def test_all_claim_observation_ids_exist(self):
        """Every observation_id referenced by a claim exists in report."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        obs_ids = {o.observation_id for o in report.observations}
        for claim in report.claims:
            for oid in claim.observation_ids:
                assert oid in obs_ids, (
                    f"Claim {claim.claim_id} references obs {oid} not in report"
                )

    def test_no_orphan_observations(self):
        """Every observation is referenced by at least one claim."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        referenced_ids = set()
        for claim in report.claims:
            referenced_ids.update(claim.observation_ids)

        for observation in report.observations:
            assert observation.observation_id in referenced_ids, (
                f"Observation {observation.observation_id} not referenced by any claim"
            )

    def test_verify_sets_all_statuses(self):
        """After verify(), all claims have SUPPORTED status."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)
        result = report.verify()

        assert result is True
        for claim in report.claims:
            assert claim.status == ClaimStatus.SUPPORTED

    def test_evidence_types_cover_bridge_output(self):
        """Report has all 4 evidence types when bridge provides full data."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        types_with_observations = {
            o.evidence_type for o in report.observations
        }
        assert EvidenceType.DOM in types_with_observations
        assert EvidenceType.ACTIONABILITY in types_with_observations
        assert EvidenceType.NETWORK in types_with_observations
        assert EvidenceType.STORAGE in types_with_observations

    def test_bridge_with_degraded_network(self):
        """Degraded network → network claim says 'degraded', chain still valid."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)

        # Intercept callbacks to simulate failures
        callbacks = {}
        original_on = page.on
        def capture_on(event, cb):
            callbacks[event] = cb
        page.on.side_effect = capture_on

        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)
        obs = bridge.observe("https://example.com")

        # Manually fire some failed responses before running adapter
        # (since bridge's network tracker only captures during observe)
        # Instead: directly construct observation with degraded network
        obs.network = NetworkActivity(
            requests_count=10, responses_count=10, failed_count=3,
            resource_types={"script": 5, "xhr": 5},
        )

        report = observation_to_report(obs)
        assert report.verify() is True

        net_claims = [c for c in report.claims if "Network" in c.description]
        assert "degraded" in net_claims[0].description

    def test_bridge_with_empty_storage(self):
        """Empty storage → storage claim says 0 keys, chain still valid."""
        page = _MockBrowserFactory.make_page(
            local_storage={}, session_storage={}, cookies=""
        )
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        assert report.verify() is True
        store_claims = [c for c in report.claims if "storage" in c.description.lower()]
        assert len(store_claims) == 1
        assert "0 localStorage" in store_claims[0].description

    def test_mixed_actionable_and_disabled_elements(self):
        """Mixed elements → correct actionable/not-actionable claims."""
        locators = {
            "button": [
                _MockBrowserFactory.make_locator(text="OK", visible=True, enabled=True),
                _MockBrowserFactory.make_locator(text="Off", visible=False, enabled=True),
                _MockBrowserFactory.make_locator(text="Lock", visible=True, enabled=False),
            ],
        }
        page = _MockBrowserFactory.make_page(locators=locators)
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)

        assert report.verify() is True
        act_claims = [c for c in report.claims if "actionable" in c.description.lower()]
        assert len(act_claims) == 3
        actionable = [c for c in act_claims if "not actionable" not in c.description.lower()]
        not_actionable = [c for c in act_claims if "not actionable" in c.description.lower()]
        assert len(actionable) == 1
        assert len(not_actionable) == 2

    def test_get_network_health_from_bridge(self):
        """get_network_health works on bridge-derived report."""
        page = _MockBrowserFactory.make_page()
        browser = _MockBrowserFactory.make_browser(page)
        bridge = CloakBrowserBridge(browser_factory=lambda **kw: browser)

        obs = bridge.observe("https://example.com")
        report = observation_to_report(obs)
        health = get_network_health(report)

        assert health["healthy"] is True
        assert isinstance(health["requests_count"], int)
