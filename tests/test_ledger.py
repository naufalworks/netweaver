"""Tests for NetWeaver Action Ledger and EvidenceBundle.

Covers:
- EvidenceBundle creation, serialization, round-trip
- EvidenceBundle validation: verified, missing-evidence rejection
- LedgerEvent creation, JSONL serialization, deserialization
- ActionLedger: append, read, filter, bundle append with validation
- Missing-evidence rejection on bundle append
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from netweaver.evidence import (
    BundleStatus,
    Claim,
    ClaimStatus,
    EvidenceBundle,
    EvidenceReport,
    EvidenceType,
    Observation,
    create_bundle,
    create_claim,
    create_observation,
)
from netweaver.ledger import (
    ActionLedger,
    LedgerError,
    LedgerEvent,
    LedgerEventType,
    MissingEvidenceError,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_report(verified: bool = True) -> EvidenceReport:
    """Create a minimal evidence report."""
    obs = create_observation(
        observation_id="obs-001",
        evidence_type=EvidenceType.DOM,
        data={"selector": "button", "exists": True},
        source="test",
    )
    report = EvidenceReport(
        report_id="rpt-001",
        url="https://example.com",
        timestamp=datetime.now(),
        observations=[obs],
    )
    if verified:
        claim = create_claim(
            claim_id="claim-001",
            description="Button exists",
            evidence_type=EvidenceType.DOM,
            observation_ids=["obs-001"],
        )
        report.add_claim(claim)
    return report


def _make_unverified_report() -> EvidenceReport:
    """Create a report with an unsupported claim."""
    claim = create_claim(
        claim_id="claim-bad",
        description="Unverified claim",
        evidence_type=EvidenceType.DOM,
        observation_ids=["obs-missing"],
    )
    report = EvidenceReport(
        report_id="rpt-bad",
        url="https://example.com",
        timestamp=datetime.now(),
        claims=[claim],
    )
    return report


def _tmp_ledger(tmp_path: Path) -> ActionLedger:
    """Create an ActionLedger with a temp file path."""
    ledger_path = tmp_path / "test_ledger.jsonl"
    return ActionLedger(ledger_path=ledger_path)


# ── EvidenceBundle Tests ────────────────────────────────────────────────

class TestEvidenceBundle:
    """Tests for EvidenceBundle data model."""

    def test_create_bundle_defaults(self):
        bundle = EvidenceBundle(
            bundle_id="b-001",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
        )
        assert bundle.bundle_id == "b-001"
        assert bundle.task_id == "NW-010"
        assert bundle.agent == "WNAL Engineer"
        assert bundle.files_changed == []
        assert bundle.commands_run == []
        assert bundle.test_results == {}
        assert bundle.claims == []
        assert bundle.reports == []
        assert bundle.risk_level == "low"
        assert bundle.status == BundleStatus.EMPTY
        assert bundle.rejection_reasons == []

    def test_create_bundle_with_data(self):
        bundle = EvidenceBundle(
            bundle_id="b-002",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
            files_changed=["netweaver/ledger.py"],
            commands_run=["python -m pytest tests/"],
            test_results={"passed": 30, "failed": 0},
            claims=["Ledger module implemented"],
            risk_level="low",
        )
        assert bundle.files_changed == ["netweaver/ledger.py"]
        assert bundle.commands_run == ["python -m pytest tests/"]
        assert bundle.test_results == {"passed": 30, "failed": 0}
        assert len(bundle.claims) == 1

    def test_bundle_validate_empty_claims_passes(self):
        bundle = EvidenceBundle(
            bundle_id="b-003",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
        )
        assert bundle.validate() is True
        assert bundle.status == BundleStatus.VERIFIED

    def test_bundle_validate_no_claims_no_reports(self):
        """Empty claims → VERIFIED (nothing to prove)."""
        bundle = create_bundle(task_id="NW-010", agent="test")
        assert bundle.validate() is True
        assert bundle.status == BundleStatus.VERIFIED

    def test_bundle_validate_claims_no_reports_rejected(self):
        """Claims with no reports → MISSING_EVIDENCE."""
        bundle = EvidenceBundle(
            bundle_id="b-004",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
            claims=["Feature implemented", "Tests pass"],
        )
        assert bundle.validate() is False
        assert bundle.status == BundleStatus.MISSING_EVIDENCE
        assert len(bundle.rejection_reasons) == 2
        assert any("Feature implemented" in r for r in bundle.rejection_reasons)

    def test_bundle_validate_with_verified_report(self):
        """Claims with verified report → VERIFIED."""
        report = _make_report(verified=True)
        bundle = EvidenceBundle(
            bundle_id="b-005",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
            claims=["Button exists"],
            reports=[report],
        )
        assert bundle.validate() is True
        assert bundle.status == BundleStatus.VERIFIED

    def test_bundle_validate_with_unverified_report_rejected(self):
        """Claims with only unverified report → MISSING_EVIDENCE."""
        report = _make_unverified_report()
        bundle = EvidenceBundle(
            bundle_id="b-006",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
            claims=["Something works"],
            reports=[report],
        )
        assert bundle.validate() is False
        assert bundle.status == BundleStatus.MISSING_EVIDENCE

    def test_bundle_add_report(self):
        bundle = create_bundle(task_id="NW-010", agent="test")
        report = _make_report()
        bundle.add_report(report)
        assert len(bundle.reports) == 1

    def test_bundle_to_dict_round_trip(self):
        ts = datetime(2026, 5, 23, 19, 0, 0)
        report = _make_report()
        bundle = EvidenceBundle(
            bundle_id="b-007",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=ts,
            files_changed=["a.py"],
            commands_run=["pytest"],
            test_results={"passed": 1},
            claims=["Works"],
            reports=[report],
            risk_level="low",
            status=BundleStatus.VERIFIED,
        )
        d = bundle.to_dict()
        assert d["bundle_id"] == "b-007"
        assert d["task_id"] == "NW-010"
        assert d["files_changed"] == ["a.py"]
        assert len(d["reports"]) == 1

        restored = EvidenceBundle.from_dict(d)
        assert restored.bundle_id == "b-007"
        assert restored.task_id == "NW-010"
        assert restored.files_changed == ["a.py"]
        assert len(restored.reports) == 1

    def test_bundle_to_json(self):
        bundle = EvidenceBundle(
            bundle_id="b-008",
            task_id="NW-010",
            agent="test",
            timestamp=datetime(2026, 5, 23, 19, 0, 0),
        )
        j = bundle.to_json()
        data = json.loads(j)
        assert data["bundle_id"] == "b-008"

    def test_create_bundle_factory(self):
        bundle = create_bundle(
            task_id="NW-010",
            agent="WNAL Engineer",
            files_changed=["ledger.py"],
            commands_run=["pytest"],
            test_results={"passed": 10, "failed": 0},
            claims=["Ledger works"],
            risk_level="low",
        )
        assert bundle.bundle_id.startswith("bundle-")
        assert bundle.task_id == "NW-010"
        assert bundle.agent == "WNAL Engineer"
        assert bundle.files_changed == ["ledger.py"]


# ── LedgerEvent Tests ───────────────────────────────────────────────────

class TestLedgerEvent:
    """Tests for LedgerEvent serialization."""

    def test_create_event(self):
        ts = datetime(2026, 5, 23, 19, 0, 0)
        event = LedgerEvent(
            event_id="evt-001",
            event_type=LedgerEventType.TASK_START,
            timestamp=ts,
            agent="WNAL Engineer",
            task_id="NW-010",
            payload={"scope": ["ledger.py"]},
        )
        assert event.event_id == "evt-001"
        assert event.event_type == LedgerEventType.TASK_START
        assert event.agent == "WNAL Engineer"

    def test_event_to_dict(self):
        ts = datetime(2026, 5, 23, 19, 0, 0)
        event = LedgerEvent(
            event_id="evt-002",
            event_type=LedgerEventType.FILE_CHANGED,
            timestamp=ts,
            agent="WNAL Engineer",
            task_id="NW-010",
            payload={"path": "ledger.py"},
        )
        d = event.to_dict()
        assert d["event_id"] == "evt-002"
        assert d["event_type"] == "file_changed"
        assert d["timestamp"] == "2026-05-23T19:00:00"

    def test_event_jsonl_round_trip(self):
        ts = datetime(2026, 5, 23, 19, 0, 0)
        event = LedgerEvent(
            event_id="evt-003",
            event_type=LedgerEventType.TEST_RESULT,
            timestamp=ts,
            agent="QA",
            task_id="NW-010",
            payload={"passed": 30, "failed": 0},
            metadata={"model": "glm-5.1"},
        )
        line = event.to_jsonl()
        assert "\n" not in line  # single line

        restored = LedgerEvent.from_jsonl(line)
        assert restored.event_id == "evt-003"
        assert restored.event_type == LedgerEventType.TEST_RESULT
        assert restored.payload == {"passed": 30, "failed": 0}
        assert restored.metadata == {"model": "glm-5.1"}

    def test_event_from_dict(self):
        d = {
            "event_id": "evt-004",
            "event_type": "task_state_change",
            "timestamp": "2026-05-23T19:00:00",
            "agent": "Architect",
            "task_id": "NW-004",
            "payload": {"from": "ready", "to": "in_progress"},
        }
        event = LedgerEvent.from_dict(d)
        assert event.event_type == LedgerEventType.TASK_STATE_CHANGE
        assert event.payload["from"] == "ready"


# ── ActionLedger Tests ──────────────────────────────────────────────────

class TestActionLedger:
    """Tests for ActionLedger append/read operations."""

    def test_append_and_read(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        event = ledger.append_event(
            event_type=LedgerEventType.TASK_START,
            agent="WNAL Engineer",
            task_id="NW-010",
            payload={"scope": ["ledger.py"]},
        )
        assert event.event_id.startswith("evt-")
        assert event.event_type == LedgerEventType.TASK_START

        events = ledger.read_events()
        assert len(events) == 1
        assert events[0].event_type == LedgerEventType.TASK_START

    def test_append_multiple_events(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        ledger.append_event(LedgerEventType.TASK_START, "Agent", "NW-010")
        ledger.append_event(LedgerEventType.FILE_CHANGED, "Agent", "NW-010",
                            payload={"path": "a.py"})
        ledger.append_event(LedgerEventType.TEST_RESULT, "Agent", "NW-010",
                            payload={"passed": 1})

        assert ledger.event_count() == 3

    def test_read_events_newest_first(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        ledger.append_event(LedgerEventType.TASK_START, "A", "NW-010",
                            event_id="evt-first")
        ledger.append_event(LedgerEventType.FILE_CHANGED, "A", "NW-010",
                            event_id="evt-second")

        events = ledger.read_events()
        assert events[0].event_id == "evt-second"
        assert events[1].event_id == "evt-first"

    def test_filter_by_task_id(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        ledger.append_event(LedgerEventType.TASK_START, "A", "NW-010")
        ledger.append_event(LedgerEventType.TASK_START, "A", "NW-004")
        ledger.append_event(LedgerEventType.FILE_CHANGED, "A", "NW-010")

        events = ledger.read_events(task_id="NW-010")
        assert len(events) == 2

    def test_filter_by_event_type(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        ledger.append_event(LedgerEventType.TASK_START, "A", "NW-010")
        ledger.append_event(LedgerEventType.FILE_CHANGED, "A", "NW-010")

        events = ledger.read_events(event_type=LedgerEventType.FILE_CHANGED)
        assert len(events) == 1

    def test_filter_by_agent(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        ledger.append_event(LedgerEventType.TASK_START, "WNAL Engineer", "NW-010")
        ledger.append_event(LedgerEventType.TASK_START, "QA", "NW-010")

        events = ledger.read_events(agent="QA")
        assert len(events) == 1
        assert events[0].agent == "QA"

    def test_limit(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        for i in range(10):
            ledger.append_event(LedgerEventType.NOTE, "A", "NW-010",
                                payload={"i": i})

        events = ledger.read_events(limit=3)
        assert len(events) == 3

    def test_read_empty_ledger(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        events = ledger.read_events()
        assert events == []

    def test_event_count(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        ledger.append_event(LedgerEventType.TASK_START, "A", "NW-010")
        ledger.append_event(LedgerEventType.TASK_START, "A", "NW-004")
        assert ledger.event_count() == 2
        assert ledger.event_count(task_id="NW-010") == 1

    def test_clear(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        ledger.append_event(LedgerEventType.TASK_START, "A", "NW-010")
        assert ledger.event_count() == 1
        ledger.clear()
        assert ledger.event_count() == 0

    def test_custom_event_id_and_timestamp(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        ts = datetime(2026, 1, 1, 0, 0, 0)
        event = ledger.append_event(
            LedgerEventType.NOTE,
            "A",
            "NW-010",
            event_id="custom-id",
            timestamp=ts,
        )
        assert event.event_id == "custom-id"
        assert event.timestamp == ts


# ── Bundle Append + Validation Tests ────────────────────────────────────

class TestBundleAppend:
    """Tests for EvidenceBundle append with validation."""

    def test_append_verified_bundle(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        report = _make_report(verified=True)
        bundle = EvidenceBundle(
            bundle_id="b-ok",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
            claims=["Feature done"],
            reports=[report],
        )
        event = ledger.append_bundle(bundle)
        assert event.event_type == LedgerEventType.EVIDENCE_BUNDLE
        assert event.payload["bundle_id"] == "b-ok"

    def test_append_bundle_missing_evidence_rejected(self, tmp_path):
        """Bundle with claims but no evidence → MissingEvidenceError."""
        ledger = _tmp_ledger(tmp_path)
        bundle = EvidenceBundle(
            bundle_id="b-bad",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
            claims=["Feature done"],
        )
        with pytest.raises(MissingEvidenceError, match="rejected"):
            ledger.append_bundle(bundle)

    def test_append_bundle_skip_validation(self, tmp_path):
        """Skip validation allows unverified bundle."""
        ledger = _tmp_ledger(tmp_path)
        bundle = EvidenceBundle(
            bundle_id="b-skip",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
            claims=["Something"],
        )
        event = ledger.append_bundle(bundle, validate=False)
        assert event.event_type == LedgerEventType.EVIDENCE_BUNDLE

    def test_append_bundle_persists_to_file(self, tmp_path):
        ledger = _tmp_ledger(tmp_path)
        report = _make_report(verified=True)
        bundle = EvidenceBundle(
            bundle_id="b-persist",
            task_id="NW-010",
            agent="WNAL Engineer",
            timestamp=datetime.now(),
            claims=["Done"],
            reports=[report],
        )
        ledger.append_bundle(bundle)

        # Read raw file and verify JSONL
        lines = ledger.ledger_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "evidence_bundle"
        assert data["payload"]["bundle_id"] == "b-persist"

    def test_full_task_lifecycle(self, tmp_path):
        """Simulate a full task lifecycle: start → files → test → bundle."""
        ledger = _tmp_ledger(tmp_path)

        # Task start
        ledger.append_event(
            LedgerEventType.TASK_START,
            "WNAL Engineer",
            "NW-010",
            payload={"scope": ["netweaver/ledger.py", "tests/test_ledger.py"]},
        )

        # File changes
        ledger.append_event(
            LedgerEventType.FILE_CHANGED,
            "WNAL Engineer",
            "NW-010",
            payload={"path": "netweaver/ledger.py", "action": "created"},
        )

        # Test results
        ledger.append_event(
            LedgerEventType.TEST_RESULT,
            "WNAL Engineer",
            "NW-010",
            payload={"passed": 30, "failed": 0, "total": 30},
        )

        # Evidence bundle
        report = _make_report(verified=True)
        bundle = create_bundle(
            task_id="NW-010",
            agent="WNAL Engineer",
            files_changed=["netweaver/ledger.py", "tests/test_ledger.py"],
            commands_run=["python -m pytest tests/test_ledger.py"],
            test_results={"passed": 30, "failed": 0},
            claims=["Ledger module implemented", "Tests pass"],
            reports=[report],
        )
        ledger.append_bundle(bundle)

        # Verify all events recorded
        events = ledger.read_events(task_id="NW-010")
        assert len(events) == 4
        types = [e.event_type for e in events]
        assert LedgerEventType.EVIDENCE_BUNDLE in types
        assert LedgerEventType.TASK_START in types


# ── Edge Cases ──────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case tests for ledger and bundle."""

    def test_corrupted_line_skipped(self, tmp_path):
        """Corrupted JSONL lines are skipped on read."""
        ledger = _tmp_ledger(tmp_path)
        # Write a good event
        ledger.append_event(LedgerEventType.TASK_START, "A", "NW-010")
        # Write a corrupted line
        with open(ledger.ledger_path, "a") as f:
            f.write("not valid json\n")
        # Write another good event
        ledger.append_event(LedgerEventType.NOTE, "A", "NW-010")

        events = ledger.read_events()
        assert len(events) == 2  # corrupted line skipped

    def test_bundle_empty_claims_validates(self, tmp_path):
        """Bundle with no claims is valid (nothing to prove)."""
        ledger = _tmp_ledger(tmp_path)
        bundle = create_bundle(task_id="NW-010", agent="test")
        event = ledger.append_bundle(bundle)
        assert event is not None

    def test_event_type_values(self):
        """All event types have string values."""
        for et in LedgerEventType:
            assert isinstance(et.value, str)
            assert len(et.value) > 0

    def test_bundle_status_values(self):
        for bs in BundleStatus:
            assert isinstance(bs.value, str)

    def test_ledger_creates_directory(self, tmp_path):
        """Ledger creates parent directories if needed."""
        nested = tmp_path / "a" / "b" / "c" / "ledger.jsonl"
        ledger = ActionLedger(ledger_path=nested)
        ledger.append_event(LedgerEventType.NOTE, "A", "NW-010")
        assert nested.exists()
