"""NetWeaver Skill Matcher Engine — Ranked skill lookup by URL + goal.

The SkillMatcher bridges the SkillStore (NW-021) with runtime orchestration
by scoring and ranking stored skills against a target URL and goal. This
enables the system to find the best-matching learned skill for reuse.

Scoring formula (composite 0.0–1.0):
  - 0.4 × site_match   (1.0 if URL matches site_pattern, else 0.0)
  - 0.3 × goal_overlap  (Jaccard similarity of tokenized goal strings)
  - 0.3 × success_rate  (success_count / total_runs; new skills get 0.5 neutral prior)

Design principles:
  - Pure data transform — no browser/Playwright/vendor imports
  - Uses existing SkillStore API from site_skill.py
  - Deterministic scoring — same inputs always produce same rankings
"""

from dataclasses import dataclass
from typing import List

from netweaver.site_skill import SiteSkill, SkillStore


@dataclass
class SkillMatch:
    """A scored match between a query and a stored skill.

    Attributes:
        skill: The matched SiteSkill.
        score: Composite score (0.0–1.0).
        site_match: Whether the URL matched the skill's site_pattern.
        goal_overlap: Jaccard similarity of goal tokens (0.0–1.0).
        success_rate: Historical success rate (0.0–1.0, 0.5 for new skills).
        rank: Position in the ranked result list (1-based).
    """

    skill: SiteSkill
    score: float
    site_match: bool
    goal_overlap: float
    success_rate: float
    rank: int = 0


class SkillMatcher:
    """Rank-based skill matcher using composite scoring.

    Takes a SkillStore and provides match() to find and rank skills
    against a target URL and goal description.

    Usage:
        store = SkillStore(Path("skills/"))
        matcher = SkillMatcher(store)
        matches = matcher.match("https://github.com/login", "sign in to account")
    """

    # Scoring weights — must sum to 1.0
    SITE_WEIGHT = 0.4
    GOAL_WEIGHT = 0.3
    SUCCESS_WEIGHT = 0.3

    # Neutral prior for skills with zero executions
    NEUTRAL_PRIOR = 0.5

    def __init__(self, store: SkillStore):
        """Initialize with a SkillStore.

        Args:
            store: The SkillStore to search for matching skills.
        """
        self.store = store

    def match(
        self, url: str, goal: str, top_k: int = 5
    ) -> List[SkillMatch]:
        """Find and rank skills matching the given URL and goal.

        Args:
            url: Target URL to match against skill site_patterns.
            goal: Target goal description for semantic similarity.
            top_k: Maximum number of results to return (default 5).

        Returns:
            List of SkillMatch objects sorted by descending score,
            each with a 1-based rank. Empty list if no skills in store.
        """
        all_skills = self.store.list_all()
        if not all_skills:
            return []

        matches: List[SkillMatch] = []
        for skill in all_skills:
            site = self._site_score(skill, url)
            goal_sim = self._goal_score(skill, goal)
            success = self._success_score(skill)

            composite = (
                self.SITE_WEIGHT * site
                + self.GOAL_WEIGHT * goal_sim
                + self.SUCCESS_WEIGHT * success
            )

            matches.append(
                SkillMatch(
                    skill=skill,
                    score=composite,
                    site_match=bool(site > 0.0),
                    goal_overlap=goal_sim,
                    success_rate=success,
                )
            )

        # Sort descending by score, then by skill_id for deterministic tie-breaking
        matches.sort(key=lambda m: (-m.score, m.skill.skill_id))

        # Truncate to top_k
        matches = matches[:top_k]

        # Assign ranks
        for i, m in enumerate(matches, start=1):
            m.rank = i

        return matches

    def _site_score(self, skill: SiteSkill, url: str) -> float:
        """Score site match: 1.0 if matches, 0.0 otherwise.

        Args:
            skill: The skill to check.
            url: The target URL.

        Returns:
            1.0 if skill.matches_site(url) is True, else 0.0.
        """
        return 1.0 if skill.matches_site(url) else 0.0

    def _goal_score(self, skill: SiteSkill, goal: str) -> float:
        """Score goal similarity using Jaccard coefficient on word tokens.

        Tokenization: lowercase, split on whitespace, remove punctuation
        tokens shorter than 2 characters.

        Args:
            skill: The skill whose goal to compare.
            goal: The target goal description.

        Returns:
            Jaccard similarity (0.0–1.0) between token sets.
        """
        skill_tokens = self._tokenize(skill.goal)
        goal_tokens = self._tokenize(goal)

        if not skill_tokens and not goal_tokens:
            return 0.0
        if not skill_tokens or not goal_tokens:
            return 0.0

        intersection = skill_tokens & goal_tokens
        union = skill_tokens | goal_tokens

        return len(intersection) / len(union)

    def _success_score(self, skill: SiteSkill) -> float:
        """Score historical success rate with neutral prior for new skills.

        Args:
            skill: The skill whose execution stats to evaluate.

        Returns:
            success_count / total_runs, or 0.5 if no executions yet.
        """
        stats = skill.execution_stats
        success = stats.get("success_count", 0)
        fail = stats.get("fail_count", 0)
        total = success + fail

        if total == 0:
            return self.NEUTRAL_PRIOR

        return success / total

    @staticmethod
    def _tokenize(text: str) -> set:
        """Tokenize a string into a set of lowercase words.

        Splits on whitespace, strips common punctuation, filters tokens
        shorter than 2 characters.

        Args:
            text: Input text to tokenize.

        Returns:
            Set of lowercase word tokens.
        """
        import string

        tokens = set()
        for word in text.lower().split():
            # Strip leading/trailing punctuation
            cleaned = word.strip(string.punctuation)
            if len(cleaned) >= 2:
                tokens.add(cleaned)
        return tokens
