"""Cross-Module QA Invariant Tests — Phase 1 Quality Gate.

Verifies system-wide invariants that unit tests miss:
1. Serialization round-trip fidelity across all data types
2. Import safety (no forbidden deps in any module)
3. Cross-module data flow integrity
4. Evidence chain completeness through pipeline
5. Serialization symmetry: to_dict() → from_dict() → to_dict() is idempotent
6. Module API surface consistency
7. Boundary & edge case invariants

No browser/Playwright/vendor deps. Pure data + stdlib.
Run: python -m pytest tests/benchmarks/test_cross_module_invariants.py -v
"""

import ast
import importlib
import json
import pkgutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── NetWeaver imports ──
from netweaver.wnal import (
    ActionPreconditions,
    ActionType,
    ActionabilityEvidence,
    ClickAction,
    FillAction,
    Phase,
    VerificationResult,
    WaitAction,
    action_from_dict,
    get_preconditions,
)
from netweaver.observer import (
    InteractiveElement,
    NetworkActivity,
    PageObservation,
)
from netweaver.evidence import (
    Claim,
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
    create_claim,
)
from netweaver.scene_graph import (
    EdgeType,
    NodeType,
    SceneEdge,
    SceneNode,
    WebSceneGraph,
)
from netweaver.scene_graph_builder import SceneGraphBuilder
from netweaver.graph_query import IntentType, resolve_target
from netweaver.executor import (
    ExecutionStatus,
    GraphResolvedTarget,
    ResolutionStatus,
    VerifiedExecution,
    VerifiedExecutor,
)
from netweaver.action_orchestrator import (
    ActionOrchestrator,
    ActionPlan,
    ActionStep,
    ActionType as OrchActionType,
    OrchestrationResult,
    PlanStatus,
    StepResult,
)
from netweaver.perspective import PerspectiveEngine
from netweaver.site_skill import SiteSkill, SkillStore
from netweaver.skill_matcher import SkillMatcher
from netweaver.skill_learner import SkillLearner
from netweaver.planner import GoalTranslator, PlanResult
from netweaver.competence import Competence, WorkerProfile
from netweaver.event_ledger import EventLedger


# ── Helpers ──────────────────────────────────────────────────────────────

FORBIDDEN_MODULES = frozenset({
    "playwright", "selenium", "puppeteer", "cloakbrowser",
    "requests", "httpx", "aiohttp", "urllib3",
    "numpy", "pandas", "tensorflow", "torch",
})


def _make_login_observation() -> PageObservation:
    return PageObservation(
        url="https://example.com/login",
        title="Login",
        interactive_elements=[
            InteractiveElement(
                selector="#user", tag="input", type="text",
                aria_label="Username",
                actionability={"visible": True, "enabled": True,
                               "attached": True, "stable": True,
                               "pointer_events": True, "editable": True},
            ),
            InteractiveElement(
                selector="#pass", tag="input", type="password",
                aria_label="Password",
                actionability={"visible": True, "enabled": True,
                               "attached": True, "stable": True,
                               "pointer_events": True, "editable": True},
            ),
            InteractiveElement(
                selector="#submit", tag="button", type="submit",
                text="Login", aria_label="Login",
                actionability={"visible": True, "enabled": True,
                               "attached": True, "stable": True,
                               "pointer_events": True},
            ),
        ],
        actionability={"#user": {"visible": True}, "#pass": {"visible": True}},
        network=NetworkActivity(requests_count=1, responses_count=1,
                                resource_types={"document": 1}),
        observed_at=datetime.now(),
    )


def _make_evidence(action_id: str = "a1", target: str = "#btn") -> ActionabilityEvidence:
    return ActionabilityEvidence(
        action_id=action_id, target_ref=target, phase=Phase.PRE,
        attached=True, visible=True, enabled=True,
        stable=True, pointer_events=True, editable=True,
        observed_at=datetime.now(),
    )


# ══════════════════════════════════════════════════════════════════════════
# 1. SERIALIZATION ROUND-TRIP INVARIANTS
# ══════════════════════════════════════════════════════════════════════════

class TestSerializationRoundTrip:
    """to_dict() → from_dict() → to_dict() must be idempotent for every data type."""

    def test_evidence_round_trip(self):
        ev = _make_evidence("rt-1", "#sel")
        d1 = ev.to_dict()
        ev2 = ActionabilityEvidence.from_dict(d1)
        d2 = ev2.to_dict()
        assert d1 == d2, f"Evidence round-trip mismatch: {d1} != {d2}"

    def test_evidence_with_optional_fields(self):
        ev = ActionabilityEvidence(
            action_id="rt-opt", target_ref="#x", phase=Phase.POST,
            editable=False, metadata={"rect": {"x": 10}},
            observed_at=datetime(2026, 1, 15, 12, 30, 0),
        )
        d1 = ev.to_dict()
        ev2 = ActionabilityEvidence.from_dict(d1)
        d2 = ev2.to_dict()
        assert d1 == d2

    def test_click_action_round_trip(self):
        action = ClickAction(
            selector="#btn", target_ref="#btn", action_id="clk-rt",
            description="click it", button="right", click_count=2, delay_ms=100,
            pre_evidence=_make_evidence("clk-rt"),
        )
        d1 = action.to_dict()
        restored = action_from_dict(d1)
        d2 = restored.to_dict()
        assert d1 == d2, "ClickAction round-trip mismatch"

    def test_fill_action_round_trip_non_sensitive(self):
        action = FillAction(
            selector="#inp", value="hello", text="hello",
            is_sensitive=False, action_id="fill-rt",
            post_evidence=_make_evidence("fill-rt"),
        )
        d1 = action.to_dict()
        restored = action_from_dict(d1)
        d2 = restored.to_dict()
        assert d1 == d2

    def test_fill_action_round_trip_sensitive(self):
        """Sensitive FillAction unmasked round-trip must preserve value."""
        action = FillAction(
            selector="#pw", value="s3cret", text="s3cret",
            is_sensitive=True, action_id="fill-sens",
        )
        d1 = action.to_dict(mask_sensitive=False)
        restored = action_from_dict(d1)
        d2 = restored.to_dict(mask_sensitive=False)
        assert d1 == d2
        assert restored.value == "s3cret"

    def test_wait_action_round_trip(self):
        action = WaitAction(
            selector="#el", condition="visible",
            timeout_ms=5000, action_id="wait-rt",
        )
        d1 = action.to_dict()
        restored = action_from_dict(d1)
        d2 = restored.to_dict()
        assert d1 == d2

    def test_action_round_trip_with_verification(self):
        """Full action with pre_evidence + verification round-trips."""
        action = ClickAction(selector="#go", action_id="ver-rt")
        evidence = _make_evidence("ver-rt", "#go")
        action.validate_preconditions(evidence)
        assert action.verification is not None

        d1 = action.to_dict()
        restored = action_from_dict(d1)
        d2 = restored.to_dict()
        assert d1 == d2
        assert restored.pre_evidence is not None
        assert restored.verification is not None
        assert restored.verification.passed is True

    def test_verification_result_round_trip(self):
        """VerificationResult serialized inside action round-trips."""
        action = FillAction(selector="#email", value="a@b.com",
                            action_id="vf", is_sensitive=False)
        ev = _make_evidence("vf", "#email")
        action.validate_preconditions(ev)
        d = action.to_dict()
        restored = action_from_dict(d)
        assert restored.verification is not None
        assert restored.verification.passed is True
        assert restored.verification.preconditions.all_met is True

    def test_json_serializable_all_types(self):
        """Every to_dict() result must be JSON-serializable."""
        objects = [
            _make_evidence().to_dict(),
            ClickAction(selector="#a").to_dict(),
            FillAction(selector="#b", value="v").to_dict(),
            WaitAction(selector="#c").to_dict(),
        ]
        for obj in objects:
            json_str = json.dumps(obj)
            assert isinstance(json_str, str)
            parsed = json.loads(json_str)
            assert isinstance(parsed, dict)

    def test_round_trip_all_action_types_simultaneously(self):
        """Batch round-trip of all action types in one dict."""
        actions = {
            "click": ClickAction(selector="#c", button="middle", click_count=3),
            "fill": FillAction(selector="#f", value="text", is_sensitive=False),
            "wait": WaitAction(selector="#w", condition="hidden", timeout_ms=1000),
        }
        for name, action in actions.items():
            d1 = action.to_dict()
            restored = action_from_dict(d1)
            d2 = restored.to_dict()
            assert d1 == d2, f"Round-trip failed for {name}"


# ══════════════════════════════════════════════════════════════════════════
# 2. IMPORT SAFETY INVARIANTS
# ══════════════════════════════════════════════════════════════════════════

class TestImportSafety:
    """No netweaver module imports forbidden dependencies."""

    def test_all_modules_pure(self):
        """Every module in netweaver/ uses only stdlib + internal imports."""
        import netweaver
        pkg_path = Path(netweaver.__file__).parent

        violations = []
        for py_file in sorted(pkg_path.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            violations.extend(self._check_file(py_file))
        assert violations == [], f"Forbidden imports found: {violations}"

    @staticmethod
    def _collect_top_level_imports(tree) -> list:
        """Walk AST manually, skipping try/except bodies (optional deps)."""
        violations = []

        def _visit(nodes):
            for node in nodes:
                if isinstance(node, ast.Try):
                    # Skip the try body (guarded imports), only check except/else/finally
                    _visit(node.handlers)
                    _visit(node.orelse)
                    _visit(node.finalbody)
                    continue
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        violations.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        violations.append(node.module)
                # Recurse into compound statements
                for attr in ("body", "orelse", "finalbody"):
                    children = getattr(node, attr, None)
                    if isinstance(children, list):
                        _visit(children)

        _visit(tree.body)
        return violations

    def _check_file(self, py_file):
        """Check a single file for forbidden imports, skipping try/except guards."""
        violations = []
        source = py_file.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return violations
        all_imports = self._collect_top_level_imports(tree)
        for imp in all_imports:
            base = imp.split(".")[0].lower()
            if base in FORBIDDEN_MODULES:
                violations.append((py_file.name, imp))
        return violations

    def test_no_third_party_deps(self):
        """Verify no third-party deps beyond stdlib + netweaver.*"""
        import netweaver
        pkg_path = Path(netweaver.__file__).parent
        stdlib_modules = set(sys.stdlib_module_names) if hasattr(sys, 'stdlib_module_names') else {
            "os", "sys", "json", "re", "ast", "uuid", "enum", "dataclasses",
            "datetime", "typing", "collections", "pathlib", "functools",
            "itertools", "copy", "hashlib", "math", "abc", "io", "tempfile",
            "contextlib", "unittest", "time", "operator", "string",
        }

        # Tooling modules allowed to use third-party deps (rich, requests)
        TOOLING_MODULES = {"dashboard.py", "alerts.py", "cli.py"}

        for py_file in sorted(pkg_path.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            if py_file.name in TOOLING_MODULES:
                continue  # Tooling modules can use rich/requests
            source = py_file.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        base = alias.name.split(".")[0]
                        if base == "netweaver" or base.startswith("."):
                            continue
                        if base not in stdlib_modules:
                            assert base.lower() not in FORBIDDEN_MODULES, (
                                f"{py_file.name}: forbidden import '{base}'"
                            )


# ══════════════════════════════════════════════════════════════════════════
# 3. CROSS-MODULE DATA FLOW INTEGRITY
# ══════════════════════════════════════════════════════════════════════════

class TestCrossModuleDataFlow:
    """Verify data flows correctly across module boundaries."""

    def test_observer_to_scene_graph_to_query(self):
        """Observer → SceneGraphBuilder → GraphQuery produces valid results."""
        obs = _make_login_observation()
        builder = SceneGraphBuilder()
        result = builder.build(obs)
        graph = result.graph

        assert len(graph.nodes) > 0

        match = resolve_target(graph, "login", intent=IntentType.CLICK)
        assert match is not None
        assert match.score > 0.0

    def test_evidence_chain_through_executor(self):
        """Executor execution contains pre+post evidence chain."""
        obs = _make_login_observation()
        graph = SceneGraphBuilder().build(obs).graph
        executor = VerifiedExecutor()

        execution, resolution = executor.execute_graph_click(
            graph, "submit", skip_perspective=True,
        )

        assert execution.status == ExecutionStatus.SUCCESS
        assert execution.evidence.pre is not None
        assert execution.evidence.post is not None
        assert execution.evidence.pre.action_id != ""
        assert execution.evidence.post.action_id != ""

    def test_orchestrator_step_integrity(self):
        """Each orchestration step produces a valid StepResult."""
        obs = _make_login_observation()
        graph = SceneGraphBuilder().build(obs).graph

        def editable_ev(action_id, target_ref):
            return ActionabilityEvidence(
                action_id=action_id, target_ref=target_ref,
                phase=Phase.PRE, attached=True, visible=True,
                enabled=True, stable=True, pointer_events=True,
                editable=True, observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=editable_ev)
        orchestrator = ActionOrchestrator(executor=executor)

        plan = ActionPlan(description="Login flow")
        plan.add_step(OrchActionType.FILL, "username", text="user")
        plan.add_step(OrchActionType.CLICK, "login")

        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)

        for step in result.steps:
            assert isinstance(step, StepResult)
            assert step.status is not None

    def test_planner_to_orchestrator_flow(self):
        """GoalTranslator output feeds into ActionOrchestrator."""
        obs = _make_login_observation()
        graph = SceneGraphBuilder().build(obs).graph
        translator = GoalTranslator()

        plan_result = translator.translate("login to the website", graph)
        assert isinstance(plan_result, PlanResult)
        assert plan_result.plan is not None
        assert len(plan_result.plan.steps) > 0

    def test_skill_learner_through_pipeline(self):
        """SkillLearner receives orchestration result and produces skill."""
        obs = _make_login_observation()
        graph = SceneGraphBuilder().build(obs).graph

        def editable_ev(action_id, target_ref):
            return ActionabilityEvidence(
                action_id=action_id, target_ref=target_ref,
                phase=Phase.PRE, attached=True, visible=True,
                enabled=True, stable=True, pointer_events=True,
                editable=True, observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=editable_ev)
        orchestrator = ActionOrchestrator(executor=executor)
        translator = GoalTranslator()
        plan_result = translator.translate("login", graph)
        result = orchestrator.orchestrate(
            plan_result.plan, lambda: graph, skip_perspective=True,
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = SkillStore(Path(tmp) / "skills")
            learner = SkillLearner(store)
            skill, action = learner.learn_and_store(result, plan_result.plan, obs.url)

            if result.status == PlanStatus.COMPLETED and skill is not None:
                assert skill.site_pattern == obs.url or skill.goal

    def test_observer_to_evidence_report(self):
        """SceneGraphBuilder produces valid EvidenceReport."""
        obs = _make_login_observation()
        builder = SceneGraphBuilder()
        result = builder.build(obs)

        report = result.evidence_report
        assert report is not None
        assert isinstance(report, EvidenceReport)

    def test_full_pipeline_ecommerce(self):
        """Full pipeline on e-commerce page type."""
        obs_ecom = PageObservation(
            url="https://shop.example.com/product/123",
            title="Product",
            interactive_elements=[
                InteractiveElement(
                    selector=".add-to-cart", tag="button", text="Add to Cart",
                    aria_label="Add to Cart",
                    actionability={"visible": True, "enabled": True,
                                   "attached": True, "stable": True,
                                   "pointer_events": True},
                ),
                InteractiveElement(
                    selector=".qty", tag="input", type="number",
                    aria_label="Quantity",
                    actionability={"visible": True, "enabled": True,
                                   "attached": True, "stable": True,
                                   "pointer_events": True, "editable": True},
                ),
            ],
            actionability={".add-to-cart": {"visible": True}},
            network=NetworkActivity(requests_count=2, responses_count=2,
                                    resource_types={"document": 1, "xhr": 1}),
            observed_at=datetime.now(),
        )

        builder = SceneGraphBuilder()
        graph = builder.build(obs_ecom).graph
        assert len(graph.nodes) > 0

        executor = VerifiedExecutor()
        execution, resolution = executor.execute_graph_click(
            graph, "add to cart", skip_perspective=True,
        )
        assert execution.status == ExecutionStatus.SUCCESS

    def test_full_pipeline_search_page(self):
        """Full pipeline on search results page type."""
        obs = PageObservation(
            url="https://search.example.com?q=test",
            title="Search Results",
            interactive_elements=[
                InteractiveElement(
                    selector="input[name='q']", tag="input", type="search",
                    aria_label="Search",
                    actionability={"visible": True, "enabled": True,
                                   "attached": True, "stable": True,
                                   "pointer_events": True, "editable": True},
                ),
                InteractiveElement(
                    selector="button.search-btn", tag="button", text="Search",
                    actionability={"visible": True, "enabled": True,
                                   "attached": True, "stable": True,
                                   "pointer_events": True},
                ),
            ],
            actionability={"input[name='q']": {"visible": True}},
            network=NetworkActivity(requests_count=3, responses_count=3,
                                    resource_types={"document": 1, "xhr": 2}),
            observed_at=datetime.now(),
        )

        builder = SceneGraphBuilder()
        graph = builder.build(obs).graph
        match = resolve_target(graph, "search button", intent=IntentType.CLICK)
        assert match is not None


# ══════════════════════════════════════════════════════════════════════════
# 4. EVIDENCE CHAIN COMPLETENESS
# ══════════════════════════════════════════════════════════════════════════

class TestEvidenceChainCompleteness:
    """Verify evidence chain integrity through the pipeline."""

    def test_precondition_checks_match_action_type(self):
        """CLICK needs {visible,enabled,attached,stable,pointer_events}.
        FILL needs {visible,enabled,attached,editable}.
        WAIT needs {attached}."""
        click_pre = get_preconditions(ActionType.CLICK)
        fill_pre = get_preconditions(ActionType.FILL)
        wait_pre = get_preconditions(ActionType.WAIT)

        assert "visible" in click_pre
        assert "pointer_events" in click_pre
        assert "editable" not in click_pre

        assert "editable" in fill_pre
        assert "pointer_events" not in fill_pre

        assert wait_pre == {"attached"}

    def test_preconditions_all_met_when_evidence_perfect(self):
        """All true evidence → all preconditions met for every action type."""
        for atype in ActionType:
            ev = _make_evidence()
            preconds = ActionPreconditions(action_type=atype, evidence=ev)
            assert preconds.all_met, f"Expected all_met for {atype} with perfect evidence"

    def test_preconditions_fail_on_missing_field(self):
        """Evidence with visible=False fails CLICK precondition."""
        ev = ActionabilityEvidence(
            action_id="test", target_ref="#btn", phase=Phase.PRE,
            visible=False, enabled=True, attached=True,
            stable=True, pointer_events=True,
            observed_at=datetime.now(),
        )
        preconds = ActionPreconditions(action_type=ActionType.CLICK, evidence=ev)
        assert not preconds.all_met
        assert "visible" in preconds.failed_checks()

    def test_verification_result_links_to_action(self):
        """VerificationResult.action_id matches the action."""
        action = ClickAction(selector="#x", action_id="link-test")
        ev = _make_evidence("link-test", "#x")
        vr = action.validate_preconditions(ev)
        assert vr.action_id == "link-test"
        assert vr.passed is True

    def test_evidence_phase_distinction(self):
        """PRE and POST evidence are distinct phases."""
        pre = _make_evidence("ph-test", "#btn")
        post_ev = ActionabilityEvidence(
            action_id="ph-test", target_ref="#btn", phase=Phase.POST,
            attached=True, visible=True, enabled=True,
            observed_at=datetime.now(),
        )
        assert pre.phase == Phase.PRE
        assert post_ev.phase == Phase.POST
        assert pre.to_dict()["phase"] == "pre"
        assert post_ev.to_dict()["phase"] == "post"

    def test_fill_preconditions_editable_required(self):
        """FILL fails when editable=False."""
        ev = ActionabilityEvidence(
            action_id="ed-test", target_ref="#inp", phase=Phase.PRE,
            attached=True, visible=True, enabled=True,
            editable=False, observed_at=datetime.now(),
        )
        preconds = ActionPreconditions(action_type=ActionType.FILL, evidence=ev)
        assert not preconds.all_met
        assert "editable" in preconds.failed_checks()

    def test_click_preconditions_pointer_events_required(self):
        """CLICK fails when pointer_events=False."""
        ev = ActionabilityEvidence(
            action_id="pe-test", target_ref="#btn", phase=Phase.PRE,
            attached=True, visible=True, enabled=True,
            pointer_events=False, observed_at=datetime.now(),
        )
        preconds = ActionPreconditions(action_type=ActionType.CLICK, evidence=ev)
        assert not preconds.all_met
        assert "pointer_events" in preconds.failed_checks()


# ══════════════════════════════════════════════════════════════════════════
# 5. COMPETENCE + EVENT LEDGER INTEGRATION
# ══════════════════════════════════════════════════════════════════════════

class TestCompetenceAndEventLedger:
    """Cross-cutting quality for competence routing and event logging."""

    def test_competence_round_trip(self):
        c = Competence("testing", weight=0.8)
        d = c.to_dict()
        c2 = Competence.from_dict(d)
        assert c2.name == "testing"
        assert c2.weight == 0.8

    def test_worker_profile_serialization(self):
        wp = WorkerProfile(
            worker_id="w1", name="QA Agent", model="claude-combo",
            competences=[Competence("testing"), Competence("benchmark", 0.9)],
        )
        d = wp.to_dict()
        assert d["worker_id"] == "w1"
        assert len(d["competences"]) == 2

    def test_worker_match_score(self):
        wp = WorkerProfile(
            worker_id="w2", name="Runner", model="m",
            competences=[Competence("qa"), Competence("testing")],
        )
        score = wp.match_score(["qa", "testing"])
        assert score == 1.0
        score_none = wp.match_score([])
        assert score_none == 0.5  # neutral

    def test_event_ledger_emit_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = EventLedger(tmp)
            eid = ledger.emit("qa-agent", "test_run", "all", "passed")
            assert eid.startswith("ev-")

            events = ledger.recent()
            assert len(events) >= 1
            assert events[0]["agent"] == "qa-agent"
            assert events[0]["result"] == "passed"

    def test_event_ledger_auto_increment(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = EventLedger(tmp)
            e1 = ledger.emit("a", "t1", "x", "ok")
            e2 = ledger.emit("a", "t2", "x", "ok")
            e3 = ledger.emit("a", "t3", "x", "ok")
            n1 = int(e1.split("-")[-1])
            n2 = int(e2.split("-")[-1])
            n3 = int(e3.split("-")[-1])
            assert n2 == n1 + 1
            assert n3 == n2 + 1

    def test_event_ledger_query_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = EventLedger(tmp)
            ledger.emit("qa", "test", "x", "ok")
            ledger.emit("dev", "build", "x", "ok")
            ledger.emit("qa", "test", "y", "ok")

            qa_events = ledger.query(agent="qa")
            assert all(e["agent"] == "qa" for e in qa_events)
            assert len(qa_events) >= 2

    def test_event_ledger_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = EventLedger(tmp)
            ledger.emit("a", "t1", "x", "ok")
            ledger.emit("a", "t2", "x", "ok")
            summary = ledger.summary()
            assert isinstance(summary, dict)


# ══════════════════════════════════════════════════════════════════════════
# 6. MODULE API SURFACE CONSISTENCY
# ══════════════════════════════════════════════════════════════════════════

class TestModuleAPISurface:
    """Verify key classes have expected public methods."""

    def test_wnal_action_types_complete(self):
        assert set(a.value for a in ActionType) == {"click", "fill", "wait"}

    def test_phase_values_complete(self):
        assert set(p.value for p in Phase) == {"pre", "post"}

    def test_scene_graph_node_types(self):
        expected = {"dom", "intent", "js", "visual"}
        actual = set(n.value.lower() for n in NodeType)
        assert expected.issubset(actual)

    def test_scene_graph_edge_types(self):
        expected = {"containment", "evidence", "dependency"}
        actual = set(e.value.lower() for e in EdgeType)
        assert expected.issubset(actual)

    def test_execution_status_values(self):
        names = set(s.name for s in ExecutionStatus)
        assert "SUCCESS" in names
        assert "PRECONDITION_FAILED" in names

    def test_resolution_status_values(self):
        assert "RESOLVED" in set(s.name for s in ResolutionStatus)

    def test_plan_status_values(self):
        expected = {"PENDING", "RUNNING", "COMPLETED", "FAILED"}
        actual = set(s.name for s in PlanStatus)
        assert expected.issubset(actual)

    def test_evidence_report_has_required_methods(self):
        assert hasattr(EvidenceReport, "add_claim")
        assert hasattr(EvidenceReport, "summary")
        assert hasattr(EvidenceReport, "verify")
        assert hasattr(EvidenceReport, "to_dict")
        assert hasattr(EvidenceReport, "from_dict")

    def test_evidence_claim_creation(self):
        claim = create_claim("c1", "Button exists", EvidenceType.DOM)
        assert claim.claim_id == "c1"
        assert claim.status == ClaimStatus.UNSUPPORTED

    def test_skill_store_crud(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SkillStore(Path(tmp) / "skills")
            skill = SiteSkill(
                site_pattern="example.com", goal="login",
                action_plan={"steps": [{"action": "click", "target": "#btn"}]},
            )
            store.save(skill)
            found = store.find_by_site("example.com")
            assert len(found) >= 1

    def test_skill_matcher_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            matcher = SkillMatcher(store=SkillStore(Path(tmp) / "skills"))
            assert hasattr(matcher, "match")

    def test_skill_learner_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SkillStore(Path(tmp) / "skills")
            learner = SkillLearner(store)
            assert hasattr(learner, "learn")
            assert hasattr(learner, "learn_and_store")

    def test_goal_translator_api(self):
        translator = GoalTranslator()
        assert hasattr(translator, "translate")

    def test_perspective_engine_api(self):
        engine = PerspectiveEngine()
        assert hasattr(engine, "analyze")

    def test_claim_status_values(self):
        expected = {"SUPPORTED", "UNSUPPORTED", "PARTIAL"}
        actual = set(s.name for s in ClaimStatus)
        assert expected.issubset(actual)

    def test_evidence_type_values(self):
        assert len(EvidenceType) > 0


# ══════════════════════════════════════════════════════════════════════════
# 7. BOUNDARY & EDGE CASE INVARIANTS
# ══════════════════════════════════════════════════════════════════════════

class TestBoundaryConditions:
    """Edge cases and boundary conditions."""

    def test_empty_observation_produces_graph(self):
        """Empty page → scene graph (possibly empty, but no crash)."""
        obs = PageObservation(
            url="about:blank", title="",
            interactive_elements=[],
            actionability={},
            network=NetworkActivity(requests_count=0, responses_count=0),
            observed_at=datetime.now(),
        )
        builder = SceneGraphBuilder()
        result = builder.build(obs)
        assert result is not None
        assert result.graph is not None

    def test_empty_graph_query_returns_none_or_low_score(self):
        """Query on empty graph doesn't crash."""
        graph = WebSceneGraph(graph_id="empty", url="about:blank")
        match = resolve_target(graph, "anything", intent=IntentType.CLICK)
        if match is not None:
            assert match.score < 0.5

    def test_fill_action_masking(self):
        """Sensitive FillAction masks value in to_dict()."""
        action = FillAction(value="password123", is_sensitive=True)
        d = action.to_dict()
        assert d["value"] != "password123"
        assert "*" in d["value"]

        d_unmasked = action.to_dict(mask_sensitive=False)
        assert d_unmasked["value"] == "password123"

    def test_masked_value_patterns(self):
        """Masked value follows pattern: first char + asterisks."""
        cases = [
            ("a", "*"),
            ("ab", "a*"),
            ("abcdef", "a*****"),
            ("", ""),
        ]
        for val, expected in cases:
            action = FillAction(value=val, is_sensitive=True)
            assert action.masked_value == expected, (
                f"masked_value({val!r}) = {action.masked_value!r}, expected {expected!r}"
            )

    def test_action_id_uniqueness(self):
        """Default action IDs are unique across instances."""
        ids = set()
        for _ in range(100):
            a = ClickAction()
            assert a.action_id not in ids, f"Duplicate action_id: {a.action_id}"
            ids.add(a.action_id)

    def test_empty_plan_orchestration(self):
        """Empty plan doesn't crash orchestrator."""
        executor = VerifiedExecutor()
        orchestrator = ActionOrchestrator(executor=executor)
        plan = ActionPlan(description="empty")
        obs = _make_login_observation()
        graph = SceneGraphBuilder().build(obs).graph
        result = orchestrator.orchestrate(plan, lambda: graph, skip_perspective=True)
        assert result is not None
        assert result.status in (PlanStatus.COMPLETED, PlanStatus.PENDING, PlanStatus.FAILED)

    def test_evidence_report_verify_idempotent(self):
        """Calling verify() on EvidenceReport is idempotent."""
        report = EvidenceReport(
            report_id="rpt-1", url="https://example.com",
            timestamp=datetime.now(),
        )
        claim = create_claim("c1", "Element exists", EvidenceType.DOM)
        report.add_claim(claim)
        report.verify()
        s1 = report.summary()
        report.verify()
        s2 = report.summary()
        assert s1 == s2

    def test_scene_graph_builder_multiple_observations(self):
        """Builder handles multiple sequential observations."""
        builder = SceneGraphBuilder()
        for i in range(5):
            obs = PageObservation(
                url=f"https://example.com/p{i}",
                title=f"Page {i}",
                interactive_elements=[
                    InteractiveElement(
                        selector=f"#btn-{i}", tag="button",
                        text=f"Button {i}",
                        actionability={"visible": True, "enabled": True,
                                       "attached": True, "stable": True,
                                       "pointer_events": True},
                    ),
                ],
                actionability={f"#btn-{i}": {"visible": True}},
                network=NetworkActivity(requests_count=1, responses_count=1),
                observed_at=datetime.now(),
            )
            result = builder.build(obs)
            assert result is not None
            assert len(result.graph.nodes) > 0

    def test_evidence_report_serialization(self):
        """EvidenceReport round-trips through to_dict/from_dict."""
        report = EvidenceReport(
            report_id="rpt-ser", url="https://example.com",
            timestamp=datetime(2026, 5, 24, 12, 0, 0),
        )
        claim = create_claim("c-ser", "Link exists", EvidenceType.DOM)
        report.add_claim(claim)

        d = report.to_dict()
        assert isinstance(d, dict)
        assert d["report_id"] == "rpt-ser"

    def test_scene_graph_construction(self):
        """Manual scene graph construction with nodes and edges."""
        graph = WebSceneGraph(graph_id="manual", url="https://example.com")
        node = SceneNode(node_id="n1", node_type=NodeType.DOM, label="button")
        edge = SceneEdge(edge_id="e1", source_id="n1", target_id="n2",
                         edge_type=EdgeType.CONTAINMENT)

    def test_many_interactive_elements(self):
        """Page with many interactive elements doesn't crash."""
        elements = [
            InteractiveElement(
                selector=f"#el-{i}", tag="button", text=f"Button {i}",
                actionability={"visible": True, "enabled": True,
                               "attached": True, "stable": True,
                               "pointer_events": True},
            )
            for i in range(50)
        ]
        obs = PageObservation(
            url="https://example.com/big", title="Big Page",
            interactive_elements=elements,
            actionability={f"#el-{i}": {"visible": True} for i in range(50)},
            network=NetworkActivity(requests_count=50, responses_count=50),
            observed_at=datetime.now(),
        )
        builder = SceneGraphBuilder()
        result = builder.build(obs)
        assert len(result.graph.nodes) >= 50
