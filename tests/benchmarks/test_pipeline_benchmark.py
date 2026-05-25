"""Full Pipeline Benchmark Tests — NW-011

Integration benchmark: Observer → Evidence → Perspective → Executor pipeline.
Tests that the complete NetWeaver stack produces consistent, verifiable output
when modules are chained together.

No browser download, no Playwright, no network required.

Run: python -m pytest tests/benchmarks/test_pipeline_benchmark.py -v
"""

import json
import pytest
from datetime import datetime
from pathlib import Path

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
)
from netweaver.observer_evidence_adapter import (
    element_to_actionability_observation,
    element_to_dom_observation,
    get_actionable_selectors,
    network_to_observation,
    observation_to_report,
)
from netweaver.evidence import EvidenceReport, EvidenceType
from netweaver.perspective import PerspectiveEngine, ResolutionStrategy
from netweaver.wnal import (
    ActionabilityEvidence,
    ClickAction,
    Phase,
)
from netweaver.executor import (
    ExecutionStatus,
    VerifiedExecutor,
)


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


def fixture_to_observation(fixture: dict) -> PageObservation:
    """Convert a fixture dict to a PageObservation (mock observer output)."""
    elements = []
    for el in fixture.get("interactive_elements", []):
        act = el.get("actionability", {})
        elements.append(InteractiveElement(
            selector=el["selector"],
            tag=el["tag"],
            type=el.get("type"),
            text=el.get("text"),
            aria_label=el.get("aria_label"),
            actionability=act,
        ))
    network = NetworkActivity()
    return PageObservation(
        url=fixture["url"],
        title=fixture["title"],
        interactive_elements=elements,
        actionability={
            "total_elements": len(elements),
            "actionable_elements": sum(
                1 for e in elements
                if e.actionability and e.actionability.get("enabled")
            ),
        },
        network=network,
        observed_at=datetime.now(),
    )


def fixture_element_to_wnal_evidence(el: dict, action_id: str) -> ActionabilityEvidence:
    """Convert fixture element actionability to WNAL ActionabilityEvidence."""
    act = el.get("actionability", {})
    return ActionabilityEvidence(
        action_id=action_id,
        target_ref=el["selector"],
        phase=Phase.PRE,
        attached=act.get("attached", True),
        visible=act.get("visible", True),
        enabled=act.get("enabled", True),
        editable=act.get("editable", False),
        stable=act.get("stable", True),
        pointer_events=act.get("pointer_events", True),
        observed_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# P-001: Observe → Evidence Report
# ---------------------------------------------------------------------------

class TestP001ObserveToEvidence:
    """P-001: Feed fixture through observer, convert to evidence report."""

    def test_report_verifies(self):
        fixture = load_fixture("static_page.json")
        observation = fixture_to_observation(fixture)
        report = observation_to_report(observation)
        assert report.verify()

    def test_element_to_dom_observation_coverage(self):
        fixture = load_fixture("static_page.json")
        observation = fixture_to_observation(fixture)
        report = observation_to_report(observation)
        dom_obs = [o for o in report.observations if o.evidence_type == EvidenceType.DOM]
        assert len(dom_obs) == len(fixture["interactive_elements"])

    def test_actionability_observation_coverage(self):
        fixture = load_fixture("static_page.json")
        observation = fixture_to_observation(fixture)
        report = observation_to_report(observation)
        act_obs = [o for o in report.observations if o.evidence_type == EvidenceType.ACTIONABILITY]
        assert len(act_obs) == len(fixture["interactive_elements"])

    def test_summary_counts_match(self):
        fixture = load_fixture("form_page.json")
        observation = fixture_to_observation(fixture)
        report = observation_to_report(observation)
        # Report should have claims proportional to elements
        assert len(report.claims) >= len(fixture["interactive_elements"])


# ---------------------------------------------------------------------------
# P-002: Observe → Evidence → Perspective Analysis
# ---------------------------------------------------------------------------

class TestP002PerspectiveIntegration:
    """P-002: Feed fixture through observer → evidence → perspective."""

    def test_safe_form_returns_action(self):
        fixture = load_fixture("form_page.json")
        observation = fixture_to_observation(fixture)
        # Build perspective context from observation
        engine = PerspectiveEngine()
        # Create a WNAL action for the submit button
        action = ClickAction(action_id="p002", target_ref="button#login")
        evidence = ActionabilityEvidence(
            action_id="p002",
            target_ref="button#login",
            phase=Phase.PRE,
            attached=True, visible=True, enabled=True,
            editable=False, stable=True, pointer_events=True,
            observed_at=datetime.now(),
        )
        context = {
            "user_intent": "log in",
            "risk_level": "low",
            "auth_state": "valid",
        }
        resolution = engine.analyze(action, evidence, context)
        assert resolution.strategy == ResolutionStrategy.ACTION

    def test_all_perspectives_assessed(self):
        """Perspective engine has all 7 perspectives registered."""
        engine = PerspectiveEngine()
        assert len(engine.perspectives) == 7
        # Keys are PerspectiveType enum values, not strings
        from netweaver.perspective import PerspectiveType
        expected = set(PerspectiveType)
        assert set(engine.perspectives.keys()) == expected


# ---------------------------------------------------------------------------
# P-003: Full Pipeline — Hidden Element Blocked
# ---------------------------------------------------------------------------

class TestP003HiddenBlocked:
    """P-003: Observer detects hidden element → executor blocks."""

    def test_hidden_element_blocked(self):
        fixture = load_fixture("spa_page.json")
        # Find the hidden element
        hidden_el = None
        for el in fixture["interactive_elements"]:
            if not el["actionability"]["visible"]:
                hidden_el = el
                break
        assert hidden_el is not None, "Fixture should have a hidden element"

        # Create WNAL evidence from the hidden element
        def hidden_collector(action_id, target_ref):
            return fixture_element_to_wnal_evidence(hidden_el, action_id)

        executor = VerifiedExecutor(evidence_collector=hidden_collector)
        action = ClickAction(action_id="p003", target_ref=hidden_el["selector"])
        result = executor.execute(action, context={"risk_level": "low"})
        assert result.status == ExecutionStatus.PRECONDITION_FAILED

    def test_hidden_element_no_execution(self):
        fixture = load_fixture("spa_page.json")
        hidden_el = [e for e in fixture["interactive_elements"]
                     if not e["actionability"]["visible"]][0]

        executed = []
        def tracking_executor(action):
            executed.append(True)
            return True

        def hidden_collector(action_id, target_ref):
            return fixture_element_to_wnal_evidence(hidden_el, action_id)

        executor = VerifiedExecutor(
            evidence_collector=hidden_collector,
            action_executor=tracking_executor,
        )
        action = ClickAction(action_id="p003b", target_ref=hidden_el["selector"])
        executor.execute(action, context={"risk_level": "low"})
        assert len(executed) == 0


# ---------------------------------------------------------------------------
# P-004: Full Pipeline — Happy Path Click
# ---------------------------------------------------------------------------

class TestP004HappyPath:
    """P-004: Full pipeline for safe, actionable element."""

    def test_success_with_evidence(self):
        fixture = load_fixture("static_page.json")
        # Find the submit button (enabled, visible)
        btn_el = [e for e in fixture["interactive_elements"]
                  if e["tag"] == "button"][0]

        def happy_collector(action_id, target_ref):
            return fixture_element_to_wnal_evidence(btn_el, action_id)

        executor = VerifiedExecutor(evidence_collector=happy_collector)
        action = ClickAction(action_id="p004", target_ref=btn_el["selector"])
        result = executor.execute(action, context={
            "user_intent": "click button",
            "risk_level": "low",
            "auth_state": "valid",
        })
        assert result.status == ExecutionStatus.SUCCESS

    def test_evidence_report_verifies(self):
        fixture = load_fixture("static_page.json")
        btn_el = [e for e in fixture["interactive_elements"]
                  if e["tag"] == "button"][0]

        def happy_collector(action_id, target_ref):
            return fixture_element_to_wnal_evidence(btn_el, action_id)

        executor = VerifiedExecutor(evidence_collector=happy_collector)
        action = ClickAction(action_id="p004b", target_ref=btn_el["selector"])
        result = executor.execute(action, context={"risk_level": "low"})
        assert result.report is not None
        assert result.report.verify()

    def test_pre_post_observations_linked(self):
        fixture = load_fixture("static_page.json")
        btn_el = [e for e in fixture["interactive_elements"]
                  if e["tag"] == "button"][0]

        def happy_collector(action_id, target_ref):
            return fixture_element_to_wnal_evidence(btn_el, action_id)

        executor = VerifiedExecutor(evidence_collector=happy_collector)
        action = ClickAction(action_id="p004c", target_ref=btn_el["selector"])
        result = executor.execute(action, context={"risk_level": "low"})
        assert result.evidence.pre is not None
        assert result.evidence.post is not None
        # Pre and post should reference same target
        assert result.evidence.pre.target_ref == btn_el["selector"]
        assert result.evidence.post.target_ref == btn_el["selector"]

    def test_actionable_selectors_from_report(self):
        """Can extract actionable selectors from evidence report."""
        fixture = load_fixture("static_page.json")
        observation = fixture_to_observation(fixture)
        report = observation_to_report(observation)
        selectors = get_actionable_selectors(report)
        # All 3 elements in static_page are actionable
        assert len(selectors) == 3
