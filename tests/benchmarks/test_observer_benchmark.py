"""Observer Benchmark Tests — NW-003

Acceptance tests for netweaver.observer using mocked page fixtures.
No browser download, no Playwright, no network required.

These tests validate that the observer output matches the Phase 1 JSON spec:
  keys: url, title, interactive_elements, actionability, network

Run: python -m pytest tests/benchmarks/ -v
"""

import json
import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a fixture JSON file."""
    path = FIXTURES_DIR / name
    with open(path) as f:
        return json.load(f)


REQUIRED_KEYS = {"url", "title", "interactive_elements", "actionability", "network"}
ACTIONABILITY_FIELDS = {"attached", "visible", "enabled", "editable", "stable", "pointer_events"}


# ---------------------------------------------------------------------------
# Fixture validation — ensure fixtures themselves are well-formed
# ---------------------------------------------------------------------------

@pytest.fixture(params=[
    "static_page.json",
    "form_page.json",
    "spa_page.json",
    "error_page.json",
    "heavy_page.json",
])
def fixture_name(request):
    return request.param


def test_fixture_is_valid_json(fixture_name):
    """Every fixture file is valid JSON."""
    data = load_fixture(fixture_name)
    assert isinstance(data, dict)
    assert "url" in data
    assert "title" in data
    assert "interactive_elements" in data


def test_fixture_elements_have_actionability(fixture_name):
    """Every interactive element in every fixture has a complete actionability block."""
    data = load_fixture(fixture_name)
    for el in data["interactive_elements"]:
        assert "selector" in el, f"Missing selector in {fixture_name}"
        assert "tag" in el, f"Missing tag in {fixture_name}"
        assert "actionability" in el, f"Missing actionability in {fixture_name} for {el['selector']}"
        act = el["actionability"]
        for field in ACTIONABILITY_FIELDS:
            assert field in act, f"Missing {field} in actionability for {el['selector']} in {fixture_name}"


# ---------------------------------------------------------------------------
# B-001: Static HTML Page — Basic Observation
# ---------------------------------------------------------------------------

def test_b001_static_page_structure():
    """Static page fixture has 3 interactive elements, no network."""
    data = load_fixture("static_page.json")
    assert data["url"] == "https://example.com/static"
    assert data["title"] == "Test Page"
    assert len(data["interactive_elements"]) == 3
    assert len(data["network"]) == 0


def test_b001_element_discovery():
    """Static page elements cover button, link, input."""
    data = load_fixture("static_page.json")
    tags = {el["tag"] for el in data["interactive_elements"]}
    assert "button" in tags
    assert "a" in tags
    assert "input" in tags


def test_b001_all_actionability_true():
    """All static page elements have full actionability."""
    data = load_fixture("static_page.json")
    for el in data["interactive_elements"]:
        act = el["actionability"]
        assert act["attached"] is True
        assert act["visible"] is True
        assert act["enabled"] is True
        assert act["stable"] is True
        assert act["pointer_events"] is True


# ---------------------------------------------------------------------------
# B-002: Form Page — Interactive Element Discovery
# ---------------------------------------------------------------------------

def test_b002_form_element_count():
    """Form page has 5 interactive elements."""
    data = load_fixture("form_page.json")
    assert len(data["interactive_elements"]) == 5


def test_b002_form_roles():
    """Form page has textbox, checkbox, button, link roles."""
    data = load_fixture("form_page.json")
    roles = {el["role"] for el in data["interactive_elements"]}
    assert "textbox" in roles
    assert "checkbox" in roles
    assert "button" in roles
    assert "link" in roles


def test_b002_password_editable():
    """Password input is marked editable."""
    data = load_fixture("form_page.json")
    pw_el = [el for el in data["interactive_elements"] if el["selector"] == "input#password"][0]
    assert pw_el["actionability"]["editable"] is True


def test_b002_button_not_editable():
    """Submit button is not editable."""
    data = load_fixture("form_page.json")
    btn = [el for el in data["interactive_elements"] if el["role"] == "button"][0]
    assert btn["actionability"]["editable"] is False


# ---------------------------------------------------------------------------
# B-003: SPA with Dynamic Content — State Observation
# ---------------------------------------------------------------------------

def test_b003_spa_element_count():
    """SPA fixture has 12 interactive elements (including shadow DOM)."""
    data = load_fixture("spa_page.json")
    assert len(data["interactive_elements"]) == 12


def test_b003_shadow_dom_elements():
    """SPA has 2 shadow DOM elements flagged."""
    data = load_fixture("spa_page.json")
    shadow_els = [el for el in data["interactive_elements"] if el.get("shadow_root")]
    assert len(shadow_els) == 2


def test_b003_hidden_element():
    """SPA has 1 hidden element with visible=false."""
    data = load_fixture("spa_page.json")
    hidden = [el for el in data["interactive_elements"] if not el["actionability"]["visible"]]
    assert len(hidden) == 1
    assert hidden[0]["selector"] == "a[href='/hidden']"


def test_b003_disabled_element():
    """SPA has 1 disabled button."""
    data = load_fixture("spa_page.json")
    disabled = [el for el in data["interactive_elements"] if not el["actionability"]["enabled"]]
    assert len(disabled) == 1
    assert disabled[0]["selector"] == "button#refresh"


def test_b003_network_events():
    """SPA has 2 network events."""
    data = load_fixture("spa_page.json")
    assert len(data["network"]) == 2
    for net in data["network"]:
        assert "url" in net
        assert "method" in net
        assert "status" in net


# ---------------------------------------------------------------------------
# B-004: Error Page — Degraded State Handling
# ---------------------------------------------------------------------------

def test_b004_error_minimal():
    """Error page has 1 interactive element."""
    data = load_fixture("error_page.json")
    assert len(data["interactive_elements"]) == 1
    assert data["title"] == "Not Found"


def test_b004_network_404():
    """Error page network has 404 status."""
    data = load_fixture("error_page.json")
    assert len(data["network"]) == 1
    assert data["network"][0]["status"] == 404


def test_b004_all_keys():
    """Error page fixture still has url, title, interactive_elements, network."""
    data = load_fixture("error_page.json")
    for key in ("url", "title", "interactive_elements", "network"):
        assert key in data, f"Missing key: {key}"
    # actionability is derived from interactive_elements, not a top-level key in fixtures


# ---------------------------------------------------------------------------
# B-005: Heavy Page — Performance Observation
# ---------------------------------------------------------------------------

def test_b005_element_count():
    """Heavy page has 51 interactive elements."""
    data = load_fixture("heavy_page.json")
    assert len(data["interactive_elements"]) == 51


def test_b005_disabled_count():
    """Heavy page has 3 disabled elements."""
    data = load_fixture("heavy_page.json")
    disabled = [el for el in data["interactive_elements"] if not el["actionability"]["enabled"]]
    assert len(disabled) == 3


def test_b005_hidden_count():
    """Heavy page has 4 hidden elements."""
    data = load_fixture("heavy_page.json")
    hidden = [el for el in data["interactive_elements"] if not el["actionability"]["visible"]]
    assert len(hidden) == 4


def test_b005_pointer_events_false():
    """Heavy page has 3 elements with pointer_events=false."""
    data = load_fixture("heavy_page.json")
    no_pointer = [el for el in data["interactive_elements"] if not el["actionability"]["pointer_events"]]
    assert len(no_pointer) == 3


def test_b005_network_count():
    """Heavy page has 10 network entries."""
    data = load_fixture("heavy_page.json")
    assert len(data["network"]) == 10


def test_b005_network_fields():
    """All network entries have url, method, status, type."""
    data = load_fixture("heavy_page.json")
    for net in data["network"]:
        assert "url" in net
        assert "method" in net
        assert "status" in net
        assert "type" in net


# ---------------------------------------------------------------------------
# Scoring helpers (for future observer output validation)
# ---------------------------------------------------------------------------

def score_observation(output: dict, fixture: dict) -> float:
    """Score an observer output against a fixture.

    Returns 0-100 composite score using the NW-003 scoring formula:
      structural_accuracy * 0.3 + element_recall * 0.25 +
      actionability_accuracy * 0.25 + network_capture * 0.2
    """
    # Structural accuracy: all 5 keys present
    structural = sum(1 for k in REQUIRED_KEYS if k in output) / len(REQUIRED_KEYS)

    # Element recall: fraction of fixture elements found
    fixture_selectors = {el["selector"] for el in fixture["interactive_elements"]}
    output_selectors = set()
    for el in output.get("interactive_elements", []):
        if isinstance(el, dict) and "selector" in el:
            output_selectors.add(el["selector"])
    recall = len(fixture_selectors & output_selectors) / len(fixture_selectors) if fixture_selectors else 0.0

    # Actionability accuracy: correct flag values
    correct_flags = 0
    total_flags = 0
    fixture_by_sel = {el["selector"]: el for el in fixture["interactive_elements"]}
    for el in output.get("interactive_elements", []):
        if not isinstance(el, dict):
            continue
        sel = el.get("selector")
        if sel not in fixture_by_sel:
            continue
        expected_act = fixture_by_sel[sel]["actionability"]
        actual_act = el.get("actionability", {})
        if isinstance(actual_act, dict):
            for field in ACTIONABILITY_FIELDS:
                total_flags += 1
                if actual_act.get(field) == expected_act.get(field):
                    correct_flags += 1
    actionability_acc = correct_flags / total_flags if total_flags else 0.0

    # Network capture
    fixture_urls = {(n["url"], n["method"]) for n in fixture.get("network", [])}
    output_urls = set()
    for n in output.get("network", []):
        if isinstance(n, dict) and "url" in n and "method" in n:
            output_urls.add((n["url"], n["method"]))
    network_cap = len(fixture_urls & output_urls) / len(fixture_urls) if fixture_urls else 1.0

    return (structural * 0.3) + (recall * 0.25) + (actionability_acc * 0.25) + (network_cap * 0.2)
