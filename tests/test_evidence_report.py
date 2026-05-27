"""Tests for netweaver.evidence_report — EvidenceReportRenderer.

Tests cover: rendering, sections, stats, edge cases, recommendations.
No browser/vendor imports.
"""

import pytest
from datetime import datetime, timedelta

from netweaver.evidence import (
    Claim,
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
    Observation,
    create_claim,
    create_observation,
)
from netweaver.evidence_report import (
    EvidenceReportRenderer,
    RenderStats,
    RenderedReport,
    render_evidence_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_observation(
    obs_id: str = "obs-1",
    evidence_type: EvidenceType = EvidenceType.DOM,
    data: dict = None,
    source: str = "observer",
    timestamp: datetime = None,
) -> Observation:
    return Observation(
        observation_id=obs_id,
        evidence_type=evidence_type,
        timestamp=timestamp if timestamp is not None else datetime(2026, 5, 28, 10, 0, 0),
        data=data if data is not None else {"element": "button", "visible": True},
        source=source,
    )


def _make_claim(
    claim_id: str = "claim-1",
    description: str = "Login button is visible",
    evidence_type: EvidenceType = EvidenceType.DOM,
    observation_ids: list = None,
    status: ClaimStatus = ClaimStatus.UNSUPPORTED,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        description=description,
        evidence_type=evidence_type,
        observation_ids=observation_ids or [],
        status=status,
    )


def _make_report(
    report_id: str = "report-1",
    url: str = "https://example.com",
    observations: list = None,
    claims: list = None,
    timestamp: datetime = None,
) -> EvidenceReport:
    return EvidenceReport(
        report_id=report_id,
        url=url,
        timestamp=timestamp if timestamp is not None else datetime(2026, 5, 28, 10, 0, 0),
        observations=observations if observations is not None else [],
        claims=claims if claims is not None else [],
    )


def _verified_report() -> EvidenceReport:
    """Create a fully verified report with matching observations and claims."""
    obs1 = _make_observation("obs-1", EvidenceType.DOM, {"element": "button"})
    obs2 = _make_observation("obs-2", EvidenceType.NETWORK, {"status": 200})
    obs3 = _make_observation("obs-3", EvidenceType.STORAGE, {"key": "session_token"})

    claim1 = _make_claim(
        "claim-1", "Login button exists",
        EvidenceType.DOM, ["obs-1"], ClaimStatus.SUPPORTED,
    )
    claim2 = _make_claim(
        "claim-2", "API returned 200",
        EvidenceType.NETWORK, ["obs-2"], ClaimStatus.SUPPORTED,
    )
    claim3 = _make_claim(
        "claim-3", "Session token stored",
        EvidenceType.STORAGE, ["obs-3"], ClaimStatus.SUPPORTED,
    )

    return _make_report(observations=[obs1, obs2, obs3], claims=[claim1, claim2, claim3])


# ---------------------------------------------------------------------------
# Tests: render_markdown basic
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    """Test render_markdown returns valid markdown."""

    def test_returns_string(self):
        report = _make_report()
        renderer = EvidenceReportRenderer()
        result = renderer.render_markdown(report)
        assert isinstance(result, str)

    def test_convenience_function(self):
        report = _make_report()
        result = render_evidence_report(report)
        assert isinstance(result, str)
        assert "# Evidence Report" in result

    def test_header_contains_report_id(self):
        report = _make_report(report_id="rpt-abc")
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "rpt-abc" in md

    def test_header_contains_url(self):
        report = _make_report(url="https://test.example.com/page")
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "https://test.example.com/page" in md


# ---------------------------------------------------------------------------
# Tests: Summary section
# ---------------------------------------------------------------------------


class TestSummarySection:
    """Test the summary section rendering."""

    def test_summary_section_present(self):
        report = _make_report()
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "## Summary" in md

    def test_verified_verdict(self):
        report = _verified_report()
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "VERIFIED" in md

    def test_not_verified_verdict(self):
        claim = _make_claim("c1", "test", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        report = _make_report(claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "NOT VERIFIED" in md

    def test_summary_counts(self):
        obs = _make_observation("obs-1")
        claim_sup = _make_claim("c1", "supported", EvidenceType.DOM, ["obs-1"], ClaimStatus.SUPPORTED)
        claim_unsup = _make_claim("c2", "unsupported", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        claim_partial = _make_claim("c3", "partial", EvidenceType.DOM, ["obs-1"], ClaimStatus.PARTIAL)
        report = _make_report(observations=[obs], claims=[claim_sup, claim_unsup, claim_partial])
        renderer = EvidenceReportRenderer()
        result = renderer.render(report)
        assert result.stats.total_claims == 3
        assert result.stats.supported == 1
        assert result.stats.unsupported == 1
        assert result.stats.partial == 1

    def test_claims_by_type_subsection(self):
        report = _verified_report()
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "Claims by Evidence Type" in md
        assert "DOM" in md
        assert "Network" in md


# ---------------------------------------------------------------------------
# Tests: Claims section
# ---------------------------------------------------------------------------


class TestClaimsSection:
    """Test the claims section rendering."""

    def test_claims_section_present(self):
        report = _make_report()
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "## Claims" in md

    def test_empty_claims_message(self):
        report = _make_report(claims=[])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "No claims" in md

    def test_claim_shows_status(self):
        claim = _make_claim("c1", "test", EvidenceType.DOM, ["obs-1"], ClaimStatus.SUPPORTED)
        obs = _make_observation("obs-1")
        report = _make_report(observations=[obs], claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "SUPPORTED" in md

    def test_claim_shows_description(self):
        claim = _make_claim("c1", "The login form is present", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        report = _make_report(claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "The login form is present" in md

    def test_claim_shows_observation_ids(self):
        claim = _make_claim("c1", "test", EvidenceType.DOM, ["obs-a", "obs-b"], ClaimStatus.SUPPORTED)
        report = _make_report(claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "obs-a" in md
        assert "obs-b" in md

    def test_claim_no_observations_shows_none(self):
        claim = _make_claim("c1", "test", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        report = _make_report(claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "*none*" in md

    def test_unsupported_claim_icon(self):
        claim = _make_claim("c1", "test", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        report = _make_report(claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "❌" in md

    def test_partial_claim_icon(self):
        claim = _make_claim("c1", "test", EvidenceType.DOM, ["obs-1"], ClaimStatus.PARTIAL)
        obs = _make_observation("obs-1")
        report = _make_report(observations=[obs], claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "⚠️" in md


# ---------------------------------------------------------------------------
# Tests: Evidence Chain section
# ---------------------------------------------------------------------------


class TestEvidenceChain:
    """Test the evidence chain section rendering."""

    def test_evidence_chain_section_present(self):
        report = _make_report()
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "## Evidence Chain" in md

    def test_empty_observations_message(self):
        report = _make_report(observations=[])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "No observations" in md

    def test_observations_chronological(self):
        t1 = datetime(2026, 5, 28, 10, 0, 0)
        t2 = datetime(2026, 5, 28, 10, 0, 5)
        t3 = datetime(2026, 5, 28, 10, 0, 10)
        obs3 = _make_observation("obs-3", timestamp=t3)
        obs1 = _make_observation("obs-1", timestamp=t1)
        obs2 = _make_observation("obs-2", timestamp=t2)
        report = _make_report(observations=[obs3, obs1, obs2])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        # obs-1 should appear before obs-2 before obs-3
        pos1 = md.index("obs-1")
        pos2 = md.index("obs-2")
        pos3 = md.index("obs-3")
        assert pos1 < pos2 < pos3

    def test_observation_shows_source(self):
        obs = _make_observation("obs-1", source="network_monitor")
        report = _make_report(observations=[obs])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "network_monitor" in md

    def test_observation_shows_linked_claims(self):
        obs = _make_observation("obs-1")
        claim = _make_claim("c1", "test", EvidenceType.DOM, ["obs-1"], ClaimStatus.SUPPORTED)
        report = _make_report(observations=[obs], claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "Supports Claims:" in md
        assert "c1" in md

    def test_observation_orphan_label(self):
        obs = _make_observation("obs-orphan")
        report = _make_report(observations=[obs], claims=[])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "orphan" in md

    def test_observation_data_preview(self):
        obs = _make_observation("obs-1", data={"selector": "#login-btn", "visible": True})
        report = _make_report(observations=[obs])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "#login-btn" in md


# ---------------------------------------------------------------------------
# Tests: Recommendations section
# ---------------------------------------------------------------------------


class TestRecommendations:
    """Test the recommendations section."""

    def test_recommendations_section_present(self):
        report = _make_report()
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "## Recommendations" in md

    def test_no_recommendations_when_all_supported(self):
        report = _verified_report()
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "No action needed" in md

    def test_unsupported_claim_recommendation(self):
        claim = _make_claim("c-bad", "broken claim", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        report = _make_report(claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "c-bad" in md
        assert "Investigate" in md or "unsupported" in md.lower()

    def test_partial_claim_recommendation(self):
        obs = _make_observation("obs-1")
        claim = _make_claim("c-partial", "conflicting", EvidenceType.DOM, ["obs-1"], ClaimStatus.PARTIAL)
        report = _make_report(observations=[obs], claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "c-partial" in md
        assert "partial" in md.lower() or "conflicting" in md.lower()

    def test_no_observations_recommendation(self):
        claim = _make_claim("c1", "test", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        report = _make_report(observations=[], claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "observer" in md.lower() or "observation" in md.lower()

    def test_zero_observation_links_recommendation(self):
        claim = _make_claim("c-noobs", "unlinked", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        report = _make_report(claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "c-noobs" in md


# ---------------------------------------------------------------------------
# Tests: Orphan Observations section
# ---------------------------------------------------------------------------


class TestOrphanObservations:
    """Test orphan observations section."""

    def test_orphan_section_when_orphans_exist(self):
        obs = _make_observation("obs-orphan")
        report = _make_report(observations=[obs], claims=[])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "Orphan Observations" in md
        assert "obs-orphan" in md

    def test_no_orphan_section_when_all_linked(self):
        report = _verified_report()
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "## Orphan Observations" not in md

    def test_orphan_section_disabled(self):
        obs = _make_observation("obs-orphan")
        report = _make_report(observations=[obs], claims=[])
        renderer = EvidenceReportRenderer(show_orphan_observations=False)
        md = renderer.render_markdown(report)
        assert "## Orphan Observations" not in md


# ---------------------------------------------------------------------------
# Tests: RenderStats
# ---------------------------------------------------------------------------


class TestRenderStats:
    """Test RenderStats dataclass."""

    def test_to_dict(self):
        stats = RenderStats(total_claims=5, supported=3, unsupported=1, partial=1, total_observations=10, orphan_observations=2)
        d = stats.to_dict()
        assert d["total_claims"] == 5
        assert d["supported"] == 3
        assert d["unsupported"] == 1
        assert d["partial"] == 1
        assert d["total_observations"] == 10
        assert d["orphan_observations"] == 2

    def test_defaults(self):
        stats = RenderStats()
        assert stats.total_claims == 0
        assert stats.supported == 0
        assert stats.unsupported == 0


# ---------------------------------------------------------------------------
# Tests: RenderedReport
# ---------------------------------------------------------------------------


class TestRenderedReport:
    """Test RenderedReport output structure."""

    def test_rendered_report_fields(self):
        report = _verified_report()
        renderer = EvidenceReportRenderer()
        result = renderer.render(report)
        assert isinstance(result, RenderedReport)
        assert isinstance(result.markdown, str)
        assert isinstance(result.stats, RenderStats)
        assert result.report_id == report.report_id
        assert result.url == report.url
        assert isinstance(result.rendered_at, datetime)

    def test_rendered_report_to_dict(self):
        report = _verified_report()
        renderer = EvidenceReportRenderer()
        result = renderer.render(report)
        d = result.to_dict()
        assert "markdown" in d
        assert "stats" in d
        assert "report_id" in d
        assert "url" in d
        assert "rendered_at" in d


# ---------------------------------------------------------------------------
# Tests: Data preview truncation
# ---------------------------------------------------------------------------


class TestDataPreview:
    """Test observation data preview truncation."""

    def test_short_data_not_truncated(self):
        obs = _make_observation("obs-1", data={"key": "val"})
        report = _make_report(observations=[obs])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "key=val" in md

    def test_long_data_truncated(self):
        long_val = "x" * 500
        obs = _make_observation("obs-1", data={"big": long_val})
        report = _make_report(observations=[obs])
        renderer = EvidenceReportRenderer(max_data_preview=50)
        md = renderer.render_markdown(report)
        assert "..." in md

    def test_empty_data_shows_empty(self):
        obs = _make_observation("obs-1", data={})
        report = _make_report(observations=[obs])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "*empty*" in md


# ---------------------------------------------------------------------------
# Tests: High orphan ratio recommendation
# ---------------------------------------------------------------------------


class TestHighOrphanRatio:
    """Test orphan ratio recommendation."""

    def test_high_orphan_ratio_recommendation(self):
        # 10 observations, only 1 linked
        obs_list = [_make_observation(f"obs-{i}") for i in range(10)]
        claim = _make_claim("c1", "test", EvidenceType.DOM, ["obs-0"], ClaimStatus.SUPPORTED)
        report = _make_report(observations=obs_list, claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "orphan" in md.lower()


# ---------------------------------------------------------------------------
# Tests: Multiple evidence types
# ---------------------------------------------------------------------------


class TestMultipleEvidenceTypes:
    """Test rendering with multiple evidence types."""

    def test_all_evidence_types(self):
        obs_dom = _make_observation("obs-dom", EvidenceType.DOM)
        obs_net = _make_observation("obs-net", EvidenceType.NETWORK)
        obs_sto = _make_observation("obs-sto", EvidenceType.STORAGE)
        obs_act = _make_observation("obs-act", EvidenceType.ACTIONABILITY)

        claim_dom = _make_claim("c-dom", "dom claim", EvidenceType.DOM, ["obs-dom"], ClaimStatus.SUPPORTED)
        claim_net = _make_claim("c-net", "net claim", EvidenceType.NETWORK, ["obs-net"], ClaimStatus.SUPPORTED)
        claim_sto = _make_claim("c-sto", "sto claim", EvidenceType.STORAGE, ["obs-sto"], ClaimStatus.SUPPORTED)
        claim_act = _make_claim("c-act", "act claim", EvidenceType.ACTIONABILITY, ["obs-act"], ClaimStatus.SUPPORTED)

        report = _make_report(
            observations=[obs_dom, obs_net, obs_sto, obs_act],
            claims=[claim_dom, claim_net, claim_sto, claim_act],
        )
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "DOM" in md
        assert "Network" in md
        assert "Storage" in md
        assert "Actionability" in md


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_report(self):
        report = _make_report()
        renderer = EvidenceReportRenderer()
        result = renderer.render(report)
        assert result.stats.total_claims == 0
        assert result.stats.total_observations == 0
        assert "No claims" in result.markdown
        assert "No observations" in result.markdown

    def test_report_with_only_observations(self):
        obs = _make_observation("obs-1")
        report = _make_report(observations=[obs])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "## Evidence Chain" in md
        assert "obs-1" in md

    def test_report_with_only_claims(self):
        claim = _make_claim("c1", "test", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
        report = _make_report(claims=[claim])
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        assert "## Claims" in md
        assert "c1" in md

    def test_many_claims_numbered(self):
        claims = [
            _make_claim(f"c{i}", f"claim {i}", EvidenceType.DOM, [], ClaimStatus.UNSUPPORTED)
            for i in range(10)
        ]
        report = _make_report(claims=claims)
        renderer = EvidenceReportRenderer()
        md = renderer.render_markdown(report)
        # Check numbered headers
        assert "### 1." in md
        assert "### 10." in md
