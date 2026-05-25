"""Tests for NetWeaver Evidence Report — NW-006

Validates the evidence report contract:
- Evidence report links claims to observations
- Supports DOM, network, storage, actionability evidence types
- Unsupported claims cause verification failure

Run: python -m pytest tests/test_evidence.py -v
"""

import json
from datetime import datetime

import pytest

from netweaver.evidence import (
    Claim,
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
    Observation,
    create_claim,
    create_observation,
)


# ---------------------------------------------------------------------------
# Observation tests
# ---------------------------------------------------------------------------

def test_observation_creation():
    obs = Observation(
        observation_id="obs-001",
        evidence_type=EvidenceType.DOM,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        data={"selector": "button#submit", "visible": True},
        source="observer",
    )
    assert obs.observation_id == "obs-001"
    assert obs.evidence_type == EvidenceType.DOM
    assert obs.data["selector"] == "button#submit"
    assert obs.source == "observer"


def test_observation_serialization():
    obs = Observation(
        observation_id="obs-002",
        evidence_type=EvidenceType.NETWORK,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        data={"url": "/api/data", "status": 200},
        source="network_monitor",
    )
    d = obs.to_dict()
    assert d["observation_id"] == "obs-002"
    assert d["evidence_type"] == "network"
    assert d["data"]["status"] == 200

    # Round-trip
    restored = Observation.from_dict(d)
    assert restored.observation_id == obs.observation_id
    assert restored.evidence_type == obs.evidence_type
    assert restored.data == obs.data


def test_observation_all_evidence_types():
    """All four evidence types are representable."""
    for et in EvidenceType:
        obs = Observation(
            observation_id=f"obs-{et.value}",
            evidence_type=et,
            timestamp=datetime(2026, 1, 1),
            data={},
            source="test",
        )
        assert obs.evidence_type == et


# ---------------------------------------------------------------------------
# Claim tests
# ---------------------------------------------------------------------------

def test_claim_creation():
    claim = Claim(
        claim_id="claim-001",
        description="Submit button is visible",
        evidence_type=EvidenceType.DOM,
    )
    assert claim.claim_id == "claim-001"
    assert claim.status == ClaimStatus.UNSUPPORTED
    assert claim.observation_ids == []


def test_claim_add_observation():
    claim = Claim(
        claim_id="claim-002",
        description="Button is enabled",
        evidence_type=EvidenceType.ACTIONABILITY,
    )
    claim.add_observation("obs-001")
    claim.add_observation("obs-002")
    assert claim.observation_ids == ["obs-001", "obs-002"]
    # Adding same observation again should not duplicate
    claim.add_observation("obs-001")
    assert len(claim.observation_ids) == 2


def test_claim_serialization():
    claim = Claim(
        claim_id="claim-003",
        description="API returned 200",
        evidence_type=EvidenceType.NETWORK,
        observation_ids=["obs-010"],
        status=ClaimStatus.SUPPORTED,
    )
    d = claim.to_dict()
    assert d["claim_id"] == "claim-003"
    assert d["evidence_type"] == "network"
    assert d["status"] == "supported"
    assert d["observation_ids"] == ["obs-010"]

    restored = Claim.from_dict(d)
    assert restored.claim_id == claim.claim_id
    assert restored.evidence_type == claim.evidence_type
    assert restored.observation_ids == claim.observation_ids


# ---------------------------------------------------------------------------
# Evidence Report — basic structure
# ---------------------------------------------------------------------------

def _make_report():
    """Create a minimal valid evidence report."""
    report = EvidenceReport(
        report_id="rpt-001",
        url="https://example.com/page",
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
    )
    obs = Observation(
        observation_id="obs-001",
        evidence_type=EvidenceType.DOM,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        data={"selector": "button#submit", "visible": True},
        source="observer",
    )
    claim = Claim(
        claim_id="claim-001",
        description="Submit button is visible",
        evidence_type=EvidenceType.DOM,
        observation_ids=["obs-001"],
    )
    report.add_observation(obs)
    report.add_claim(claim)
    return report


def test_report_creation():
    report = _make_report()
    assert report.report_id == "rpt-001"
    assert report.url == "https://example.com/page"
    assert len(report.observations) == 1
    assert len(report.claims) == 1


def test_report_verify_supported():
    """Report with all claims supported → verify returns True."""
    report = _make_report()
    assert report.verify() is True


def test_report_verify_unsupported_claim():
    """Claim with no observations → verify returns False."""
    report = EvidenceReport(
        report_id="rpt-002",
        url="https://example.com/broken",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_claim(Claim(
        claim_id="claim-bad",
        description="Ghost element exists",
        evidence_type=EvidenceType.DOM,
        observation_ids=[],  # No observations linked
    ))
    assert report.verify() is False


def test_report_verify_observation_not_found():
    """Claim referencing nonexistent observation → verify returns False."""
    report = EvidenceReport(
        report_id="rpt-003",
        url="https://example.com/stale",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_claim(Claim(
        claim_id="claim-stale",
        description="Button is enabled",
        evidence_type=EvidenceType.ACTIONABILITY,
        observation_ids=["obs-nonexistent"],  # Not in report
    ))
    assert report.verify() is False


def test_report_verify_no_claims():
    """Report with zero claims → verify returns True (vacuously)."""
    report = EvidenceReport(
        report_id="rpt-004",
        url="https://example.com/empty",
        timestamp=datetime(2026, 1, 1),
    )
    assert report.verify() is True


# ---------------------------------------------------------------------------
# Evidence type coverage
# ---------------------------------------------------------------------------

def test_dom_evidence():
    """DOM evidence: element existence, visibility."""
    report = EvidenceReport(
        report_id="rpt-dom",
        url="https://example.com/form",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_observation(Observation(
        observation_id="obs-dom-1",
        evidence_type=EvidenceType.DOM,
        timestamp=datetime(2026, 1, 1),
        data={"selector": "input#email", "tag": "input", "visible": True},
        source="observer",
    ))
    report.add_claim(Claim(
        claim_id="claim-dom-1",
        description="Email input exists and is visible",
        evidence_type=EvidenceType.DOM,
        observation_ids=["obs-dom-1"],
    ))
    assert report.verify() is True
    assert len(report.get_claims_by_type(EvidenceType.DOM)) == 1
    assert len(report.get_observations_by_type(EvidenceType.DOM)) == 1


def test_network_evidence():
    """Network evidence: request/response status."""
    report = EvidenceReport(
        report_id="rpt-net",
        url="https://example.com/api",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_observation(Observation(
        observation_id="obs-net-1",
        evidence_type=EvidenceType.NETWORK,
        timestamp=datetime(2026, 1, 1),
        data={"url": "/api/users", "method": "GET", "status": 200},
        source="network_monitor",
    ))
    report.add_claim(Claim(
        claim_id="claim-net-1",
        description="Users API returned 200",
        evidence_type=EvidenceType.NETWORK,
        observation_ids=["obs-net-1"],
    ))
    assert report.verify() is True
    assert len(report.get_claims_by_type(EvidenceType.NETWORK)) == 1


def test_storage_evidence():
    """Storage evidence: localStorage, sessionStorage, cookies."""
    report = EvidenceReport(
        report_id="rpt-store",
        url="https://example.com/app",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_observation(Observation(
        observation_id="obs-store-1",
        evidence_type=EvidenceType.STORAGE,
        timestamp=datetime(2026, 1, 1),
        data={"store": "localStorage", "key": "auth_token", "exists": True},
        source="storage_probe",
    ))
    report.add_claim(Claim(
        claim_id="claim-store-1",
        description="Auth token exists in localStorage",
        evidence_type=EvidenceType.STORAGE,
        observation_ids=["obs-store-1"],
    ))
    assert report.verify() is True
    assert len(report.get_claims_by_type(EvidenceType.STORAGE)) == 1


def test_actionability_evidence():
    """Actionability evidence: element state checks."""
    report = EvidenceReport(
        report_id="rpt-act",
        url="https://example.com/page",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_observation(Observation(
        observation_id="obs-act-1",
        evidence_type=EvidenceType.ACTIONABILITY,
        timestamp=datetime(2026, 1, 1),
        data={
            "selector": "button#submit",
            "attached": True,
            "visible": True,
            "enabled": True,
            "editable": False,
        },
        source="observer",
    ))
    report.add_claim(Claim(
        claim_id="claim-act-1",
        description="Submit button is actionable",
        evidence_type=EvidenceType.ACTIONABILITY,
        observation_ids=["obs-act-1"],
    ))
    assert report.verify() is True


# ---------------------------------------------------------------------------
# Unsupported claim scenarios
# ---------------------------------------------------------------------------

def test_unsupported_claim_from_missing_observation():
    """Claim references observation that doesn't exist in report."""
    report = EvidenceReport(
        report_id="rpt-bad-1",
        url="https://example.com/bad",
        timestamp=datetime(2026, 1, 1),
    )
    # Add an observation
    report.add_observation(Observation(
        observation_id="obs-real",
        evidence_type=EvidenceType.DOM,
        timestamp=datetime(2026, 1, 1),
        data={"selector": "a.link"},
        source="observer",
    ))
    # Claim references wrong observation
    report.add_claim(Claim(
        claim_id="claim-bad-ref",
        description="Element exists",
        evidence_type=EvidenceType.DOM,
        observation_ids=["obs-fake"],  # Not in report
    ))
    assert report.verify() is False
    unsupported = report.get_unsupported_claims()
    assert len(unsupported) == 1
    assert unsupported[0].claim_id == "claim-bad-ref"


def test_unsupported_claim_no_observations_linked():
    """Claim with empty observation_ids list fails."""
    report = EvidenceReport(
        report_id="rpt-bad-2",
        url="https://example.com/empty-claim",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_observation(Observation(
        observation_id="obs-exists",
        evidence_type=EvidenceType.DOM,
        timestamp=datetime(2026, 1, 1),
        data={"selector": "div"},
        source="observer",
    ))
    report.add_claim(Claim(
        claim_id="claim-empty",
        description="No observations linked",
        evidence_type=EvidenceType.DOM,
        observation_ids=[],
    ))
    assert report.verify() is False
    assert len(report.get_unsupported_claims()) == 1


def test_mixed_supported_and_unsupported():
    """Report with some supported, some unsupported claims."""
    report = EvidenceReport(
        report_id="rpt-mixed",
        url="https://example.com/mixed",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_observation(Observation(
        observation_id="obs-1",
        evidence_type=EvidenceType.DOM,
        timestamp=datetime(2026, 1, 1),
        data={"selector": "a"},
        source="observer",
    ))
    report.add_claim(Claim(
        claim_id="claim-good",
        description="Link exists",
        evidence_type=EvidenceType.DOM,
        observation_ids=["obs-1"],
    ))
    report.add_claim(Claim(
        claim_id="claim-bad",
        description="Ghost element",
        evidence_type=EvidenceType.DOM,
        observation_ids=["obs-missing"],
    ))
    # Any unsupported → overall verify is False
    assert report.verify() is False
    assert len(report.get_unsupported_claims()) == 1


# ---------------------------------------------------------------------------
# Summary and serialization
# ---------------------------------------------------------------------------

def test_report_summary():
    """Summary contains correct counts."""
    report = _make_report()
    s = report.summary()
    assert s["report_id"] == "rpt-001"
    assert s["url"] == "https://example.com/page"
    assert s["total_claims"] == 1
    assert s["total_observations"] == 1
    assert s["unsupported_claims"] == 0
    assert s["verified"] is True


def test_report_summary_unsupported():
    """Summary reflects unsupported claims."""
    report = EvidenceReport(
        report_id="rpt-sum-bad",
        url="https://example.com/summary",
        timestamp=datetime(2026, 1, 1),
    )
    report.add_claim(Claim(
        claim_id="claim-alone",
        description="Unsupported claim",
        evidence_type=EvidenceType.NETWORK,
    ))
    s = report.summary()
    assert s["unsupported_claims"] == 1
    assert s["verified"] is False


def test_report_serialization_roundtrip():
    """Full report survives JSON serialization round-trip."""
    report = _make_report()
    d = report.to_dict()
    json_str = json.dumps(d)
    restored_d = json.loads(json_str)
    restored = EvidenceReport.from_dict(restored_d)
    assert restored.report_id == report.report_id
    assert restored.url == report.url
    assert len(restored.observations) == len(report.observations)
    assert len(restored.claims) == len(report.claims)
    assert restored.observations[0].observation_id == "obs-001"
    assert restored.claims[0].claim_id == "claim-001"


def test_report_json_valid():
    """Report to_dict produces JSON-serializable output."""
    report = _make_report()
    d = report.to_dict()
    # Must not raise
    json_str = json.dumps(d)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["report_id"] == "rpt-001"


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def test_create_observation():
    obs = create_observation(
        "obs-factory",
        EvidenceType.DOM,
        {"selector": "button"},
    )
    assert obs.observation_id == "obs-factory"
    assert obs.evidence_type == EvidenceType.DOM
    assert obs.source == "observer"
    assert isinstance(obs.timestamp, datetime)


def test_create_claim():
    claim = create_claim(
        "claim-factory",
        "Test claim",
        EvidenceType.NETWORK,
        observation_ids=["obs-1"],
    )
    assert claim.claim_id == "claim-factory"
    assert claim.description == "Test claim"
    assert claim.observation_ids == ["obs-1"]


def test_create_claim_no_observations():
    claim = create_claim(
        "claim-empty",
        "No observations",
        EvidenceType.STORAGE,
    )
    assert claim.observation_ids == []


# ---------------------------------------------------------------------------
# Tech debt fix: summary() should NOT mutate claim statuses
# ---------------------------------------------------------------------------

def test_summary_does_not_mutate_claim_statuses():
    """summary() must be read-only — calling it must not change claim.status."""
    report = EvidenceReport(
        report_id="r-mutation",
        url="https://example.com",
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
        claims=[
            Claim(
                claim_id="c-1",
                description="Button exists",
                evidence_type=EvidenceType.DOM,
                observation_ids=["obs-1"],
            )
        ],
        observations=[
            Observation(
                observation_id="obs-1",
                evidence_type=EvidenceType.DOM,
                timestamp=datetime(2026, 1, 1, 0, 0, 0),
                data={"selector": "button", "visible": True},
                source="observer",
            )
        ],
    )
    # Claim starts with UNSUPPORTED (default) — verify() would change it to SUPPORTED
    assert report.claims[0].status == ClaimStatus.UNSUPPORTED

    # Call summary — must NOT change status
    s = report.summary()
    assert s["verified"] is True
    assert report.claims[0].status == ClaimStatus.UNSUPPORTED

    # Verify still works normally and DOES mutate
    assert report.verify() is True
    assert report.claims[0].status == ClaimStatus.SUPPORTED


def test_summary_does_not_mutate_on_unsupported():
    """summary() on unsupported report must not touch claim statuses."""
    report = EvidenceReport(
        report_id="r-unsup",
        url="https://example.com",
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
        claims=[
            Claim(
                claim_id="c-2",
                description="No evidence",
                evidence_type=EvidenceType.NETWORK,
                observation_ids=[],
            )
        ],
        observations=[],
    )
    assert report.claims[0].status == ClaimStatus.UNSUPPORTED

    s = report.summary()
    assert s["verified"] is False
    assert report.claims[0].status == ClaimStatus.UNSUPPORTED


def test_check_verified_matches_verify_outcome():
    """_check_verified() returns same bool as verify() without side effects."""
    report = EvidenceReport(
        report_id="r-check",
        url="https://example.com",
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
        claims=[
            Claim(
                claim_id="c-3",
                description="Supported",
                evidence_type=EvidenceType.STORAGE,
                observation_ids=["obs-2"],
            )
        ],
        observations=[
            Observation(
                observation_id="obs-2",
                evidence_type=EvidenceType.STORAGE,
                timestamp=datetime(2026, 1, 1, 0, 0, 0),
                data={"key": "token"},
                source="storage",
            )
        ],
    )
    assert report._check_verified() is True
    assert report.verify() is True
