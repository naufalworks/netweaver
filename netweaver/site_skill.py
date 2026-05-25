"""Site-Specific Skills — learned behaviors for interacting with web sites.

The SiteSkill dataclass captures a learned sequence of browser interactions
at a specific URL domain. Skills are persisted via SkillStore as JSON files
and used by SkillMatcher at runtime to find reusable site knowledge.

Design:
  - Pure data — no browser/vendor imports
  - Serialized as JSON on disk under skills/<skill_id>.json
  - site_patterns: list of URL patterns this skill applies to (fnmatch-style)
  - action_plan: ordered list of browser action dicts from a successful orchestration
  - preconditions: list of conditions that must hold before the skill can be replayed
  - learned_selectors: CSS/XPath selectors discovered during execution
  - execution_stats: success_count, fail_count, last_used_at, etc.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SiteSkill:
    """A learned skill for interacting with a specific web site.

    Created from a successful OrchestrationResult, persisted to disk,
    and loaded by SkillMatcher for reuse at runtime.
    """

    def __init__(
        self,
        *,
        skill_id: Optional[str] = None,
        name: str = "",
        goal: str = "",
        site_url: str = "",
        site_pattern: str = "",
        site_patterns: Optional[List[str]] = None,
        action_plan: Optional[Dict[str, Any]] = None,
        preconditions: Optional[List[str]] = None,
        postconditions: Optional[List[str]] = None,
        evidence_requirements: Optional[List[str]] = None,
        learned_selectors: Optional[Dict[str, str]] = None,
        execution_stats: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.skill_id = skill_id if skill_id is not None else uuid.uuid4().hex[:8]
        self.name = name
        self.goal = goal
        self.site_url = site_url
        self.site_pattern = site_pattern
        self.site_patterns = site_patterns or ([f"{site_url}*"] if site_url else [])
        if site_pattern and not self.site_patterns:
            self.site_patterns = [site_pattern]
        self.action_plan = action_plan or {}
        self.preconditions = preconditions or []
        self.postconditions = postconditions or []
        self.evidence_requirements = evidence_requirements or []
        self.learned_selectors = learned_selectors or {}
        self.execution_stats = execution_stats or {
            "success_count": 0,
            "fail_count": 0,
            "total_count": 0,
            "last_used_at": None,
            "last_success_at": None,
        }
        now = datetime.now()
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def record_success(self) -> None:
        """Record a successful execution, updating stats."""
        self.execution_stats["success_count"] = self.execution_stats.get("success_count", 0) + 1
        self.execution_stats["total_count"] = self.execution_stats.get("total_count", 0) + 1
        self.execution_stats["last_used_at"] = datetime.now().isoformat()
        self.execution_stats["last_success_at"] = datetime.now().isoformat()
        self.updated_at = datetime.now()

    def record_failure(self) -> None:
        """Record a failed execution, updating stats."""
        self.execution_stats["fail_count"] = self.execution_stats.get("fail_count", 0) + 1
        self.execution_stats["total_count"] = self.execution_stats.get("total_count", 0) + 1
        self.execution_stats["last_used_at"] = datetime.now().isoformat()
        self.updated_at = datetime.now()

    def matches_site(self, url: str) -> bool:
        """Check if this skill might apply to the given URL."""
        import re
        from fnmatch import fnmatch

        # Try regex-based match first (site_pattern)
        if self.site_pattern:
            try:
                if re.search(self.site_pattern, url):
                    return True
            except re.error:
                pass

        # Fall back to fnmatch (site_patterns list)
        for pattern in self.site_patterns:
            if fnmatch(url, pattern):
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "goal": self.goal,
            "site_url": self.site_url,
            "site_pattern": self.site_pattern,
            "site_patterns": self.site_patterns,
            "action_plan": self.action_plan,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "evidence_requirements": self.evidence_requirements,
            "learned_selectors": self.learned_selectors,
            "execution_stats": self.execution_stats,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SiteSkill:
        return cls(
            skill_id=data.get("skill_id", None) or "",
            name=data.get("name", ""),
            goal=data.get("goal", ""),
            site_url=data.get("site_url", ""),
            site_pattern=data.get("site_pattern", ""),
            site_patterns=data.get("site_patterns", None),
            action_plan=data.get("action_plan"),
            preconditions=data.get("preconditions"),
            postconditions=data.get("postconditions"),
            evidence_requirements=data.get("evidence_requirements"),
            learned_selectors=data.get("learned_selectors"),
            execution_stats=data.get("execution_stats"),
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
        )

    @classmethod
    def from_orchestration_result(
        cls,
        result_dict: Dict[str, Any],
        plan_dict: Dict[str, Any],
        site_url: str,
        name: str = "",
        goal: str = "",
        learned_selectors: Optional[Dict[str, str]] = None,
    ) -> SiteSkill:
        """Create a SiteSkill from a successful orchestration result + plan.

        Extracts:
          - site_pattern from site_url (escaped domain)
          - preconditions from plan steps' pre_condition keys
          - postconditions from plan steps' post_condition keys
          - evidence_requirements from result steps' evidence_chain_ids (deduplicated)
          - goal from plan_dict description if not provided explicitly
        """
        import re as _re

        # Extract preconditions / postconditions from plan steps
        # Also fall back to result_dict preconditions
        preconds = list(result_dict.get("preconditions", []))
        postconds: list[str] = []
        for step in plan_dict.get("steps", []):
            if "pre_condition" in step and step["pre_condition"] not in preconds:
                pc = step["pre_condition"]
                if pc:
                    preconds.append(pc)
            if "post_condition" in step:
                postconds.append(step["post_condition"])

        # Extract evidence_chain_ids from all result steps (deduplicated)
        ev_ids: set[str] = set()
        for step in result_dict.get("steps", []):
            for eid in step.get("evidence_chain_ids", []):
                if eid:
                    ev_ids.add(eid)

        # Build site_pattern from URL (escaped domain)
        domain = site_url.split("//")[-1].split("/")[0]
        site_pattern = domain + r".*"

        # Goal falls back to plan description
        goal = goal or plan_dict.get("description", "")

        return cls(
            name=name or f"Skill-{domain}",
            goal=goal,
            site_url=site_url,
            site_pattern=site_pattern,
            site_patterns=[f"*{domain}*"],
            action_plan=plan_dict,
            preconditions=preconds,
            postconditions=postconds,
            evidence_requirements=sorted(ev_ids),
            learned_selectors=learned_selectors or {},
            execution_stats={
                "success_count": 1,
                "fail_count": 0,
                "last_success_at": datetime.now().isoformat(),
                "last_used_at": datetime.now().isoformat(),
            },
        )


class SkillStore:
    """Persistent store for SiteSkills, backed by JSON files on disk."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, skill_id: str) -> Path:
        return self.skills_dir / f"{skill_id}.json"

    def save(self, skill: SiteSkill) -> Path:
        skill.updated_at = datetime.now()
        path = self._path(skill.skill_id)
        path.write_text(json.dumps(skill.to_dict(), indent=2))
        return path

    def load(self, skill_id: str) -> Optional[SiteSkill]:
        path = self._path(skill_id)
        if path.exists():
            try:
                return SiteSkill.from_dict(json.loads(path.read_text()))
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def delete(self, skill_id: str) -> bool:
        path = self._path(skill_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self) -> List[SiteSkill]:
        skills = []
        for f in sorted(self.skills_dir.glob("*.json")):
            try:
                skills.append(SiteSkill.from_dict(json.loads(f.read_text())))
            except (json.JSONDecodeError, KeyError):
                continue
        return skills

    def find_by_site(self, site_url: str) -> List[SiteSkill]:
        return [s for s in self.list_all() if s.matches_site(site_url)]

    def find_by_goal(self, pattern: str) -> List[SiteSkill]:
        """Find skills whose goal matches a regex pattern (case-insensitive)."""
        import re
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return []
        return [s for s in self.list_all() if regex.search(s.goal)]

    def count(self) -> int:
        return len(list(self.skills_dir.glob("*.json")))


def _parse_dt(val: Any) -> Optional[datetime]:
    """Parse an ISO datetime string or return None."""
    if isinstance(val, datetime):
        return val
    if isinstance(val, str) and val:
        try:
            return datetime.fromisoformat(val)
        except (ValueError, TypeError):
            pass
    return None
