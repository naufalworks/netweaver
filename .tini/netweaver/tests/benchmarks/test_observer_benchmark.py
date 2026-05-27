"""
NW-003 Observer Benchmark Tests

Validates observer output fixtures and provides score_observation() helper
for future observer module validation.

B-001: Static Page  — 3 elements, 0 network
B-002: Form Page    — 5 form elements, editable/password checks
B-003: SPA Page     — 12 elements, shadow DOM, hidden, disabled, 2 network
B-004: Error Page   — 1 element, 404 network, degraded state
B-005: Heavy Page   — 51 elements, 10 network, mixed visibility/state

No browser download required — tests validate fixture integrity only.
"""

import json
import os
import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")
BENCHMARKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "benchmarks")


def load_fixture(name: str) -> dict:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path) as f:
        return json.load(f)


def validate_observer_shape(data: dict) -> list[str]:
    """Validate required top-level keys and structure."""
    errors = []
    required_keys = {"url", "title", "interactive_elements", "actionability", "network"}
    missing = required_keys - set(data.keys())
    if missing:
        errors.append(f"Missing top-level keys: {missing}")

    if "interactive_elements" in data:
        if not isinstance(data["interactive_elements"], list):
            errors.append("interactive_elements must be a list")
        else:
            for i, el in enumerate(data["interactive_elements"]):
                el_errors = validate_element_shape(el, i)
                errors.extend(el_errors)

    if "actionability" in data:
        a = data["actionability"]
        if not isinstance(a, dict):
            errors.append("actionability must be a dict")
        else:
            for k in ["total", "actionable", "blocked"]:
                if k not in a:
                    errors.append(f"actionability missing '{k}'")

    if "network" in data:
        if not isinstance(data["network"], list):
            errors.append("network must be a list")

    return errors


def validate_element_shape(el: dict, idx: int) -> list[str]:
    """Validate a single interactive element structure."""
    errors = []
    required = {"selector", "tag", "actionability"}
    missing = required - set(el.keys())
    if missing:
        errors.append(f"Element {idx}: missing keys {missing}")

    if "actionability" in el:
        a = el["actionability"]
        act_required = {"visible", "enabled", "attached", "stable", "pointer_events"}
        act_missing = act_required - set(a.keys())
        if act_missing:
            errors.append(f"Element {idx}: actionability missing {act_missing}")

    return errors


def score_observation(observation: dict, fixture: dict) -> dict:
    """
    Score an observer output against a fixture.

    Returns dict with:
      - score: 0.0 to 1.0
      - element_recall: fraction of fixture elements found
      - actionability_accuracy: fraction of correct actionability calls
      - network_recall: fraction of network events captured
      - details: per-element breakdown
    """
    fixture_elements = {el["selector"]: el for el in fixture["interactive_elements"]}
    obs_elements = {el["selector"]: el for el in observation.get("interactive_elements", [])}

    # Element recall
    found = set(fixture_elements.keys()) & set(obs_elements.keys())
    element_recall = len(found) / max(len(fixture_elements), 1)

    # Actionability accuracy
    correct_actionability = 0
    total_actionability = 0
    for selector in found:
        f_el = fixture_elements[selector]
        o_el = obs_elements[selector]
        f_act = f_el.get("actionability", {})
        o_act = o_el.get("actionability", {})
        for key in ["visible", "enabled", "attached", "stable", "pointer_events"]:
            if key in f_act:
                total_actionability += 1
                if key in o_act and o_act[key] == f_act[key]:
                    correct_actionability += 1

    actionability_accuracy = correct_actionability / max(total_actionability, 1)

    # Network recall (vacuously 1.0 if fixture has no network events)
    fixture_network = {(n["url"], n["method"]) for n in fixture.get("network", [])}
    obs_network = {(n.get("url"), n.get("method")) for n in observation.get("network", [])}
    network_found = fixture_network & obs_network
    if len(fixture_network) == 0:
        network_recall = 1.0
    else:
        network_recall = len(network_found) / len(fixture_network)

    # Weighted score: 40% element recall, 40% actionability, 20% network
    score = (0.4 * element_recall + 0.4 * actionability_accuracy + 0.2 * network_recall)

    return {
        "score": score,
        "element_recall": element_recall,
        "actionability_accuracy": actionability_accuracy,
        "network_recall": network_recall,
        "elements_found": len(found),
        "elements_total": len(fixture_elements),
    }


# ============================================================
# B-001: Static Page
# ============================================================

class TestB001StaticPage:
    """B-001: 3 elements, 0 network events — simplest case."""

    def test_fixture_loads(self):
        data = load_fixture("static_page.json")
        assert data["url"] == "https://example.com/static"
        assert data["title"] == "Static Page"

    def test_element_count(self):
        data = load_fixture("static_page.json")
        assert len(data["interactive_elements"]) == 3

    def test_all_actionable(self):
        data = load_fixture("static_page.json")
        for el in data["interactive_elements"]:
            a = el["actionability"]
            assert a["visible"] is True
            assert a["enabled"] is True
            assert a["attached"] is True

    def test_no_network(self):
        data = load_fixture("static_page.json")
        assert data["network"] == []
        assert data["actionability"]["blocked"] == 0

    def test_valid_shape(self):
        data = load_fixture("static_page.json")
        errors = validate_observer_shape(data)
        assert errors == []

    def test_actionability_summary_consistent(self):
        data = load_fixture("static_page.json")
        a = data["actionability"]
        assert a["total"] == len(data["interactive_elements"])
        assert a["actionable"] + a["blocked"] == a["total"]

    def test_score_perfect_observation(self):
        data = load_fixture("static_page.json")
        result = score_observation(data, data)
        assert result["score"] == 1.0
        assert result["element_recall"] == 1.0


# ============================================================
# B-002: Form Page
# ============================================================

class TestB002FormPage:
    """B-002: 5 form elements with editable/password checks."""

    def test_fixture_loads(self):
        data = load_fixture("form_page.json")
        assert data["url"] == "https://example.com/form"

    def test_element_count(self):
        data = load_fixture("form_page.json")
        assert len(data["interactive_elements"]) == 5

    def test_editable_fields(self):
        data = load_fixture("form_page.json")
        editable = [el for el in data["interactive_elements"]
                    if el["actionability"].get("editable") is True]
        # input, textarea, select are editable
        assert len(editable) == 4  # username, password, comment, country

    def test_password_field(self):
        data = load_fixture("form_page.json")
        pwd = [el for el in data["interactive_elements"]
               if el["actionability"].get("password") is True]
        assert len(pwd) == 1

    def test_all_actionable(self):
        data = load_fixture("form_page.json")
        assert data["actionability"]["blocked"] == 0
        assert data["actionability"]["actionable"] == 5

    def test_valid_shape(self):
        data = load_fixture("form_page.json")
        errors = validate_observer_shape(data)
        assert errors == []

    def test_score_perfect_observation(self):
        data = load_fixture("form_page.json")
        result = score_observation(data, data)
        assert result["score"] == 1.0


# ============================================================
# B-003: SPA Page
# ============================================================

class TestB003SPAPage:
    """B-003: 12 elements, shadow DOM, hidden, disabled, 2 network events."""

    def test_fixture_loads(self):
        data = load_fixture("spa_page.json")
        assert data["url"] == "https://example.com/spa"

    def test_element_count(self):
        data = load_fixture("spa_page.json")
        assert len(data["interactive_elements"]) == 12

    def test_hidden_elements(self):
        data = load_fixture("spa_page.json")
        hidden = [el for el in data["interactive_elements"]
                  if el["actionability"]["visible"] is False]
        assert len(hidden) >= 1

    def test_disabled_elements(self):
        data = load_fixture("spa_page.json")
        disabled = [el for el in data["interactive_elements"]
                    if el["actionability"]["enabled"] is False]
        assert len(disabled) >= 1

    def test_network_events(self):
        data = load_fixture("spa_page.json")
        assert len(data["network"]) == 2
        statuses = [n["status"] for n in data["network"]]
        assert 200 in statuses
        assert 401 in statuses

    def test_shadow_dom_element(self):
        data = load_fixture("spa_page.json")
        shadow = [el for el in data["interactive_elements"]
                  if "shadow" in el["selector"]]
        assert len(shadow) >= 1

    def test_blocked_count(self):
        data = load_fixture("spa_page.json")
        assert data["actionability"]["blocked"] == 3  # 1 hidden + 2 disabled

    def test_valid_shape(self):
        data = load_fixture("spa_page.json")
        errors = validate_observer_shape(data)
        assert errors == []

    def test_score_perfect_observation(self):
        data = load_fixture("spa_page.json")
        result = score_observation(data, data)
        assert result["score"] == 1.0


# ============================================================
# B-004: Error Page
# ============================================================

class TestB004ErrorPage:
    """B-004: 1 element, 404 network response, degraded state."""

    def test_fixture_loads(self):
        data = load_fixture("error_page.json")
        assert data["title"] == "404 Not Found"

    def test_minimal_elements(self):
        data = load_fixture("error_page.json")
        assert len(data["interactive_elements"]) == 1

    def test_network_error(self):
        data = load_fixture("error_page.json")
        assert len(data["network"]) == 1
        assert data["network"][0]["status"] == 404

    def test_element_still_actionable(self):
        data = load_fixture("error_page.json")
        el = data["interactive_elements"][0]
        assert el["actionability"]["visible"] is True
        assert el["actionability"]["enabled"] is True

    def test_valid_shape(self):
        data = load_fixture("error_page.json")
        errors = validate_observer_shape(data)
        assert errors == []

    def test_score_perfect_observation(self):
        data = load_fixture("error_page.json")
        result = score_observation(data, data)
        assert result["score"] == 1.0


# ============================================================
# B-005: Heavy Page
# ============================================================

class TestB005HeavyPage:
    """B-005: 51 elements, 10 network events, mixed visibility/state."""

    def test_fixture_loads(self):
        data = load_fixture("heavy_page.json")
        assert data["url"] == "https://example.com/heavy"

    def test_element_count(self):
        data = load_fixture("heavy_page.json")
        assert len(data["interactive_elements"]) == 51

    def test_network_event_count(self):
        data = load_fixture("heavy_page.json")
        assert len(data["network"]) == 10

    def test_mixed_visibility(self):
        data = load_fixture("heavy_page.json")
        hidden = [el for el in data["interactive_elements"]
                  if el["actionability"]["visible"] is False]
        assert len(hidden) == 4

    def test_mixed_enabled(self):
        data = load_fixture("heavy_page.json")
        disabled = [el for el in data["interactive_elements"]
                    if el["actionability"]["enabled"] is False]
        assert len(disabled) == 3

    def test_pointer_events_off(self):
        data = load_fixture("heavy_page.json")
        no_pointer = [el for el in data["interactive_elements"]
                      if el["actionability"]["pointer_events"] is False]
        assert len(no_pointer) == 3

    def test_blocked_count(self):
        data = load_fixture("heavy_page.json")
        # 4 hidden + 3 disabled + 3 no-pointer (no overlaps) = 10 blocked
        assert data["actionability"]["blocked"] == 10
        assert data["actionability"]["actionable"] == 41
        assert data["actionability"]["total"] == 51

    def test_valid_shape(self):
        data = load_fixture("heavy_page.json")
        errors = validate_observer_shape(data)
        assert errors == []

    def test_score_perfect_observation(self):
        data = load_fixture("heavy_page.json")
        result = score_observation(data, data)
        assert result["score"] == 1.0

    def test_network_error_event(self):
        data = load_fixture("heavy_page.json")
        errors = [n for n in data["network"] if n["status"] >= 400]
        assert len(errors) >= 1


# ============================================================
# Score Helper Tests
# ============================================================

class TestScoreObservation:
    """Tests for the score_observation() helper."""

    def test_perfect_score(self):
        data = load_fixture("static_page.json")
        result = score_observation(data, data)
        assert result["score"] == 1.0

    def test_missing_elements(self):
        fixture = load_fixture("static_page.json")
        obs = {"interactive_elements": [], "network": []}
        result = score_observation(obs, fixture)
        assert result["element_recall"] == 0.0
        assert result["score"] < 0.5

    def test_half_elements(self):
        fixture = load_fixture("static_page.json")
        obs = {
            "interactive_elements": fixture["interactive_elements"][:1],
            "network": []
        }
        result = score_observation(obs, fixture)
        assert 0.0 < result["element_recall"] < 1.0

    def test_wrong_actionability(self):
        fixture = load_fixture("static_page.json")
        obs = json.loads(json.dumps(fixture))
        obs["interactive_elements"][0]["actionability"]["visible"] = False
        result = score_observation(obs, fixture)
        assert result["actionability_accuracy"] < 1.0

    def test_missing_network(self):
        fixture = load_fixture("spa_page.json")
        obs = json.loads(json.dumps(fixture))
        obs["network"] = []
        result = score_observation(obs, fixture)
        assert result["network_recall"] == 0.0
        assert result["score"] < 1.0

    def test_empty_fixture(self):
        result = score_observation({}, {"interactive_elements": [], "network": []})
        # No elements to find → perfect recall (vacuously true / 0 elements)
        assert result["element_recall"] == 1.0 or result["elements_total"] == 0
