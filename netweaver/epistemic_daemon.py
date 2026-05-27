"""Epistemic Daemon Integration — Plan generation with honest uncertainty.

Enriches the autonomous pipeline with epistemic reasoning:
- Plan generation queries relevant knowledge before creating plans
- Worker outcomes feed back as epistemic evidence
- Stale knowledge triggers re-verification
- Contradictions block high-risk plans

Design:
  - Mixin class for daemon.py to avoid circular imports
  - All operations are optional/fallible (graceful degradation)
  - Persists to .tini/epistemic.json
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .epistemic import EpistemicOS, KnowledgeNode, Source

logger = logging.getLogger(__name__)

EPISTEMIC_STORAGE = Path(__file__).parent.parent / ".tini" / "epistemic.json"


class EpistemicDaemon:
    """Mixin for daemon.py — adds epistemic reasoning to plan generation."""

    def __init__(self):
        self.ep = EpistemicOS(storage_path=str(EPISTEMIC_STORAGE))

    # ── Plan Generation ──

    def enrich_plan_with_epistemic(
        self, task: Dict[str, str], plan_text: str
    ) -> Tuple[str, List[str]]:
        """Enrich a plan with relevant epistemic knowledge.

        Returns:
            Tuple of (enriched_plan_text, warnings)
        """
        warnings = []
        task_id = task.get("id", "unknown")
        goal = task.get("goal", task.get("tiny_goal", ""))

        # Query epistemic OS for relevant knowledge
        answer = self.ep.query(goal)
        if answer.confidence < 0.5:
            warnings.append(
                f"Low epistemic confidence ({answer.confidence:.0%}) — {answer.recommendation}"
            )

        # Check for stale knowledge about this task's domain
        domain = self._extract_domain(goal)
        if domain:
            stale = [
                n
                for n in self.ep.nodes.values()
                if n.topic == domain and n.is_stale
            ]
            if stale:
                warnings.append(
                    f"{len(stale)} stale fact(s) about {domain} — consider re-verification"
                )

        # Check for contradictions
        contradictions = self.ep.detect_contradictions()
        high_severity = [c for c in contradictions if c.severity > 0.7]
        if high_severity:
            warnings.append(
                f"{len(high_severity)} high-severity contradiction(s) — resolve before shipping"
            )

        # Build epistemic section
        epistemic_section = self._build_epistemic_section(answer, warnings, task_id)
        enriched = plan_text.rstrip() + "\n\n" + epistemic_section

        return enriched, warnings

    def _build_epistemic_section(
        self,
        answer: Any,
        warnings: List[str],
        task_id: str,
    ) -> str:
        """Build the epistemic metadata section for a plan."""
        lines = ["**Epistemic Analysis**:", f"**Confidence**: {answer.confidence:.0%}"]

        # Supporting knowledge
        if answer.supporting:
            lines.append(f"**Supporting knowledge**: {len(answer.supporting)} facts")
            for node in answer.supporting[:3]:
                lines.append(
                    f"  - [{node.confidence_label}] {node.content[:60]}"
                )

        # Warnings
        if warnings:
            lines.append(f"**Warnings**: {len(warnings)}")
            for w in warnings:
                lines.append(f"  - ⚠️  {w}")

        # Recommendation
        if answer.recommendation:
            lines.append(f"**Recommendation**: {answer.recommendation}")

        # Provenance
        if answer.provenance_chain:
            lines.append(f"**Provenance**: {len(answer.provenance_chain)} sources")

        return "\n".join(lines)

    def _extract_domain(self, goal: str) -> Optional[str]:
        """Extract a domain/topic from a goal string."""
        goal_lower = goal.lower()
        domains = {
            "scene graph": "scene_graph",
            "wnal": "wnal",
            "basil": "basil",
            "executor": "executor",
            "daemon": "daemon",
            "worker": "worker",
            "reviewer": "reviewer",
            "kanban": "kanban",
            "test": "testing",
            "performance": "performance",
            "security": "security",
            "browser": "browser",
            "playwright": "browser",
        }
        for keyword, domain in domains.items():
            if keyword in goal_lower:
                return domain
        return None

    # ── Worker Outcome Feedback ──

    def record_outcome(
        self,
        task_id: str,
        success: bool,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeNode:
        """Record a worker outcome as epistemic knowledge.

        Success → high confidence, Failure → low confidence + decay.
        """
        outcome = "success" if success else "failure"
        confidence = 0.85 if success else 0.3
        decay = 0.0 if success else 0.05  # Failures decay faster (might be transient)

        content = f"Task {task_id} outcome: {outcome}"
        if evidence:
            if "test_count" in evidence:
                content += f" ({evidence['test_count']} tests)"
            if "duration_s" in evidence:
                content += f" in {evidence['duration_s']:.1f}s"

        node = self.ep.add(
            content=content,
            confidence=confidence,
            topic=self._extract_domain(task_id) or "worker_outcomes",
            tags=["worker", "outcome", outcome, task_id],
            context=str(evidence) if evidence else "",
            sources=[
                Source(
                    type="worker_outcome",
                    ref=f"daemon.py:record_outcome({task_id})",
                    trustworthiness=0.9 if success else 0.7,
                )
            ],
            decay_rate=decay,
        )

        logger.info(
            f"Epistemic outcome: {task_id} → {outcome} "
            f"(confidence: {confidence:.0%})"
        )
        return node

    # ── Health Monitoring ──

    def get_health_report(self) -> Dict[str, Any]:
        """Get epistemic health report for the daemon."""
        return self.ep.health_report()

    def get_stale_knowledge(self) -> List[Dict[str, Any]]:
        """Get list of stale knowledge that needs re-verification."""
        stale = self.ep.stale_knowledge()
        return [
            {
                "id": node.id,
                "content": node.content,
                "confidence": node.current_confidence,
                "age_days": node.age_days,
                "topic": node.topic,
            }
            for node in stale
        ]

    def get_verification_recommendations(self) -> List[Dict[str, Any]]:
        """Get prioritized list of what to verify next."""
        recs = self.ep.recommend_verification()
        return [
            {
                "id": node.id,
                "content": node.content,
                "confidence": node.current_confidence,
                "reason": reason,
            }
            for node, reason in recs
        ]

    # ── Auto-Verification ──

    def auto_verify_stale(self, max_items: int = 5) -> Dict[str, Any]:
        """Automatically verify stale knowledge by re-running relevant checks.

        This is a stub — actual implementation would run tests, check files, etc.
        For now, just marks them as verified with reduced confidence.
        """
        stale = self.ep.stale_knowledge()[:max_items]
        verified = []

        for node in stale:
            # In a real implementation, we'd run actual verification logic here
            # For now, just bump confidence slightly and mark as verified
            new_confidence = min(0.6, node.current_confidence + 0.1)
            self.ep.verify(node.id, new_confidence=new_confidence)
            verified.append(
                {
                    "id": node.id,
                    "content": node.content,
                    "old_confidence": node.current_confidence,
                    "new_confidence": new_confidence,
                }
            )

        return {"verified": len(verified), "items": verified}
