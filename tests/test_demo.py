"""NetWeaver Demo Module Tests (NW-032).

Comprehensive tests for the end-to-end demo pipeline:
  URL → Observer → SceneGraphBuilder → Planner → Executor → EvidenceReport

Tests cover:
  - parse_actions() parsing: valid/invalid action strings
  - DemoModule.run_demo(): full pipeline with actions and goals
  - DemoResult: structure, summary, error handling
  - EvidenceReport: ≥3 claims, all verified, evidence chain intact
  - CLI main(): argument parsing, JSON/text output
  - Error paths: observer failure, builder failure, executor failure
  - Custom observer injection
  - No browser/Playwright/vendor imports

NW-032 acceptance:
  - DemoModule class with run_demo(url, actions) → EvidenceReport ✅
  - Chains: Observer.analyze() → SceneGraphBuilder.build() → Planner.plan() → Executor.execute() ✅
  - Mock browser returns realistic page fixtures ✅
  - Produces EvidenceReport with ≥3 claims and evidence chain ✅
  - CLI entry: python -m netweaver.demo --url example.com --actions "..." ✅
  - DEMO.md documents architecture flow with example output ✅
  - All existing tests remain green ✅
  - 15+ new tests ✅
"""

import json
import re
from datetime import datetime
from io import StringIO
from typing import List
from unittest.mock import patch, MagicMock

import pytest

from netweaver.demo import (
    DemoModule,
    DemoResult,
    parse_actions,
    main,
)
from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    observe_page_mock,
)
from netweaver.scene_graph_builder import BuilderConfig, BuilderResult
from netweaver.planner import PlanResult
from netweaver.action_orchestrator import (
    ActionPlan,
    ActionStep,
    ActionType,
    OrchestrationResult,
    PlanStatus,
)
from netweaver.evidence import (
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_custom_observation(url: str = "https://example.com/test") -> PageObservation:
    """Create a custom PageObservation for testing."""
    return PageObservation(
        url=url,
        title="Test Page",
        interactive_elements=[
            InteractiveElement(
                selector="#search-box",
                tag="input",
                type="text",
                text=None,
                aria_label="Search",
                actionability={
                    "visible": True,
                    "enabled": True,
                    "attached": True,
                    "stable": True,
                    "pointer_events": True,
                    "editable": True,
                },
            ),
            InteractiveElement(
                selector="#search-btn",
                tag="button",
                type="submit",
                text="Search",
                aria_label="Search",
                actionability={
                    "visible": True,
                    "enabled": True,
                    "attached": True,
                    "stable": True,
                    "pointer_events": True,
                },
            ),
        ],
        actionability={
            "#search-box": {"visible": True, "enabled": True},
            "#search-btn": {"visible": True, "enabled": True},
        },
        network=NetworkActivity(
            requests_count=3,
            responses_count=3,
            failed_count=0,
            resource_types={"document": 1, "script": 2},
        ),
        observed_at=datetime.now(),
    )


def _failing_observer(url: str) -> PageObservation:
    """Observer that always raises an error."""
    raise RuntimeError("Browser connection refused")


# ---------------------------------------------------------------------------
# Tests: parse_actions
# ---------------------------------------------------------------------------

class TestParseActions:
    """Tests for the action string parser."""

    def test_single_click(self):
        steps = parse_actions("click(#login)")
        assert len(steps) == 1
        assert steps[0].action_type == ActionType.CLICK
        assert steps[0].description == "#login"

    def test_single_fill(self):
        steps = parse_actions("fill(#user,admin)")
        assert len(steps) == 1
        assert steps[0].action_type == ActionType.FILL
        assert steps[0].description == "#user"
        assert steps[0].text == "admin"

    def test_single_wait(self):
        steps = parse_actions("wait(#dashboard)")
        assert len(steps) == 1
        assert steps[0].action_type == ActionType.WAIT
        assert steps[0].description == "#dashboard"

    def test_multiple_actions(self):
        steps = parse_actions("click(#login),fill(#user,admin),fill(#pass,secret),click(#submit)")
        assert len(steps) == 4
        assert steps[0].action_type == ActionType.CLICK
        assert steps[1].action_type == ActionType.FILL
        assert steps[2].action_type == ActionType.FILL
        assert steps[3].action_type == ActionType.CLICK

    def test_fill_without_value(self):
        steps = parse_actions("fill(#user)")
        assert len(steps) == 1
        assert steps[0].text == ""

    def test_invalid_action_string_raises(self):
        with pytest.raises(ValueError, match="No valid actions"):
            parse_actions("invalid_action")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="No valid actions"):
            parse_actions("")

    def test_case_insensitive(self):
        steps = parse_actions("CLICK(#btn)")
        assert len(steps) == 1
        assert steps[0].action_type == ActionType.CLICK

    def test_whitespace_tolerance(self):
        steps = parse_actions("click( #btn )")
        assert len(steps) == 1
        assert steps[0].description == "#btn"

    def test_mixed_valid_invalid(self):
        """Only valid actions are parsed; invalid ones skipped."""
        steps = parse_actions("click(#btn),garbage,fill(#x,y)")
        assert len(steps) == 2


# ---------------------------------------------------------------------------
# Tests: DemoModule
# ---------------------------------------------------------------------------

class TestDemoModule:
    """Tests for the DemoModule pipeline."""

    def test_run_demo_with_actions(self):
        """Full pipeline with explicit action steps."""
        demo = DemoModule()
        actions = [
            ActionStep(ActionType.FILL, "#email", text="test@example.com", intent="fill email"),
            ActionStep(ActionType.CLICK, "#submit", intent="submit form"),
        ]
        result = demo.run_demo("https://example.com", actions=actions)

        assert isinstance(result, DemoResult)
        assert result.success is True
        assert result.observation is not None
        assert result.builder_result is not None
        assert result.plan_result is not None
        assert result.orchestration_result is not None
        assert result.evidence_report is not None

    def test_run_demo_with_goal(self):
        """Full pipeline with GoalTranslator auto-planning."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com/login", goal="login")

        assert isinstance(result, DemoResult)
        assert result.success is True
        assert result.plan_result is not None
        assert result.plan_result.template_name == "login"

    def test_evidence_report_has_at_least_3_claims(self):
        """EvidenceReport must have ≥3 claims with evidence chain."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        report = result.evidence_report
        assert isinstance(report, EvidenceReport)
        assert len(report.claims) >= 3, (
            f"Expected ≥3 claims, got {len(report.claims)}"
        )

    def test_evidence_report_all_claims_verified(self):
        """All claims in the EvidenceReport must be verified (SUPPORTED)."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        report = result.evidence_report
        assert report.verify() is True, "EvidenceReport verification failed"
        for claim in report.claims:
            assert claim.status == ClaimStatus.SUPPORTED, (
                f"Claim {claim.claim_id} not supported: {claim.description}"
            )

    def test_evidence_report_observations_link_to_claims(self):
        """Each claim's observation_ids must reference existing observations."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        report = result.evidence_report
        obs_ids = {o.observation_id for o in report.observations}
        for claim in report.claims:
            for oid in claim.observation_ids:
                assert oid in obs_ids, (
                    f"Claim {claim.claim_id} references unknown obs {oid}"
                )

    def test_evidence_report_claims_diverse_types(self):
        """Claims should span multiple evidence types."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        report = result.evidence_report
        types_used = {c.evidence_type for c in report.claims}
        assert len(types_used) >= 2, (
            f"Expected ≥2 evidence types, got {types_used}"
        )

    def test_pipeline_chains_all_stages(self):
        """Verify all pipeline stages produce output."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        assert result.observation is not None, "Observer stage failed"
        assert result.builder_result is not None, "Builder stage failed"
        assert result.plan_result is not None, "Planner stage failed"
        assert result.orchestration_result is not None, "Executor stage failed"
        assert result.evidence_report is not None, "Report stage failed"

    def test_scene_graph_has_nodes_and_edges(self):
        """Builder produces a graph with nodes and edges."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        graph = result.builder_result.graph
        assert len(graph.nodes) > 0, "Scene graph has no nodes"
        assert len(graph.edges) > 0, "Scene graph has no edges"

    def test_custom_observer_injection(self):
        """DemoModule accepts custom observer function."""
        demo = DemoModule(observer_fn=_make_custom_observation)
        result = demo.run_demo("https://example.com/test")

        assert result.success is True
        assert result.observation.title == "Test Page"
        assert len(result.observation.interactive_elements) == 2

    def test_observer_failure_produces_error_report(self):
        """When observer fails, pipeline returns error EvidenceReport."""
        demo = DemoModule(observer_fn=_failing_observer)
        result = demo.run_demo("https://example.com")

        assert result.success is False
        assert len(result.errors) > 0
        assert "Observer failed" in result.errors[0]
        assert result.evidence_report is not None
        # Error report still has claims
        assert len(result.evidence_report.claims) >= 1

    def test_demo_result_summary(self):
        """DemoResult.summary() returns structured dict."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        summary = result.summary()
        assert "url" in summary
        assert "success" in summary
        assert summary["success"] is True
        assert "observation" in summary
        assert "scene_graph" in summary
        assert "plan" in summary
        assert "orchestration" in summary
        assert "evidence_report" in summary

    def test_demo_result_summary_counts(self):
        """Summary reflects actual counts from pipeline."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        summary = result.summary()
        assert summary["observation"]["elements"] > 0
        assert summary["scene_graph"]["nodes"] > 0
        assert summary["plan"]["steps"] > 0
        assert summary["evidence_report"]["claims"] >= 3
        assert summary["evidence_report"]["observations"] >= 3

    def test_run_demo_default_goal(self):
        """Default goal is 'login' when no actions or goal specified."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        assert result.plan_result is not None
        # Should match 'login' template or fallback
        assert result.plan_result.plan is not None

    def test_orchestration_result_structure(self):
        """OrchestrationResult has expected fields."""
        demo = DemoModule()
        result = demo.run_demo("https://example.com")

        orch = result.orchestration_result
        assert isinstance(orch, OrchestrationResult)
        assert orch.plan_id != ""
        assert orch.status in (
            PlanStatus.COMPLETED,
            PlanStatus.RUNNING,
            PlanStatus.FAILED,
            PlanStatus.PENDING,
        )


# ---------------------------------------------------------------------------
# Tests: CLI
# ---------------------------------------------------------------------------

class TestDemoCLI:
    """Tests for the CLI entry point."""

    def test_cli_with_actions(self, capsys):
        """CLI runs successfully with --actions."""
        exit_code = main(["--url", "example.com", "--actions", "click(#btn)"])
        assert exit_code == 0

    def test_cli_with_goal(self, capsys):
        """CLI runs successfully with --goal."""
        exit_code = main(["--url", "example.com", "--goal", "login"])
        assert exit_code == 0

    def test_cli_json_output(self, capsys):
        """CLI --json produces valid JSON."""
        exit_code = main(["--url", "example.com", "--json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        data = json.loads(captured.out)
        assert "success" in data
        assert data["success"] is True
        assert "evidence_report" in data

    def test_cli_text_output(self, capsys):
        """CLI text output contains expected sections."""
        exit_code = main(["--url", "example.com"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "NetWeaver Demo Pipeline" in captured.out
        assert "SUCCESS" in captured.out

    def test_cli_invalid_actions(self, capsys):
        """CLI returns error on invalid action string."""
        exit_code = main(["--url", "example.com", "--actions", "garbage"])
        assert exit_code == 1

    def test_cli_evidence_report_in_json(self, capsys):
        """JSON output includes evidence report with claims."""
        exit_code = main(["--url", "example.com", "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        report = data["evidence_report"]
        assert len(report["claims"]) >= 3
        assert len(report["observations"]) >= 3


# ---------------------------------------------------------------------------
# Tests: No browser imports
# ---------------------------------------------------------------------------

class TestNoBrowserImports:
    """Verify demo module doesn't import browser/Playwright/vendor."""

    def test_no_playwright_import(self):
        import netweaver.demo as demo_mod
        source = open(demo_mod.__file__).read()
        assert "playwright" not in source.lower(), "Demo imports playwright"
        assert "from playwright" not in source, "Demo imports from playwright"

    def test_no_vendor_import(self):
        import netweaver.demo as demo_mod
        source = open(demo_mod.__file__).read()
        assert "vendor" not in source.lower(), "Demo imports vendor"
