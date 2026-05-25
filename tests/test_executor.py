"""Tests for NetWeaver Verified Executor.

Covers:
- Successful verified click execution (full pipeline)
- Precondition failure (element not visible/enabled)
- Perspective block (safety abort)
- Perspective ASK (confirmation required)
- Execution error (action executor fails)
- Evidence report structure (pre/post observations and claims)
- Serialization round-trip
- execute_click convenience method
- Custom evidence collectors and action executors
- Pre/post evidence phase tracking
"""

import pytest
from datetime import datetime

from netweaver.wnal import (
    ActionabilityEvidence,
    ActionType,
    ClickAction,
    FillAction,
    Phase,
    TypedAction,
    WaitAction,
)
from netweaver.perspective import ResolutionStrategy
from netweaver.evidence import EvidenceType, ClaimStatus
from netweaver.executor import (
    ExecutionStatus,
    PrePostEvidence,
    VerifiedExecution,
    VerifiedExecutor,
    mock_evidence_collector,
    mock_action_executor,
    _build_evidence_report,
    _make_id,
)


# ── Fixtures ─────────────────────────────────────────────────────────

def _make_action(action_type: ActionType = ActionType.CLICK, **kwargs) -> TypedAction:
    """Create a test action with defaults."""
    defaults = {
        "action_id": "test-action-001",
        "target_ref": "button#submit",
    }
    defaults.update(kwargs)
    if action_type == ActionType.CLICK:
        return ClickAction(
            action_id=defaults["action_id"],
            target_ref=defaults["target_ref"],
            button=kwargs.get("button", "left"),
        )
    return TypedAction(
        action_id=defaults["action_id"],
        action_type=action_type,
        target_ref=defaults["target_ref"],
    )


def _make_evidence(
    phase: Phase = Phase.PRE,
    attached: bool = True,
    visible: bool = True,
    enabled: bool = True,
    editable: bool = False,
    stable: bool = True,
    pointer_events: bool = True,
) -> ActionabilityEvidence:
    """Create test evidence with defaults."""
    return ActionabilityEvidence(
        action_id="test-action-001",
        target_ref="button#submit",
        phase=phase,
        attached=attached,
        visible=visible,
        enabled=enabled,
        editable=editable,
        stable=stable,
        pointer_events=pointer_events,
        observed_at=datetime.now(),
    )


# ── Helper Tests ─────────────────────────────────────────────────────

class TestMakeId:
    def test_with_prefix(self):
        uid = _make_id("exec")
        assert uid.startswith("exec-")
        assert len(uid) > 5

    def test_without_prefix(self):
        uid = _make_id()
        assert len(uid) == 16

    def test_uniqueness(self):
        ids = {_make_id("x") for _ in range(100)}
        assert len(ids) == 100


class TestMockCallbacks:
    def test_mock_evidence_collector(self):
        ev = mock_evidence_collector("act-1", "button#x")
        assert ev.action_id == "act-1"
        assert ev.target_ref == "button#x"
        assert ev.phase == Phase.PRE
        assert ev.attached is True
        assert ev.visible is True
        assert ev.enabled is True

    def test_mock_action_executor(self):
        assert mock_action_executor(_make_action()) is True


# ── PrePostEvidence Tests ────────────────────────────────────────────

class TestPrePostEvidence:
    def test_empty(self):
        pp = PrePostEvidence()
        d = pp.to_dict()
        assert d["pre"] is None
        assert d["post"] is None

    def test_with_pre_only(self):
        ev = _make_evidence()
        pp = PrePostEvidence(pre=ev)
        d = pp.to_dict()
        assert d["pre"] is not None
        assert d["pre"]["phase"] == "pre"
        assert d["post"] is None

    def test_with_both(self):
        pre = _make_evidence(phase=Phase.PRE)
        post = _make_evidence(phase=Phase.POST)
        pp = PrePostEvidence(pre=pre, post=post)
        d = pp.to_dict()
        assert d["pre"]["phase"] == "pre"
        assert d["post"]["phase"] == "post"


# ── VerifiedExecution Serialization ──────────────────────────────────

class TestVerifiedExecutionSerialization:
    def test_success_serialization(self):
        exec_result = VerifiedExecution(
            execution_id="exec-001",
            action=_make_action(),
            status=ExecutionStatus.SUCCESS,
            evidence=PrePostEvidence(
                pre=_make_evidence(Phase.PRE),
                post=_make_evidence(Phase.POST),
            ),
        )
        d = exec_result.to_dict()
        assert d["execution_id"] == "exec-001"
        assert d["status"] == "success"
        assert d["action"]["action_type"] == "click"
        assert d["evidence"]["pre"] is not None
        assert d["evidence"]["post"] is not None
        assert d["perspective_resolution"] is None
        assert d["report"] is None
        assert d["error"] is None

    def test_failed_serialization(self):
        exec_result = VerifiedExecution(
            execution_id="exec-002",
            action=_make_action(),
            status=ExecutionStatus.PRECONDITION_FAILED,
            evidence=PrePostEvidence(pre=_make_evidence()),
            error="Preconditions failed: ['visible']",
        )
        d = exec_result.to_dict()
        assert d["status"] == "precondition_failed"
        assert d["error"] is not None


# ── VerifiedExecutor: Successful Execution ───────────────────────────

class TestSuccessfulExecution:
    def test_full_pipeline_success(self):
        executor = VerifiedExecutor()
        action = _make_action()
        result = executor.execute(action, skip_perspective=True)

        assert result.status == ExecutionStatus.SUCCESS
        assert result.evidence.pre is not None
        assert result.evidence.post is not None
        assert result.evidence.pre.phase == Phase.PRE
        assert result.evidence.post.phase == Phase.POST
        assert result.error is None
        assert result.report is not None

    def test_evidence_report_verified(self):
        executor = VerifiedExecutor()
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.report is not None
        assert result.report.verify() is True

    def test_report_has_pre_post_observations(self):
        executor = VerifiedExecutor()
        result = executor.execute(_make_action(), skip_perspective=True)

        obs = result.report.observations
        assert len(obs) == 2  # pre + post
        types = {o.evidence_type for o in obs}
        assert types == {EvidenceType.ACTIONABILITY}

    def test_report_has_pre_post_claims(self):
        executor = VerifiedExecutor()
        result = executor.execute(_make_action(), skip_perspective=True)

        claims = result.report.claims
        assert len(claims) == 2  # pre-claim + post-claim
        result.report.verify()  # Set claim statuses
        assert all(c.status == ClaimStatus.SUPPORTED for c in claims)

    def test_execute_click_convenience(self):
        executor = VerifiedExecutor()
        result = executor.execute_click("button#submit", skip_perspective=True)

        assert result.status == ExecutionStatus.SUCCESS
        assert result.action.action_type == ActionType.CLICK
        assert result.action.target_ref == "button#submit"

    def test_execution_id_unique(self):
        executor = VerifiedExecutor()
        r1 = executor.execute(_make_action(action_id="a1"), skip_perspective=True)
        r2 = executor.execute(_make_action(action_id="a2"), skip_perspective=True)
        assert r1.execution_id != r2.execution_id


# ── VerifiedExecutor: Precondition Failures ──────────────────────────

class TestPreconditionFailures:
    def test_not_visible(self):
        def collector(aid, target):
            return _make_evidence(visible=False)

        executor = VerifiedExecutor(evidence_collector=collector)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.status == ExecutionStatus.PRECONDITION_FAILED
        assert "visible" in result.error

    def test_not_enabled(self):
        def collector(aid, target):
            return _make_evidence(enabled=False)

        executor = VerifiedExecutor(evidence_collector=collector)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.status == ExecutionStatus.PRECONDITION_FAILED
        assert "enabled" in result.error

    def test_not_attached(self):
        def collector(aid, target):
            return _make_evidence(attached=False)

        executor = VerifiedExecutor(evidence_collector=collector)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.status == ExecutionStatus.PRECONDITION_FAILED
        assert "attached" in result.error

    def test_not_stable(self):
        def collector(aid, target):
            return _make_evidence(stable=False)

        executor = VerifiedExecutor(evidence_collector=collector)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.status == ExecutionStatus.PRECONDITION_FAILED
        assert "stable" in result.error

    def test_no_pointer_events(self):
        def collector(aid, target):
            return _make_evidence(pointer_events=False)

        executor = VerifiedExecutor(evidence_collector=collector)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.status == ExecutionStatus.PRECONDITION_FAILED
        assert "pointer_events" in result.error

    def test_fill_needs_editable(self):
        def collector(aid, target):
            # Return evidence matching the action's target
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=False,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        action = FillAction(
            action_id="test-fill-001",
            target_ref="input#email",
            text="test@example.com",
        )
        executor = VerifiedExecutor(evidence_collector=collector)
        result = executor.execute(action, skip_perspective=True)

        assert result.status == ExecutionStatus.PRECONDITION_FAILED
        assert "editable" in result.error

    def test_precondition_failure_still_has_pre_evidence(self):
        def collector(aid, target):
            return _make_evidence(visible=False)

        executor = VerifiedExecutor(evidence_collector=collector)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.evidence.pre is not None
        assert result.evidence.pre.visible is False
        assert result.evidence.post is None


# ── VerifiedExecutor: Perspective Blocking ───────────────────────────

class TestPerspectiveBlocking:
    def test_safety_abort(self):
        """Critical risk level → perspective ABORT → execution blocked."""
        executor = VerifiedExecutor()
        result = executor.execute(
            _make_action(),
            context={"risk_level": "critical"},
        )

        assert result.status == ExecutionStatus.PERSPECTIVE_BLOCKED
        assert result.perspective_resolution is not None
        assert result.perspective_resolution.strategy == ResolutionStrategy.ABORT

    def test_safety_ask_blocks_automated(self):
        """High risk → perspective ASK → automated mode blocks."""
        executor = VerifiedExecutor()
        result = executor.execute(
            _make_action(),
            context={"risk_level": "high"},
        )

        assert result.status == ExecutionStatus.PERSPECTIVE_BLOCKED
        assert result.perspective_resolution is not None
        assert result.perspective_resolution.strategy == ResolutionStrategy.ASK

    def test_safe_context_passes_perspective(self):
        """Low risk + all clear → perspective ACTION → execution proceeds."""
        executor = VerifiedExecutor()
        result = executor.execute(
            _make_action(),
            context={"risk_level": "low"},
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert result.perspective_resolution is not None
        assert result.perspective_resolution.strategy == ResolutionStrategy.ACTION

    def test_skip_perspective(self):
        """skip_perspective=True bypasses perspective analysis entirely."""
        executor = VerifiedExecutor()
        result = executor.execute(
            _make_action(),
            context={"risk_level": "critical"},
            skip_perspective=True,
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert result.perspective_resolution is None


# ── VerifiedExecutor: Execution Errors ───────────────────────────────

class TestExecutionErrors:
    def test_executor_returns_false(self):
        def failing_executor(action):
            return False

        executor = VerifiedExecutor(action_executor=failing_executor)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.status == ExecutionStatus.EXECUTION_ERROR
        assert "failure" in result.error.lower()

    def test_executor_raises_exception(self):
        def crashing_executor(action):
            raise RuntimeError("Browser crashed")

        executor = VerifiedExecutor(action_executor=crashing_executor)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.status == ExecutionStatus.EXECUTION_ERROR
        assert "Browser crashed" in result.error


# ── VerifiedExecutor: Custom Callbacks ───────────────────────────────

class TestCustomCallbacks:
    def test_custom_evidence_collector(self):
        """Custom collector that tracks call count."""
        calls = []

        def tracking_collector(aid, target):
            calls.append((aid, target))
            return _make_evidence()

        executor = VerifiedExecutor(evidence_collector=tracking_collector)
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.status == ExecutionStatus.SUCCESS
        assert len(calls) == 2  # PRE + POST
        assert calls[0][0] == "test-action-001"
        assert calls[1][0] == "test-action-001"

    def test_custom_action_executor(self):
        """Custom executor that records the action it received."""
        executed_actions = []

        def recording_executor(action):
            executed_actions.append(action)
            return True

        executor = VerifiedExecutor(action_executor=recording_executor)
        action = _make_action()
        result = executor.execute(action, skip_perspective=True)

        assert result.status == ExecutionStatus.SUCCESS
        assert len(executed_actions) == 1
        assert executed_actions[0].action_id == action.action_id


# ── Build Evidence Report ───────────────────────────────────────────

class TestBuildEvidenceReport:
    def test_report_with_post(self):
        action = _make_action()
        pre = _make_evidence(Phase.PRE)
        post = _make_evidence(Phase.POST)

        report = _build_evidence_report(
            VerifiedExecution(
                execution_id="test",
                action=action,
                status=ExecutionStatus.SUCCESS,
                evidence=PrePostEvidence(pre=pre, post=post),
            ),
            action,
            pre,
            post,
        )

        assert report.verify() is True
        assert len(report.observations) == 2
        assert len(report.claims) == 2

    def test_report_without_post(self):
        action = _make_action()
        pre = _make_evidence(Phase.PRE)

        report = _build_evidence_report(
            VerifiedExecution(
                execution_id="test",
                action=action,
                status=ExecutionStatus.PRECONDITION_FAILED,
                evidence=PrePostEvidence(pre=pre),
            ),
            action,
            pre,
            None,
        )

        assert len(report.observations) == 1  # pre only
        assert len(report.claims) == 1  # pre-claim only

    def test_report_claims_link_to_observations(self):
        action = _make_action()
        pre = _make_evidence(Phase.PRE)
        post = _make_evidence(Phase.POST)

        report = _build_evidence_report(
            VerifiedExecution(
                execution_id="test",
                action=action,
                status=ExecutionStatus.SUCCESS,
                evidence=PrePostEvidence(pre=pre, post=post),
            ),
            action,
            pre,
            post,
        )

        obs_ids = {o.observation_id for o in report.observations}
        for claim in report.claims:
            for oid in claim.observation_ids:
                assert oid in obs_ids


# ── Edge Cases ───────────────────────────────────────────────────────

class TestEdgeCases:
    def test_execute_with_none_context(self):
        executor = VerifiedExecutor()
        result = executor.execute(_make_action(), context=None, skip_perspective=True)
        assert result.status == ExecutionStatus.SUCCESS

    def test_execute_with_empty_context(self):
        executor = VerifiedExecutor()
        result = executor.execute(_make_action(), context={}, skip_perspective=True)
        assert result.status == ExecutionStatus.SUCCESS

    def test_multiple_executions_independent(self):
        executor = VerifiedExecutor()
        r1 = executor.execute_click("button#a", skip_perspective=True)
        r2 = executor.execute_click("button#b", skip_perspective=True)

        assert r1.execution_id != r2.execution_id
        assert r1.action.target_ref != r2.action.target_ref
        assert r1.report is not r2.report
        assert r1.report.report_id != r2.report.report_id

    def test_pre_evidence_phase_preserved(self):
        """PRE collector output has Phase.PRE even though we don't set it."""
        executor = VerifiedExecutor()
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.evidence.pre.phase == Phase.PRE

    def test_post_evidence_phase_changed_to_post(self):
        """Executor flips POST evidence phase from PRE to POST."""
        executor = VerifiedExecutor()
        result = executor.execute(_make_action(), skip_perspective=True)

        assert result.evidence.post is not None
        assert result.evidence.post.phase == Phase.POST


# ── Fill/Wait Convenience Methods ───────────────────────────────────

class TestExecuteFill:
    """Tests for execute_fill() convenience method."""

    def test_fill_success(self):
        """Fill action succeeds with editable evidence."""
        def fill_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=True,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=fill_collector)
        result = executor.execute_fill("input#email", "user@example.com", skip_perspective=True)

        assert result.status == ExecutionStatus.SUCCESS
        assert result.action.action_type == ActionType.FILL
        assert result.action.target_ref == "input#email"
        assert result.action.text == "user@example.com"
        assert result.evidence.pre is not None
        assert result.evidence.post is not None
        assert result.report is not None
        assert result.report.verify() is True

    def test_fill_not_editable_fails(self):
        """Fill action fails preconditions when element not editable."""
        def non_editable_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=False,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=non_editable_collector)
        result = executor.execute_fill("div#readonly", "text", skip_perspective=True)

        assert result.status == ExecutionStatus.PRECONDITION_FAILED
        assert "editable" in result.error
        assert result.evidence.post is None

    def test_fill_with_perspective(self):
        """Fill runs through perspective analysis."""
        def editable_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=True,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=editable_collector)
        result = executor.execute_fill(
            "input#email", "user@example.com",
            context={"risk_level": "low"},
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert result.perspective_resolution is not None
        assert result.perspective_resolution.strategy == ResolutionStrategy.ACTION

    def test_fill_blocked_by_critical_risk(self):
        """Fill blocked by critical risk perspective."""
        def editable_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=True,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=editable_collector)
        result = executor.execute_fill(
            "input#card", "4111111111111111",
            context={"risk_level": "critical"},
        )

        assert result.status == ExecutionStatus.PERSPECTIVE_BLOCKED

    def test_fill_evidence_report_has_fill_action(self):
        """Evidence report references fill action correctly."""
        def fill_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=True,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=fill_collector)
        result = executor.execute_fill("input#search", "query", skip_perspective=True)

        assert result.report is not None
        pre_claim = result.report.claims[0]
        assert "fill" in pre_claim.description.lower()
        assert "input#search" in pre_claim.description

    def test_fill_serialization(self):
        """Fill execution serializes correctly."""
        def fill_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=True,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=fill_collector)
        result = executor.execute_fill("textarea#body", "Hello world", skip_perspective=True)
        d = result.to_dict()

        assert d["action"]["action_type"] == "fill"
        assert d["action"]["text"] == "Hello world"
        assert d["action"]["target_ref"] == "textarea#body"
        assert d["status"] == "success"


class TestExecuteWait:
    """Tests for execute_wait() convenience method."""

    def test_wait_success_attached(self):
        """Wait action succeeds — only needs 'attached' precondition."""
        def wait_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=False,  # Not visible, but wait doesn't require it
                enabled=False,
                editable=False,
                stable=False,
                pointer_events=False,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=wait_collector)
        result = executor.execute_wait(
            "div#dynamic-element", condition="attached", skip_perspective=True,
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert result.action.action_type == ActionType.WAIT
        assert result.action.target_ref == "div#dynamic-element"
        assert result.action.condition == "attached"
        assert result.action.timeout_ms == 5000

    def test_wait_not_attached_fails(self):
        """Wait fails when element not attached (only required precondition)."""
        def detached_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=False,
                visible=False,
                enabled=False,
                editable=False,
                stable=False,
                pointer_events=False,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=detached_collector)
        result = executor.execute_wait("div#missing", skip_perspective=True)

        assert result.status == ExecutionStatus.PRECONDITION_FAILED
        assert "attached" in result.error

    def test_wait_custom_timeout(self):
        """Wait respects custom timeout_ms parameter."""
        executor = VerifiedExecutor()
        result = executor.execute_wait(
            "div#slow", condition="visible", timeout_ms=10000, skip_perspective=True,
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert result.action.timeout_ms == 10000
        assert result.action.condition == "visible"

    def test_wait_with_perspective(self):
        """Wait runs through perspective analysis."""
        executor = VerifiedExecutor()
        result = executor.execute_wait(
            "div#element", condition="attached",
            context={"risk_level": "low"},
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert result.perspective_resolution is not None

    def test_wait_evidence_report(self):
        """Wait produces valid evidence report."""
        executor = VerifiedExecutor()
        result = executor.execute_wait("span#status", skip_perspective=True)

        assert result.report is not None
        assert result.report.verify() is True
        assert len(result.report.observations) == 2  # pre + post
        assert len(result.report.claims) == 2  # pre-claim + post-claim

    def test_wait_serialization(self):
        """Wait execution serializes correctly."""
        executor = VerifiedExecutor()
        result = executor.execute_wait(
            "div#async", condition="stable", timeout_ms=3000, skip_perspective=True,
        )
        d = result.to_dict()

        assert d["action"]["action_type"] == "wait"
        assert d["action"]["condition"] == "stable"
        assert d["action"]["timeout_ms"] == 3000
        assert d["status"] == "success"


class TestAllActionTypes:
    """Cross-action-type tests ensuring all three convenience methods work consistently."""

    def test_all_actions_independent(self):
        """Click, fill, wait produce independent executions."""
        def fillable_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=True,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=fillable_collector)
        click_r = executor.execute_click("button#go", skip_perspective=True)
        fill_r = executor.execute_fill("input#name", "Alice", skip_perspective=True)
        wait_r = executor.execute_wait("div#result", skip_perspective=True)

        assert click_r.status == ExecutionStatus.SUCCESS
        assert fill_r.status == ExecutionStatus.SUCCESS
        assert wait_r.status == ExecutionStatus.SUCCESS

        # All unique execution IDs
        ids = {click_r.execution_id, fill_r.execution_id, wait_r.execution_id}
        assert len(ids) == 3

        # Correct action types
        assert click_r.action.action_type == ActionType.CLICK
        assert fill_r.action.action_type == ActionType.FILL
        assert wait_r.action.action_type == ActionType.WAIT

    def test_all_actions_produce_evidence_reports(self):
        """All action types produce valid evidence reports on success."""
        def full_collector(aid, target):
            return ActionabilityEvidence(
                action_id=aid,
                target_ref=target,
                phase=Phase.PRE,
                attached=True,
                visible=True,
                enabled=True,
                editable=True,
                stable=True,
                pointer_events=True,
                observed_at=datetime.now(),
            )

        executor = VerifiedExecutor(evidence_collector=full_collector)
        for action_type, method in [
            (ActionType.CLICK, lambda: executor.execute_click("button#x", skip_perspective=True)),
            (ActionType.FILL, lambda: executor.execute_fill("input#y", "z", skip_perspective=True)),
            (ActionType.WAIT, lambda: executor.execute_wait("div#w", skip_perspective=True)),
        ]:
            result = method()
            assert result.report is not None
            assert result.report.verify() is True
            assert result.action.action_type == action_type


class TestLiveMode:
    """Tests for VerifiedExecutor in 'live' mode with CloakBrowserBridge."""

    def test_live_mode_requires_bridge(self):
        """Live mode without bridge raises ValueError."""
        with pytest.raises(ValueError, match="CloakBrowserBridge"):
            VerifiedExecutor(mode="live")

    def test_live_mode_accepts_bridge(self):
        """Live mode with bridge constructs successfully."""
        from netweaver.cloak_bridge import CloakBrowserBridge
        bridge = CloakBrowserBridge()
        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        assert executor.mode == "live"
        assert executor.cloak_bridge is bridge

    def test_live_evidence_collector_delegates_to_bridge(self):
        """_live_evidence_collector calls bridge.collect_evidence and returns ActionabilityEvidence."""
        from unittest.mock import MagicMock
        from netweaver.cloak_bridge import CloakBrowserBridge
        from netweaver.wnal import ActionabilityEvidence, Phase

        bridge = MagicMock(spec=CloakBrowserBridge)
        mock_evidence = ActionabilityEvidence(
            action_id="act-001",
            target_ref="button#submit",
            phase=Phase.PRE,
            attached=True,
            visible=True,
            enabled=True,
        )
        bridge.collect_evidence.return_value = mock_evidence

        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        result = executor._live_evidence_collector("act-001", "button#submit")

        bridge.collect_evidence.assert_called_once_with("act-001", "button#submit")
        assert result is mock_evidence
        assert result.attached is True
        assert result.visible is True

    def test_live_action_executor_delegates_to_bridge(self):
        """_live_action_executor calls bridge.execute_action and returns bool."""
        from unittest.mock import MagicMock
        from netweaver.cloak_bridge import CloakBrowserBridge
        from netweaver.wnal import ClickAction

        bridge = MagicMock(spec=CloakBrowserBridge)
        bridge.execute_action.return_value = True

        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        action = ClickAction(action_id="act-001", target_ref="button#submit")
        result = executor._live_action_executor(action)

        bridge.execute_action.assert_called_once_with(action)
        assert result is True

    def test_live_action_executor_failure_propagates(self):
        """When bridge.execute_action returns False, execution fails."""
        from unittest.mock import MagicMock
        from netweaver.cloak_bridge import CloakBrowserBridge
        from netweaver.wnal import ClickAction

        bridge = MagicMock(spec=CloakBrowserBridge)
        bridge.execute_action.return_value = False
        bridge.collect_evidence.return_value = None

        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        # Override evidence collector so pre-condition passes
        executor._evidence_collector = lambda aid, ref: ActionabilityEvidence(
            action_id=aid, target_ref=ref, phase=Phase.PRE,
            attached=True, visible=True, enabled=True,
        )

        action = ClickAction(action_id="act-001", target_ref="button#submit")
        result = executor.execute(action, skip_perspective=True)

        assert result.status == ExecutionStatus.EXECUTION_ERROR

    def test_existing_mock_tests_still_pass_without_bridge(self):
        """Existing mock-mode tests work unchanged — backward compat."""
        executor = VerifiedExecutor()
        result = executor.execute_click("button#submit", skip_perspective=True)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.report is not None

    def test_live_execute_click_success(self):
        """Full execute_click in live mode via mocked bridge."""
        from unittest.mock import MagicMock
        from netweaver.cloak_bridge import CloakBrowserBridge
        from netweaver.wnal import ActionabilityEvidence, Phase, ClickAction

        bridge = MagicMock(spec=CloakBrowserBridge)
        bridge.collect_evidence.return_value = ActionabilityEvidence(
            action_id="act-001", target_ref="button#submit", phase=Phase.PRE,
            attached=True, visible=True, enabled=True,
        )
        bridge.execute_action.return_value = True

        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        result = executor.execute_click("button#submit", skip_perspective=True)

        assert result.status == ExecutionStatus.SUCCESS
        assert result.report is not None
        assert bridge.collect_evidence.call_count >= 1  # pre + post
        bridge.execute_action.assert_called_once()

    def test_live_execute_fill_success(self):
        """Full execute_fill in live mode via mocked bridge."""
        from unittest.mock import MagicMock
        from netweaver.cloak_bridge import CloakBrowserBridge
        from netweaver.wnal import ActionabilityEvidence, Phase

        bridge = MagicMock(spec=CloakBrowserBridge)
        bridge.collect_evidence.return_value = ActionabilityEvidence(
            action_id="act-001", target_ref="input#search", phase=Phase.PRE,
            attached=True, visible=True, enabled=True, editable=True,
        )
        bridge.execute_action.return_value = True

        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        result = executor.execute_fill("input#search", "query", skip_perspective=True)

        assert result.status == ExecutionStatus.SUCCESS
        assert result.report is not None
        bridge.execute_action.assert_called_once()

    def test_live_execute_wait_success(self):
        """Full execute_wait in live mode via mocked bridge."""
        from unittest.mock import MagicMock
        from netweaver.cloak_bridge import CloakBrowserBridge
        from netweaver.wnal import ActionabilityEvidence, Phase

        bridge = MagicMock(spec=CloakBrowserBridge)
        bridge.collect_evidence.return_value = ActionabilityEvidence(
            action_id="act-001", target_ref="div#result", phase=Phase.PRE,
            attached=True, visible=False, enabled=False,
        )
        bridge.execute_action.return_value = True

        executor = VerifiedExecutor(mode="live", cloak_bridge=bridge)
        result = executor.execute_wait("div#result", skip_perspective=True)

        assert result.status == ExecutionStatus.SUCCESS
        assert result.report is not None
        bridge.execute_action.assert_called_once()
