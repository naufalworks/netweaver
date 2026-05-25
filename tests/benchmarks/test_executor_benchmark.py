"""Executor Benchmark Tests — NW-010

Acceptance tests for netweaver.executor using mocked callbacks.
Tests the 6-phase evidence-first pipeline: PRE → PRECONDITION → PERSPECTIVE → EXECUTE → POST → VERIFY.

No browser download, no Playwright, no network required.

Run: python -m pytest tests/benchmarks/test_executor_benchmark.py -v
"""

import pytest
from datetime import datetime

from netweaver.wnal import (
    ActionabilityEvidence,
    ActionType,
    ClickAction,
    FillAction,
    Phase,
)
from netweaver.executor import (
    ExecutionStatus,
    PrePostEvidence,
    VerifiedExecution,
    VerifiedExecutor,
    mock_action_executor,
    mock_evidence_collector,
)
from netweaver.evidence import EvidenceType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_evidence(
    action_id: str = "test-action",
    target_ref: str = "button#submit",
    phase: Phase = Phase.PRE,
    attached: bool = True,
    visible: bool = True,
    enabled: bool = True,
    editable: bool = False,
    stable: bool = True,
    pointer_events: bool = True,
) -> ActionabilityEvidence:
    return ActionabilityEvidence(
        action_id=action_id,
        target_ref=target_ref,
        phase=phase,
        attached=attached,
        visible=visible,
        enabled=enabled,
        editable=editable,
        stable=stable,
        pointer_events=pointer_events,
        observed_at=datetime.now(),
    )


def safe_context(**overrides):
    ctx = {
        "user_intent": "click submit button",
        "risk_level": "low",
        "payment_in_progress": False,
        "auth_state": "valid",
    }
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# E-001: Happy Path Click — Full Pipeline
# ---------------------------------------------------------------------------

class TestE001HappyPath:
    """E-001: Full pipeline succeeds on safe, visible, enabled element."""

    def test_returns_success(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e001", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        assert result.status == ExecutionStatus.SUCCESS

    def test_evidence_report_verifies(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e001", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        assert result.report is not None
        assert result.report.verify()

    def test_pre_and_post_observations(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e001", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        assert result.evidence.pre is not None
        assert result.evidence.post is not None
        assert result.evidence.pre.phase == Phase.PRE
        assert result.evidence.post.phase == Phase.POST

    def test_unique_execution_id(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e001", target_ref="button#submit")
        r1 = executor.execute(action, context=safe_context())
        r2 = executor.execute(action, context=safe_context())
        assert r1.execution_id != r2.execution_id

    def test_all_claims_supported(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e001", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        # Report verify() sets claim statuses
        report = result.report
        report.verify()
        for claim in report.claims:
            assert claim.status.value == "supported", f"Claim {claim.claim_id} not supported"

    def test_phase_ordering(self):
        """Verify execution went through all phases via callback tracking."""
        phases_seen = []
        def tracking_collector(action_id, target_ref):
            phases_seen.append(("collect", action_id))
            return make_evidence(action_id=action_id, target_ref=target_ref)

        def tracking_executor(action):
            phases_seen.append(("execute", action.action_id))
            return True

        executor = VerifiedExecutor(
            evidence_collector=tracking_collector,
            action_executor=tracking_executor,
        )
        action = ClickAction(action_id="e001", target_ref="button#submit")
        executor.execute(action, context=safe_context())
        # Should see: 2 collects (PRE + POST) + 1 execute
        assert len(phases_seen) == 3
        assert phases_seen[0][0] == "collect"
        assert phases_seen[1][0] == "execute"
        assert phases_seen[2][0] == "collect"

    def test_execution_timestamp_recorded(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e001", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        assert result.executed_at is not None


# ---------------------------------------------------------------------------
# E-002: Precondition Gate — Invisible Element
# ---------------------------------------------------------------------------

class TestE002InvisibleElement:
    """E-002: Click on hidden element is blocked at PRECONDITION phase."""

    def _make_invisible_collector(self):
        def invisible_collector(action_id, target_ref):
            return make_evidence(
                action_id=action_id,
                target_ref=target_ref,
                visible=False,
            )
        return invisible_collector

    def test_precondition_failed(self):
        executor = VerifiedExecutor(
            evidence_collector=self._make_invisible_collector(),
        )
        action = ClickAction(action_id="e002", target_ref="a[href='/hidden']")
        result = executor.execute(action, context=safe_context())
        assert result.status == ExecutionStatus.PRECONDITION_FAILED

    def test_no_execution_reached(self):
        executed = []
        def tracking_executor(action):
            executed.append(action.action_id)
            return True

        executor = VerifiedExecutor(
            evidence_collector=self._make_invisible_collector(),
            action_executor=tracking_executor,
        )
        action = ClickAction(action_id="e002", target_ref="a[href='/hidden']")
        executor.execute(action, context=safe_context())
        assert len(executed) == 0, "Executor should not have been called"

    def test_no_post_evidence(self):
        executor = VerifiedExecutor(
            evidence_collector=self._make_invisible_collector(),
        )
        action = ClickAction(action_id="e002", target_ref="a[href='/hidden']")
        result = executor.execute(action, context=safe_context())
        assert result.evidence.post is None

    def test_error_message_mentions_precondition(self):
        executor = VerifiedExecutor(
            evidence_collector=self._make_invisible_collector(),
        )
        action = ClickAction(action_id="e002", target_ref="a[href='/hidden']")
        result = executor.execute(action, context=safe_context())
        assert result.error is not None
        assert "Preconditions failed" in result.error


# ---------------------------------------------------------------------------
# E-003: Perspective Safety Gate — Critical Risk
# ---------------------------------------------------------------------------

class TestE003CriticalRisk:
    """E-003: Click in critical-risk context is blocked by perspective engine."""

    def test_perspective_blocked(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e003", target_ref="button#pay")
        result = executor.execute(action, context=safe_context(
            risk_level="critical",
            payment_in_progress=True,
        ))
        assert result.status == ExecutionStatus.PERSPECTIVE_BLOCKED

    def test_abort_strategy(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e003", target_ref="button#pay")
        result = executor.execute(action, context=safe_context(
            risk_level="critical",
            payment_in_progress=True,
        ))
        assert result.perspective_resolution is not None
        assert result.perspective_resolution.strategy.value == "abort"

    def test_no_execution_reached(self):
        executed = []
        def tracking_executor(action):
            executed.append(action.action_id)
            return True

        executor = VerifiedExecutor(action_executor=tracking_executor)
        action = ClickAction(action_id="e003", target_ref="button#pay")
        executor.execute(action, context=safe_context(
            risk_level="critical",
            payment_in_progress=True,
        ))
        assert len(executed) == 0


# ---------------------------------------------------------------------------
# E-004: Perspective Safety Gate — High Risk (ASK)
# ---------------------------------------------------------------------------

class TestE004HighRiskAsk:
    """E-004: Click in high-risk context triggers ASK (user confirmation)."""

    def test_perspective_blocked(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e004", target_ref="button#submit")
        result = executor.execute(action, context=safe_context(
            risk_level="high",
        ))
        assert result.status == ExecutionStatus.PERSPECTIVE_BLOCKED

    def test_ask_strategy(self):
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e004", target_ref="button#submit")
        result = executor.execute(action, context=safe_context(
            risk_level="high",
        ))
        assert result.perspective_resolution is not None
        assert result.perspective_resolution.strategy.value == "ask"

    def test_critical_vs_high_distinction(self):
        """Critical and high produce different strategies."""
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e004", target_ref="button#submit")
        result_critical = executor.execute(action, context=safe_context(
            risk_level="critical",
            payment_in_progress=True,
        ))
        result_high = executor.execute(action, context=safe_context(
            risk_level="high",
        ))
        assert result_critical.perspective_resolution.strategy.value == "abort"
        assert result_high.perspective_resolution.strategy.value == "ask"

    def test_low_risk_passes(self):
        """Low risk should pass perspective check."""
        executor = VerifiedExecutor()
        action = ClickAction(action_id="e004c", target_ref="button#submit")
        result = executor.execute(action, context=safe_context(risk_level="low"))
        assert result.status == ExecutionStatus.SUCCESS


# ---------------------------------------------------------------------------
# E-005: Execution Failure — Executor Error
# ---------------------------------------------------------------------------

class TestE005ExecutionError:
    """E-005: Executor callback raises exception, captured gracefully."""

    def test_execution_error_status(self):
        def failing_executor(action):
            raise RuntimeError("Browser connection lost")

        executor = VerifiedExecutor(action_executor=failing_executor)
        action = ClickAction(action_id="e005", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        assert result.status == ExecutionStatus.EXECUTION_ERROR

    def test_error_captured(self):
        def failing_executor(action):
            raise RuntimeError("Browser connection lost")

        executor = VerifiedExecutor(action_executor=failing_executor)
        action = ClickAction(action_id="e005", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        assert result.error is not None
        assert "Browser connection lost" in result.error

    def test_no_post_evidence(self):
        def failing_executor(action):
            raise RuntimeError("fail")

        executor = VerifiedExecutor(action_executor=failing_executor)
        action = ClickAction(action_id="e005", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        assert result.evidence.post is None

    def test_executor_returns_false(self):
        """Executor returning False (not exception) also triggers error."""
        def false_executor(action):
            return False

        executor = VerifiedExecutor(action_executor=false_executor)
        action = ClickAction(action_id="e005b", target_ref="button#submit")
        result = executor.execute(action, context=safe_context())
        assert result.status == ExecutionStatus.EXECUTION_ERROR
        assert "failure" in result.error.lower()


# ---------------------------------------------------------------------------
# E-006: Multiple Preconditions — Fill on Disabled Element
# ---------------------------------------------------------------------------

class TestE006CompoundPreconditions:
    """E-006: Fill action on disabled, non-editable input blocked."""

    def test_disabled_fill_blocked(self):
        def disabled_collector(action_id, target_ref):
            return make_evidence(
                action_id=action_id,
                target_ref=target_ref,
                enabled=False,
                editable=False,
            )

        executor = VerifiedExecutor(evidence_collector=disabled_collector)
        action = FillAction(action_id="e006", target_ref="input#readonly", text="test")
        result = executor.execute(action, context=safe_context())
        assert result.status == ExecutionStatus.PRECONDITION_FAILED

    def test_not_attached_blocked(self):
        def detached_collector(action_id, target_ref):
            return make_evidence(
                action_id=action_id,
                target_ref=target_ref,
                attached=False,
            )

        executor = VerifiedExecutor(evidence_collector=detached_collector)
        action = ClickAction(action_id="e006b", target_ref="div#removed")
        result = executor.execute(action, context=safe_context())
        assert result.status == ExecutionStatus.PRECONDITION_FAILED

    def test_pointer_events_false_blocked(self):
        def no_pointer_collector(action_id, target_ref):
            return make_evidence(
                action_id=action_id,
                target_ref=target_ref,
                pointer_events=False,
            )

        executor = VerifiedExecutor(evidence_collector=no_pointer_collector)
        action = ClickAction(action_id="e006c", target_ref="button#overlay")
        result = executor.execute(action, context=safe_context())
        assert result.status == ExecutionStatus.PRECONDITION_FAILED

    def test_not_stable_blocked(self):
        def unstable_collector(action_id, target_ref):
            return make_evidence(
                action_id=action_id,
                target_ref=target_ref,
                stable=False,
            )

        executor = VerifiedExecutor(evidence_collector=unstable_collector)
        action = ClickAction(action_id="e006d", target_ref="button#moving")
        result = executor.execute(action, context=safe_context())
        assert result.status == ExecutionStatus.PRECONDITION_FAILED


# ---------------------------------------------------------------------------
# Scoring helper — for future executor output validation
# ---------------------------------------------------------------------------

def score_executor_result(result: VerifiedExecution) -> float:
    """Score an executor result 0-100 using the NW-010 scoring formula.

    task_score = (phase_accuracy * 0.3) + (evidence_completeness * 0.3) +
                 (gate_accuracy * 0.2) + (error_handling * 0.2)
    """
    # Phase accuracy: did execution reach expected phases
    phase_acc = 0.5
    if result.status == ExecutionStatus.SUCCESS:
        phase_acc = 1.0 if result.evidence.pre and result.evidence.post else 0.5
    elif result.status in (ExecutionStatus.PRECONDITION_FAILED, ExecutionStatus.PERSPECTIVE_BLOCKED):
        phase_acc = 1.0  # Correctly stopped early

    # Evidence completeness
    ev_complete = 0.0
    if result.report:
        ev_complete = 1.0 if result.report.verify() else 0.5
    if result.evidence.pre:
        ev_complete = max(ev_complete, 0.3)

    # Gate accuracy (default; specific tests validate gates)
    gate_acc = 1.0

    # Error handling
    err_handling = 0.0
    if result.status == ExecutionStatus.EXECUTION_ERROR:
        err_handling = 1.0 if result.error is not None else 0.0
    elif result.status == ExecutionStatus.SUCCESS:
        err_handling = 1.0

    return (phase_acc * 0.3) + (ev_complete * 0.3) + (gate_acc * 0.2) + (err_handling * 0.2)
