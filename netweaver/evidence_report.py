"""NetWeaver Evidence Report Renderer — human-readable markdown from EvidenceReport.

Takes EvidenceReport objects and produces markdown summaries showing:
- What was observed
- What claims were made
- What evidence backs each claim
- Recommendations for unsupported claims

Used for debugging, audit trails, and human review of automated navigation results.
No browser/vendor imports.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from netweaver.evidence import (
    Claim,
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
    Observation,
)


# ---------------------------------------------------------------------------
# Status icons for readable output
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    ClaimStatus.SUPPORTED: "✅",
    ClaimStatus.UNSUPPORTED: "❌",
    ClaimStatus.PARTIAL: "⚠️",
}

_EVIDENCE_TYPE_LABELS = {
    EvidenceType.DOM: "DOM",
    EvidenceType.NETWORK: "Network",
    EvidenceType.STORAGE: "Storage",
    EvidenceType.ACTIONABILITY: "Actionability",
}


@dataclass
class RenderStats:
    """Statistics computed during rendering."""

    total_claims: int = 0
    supported: int = 0
    unsupported: int = 0
    partial: int = 0
    total_observations: int = 0
    orphan_observations: int = 0  # observations not linked to any claim

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_claims": self.total_claims,
            "supported": self.supported,
            "unsupported": self.unsupported,
            "partial": self.partial,
            "total_observations": self.total_observations,
            "orphan_observations": self.orphan_observations,
        }


@dataclass
class RenderedReport:
    """Output of rendering an EvidenceReport."""

    markdown: str
    stats: RenderStats
    report_id: str
    url: str
    rendered_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "markdown": self.markdown,
            "stats": self.stats.to_dict(),
            "report_id": self.report_id,
            "url": self.url,
            "rendered_at": self.rendered_at.isoformat(),
        }


class EvidenceReportRenderer:
    """Renders EvidenceReport objects into human-readable markdown.

    Usage:
        renderer = EvidenceReportRenderer()
        result = renderer.render(report)
        print(result.markdown)
    """

    def __init__(self, show_orphan_observations: bool = True, max_data_preview: int = 200):
        """Initialize renderer.

        Args:
            show_orphan_observations: Include observations not linked to any claim.
            max_data_preview: Max chars for observation data preview (truncated with ...).
        """
        self.show_orphan_observations = show_orphan_observations
        self.max_data_preview = max_data_preview

    def render(self, report: EvidenceReport) -> RenderedReport:
        """Render an EvidenceReport into a RenderedReport with markdown.

        Args:
            report: The EvidenceReport to render.

        Returns:
            RenderedReport with markdown string, stats, and metadata.
        """
        stats = self._compute_stats(report)
        sections = [
            self._render_header(report),
            self._render_summary(report, stats),
            self._render_claims(report),
            self._render_evidence_chain(report),
            self._render_recommendations(report, stats),
        ]

        if self.show_orphan_observations:
            orphan_section = self._render_orphan_observations(report)
            if orphan_section:
                sections.append(orphan_section)

        markdown = "\n".join(sections)
        return RenderedReport(
            markdown=markdown,
            stats=stats,
            report_id=report.report_id,
            url=report.url,
            rendered_at=datetime.now(),
        )

    def render_markdown(self, report: EvidenceReport) -> str:
        """Convenience method: render and return just the markdown string.

        Args:
            report: The EvidenceReport to render.

        Returns:
            Markdown string.
        """
        return self.render(report).markdown

    # -----------------------------------------------------------------------
    # Internal: stats computation
    # -----------------------------------------------------------------------

    def _compute_stats(self, report: EvidenceReport) -> RenderStats:
        """Compute rendering statistics."""
        stats = RenderStats()
        stats.total_claims = len(report.claims)
        stats.total_observations = len(report.observations)

        for claim in report.claims:
            if claim.status == ClaimStatus.SUPPORTED:
                stats.supported += 1
            elif claim.status == ClaimStatus.UNSUPPORTED:
                stats.unsupported += 1
            elif claim.status == ClaimStatus.PARTIAL:
                stats.partial += 1

        # Orphan observations: not referenced by any claim
        linked_obs_ids = set()
        for claim in report.claims:
            linked_obs_ids.update(claim.observation_ids)
        stats.orphan_observations = sum(
            1 for obs in report.observations if obs.observation_id not in linked_obs_ids
        )

        return stats

    # -----------------------------------------------------------------------
    # Internal: section renderers
    # -----------------------------------------------------------------------

    def _render_header(self, report: EvidenceReport) -> str:
        """Render the report header."""
        lines = [
            f"# Evidence Report: {report.report_id}",
            "",
            f"**URL:** {report.url}",
            f"**Timestamp:** {report.timestamp.isoformat()}",
            "",
        ]
        return "\n".join(lines)

    def _render_summary(self, report: EvidenceReport, stats: RenderStats) -> str:
        """Render the summary section."""
        verified = report._check_verified()
        verdict = "✅ VERIFIED" if verified else "❌ NOT VERIFIED"

        lines = [
            "## Summary",
            "",
            f"**Verdict:** {verdict}",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Total Claims | {stats.total_claims} |",
            f"| Supported | {stats.supported} |",
            f"| Unsupported | {stats.unsupported} |",
            f"| Partial | {stats.partial} |",
            f"| Total Observations | {stats.total_observations} |",
            f"| Orphan Observations | {stats.orphan_observations} |",
            "",
        ]

        # Claims by evidence type
        if report.claims:
            lines.append("### Claims by Evidence Type")
            lines.append("")
            lines.append("| Type | Count |")
            lines.append("|------|-------|")
            for et in EvidenceType:
                count = len(report.get_claims_by_type(et))
                if count > 0:
                    lines.append(f"| {_EVIDENCE_TYPE_LABELS.get(et, et.value)} | {count} |")
            lines.append("")

        return "\n".join(lines)

    def _render_claims(self, report: EvidenceReport) -> str:
        """Render the claims section."""
        lines = [
            "## Claims",
            "",
        ]

        if not report.claims:
            lines.append("*No claims in this report.*")
            lines.append("")
            return "\n".join(lines)

        for i, claim in enumerate(report.claims, 1):
            icon = _STATUS_ICONS.get(claim.status, "❓")
            status_label = claim.status.value.upper()
            et_label = _EVIDENCE_TYPE_LABELS.get(claim.evidence_type, claim.evidence_type.value)

            lines.append(f"### {i}. {icon} {claim.claim_id} — {status_label}")
            lines.append("")
            lines.append(f"**Statement:** {claim.description}")
            lines.append(f"**Evidence Type:** {et_label}")
            lines.append(f"**Backing Observations:** {', '.join(claim.observation_ids) if claim.observation_ids else '*none*'}")
            lines.append("")

        return "\n".join(lines)

    def _render_evidence_chain(self, report: EvidenceReport) -> str:
        """Render the evidence chain — observations in chronological order."""
        lines = [
            "## Evidence Chain",
            "",
        ]

        if not report.observations:
            lines.append("*No observations recorded.*")
            lines.append("")
            return "\n".join(lines)

        # Sort observations chronologically
        sorted_obs = sorted(report.observations, key=lambda o: o.timestamp)

        # Build reverse map: observation_id → list of claim_ids that reference it
        obs_to_claims: Dict[str, List[str]] = {}
        for claim in report.claims:
            for oid in claim.observation_ids:
                obs_to_claims.setdefault(oid, []).append(claim.claim_id)

        for i, obs in enumerate(sorted_obs, 1):
            et_label = _EVIDENCE_TYPE_LABELS.get(obs.evidence_type, obs.evidence_type.value)
            linked_claims = obs_to_claims.get(obs.observation_id, [])

            lines.append(f"### Obs {i}: {obs.observation_id}")
            lines.append("")
            lines.append(f"- **Type:** {et_label}")
            lines.append(f"- **Time:** {obs.timestamp.isoformat()}")
            lines.append(f"- **Source:** {obs.source}")
            if linked_claims:
                lines.append(f"- **Supports Claims:** {', '.join(linked_claims)}")
            else:
                lines.append(f"- **Supports Claims:** *orphan (not linked)*")

            # Data preview
            data_str = self._format_data_preview(obs.data)
            lines.append(f"- **Data:** {data_str}")
            lines.append("")

        return "\n".join(lines)

    def _render_recommendations(self, report: EvidenceReport, stats: RenderStats) -> str:
        """Render recommendations based on report state."""
        lines = [
            "## Recommendations",
            "",
        ]

        recommendations = self._generate_recommendations(report, stats)

        if not recommendations:
            lines.append("✅ All claims are supported. No action needed.")
            lines.append("")
            return "\n".join(lines)

        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

        return "\n".join(lines)

    def _render_orphan_observations(self, report: EvidenceReport) -> Optional[str]:
        """Render orphan observations section, if any exist."""
        linked_obs_ids = set()
        for claim in report.claims:
            linked_obs_ids.update(claim.observation_ids)

        orphans = [obs for obs in report.observations if obs.observation_id not in linked_obs_ids]
        if not orphans:
            return None

        lines = [
            "## Orphan Observations",
            "",
            "The following observations were recorded but not linked to any claim:",
            "",
        ]

        for obs in orphans:
            et_label = _EVIDENCE_TYPE_LABELS.get(obs.evidence_type, obs.evidence_type.value)
            lines.append(f"- **{obs.observation_id}** ({et_label}) — {obs.source} at {obs.timestamp.isoformat()}")
        lines.append("")

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Internal: helpers
    # -----------------------------------------------------------------------

    def _generate_recommendations(self, report: EvidenceReport, stats: RenderStats) -> List[str]:
        """Generate actionable recommendations based on report state."""
        recommendations = []

        # Unsupported claims
        unsupported = [c for c in report.claims if c.status == ClaimStatus.UNSUPPORTED]
        if unsupported:
            claim_ids = ", ".join(c.claim_id for c in unsupported)
            recommendations.append(
                f"Investigate unsupported claims ({claim_ids}): "
                f"add observations or revise claim descriptions."
            )

        # Partial claims
        partial = [c for c in report.claims if c.status == ClaimStatus.PARTIAL]
        if partial:
            claim_ids = ", ".join(c.claim_id for c in partial)
            recommendations.append(
                f"Review partial claims ({claim_ids}): "
                f"conflicting observations detected — verify which observations are authoritative."
            )

        # No observations at all
        if stats.total_observations == 0 and stats.total_claims > 0:
            recommendations.append(
                "No observations recorded. Run the observer pipeline to collect DOM/network/storage evidence."
            )

        # High orphan ratio
        if stats.total_observations > 0:
            orphan_ratio = stats.orphan_observations / stats.total_observations
            if orphan_ratio > 0.5:
                recommendations.append(
                    f"{stats.orphan_observations}/{stats.total_observations} observations are orphans "
                    f"(not linked to any claim). Consider linking them or pruning stale observations."
                )

        # Claims without any observation IDs
        no_obs_claims = [c for c in report.claims if not c.observation_ids]
        if no_obs_claims:
            claim_ids = ", ".join(c.claim_id for c in no_obs_claims)
            recommendations.append(
                f"Claims with zero observation links ({claim_ids}): "
                f"these will always be unsupported. Add observation references."
            )

        return recommendations

    def _format_data_preview(self, data: Dict[str, Any]) -> str:
        """Format observation data as a concise preview string."""
        if not data:
            return "*empty*"

        parts = []
        for key, value in data.items():
            val_str = str(value)
            if len(val_str) > self.max_data_preview:
                val_str = val_str[:self.max_data_preview] + "..."
            parts.append(f"{key}={val_str}")

        result = ", ".join(parts)
        if len(result) > self.max_data_preview * 2:
            result = result[:self.max_data_preview * 2] + "..."
        return f"`{result}`"


def render_evidence_report(report: EvidenceReport) -> str:
    """Convenience function: render an EvidenceReport to markdown.

    Args:
        report: The EvidenceReport to render.

    Returns:
        Markdown string.
    """
    renderer = EvidenceReportRenderer()
    return renderer.render_markdown(report)
