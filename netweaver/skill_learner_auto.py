"""NetWeaver Auto Skill Learner — Automatic skill learning from execution logs.

The AutoSkillLearner observes execution sequences with evidence,
identifies successful patterns, and persists them as reusable SiteSkills.
It builds on the existing SkillLearner system (NW-025) by adding:

  - Execution log observation: scans action sequences with evidence
  - Pattern detection: identifies action sequences that consistently succeed
  - Automatic persistence: learns from execution results via poll_and_learn()
  - Integration with AutoSkillStore for confidence/trusted status

Core concepts:
  - ActionEvidence: a single step's evidence (action + execution + result)
  - learn_from_execution(): extracts SiteSkills from a list of ActionEvidence
  - poll_and_learn(): scans trace directory for completed traces to learn from

Design principles:
  - Pure data transform — no browser/Playwright/vendor imports
  - Uses existing SkillLearner and AutoSkillStore under the hood
  - No side effects when learn_from_execution() returns empty
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from netweaver.site_skill import SiteSkill
from netweaver.skill_store import AutoSkillStore, DEFAULT_SKILLS_DIR
from netweaver.skill_learner import SkillLearner


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ActionEvidence:
    """Evidence from a single action execution step.

    Captures what action was taken, whether it succeeded, and what
    evidence observations were produced. Used as input to the
    AutoSkillLearner for pattern detection.

    Attributes:
        action_id: Unique identifier for this action.
        action_type: Type of action (click, fill, wait, navigate).
        target_ref: CSS selector or description of the target element.
        status: Execution status ('success', 'failed', 'safety_blocked').
        evidence_observation_ids: List of observation IDs produced.
        url: URL where the action was executed.
        timestamp: When the action was executed.
        error: Error message if the action failed.
        metadata: Additional context (page state, etc.).
    """
    action_id: str
    action_type: str
    target_ref: str
    status: str
    evidence_observation_ids: List[str] = field(default_factory=list)
    url: str = ""
    timestamp: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionEvidence":
        """Create from a dict (e.g., parsed from trace JSONL)."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                ts = None
        return cls(
            action_id=data.get("action_id", ""),
            action_type=data.get("action_type", ""),
            target_ref=data.get("target_ref", ""),
            status=data.get("status", ""),
            evidence_observation_ids=data.get("evidence_observation_ids", []),
            url=data.get("url", ""),
            timestamp=ts,
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target_ref": self.target_ref,
            "status": self.status,
            "evidence_observation_ids": self.evidence_observation_ids,
            "url": self.url,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "error": self.error,
            "metadata": self.metadata,
        }

    @property
    def is_success(self) -> bool:
        """Check if this action execution was successful."""
        return self.status in ("success", "completed")


# ---------------------------------------------------------------------------
# Default trace directory
# ---------------------------------------------------------------------------

DEFAULT_TRACES_DIR = Path.home() / ".tini" / "netweaver" / "traces"


# ---------------------------------------------------------------------------
# Auto Skill Learner
# ---------------------------------------------------------------------------

class AutoSkillLearner:
    """Automatic skill learner that observes execution logs and persists skills.

    Observes sequences of ActionEvidence, identifies successful patterns,
    and uses the existing SkillLearner to create/merge SiteSkills.

    Usage:
        learner = AutoSkillLearner()
        execution_log = [
            ActionEvidence(action_id="act-1", action_type="click", ...),
            ActionEvidence(action_id="act-2", action_type="fill", ...),
        ]
        skills = learner.learn_from_execution(execution_log, url="https://example.com")

        # Or scan trace directory for completed traces:
        new_skills = learner.poll_and_learn()
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        traces_dir: Optional[Path] = None,
    ):
        """Initialize the AutoSkillLearner.

        Args:
            skills_dir: Directory for skill persistence.
                Defaults to ~/.tini/netweaver/skills/
            traces_dir: Directory to scan for execution traces.
                Defaults to ~/.tini/netweaver/traces/
        """
        self._store = AutoSkillStore(skills_dir)
        self._base_learner = SkillLearner(self._store)
        self.traces_dir = traces_dir or DEFAULT_TRACES_DIR
        self._processed_traces: set = set()
        # Track recently learned skills to avoid duplicates in same batch
        self._recent_skill_ids: set = set()

    # ---- Public API ----

    def learn_from_execution(
        self,
        execution_log: List[ActionEvidence],
        *,
        url: str = "",
        goal: str = "",
    ) -> List[SiteSkill]:
        """Learn skills from an execution log.

        Analyzes an execution log (list of ActionEvidence), identifies
        successful action sequences, and creates/merges SiteSkills.

        Args:
            execution_log: List of ActionEvidence from an execution run.
            url: The URL where the execution occurred.
            goal: Optional goal description for the learned skill.

        Returns:
            List of SiteSkills that were created or merged.
        """
        if not execution_log:
            return []

        # Identify successful patterns
        successful_actions = self._find_successful_patterns(execution_log)
        if not successful_actions:
            return []

        # Group by URL and extract site context
        site_url = url or self._infer_url(execution_log)
        if not site_url:
            return []

        # Build a synthetic skill from the successful pattern
        # Use the existing from_orchestration_result pattern via base learner
        skill = self._build_skill_from_pattern(
            actions=successful_actions,
            site_url=site_url,
            goal=goal,
        )
        if skill is None:
            return []

        # Dedup against recently learned skills in this batch
        if skill.skill_id in self._recent_skill_ids:
            return []

        # Persist via base learner pattern (quality gate, dedup, merge)
        return self._persist_skill(skill)

    def poll_and_learn(self) -> List[SiteSkill]:
        """Scan trace directory for new completed traces and learn from them.

        Reads JSONL trace files from the traces directory, parses
        completed executions, and creates/merges SiteSkills.

        Returns:
            List of SiteSkills that were created or merged.
        """
        if not self.traces_dir.exists():
            return []

        new_skills: List[SiteSkill] = []
        trace_files = sorted(self.traces_dir.glob("*.jsonl"))

        for trace_path in trace_files:
            if str(trace_path) in self._processed_traces:
                continue

            execution_log = self._parse_trace(trace_path)
            if not execution_log:
                self._processed_traces.add(str(trace_path))
                continue

            # Infer URL and goal from trace
            url = self._infer_url(execution_log)
            goal = self._infer_goal(execution_log)

            skills = self.learn_from_execution(
                execution_log,
                url=url,
                goal=goal,
            )
            new_skills.extend(skills)
            self._processed_traces.add(str(trace_path))

        return new_skills

    # ---- Internal helpers ----

    def _find_successful_patterns(self, log: List[ActionEvidence]) -> List[ActionEvidence]:
        """Find sequences of actions that were fully successful.

        Returns the longest contiguous suffix (or all if all succeed)
        of successful actions. Includes at least 2 actions for a meaningful skill.

        Args:
            log: Execution log to analyze.

        Returns:
            List of successful ActionEvidence entries.
        """
        if not log:
            return []

        # All successful?
        all_success = all(a.is_success for a in log)
        if all_success and len(log) >= 2:
            return log

        # Find the longest trailing successful sequence
        for i in range(len(log) - 1, -1, -1):
            if not log[i].is_success:
                trailing = log[i + 1:]
                return trailing if len(trailing) >= 2 else []

        # Partial but enough successful
        successful = [a for a in log if a.is_success]
        return successful if len(successful) >= 2 else []

    def _build_skill_from_pattern(
        self,
        actions: List[ActionEvidence],
        site_url: str,
        goal: str = "",
    ) -> Optional[SiteSkill]:
        """Build a SiteSkill from a successful action pattern.

        Constructs a minimal SiteSkill with action plan derived from
        the successful action sequence.

        Args:
            actions: Successful ActionEvidence list.
            site_url: URL where the pattern was found.
            goal: Optional goal description.

        Returns:
            A SiteSkill, or None if the pattern is invalid.
        """
        if not actions:
            return None

        import uuid
        from netweaver.site_skill import SiteSkill

        # Build action plan from the action sequence
        steps = []
        for i, act in enumerate(actions):
            step = {
                "action_type": act.action_type,
                "description": act.target_ref,
                "intent": act.metadata.get("intent", act.action_type),
                "text": act.metadata.get("text", ""),
                "condition": act.metadata.get("condition", "attached"),
                "timeout_ms": act.metadata.get("timeout_ms", 5000),
                "pre_condition": act.metadata.get("pre_condition", ""),
                "post_condition": act.metadata.get("post_condition", ""),
            }
            steps.append(step)

        action_plan = {
            "plan_id": f"auto-{uuid.uuid4().hex[:12]}",
            "description": goal or f"Auto-learned from {site_url}",
            "steps": steps,
            "metadata": {},
        }

        # Extract learned selectors
        learned_selectors: dict = {}
        for act in actions:
            selector = act.target_ref
            if selector and selector not in learned_selectors:
                learned_selectors[act.action_type] = selector

        # Determine domain for naming
        domain = site_url.split("//")[-1].split("/")[0] if site_url else "unknown"

        return SiteSkill(
            name=f"AutoSkill-{domain}",
            goal=goal or f"Auto-learned sequence on {domain}",
            site_url=site_url,
            site_pattern=domain + r".*",
            site_patterns=[f"*{domain}*"],
            action_plan=action_plan,
            preconditions=[act.metadata.get("pre_condition", "") for act in actions if act.metadata.get("pre_condition")],
            postconditions=[act.metadata.get("post_condition", "") for act in actions if act.metadata.get("post_condition")],
            evidence_requirements=list(set(
                oid for act in actions for oid in act.evidence_observation_ids
            )),
            learned_selectors=learned_selectors,
        )

    def _persist_skill(self, skill: SiteSkill) -> List[SiteSkill]:
        """Persist a skill using quality gates and dedup/merge.

        Similar to SkillLearner.learn_and_store() but operates on
        the new skill directly (no OrchestrationResult needed).

        Args:
            skill: The SiteSkill to persist.

        Returns:
            List with the persisted skill, or empty if rejected.
        """
        # Quality gate
        if not self._passes_quality_gate(skill):
            return []

        # Dedup: check for similar skills at the same site
        existing = self._find_similar(skill, skill.site_url)
        if existing:
            merged = self._store.merge_duplicate_skills(existing, skill)
            self._store.save(merged)
            self._recent_skill_ids.add(merged.skill_id)
            return [merged]

        # Save as new
        self._store.save(skill)
        self._recent_skill_ids.add(skill.skill_id)
        return [skill]

    def _passes_quality_gate(self, skill: SiteSkill) -> bool:
        """Check if a skill meets minimum quality requirements.

        A skill must have:
        - At least one step in its action plan
        - Non-empty goal string
        - A name

        Args:
            skill: The skill to check.

        Returns:
            True if the skill passes all quality checks.
        """
        steps = skill.action_plan.get("steps", [])
        if len(steps) == 0:
            return False
        if not skill.goal or not skill.goal.strip():
            return False
        if not skill.name or not skill.name.strip():
            return False
        return True

    def _find_similar(self, skill: SiteSkill, site_url: str) -> Optional[SiteSkill]:
        """Find a similar existing skill at the same site.

        Similarity measured by Jaccard overlap on goal tokens (>0.5).

        Args:
            skill: The new skill to compare.
            site_url: URL to filter existing skills by.

        Returns:
            A similar existing SiteSkill, or None.
        """
        try:
            existing_skills = self._store.find_by_site(site_url)
        except Exception:
            return None

        new_tokens = self._tokenize_goal(skill.goal)
        if not new_tokens:
            return None

        for existing in existing_skills:
            existing_tokens = self._tokenize_goal(existing.goal)
            if not existing_tokens:
                continue
            intersection = new_tokens & existing_tokens
            union = new_tokens | existing_tokens
            jaccard = len(intersection) / len(union)
            if jaccard > 0.5:
                return existing

        return None

    @staticmethod
    def _tokenize_goal(text: str) -> set:
        """Tokenize goal text for similarity comparison.

        Splits on whitespace, strips punctuation, filters short tokens.

        Args:
            text: Goal text to tokenize.

        Returns:
            Set of lowercase word tokens (2+ chars).
        """
        import string as _string
        tokens = set()
        for word in text.lower().split():
            cleaned = word.strip(_string.punctuation)
            if len(cleaned) >= 2:
                tokens.add(cleaned)
        return tokens

    # ---- Trace parsing ----

    def _parse_trace(self, trace_path: Path) -> List[ActionEvidence]:
        """Parse a JSONL trace file into ActionEvidence entries.

        Reads step_transition entries from the trace and converts them
        to ActionEvidence objects.

        Args:
            trace_path: Path to the JSONL trace file.

        Returns:
            List of ActionEvidence entries.
        """
        if not trace_path.exists():
            return []

        entries: List[Dict[str, Any]] = []
        try:
            with open(trace_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except (json.JSONDecodeError, IOError, OSError):
            return []

        # Only learn from completed plans (plan_end with status COMPLETED)
        plan_ended_ok = any(
            e.get("type") == "plan_end" and e.get("status") == "completed"
            for e in entries
        )
        if not plan_ended_ok:
            return []

        # Extract step transitions
        step_entries = [e for e in entries if e.get("type") == "step_transition"]
        if not step_entries:
            return []

        # Infer URL from plan metadata
        plan_header = next((e for e in entries if e.get("type") == "plan_start"), {})
        trace_url = plan_header.get("url", "")

        execution_log: List[ActionEvidence] = []
        for entry in step_entries:
            status = entry.get("status", "pending")
            # Map plan status to execution status
            if status in ("completed", "COMPLETED"):
                exec_status = "success"
            elif status in ("failed", "FAILED", "safety_blocked", "SAFETY_BLOCKED"):
                exec_status = "failed"
            else:
                exec_status = "pending"

            evidence_ids: List[str] = []
            evidence_entry = entry.get("evidence_chain_ids", [])
            if evidence_entry:
                evidence_ids = list(evidence_entry)

            evidence = ActionEvidence(
                action_id=f"trace-step-{entry.get('step_index', 0)}",
                action_type=entry.get("action_type", "unknown"),
                target_ref=entry.get("description", ""),
                status=exec_status,
                evidence_observation_ids=evidence_ids,
                url=entry.get("url", trace_url),
                error=entry.get("error"),
                metadata={
                    "intent": entry.get("intent", ""),
                    "pre_condition": entry.get("pre_condition", ""),
                    "post_condition": entry.get("post_condition", ""),
                },
            )
            execution_log.append(evidence)

        return execution_log

    @staticmethod
    def _infer_url(log: List[ActionEvidence]) -> str:
        """Infer the primary URL from an execution log.

        Takes the URL from the first entry that has one.

        Args:
            log: Execution log to analyze.

        Returns:
            URL string, or empty string if none found.
        """
        for entry in log:
            if entry.url:
                return entry.url
        return ""

    @staticmethod
    def _infer_goal(log: List[ActionEvidence]) -> str:
        """Infer a goal description from an execution log.

        Concatenates action descriptions into a brief goal.

        Args:
            log: Execution log to analyze.

        Returns:
            Goal string describing the action sequence.
        """
        if not log:
            return ""
        descriptions = [a.target_ref for a in log if a.target_ref and a.is_success]
        if not descriptions:
            return ""
        # Take first 3 action descriptions for a concise goal
        goal_parts = descriptions[:3]
        return " → ".join(goal_parts) if len(goal_parts) <= 5 else f"{' → '.join(goal_parts[:3])}…"
