"""NetWeaver Demo Module — End-to-end pipeline demonstration (NW-032).

Exercises the full NetWeaver stack with mocked browser:
  URL → Observer → SceneGraphBuilder → GoalTranslator → ActionOrchestrator → EvidenceReport

The demo proves the architecture works end-to-end without requiring
a real browser. All modules are chained with their real implementations;
only the browser observation layer is mocked via observe_page_mock().

Usage:
    python -m netweaver.demo --url example.com --actions "click(#login),fill(#user,admin)"

Design:
    - DemoModule: orchestrates the full pipeline
    - parse_actions(): converts CLI action strings to ActionStep objects
    - run_demo(): chains Observer → Builder → Planner → Executor
    - Produces EvidenceReport with ≥3 claims and evidence chain
    - No browser/Playwright/vendor imports
"""

import argparse
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
    observe_page_mock,
)
from netweaver.scene_graph import WebSceneGraph
from netweaver.scene_graph_builder import (
    BuilderConfig,
    BuilderResult,
    SceneGraphBuilder,
)
from netweaver.planner import GoalTranslator, PlanResult
from netweaver.action_orchestrator import (
    ActionOrchestrator,
    ActionPlan,
    ActionStep,
    ActionType,
    OrchestrationResult,
    PlanStatus,
)
from netweaver.executor import (
    ExecutionStatus,
    VerifiedExecutor,
)
from netweaver.evidence import (
    Claim,
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
    Observation,
    create_claim,
    create_observation,
)
from netweaver.wnal import ActionabilityEvidence, Phase


# ---------------------------------------------------------------------------
# Action string parsing
# ---------------------------------------------------------------------------

_ACTION_PATTERN = re.compile(
    r"(click|fill|wait)\(([^)]+)\)",
    re.IGNORECASE,
)


def parse_actions(actions_str: str) -> List[ActionStep]:
    """Parse a comma-separated action string into ActionStep objects.

    Supported formats:
        click(#selector)
        fill(#selector,value)
        wait(#selector)

    Args:
        actions_str: Comma-separated actions, e.g.
            "click(#login),fill(#user,admin),wait(#dashboard)"

    Returns:
        List of ActionStep objects.

    Raises:
        ValueError: If no valid actions found.
    """
    steps: List[ActionStep] = []

    # Split by ), then re-add ) to get individual action tokens
    # This handles the comma-inside-parens issue
    tokens = _ACTION_PATTERN.findall(actions_str)

    for action_type_str, args_str in tokens:
        action_type_str = action_type_str.lower().strip()
        args = [a.strip() for a in args_str.split(",")]

        if action_type_str == "click":
            selector = args[0]
            steps.append(ActionStep(
                action_type=ActionType.CLICK,
                description=selector,
                intent=f"click {selector}",
            ))
        elif action_type_str == "fill":
            selector = args[0]
            value = args[1] if len(args) > 1 else ""
            steps.append(ActionStep(
                action_type=ActionType.FILL,
                description=selector,
                intent=f"fill {selector}",
                text=value,
            ))
        elif action_type_str == "wait":
            selector = args[0]
            steps.append(ActionStep(
                action_type=ActionType.WAIT,
                description=selector,
                intent=f"wait for {selector}",
                condition="attached",
                timeout_ms=5000,
            ))

    if not steps:
        raise ValueError(
            f"No valid actions parsed from: {actions_str!r}. "
            "Expected format: click(#sel),fill(#sel,val),wait(#sel)"
        )

    return steps


# ---------------------------------------------------------------------------
# Demo result
# ---------------------------------------------------------------------------

@dataclass
class DemoResult:
    """Complete result from a demo pipeline run.

    Attributes:
        url: Target URL.
        observation: The PageObservation from the observer.
        builder_result: The SceneGraphBuilder output.
        plan_result: The GoalTranslator output.
        orchestration_result: The ActionOrchestrator output.
        evidence_report: Final EvidenceReport with ≥3 claims.
        success: Whether the demo ran successfully end-to-end.
        errors: Any errors encountered during pipeline stages.
    """
    url: str
    observation: Optional[PageObservation] = None
    builder_result: Optional[BuilderResult] = None
    plan_result: Optional[PlanResult] = None
    orchestration_result: Optional[OrchestrationResult] = None
    evidence_report: Optional[EvidenceReport] = None
    success: bool = False
    errors: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        """Produce a human-readable summary dict."""
        return {
            "url": self.url,
            "success": self.success,
            "errors": self.errors,
            "observation": {
                "elements": len(self.observation.interactive_elements) if self.observation else 0,
                "title": self.observation.title if self.observation else None,
            },
            "scene_graph": {
                "nodes": len(self.builder_result.graph.nodes) if self.builder_result else 0,
                "edges": len(self.builder_result.graph.edges) if self.builder_result else 0,
            },
            "plan": {
                "template": self.plan_result.template_name if self.plan_result else None,
                "confidence": self.plan_result.confidence if self.plan_result else None,
                "steps": len(self.plan_result.plan.steps) if self.plan_result else 0,
            },
            "orchestration": {
                "status": self.orchestration_result.status.value if self.orchestration_result else None,
                "completed_steps": self.orchestration_result.completed_steps if self.orchestration_result else 0,
            },
            "evidence_report": {
                "claims": len(self.evidence_report.claims) if self.evidence_report else 0,
                "observations": len(self.evidence_report.observations) if self.evidence_report else 0,
                "verified": self.evidence_report.verify() if self.evidence_report else False,
            },
        }


# ---------------------------------------------------------------------------
# DemoModule — the main pipeline
# ---------------------------------------------------------------------------

def _make_editable_evidence(action_id: str, target_ref: str) -> ActionabilityEvidence:
    """Mock evidence collector with editable=True for fill support."""
    return ActionabilityEvidence(
        action_id=action_id,
        target_ref=target_ref,
        phase=Phase.PRE,
        attached=True,
        visible=True,
        enabled=True,
        editable=True,
        stable=True,
        pointer_events=True,
        observed_at=datetime.now(),
    )


class DemoModule:
    """End-to-end demo exercising the full NetWeaver pipeline.

    Pipeline stages:
        1. Observer: observe_page_mock(url) → PageObservation
        2. Builder: SceneGraphBuilder.build(obs) → BuilderResult (graph + evidence)
        3. Planner: GoalTranslator.translate(goal, graph) → PlanResult (ActionPlan)
        4. Executor: ActionOrchestrator.orchestrate(plan, graph_supplier) → result
        5. Report: Assemble final EvidenceReport with ≥3 claims + evidence chain

    Usage:
        demo = DemoModule()
        result = demo.run_demo("https://example.com/login", [
            ActionStep(ActionType.FILL, "#user", text="admin"),
            ActionStep(ActionType.CLICK, "#login-btn"),
        ])
    """

    def __init__(
        self,
        builder_config: Optional[BuilderConfig] = None,
        observer_fn: Optional[Any] = None,
    ):
        """Initialize the demo module.

        Args:
            builder_config: Optional SceneGraphBuilder config.
            observer_fn: Optional observer function override (for testing).
                Defaults to observe_page_mock.
        """
        self.builder_config = builder_config or BuilderConfig()
        self._observer_fn = observer_fn or observe_page_mock

    def run_demo(
        self,
        url: str,
        actions: Optional[List[ActionStep]] = None,
        goal: str = "login",
    ) -> DemoResult:
        """Run the full demo pipeline.

        Args:
            url: Target URL to observe (mocked).
            actions: Optional list of ActionStep objects. If provided, used
                directly as the plan. If None, GoalTranslator generates plan.
            goal: Goal string for GoalTranslator (used when actions is None).

        Returns:
            DemoResult with all pipeline outputs and final EvidenceReport.
        """
        result = DemoResult(url=url)

        # Stage 1: Observer
        try:
            observation = self._observer_fn(url)
            result.observation = observation
        except Exception as e:
            result.errors.append(f"Observer failed: {e}")
            result.evidence_report = self._build_error_report(url, result.errors)
            return result

        # Stage 2: Scene Graph Builder
        try:
            builder = SceneGraphBuilder(config=self.builder_config)
            builder_result = builder.build(observation)
            result.builder_result = builder_result
        except Exception as e:
            result.errors.append(f"Builder failed: {e}")
            result.evidence_report = self._build_error_report(url, result.errors)
            return result

        graph = builder_result.graph

        # Stage 3: Planner
        try:
            if actions is not None:
                # Use provided actions directly as an ActionPlan
                plan = ActionPlan(
                    description=f"Demo plan for {url}",
                    steps=list(actions),
                    metadata={"url": url},
                )
                plan_result = PlanResult(
                    plan=plan,
                    template_name="custom",
                    confidence=1.0,
                    graph_validation=True,
                )
            else:
                # Use GoalTranslator to generate plan from goal string
                translator = GoalTranslator()
                plan_result = translator.translate(goal, graph)

            result.plan_result = plan_result
        except Exception as e:
            result.errors.append(f"Planner failed: {e}")
            result.evidence_report = self._build_error_report(url, result.errors)
            return result

        # Stage 4: Executor (Orchestrator)
        try:
            executor = VerifiedExecutor(
                evidence_collector=_make_editable_evidence,
            )
            orchestrator = ActionOrchestrator(executor=executor)
            graph_supplier = lambda: graph  # Mock: graph doesn't change

            orch_result = orchestrator.orchestrate(
                plan_result.plan,
                graph_supplier,
                skip_perspective=True,
            )
            result.orchestration_result = orch_result
        except Exception as e:
            result.errors.append(f"Executor failed: {e}")
            result.evidence_report = self._build_error_report(url, result.errors)
            return result

        # Stage 5: Build final EvidenceReport
        result.evidence_report = self._build_demo_report(
            url=url,
            observation=observation,
            builder_result=builder_result,
            plan_result=plan_result,
            orch_result=orch_result,
        )
        result.success = True
        return result

    def _build_demo_report(
        self,
        url: str,
        observation: PageObservation,
        builder_result: BuilderResult,
        plan_result: PlanResult,
        orch_result: OrchestrationResult,
    ) -> EvidenceReport:
        """Build the final EvidenceReport with ≥3 claims and evidence chain.

        Claims:
            1. Page observation collected with interactive elements (DOM)
            2. Scene graph built with nodes and edges (DOM)
            3. Plan generated and executed (ACTIONABILITY)
        """
        report = EvidenceReport(
            report_id=f"demo-{uuid.uuid4().hex[:12]}",
            url=url,
            timestamp=datetime.now(),
        )

        # Claim 1: Page observation collected
        obs_id_1 = f"obs-demo-page-{uuid.uuid4().hex[:8]}"
        obs_1 = create_observation(
            observation_id=obs_id_1,
            evidence_type=EvidenceType.DOM,
            data={
                "url": url,
                "title": observation.title,
                "element_count": len(observation.interactive_elements),
                "elements": [e.selector for e in observation.interactive_elements],
            },
            source="demo_observer",
        )
        report.add_observation(obs_1)

        claim_1 = create_claim(
            claim_id="demo-claim-observation",
            description=(
                f"Page observation collected for {url}: "
                f"{len(observation.interactive_elements)} interactive elements found"
            ),
            evidence_type=EvidenceType.DOM,
            observation_ids=[obs_id_1],
        )
        report.add_claim(claim_1)

        # Claim 2: Scene graph built
        obs_id_2 = f"obs-demo-graph-{uuid.uuid4().hex[:8]}"
        graph = builder_result.graph
        obs_2 = create_observation(
            observation_id=obs_id_2,
            evidence_type=EvidenceType.DOM,
            data={
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "graph_url": graph.url,
            },
            source="demo_builder",
        )
        report.add_observation(obs_2)

        claim_2 = create_claim(
            claim_id="demo-claim-scene-graph",
            description=(
                f"Scene graph built: {len(graph.nodes)} nodes, "
                f"{len(graph.edges)} edges"
            ),
            evidence_type=EvidenceType.DOM,
            observation_ids=[obs_id_2],
        )
        report.add_claim(claim_2)

        # Claim 3: Plan executed
        obs_id_3 = f"obs-demo-exec-{uuid.uuid4().hex[:8]}"
        obs_3 = create_observation(
            observation_id=obs_id_3,
            evidence_type=EvidenceType.ACTIONABILITY,
            data={
                "plan_steps": len(plan_result.plan.steps),
                "template": plan_result.template_name,
                "confidence": plan_result.confidence,
                "orchestration_status": orch_result.status.value,
                "completed_steps": orch_result.completed_steps,
            },
            source="demo_executor",
        )
        report.add_observation(obs_3)

        claim_3 = create_claim(
            claim_id="demo-claim-execution",
            description=(
                f"Plan executed: {len(plan_result.plan.steps)} steps, "
                f"status={orch_result.status.value}, "
                f"completed={orch_result.completed_steps}"
            ),
            evidence_type=EvidenceType.ACTIONABILITY,
            observation_ids=[obs_id_3],
        )
        report.add_claim(claim_3)

        # Claim 4: Network activity observed
        obs_id_4 = f"obs-demo-net-{uuid.uuid4().hex[:8]}"
        obs_4 = create_observation(
            observation_id=obs_id_4,
            evidence_type=EvidenceType.NETWORK,
            data={
                "requests": observation.network.requests_count,
                "responses": observation.network.responses_count,
                "failed": observation.network.failed_count,
                "resource_types": observation.network.resource_types,
            },
            source="demo_network",
        )
        report.add_observation(obs_4)

        claim_4 = create_claim(
            claim_id="demo-claim-network",
            description=(
                f"Network activity: {observation.network.requests_count} requests, "
                f"{observation.network.failed_count} failures"
            ),
            evidence_type=EvidenceType.NETWORK,
            observation_ids=[obs_id_4],
        )
        report.add_claim(claim_4)

        # Verify all claims
        report.verify()
        return report

    def _build_error_report(self, url: str, errors: List[str]) -> EvidenceReport:
        """Build a minimal error EvidenceReport when pipeline fails early."""
        report = EvidenceReport(
            report_id=f"demo-error-{uuid.uuid4().hex[:12]}",
            url=url,
            timestamp=datetime.now(),
        )

        obs_id = f"obs-demo-err-{uuid.uuid4().hex[:8]}"
        obs = create_observation(
            observation_id=obs_id,
            evidence_type=EvidenceType.DOM,
            data={"errors": errors},
            source="demo_error",
        )
        report.add_observation(obs)

        claim = create_claim(
            claim_id="demo-claim-error",
            description=f"Pipeline failed: {'; '.join(errors)}",
            evidence_type=EvidenceType.DOM,
            observation_ids=[obs_id],
        )
        report.add_claim(claim)
        report.verify()
        return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for the demo module.

    Usage:
        python -m netweaver.demo --url example.com --actions "click(#login),fill(#user,admin)"
    """
    parser = argparse.ArgumentParser(
        description="NetWeaver End-to-End Demo Pipeline",
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Target URL to observe (mocked)",
    )
    parser.add_argument(
        "--actions",
        default=None,
        help='Comma-separated actions: "click(#sel),fill(#sel,val),wait(#sel)"',
    )
    parser.add_argument(
        "--goal",
        default="login",
        help='Goal string for auto-planning (default: "login")',
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    args = parser.parse_args(argv)

    # Parse actions if provided
    actions = None
    if args.actions:
        try:
            actions = parse_actions(args.actions)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Run demo
    demo = DemoModule()
    result = demo.run_demo(
        url=args.url,
        actions=actions,
        goal=args.goal,
    )

    if args.json:
        import json
        output = {
            "success": result.success,
            "errors": result.errors,
            "summary": result.summary(),
        }
        if result.evidence_report:
            output["evidence_report"] = result.evidence_report.to_dict()
        print(json.dumps(output, indent=2, default=str))
    else:
        summary = result.summary()
        print(f"NetWeaver Demo Pipeline — {args.url}")
        print(f"{'=' * 50}")
        print(f"Status: {'SUCCESS' if result.success else 'FAILED'}")
        if result.errors:
            print(f"Errors: {'; '.join(result.errors)}")
        print(f"Observation: {summary['observation']['elements']} elements on '{summary['observation']['title']}'")
        print(f"Scene Graph: {summary['scene_graph']['nodes']} nodes, {summary['scene_graph']['edges']} edges")
        print(f"Plan: template={summary['plan']['template']}, confidence={summary['plan']['confidence']}, steps={summary['plan']['steps']}")
        print(f"Orchestration: status={summary['orchestration']['status']}, completed={summary['orchestration']['completed_steps']}")
        print(f"Evidence Report: {summary['evidence_report']['claims']} claims, "
              f"{summary['evidence_report']['observations']} observations, "
              f"verified={summary['evidence_report']['verified']}")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
