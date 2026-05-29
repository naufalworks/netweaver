"""Enhanced SkillStore with confidence scoring, URL grouping, and intent-based retrieval.

Extends persistence concepts from site_skill.py with:
  - Confidence scoring (trusted status at >5 successful uses)
  - URL pattern grouping (group skills by site domain)
  - Combined URL + intent matching for skill retrieval
  - Default persistence to .tini/netweaver/skills/

Design:
  - Pure data — no browser/vendor imports
  - Uses existing SiteSkill as the data model
  - AutoSkillStore wraps filesystem persistence with enhanced queries
"""

from __future__ import annotations

import json
import string
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from netweaver.site_skill import SiteSkill


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRUSTED_THRESHOLD = 5  # skills with >5 successful uses get trusted status
DEFAULT_SKILLS_DIR = Path.home() / ".tini" / "netweaver" / "skills"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def compute_confidence(stats: Dict[str, Any]) -> float:
    """Compute a confidence score from execution stats.

    Confidence = success rate with a neutral prior of 0.5 for new skills.
    Skills with >TRUSTED_THRESHOLD successful uses get trusted status.

    Args:
        stats: Execution stats dict (success_count, total_count, etc.).

    Returns:
        Float in [0.0, 1.0] representing confidence.
    """
    success_count = stats.get("success_count", 0)
    total_count = stats.get("total_count", 0) or success_count
    if total_count == 0:
        return 0.5  # neutral prior
    return success_count / total_count


def is_trusted(skill: SiteSkill) -> bool:
    """Check if a skill has reached trusted status (>5 successful uses).

    Args:
        skill: The SiteSkill to check.

    Returns:
        True if the skill's success_count exceeds TRUSTED_THRESHOLD.
    """
    return skill.execution_stats.get("success_count", 0) > TRUSTED_THRESHOLD


def group_by_site(skills: List[SiteSkill]) -> Dict[str, List[SiteSkill]]:
    """Group skills by their site domain (extracted from URL/pattern).

    Args:
        skills: List of SiteSkills to group.

    Returns:
        Dict mapping domain -> list of skills at that domain.
    """
    groups: Dict[str, List[SiteSkill]] = {}
    for skill in skills:
        domain = _extract_domain(skill)
        if domain not in groups:
            groups[domain] = []
        groups[domain].append(skill)
    return groups


def _extract_domain(skill: SiteSkill) -> str:
    """Extract the primary domain from a SiteSkill's URL or pattern."""
    if skill.site_url:
        domain = skill.site_url.split("//")[-1].split("/")[0].lower()
        if domain:
            return domain
    if skill.site_pattern:
        domain = skill.site_pattern.split("/")[0].replace(".*", "").replace("*", "").lower()
        if domain:
            return domain
    return "unknown"


def _tokenize(text: str) -> set:
    """Tokenize a string into a set of lowercase words (2+ chars).

    Same tokenization as SkillMatcher._tokenize() for consistency.

    Args:
        text: Input text to tokenize.

    Returns:
        Set of lowercase word tokens with punctuation stripped.
    """
    tokens = set()
    for word in text.lower().split():
        cleaned = word.strip(string.punctuation)
        if len(cleaned) >= 2:
            tokens.add(cleaned)
    return tokens


# ---------------------------------------------------------------------------
# Enhanced SkillStore
# ---------------------------------------------------------------------------

class AutoSkillStore:
    """Enhanced SkillStore with confidence scoring, URL grouping, and intent-based retrieval.

    Wraps filesystem persistence (JSON files in a directory) and adds:
    - Confidence scoring with trusted status (>5 successful uses)
    - URL pattern grouping (group skills by site domain)
    - Combined URL + intent matching (find_by_url_and_intent)
    - Default persistence to ~/.tini/netweaver/skills/

    Usage:
        store = AutoSkillStore()
        store.save(skill)
        skills = store.find_by_url_and_intent("https://github.com/login", "log in")
        trusted = store.get_trusted_skills()
        by_site = store.get_skill_counts_by_site()
    """

    def __init__(self, skills_dir: Optional[Path] = None):
        """Initialize the AutoSkillStore.

        Args:
            skills_dir: Directory for skill persistence.
                Defaults to ~/.tini/netweaver/skills/
        """
        self.skills_dir = skills_dir or DEFAULT_SKILLS_DIR
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    # ---- CRUD operations ----

    def _path(self, skill_id: str) -> Path:
        """Get the filesystem path for a skill ID."""
        return self.skills_dir / f"{skill_id}.json"

    def save(self, skill: SiteSkill) -> Path:
        """Save a skill to disk as JSON.

        Args:
            skill: The SiteSkill to persist.

        Returns:
            Path to the saved JSON file.
        """
        skill.updated_at = datetime.now()
        path = self._path(skill.skill_id)
        path.write_text(json.dumps(skill.to_dict(), indent=2))
        return path

    def load(self, skill_id: str) -> Optional[SiteSkill]:
        """Load a skill from disk by ID.

        Args:
            skill_id: The skill's unique identifier.

        Returns:
            The SiteSkill if found, None otherwise.
        """
        path = self._path(skill_id)
        if not path.exists():
            return None
        try:
            return SiteSkill.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def delete(self, skill_id: str) -> bool:
        """Delete a skill from disk.

        Args:
            skill_id: The skill's unique identifier.

        Returns:
            True if the skill was deleted, False if it didn't exist.
        """
        path = self._path(skill_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self) -> List[SiteSkill]:
        """List all persisted skills.

        Returns:
            List of all SiteSkills, sorted by name.
        """
        skills = []
        for f in sorted(self.skills_dir.glob("*.json")):
            try:
                skill = SiteSkill.from_dict(json.loads(f.read_text()))
                skills.append(skill)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return skills

    def count(self) -> int:
        """Count the number of persisted skills.

        Returns:
            Integer count of valid skill files (corrupted files skipped).
        """
        return len(self.list_all())

    # ---- Query operations ----

    def find_by_site(self, site_url: str) -> List[SiteSkill]:
        """Find skills matching a URL pattern.

        Delegates to each skill's matches_site() method.

        Args:
            site_url: URL to match against skill patterns.

        Returns:
            List of matching SiteSkills.
        """
        return [s for s in self.list_all() if s.matches_site(site_url)]

    def find_by_goal(self, pattern: str) -> List[SiteSkill]:
        """Find skills whose goal matches a regex pattern (case-insensitive).

        Args:
            pattern: Regex pattern to match against skill goals.

        Returns:
            List of matching SiteSkills.
        """
        import re
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return []
        return [s for s in self.list_all() if regex.search(s.goal)]

    def find_by_url_and_intent(self, url: str, intent: str) -> List[SiteSkill]:
        """Find skills matching both a URL pattern and intent/goal.

        Two-stage match:
        1. Filter by site (URL pattern match via matches_site())
        2. Rank by intent overlap (Jaccard similarity on goal tokens)

        Args:
            url: The target URL.
            intent: Natural-language description of the intent.

        Returns:
            Ranked list of matching SiteSkills (best match first).
        """
        # Stage 1: filter by site
        site_skills = self.find_by_site(url)
        if not site_skills:
            return []

        # Tokenize intent
        intent_tokens = _tokenize(intent)
        if not intent_tokens:
            return site_skills

        # Stage 2: score and rank by intent overlap
        scored: List[tuple] = []
        for skill in site_skills:
            skill_tokens = _tokenize(skill.goal)
            if not skill_tokens:
                overlap = 0.0
            else:
                intersection = intent_tokens & skill_tokens
                union = intent_tokens | skill_tokens
                overlap = len(intersection) / len(union) if union else 0.0

            scored.append((overlap, skill.execution_stats.get("success_count", 0), skill))

        # Sort by overlap desc, then success_count desc
        scored.sort(key=lambda x: (-x[0], -x[1]))

        return [s for _, _, s in scored]

    # ---- Enhanced features ----

    def get_trusted_skills(self) -> List[SiteSkill]:
        """Get all skills that have reached trusted status.

        Trusted = success_count > TRUSTED_THRESHOLD (default 5).

        Returns:
            List of trusted SiteSkills.
        """
        return [s for s in self.list_all() if is_trusted(s)]

    def get_skill_counts_by_site(self) -> Dict[str, int]:
        """Get skill counts grouped by site domain.

        Returns:
            Dict mapping domain -> skill count.
        """
        grouped = group_by_site(self.list_all())
        return {domain: len(skills) for domain, skills in grouped.items()}

    def get_skills_with_confidence(self) -> List[dict]:
        """Get all skills with their computed confidence scores.

        Returns:
            List of dicts with skill_id, name, goal, domain, confidence, trusted.
        """
        results = []
        for skill in self.list_all():
            results.append({
                "skill_id": skill.skill_id,
                "name": skill.name,
                "goal": skill.goal,
                "domain": _extract_domain(skill),
                "confidence": compute_confidence(skill.execution_stats),
                "trusted": is_trusted(skill),
                "success_count": skill.execution_stats.get("success_count", 0),
                "total_count": skill.execution_stats.get("total_count", 0),
            })
        return results

    def merge_duplicate_skills(self, skill_a: SiteSkill, skill_b: SiteSkill) -> SiteSkill:
        """Merge two skills, keeping the one with higher success rate.

        Deduplication strategy: keep the skill with the higher success rate,
        merging learned selectors and evidence requirements.

        Args:
            skill_a: First skill to merge.
            skill_b: Second skill to merge.

        Returns:
            The merged SiteSkill (higher-success-rate skill with merged data).
        """
        # Determine which has higher success rate
        rate_a = compute_confidence(skill_a.execution_stats)
        rate_b = compute_confidence(skill_b.execution_stats)

        if rate_b > rate_a:
            primary, secondary = skill_b, skill_a
        else:
            primary, secondary = skill_a, skill_b

        # Merge stats
        primary.execution_stats["success_count"] = (
            primary.execution_stats.get("success_count", 0)
            + secondary.execution_stats.get("success_count", 0)
        )
        primary.execution_stats["total_count"] = (
            primary.execution_stats.get("total_count", 0)
            + secondary.execution_stats.get("total_count", 0)
        )

        # Union selectors (secondary takes precedence on conflict)
        merged_selectors = {**secondary.learned_selectors, **primary.learned_selectors}
        primary.learned_selectors = merged_selectors

        # Union evidence requirements
        merged_evidence = list(set(primary.evidence_requirements + secondary.evidence_requirements))
        primary.evidence_requirements = merged_evidence

        primary.updated_at = datetime.now()
        return primary
