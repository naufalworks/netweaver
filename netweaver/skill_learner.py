"""NetWeaver Skill Learner — Closes the learning loop from execution to reusable skill.

The SkillLearner transforms successful OrchestrationResults into persistent
SiteSkills, enabling the system to learn from its own successful executions.
It enforces quality gates, handles deduplication via goal overlap (Jaccard),
and merges new observations into existing skills when a similar one is found.

Core concepts:
  - learn(): extract a SiteSkill from a successful OrchestrationResult + ActionPlan
  - learn_and_store(): learn + quality gate + dedup/merge + persist via SkillStore
  - Quality gate: rejects skills with empty steps, preconditions, or goal
  - Deduplication: Jaccard > 0.5 on goal tokens triggers merge instead of create
  - Merge: increment success_count, union learned_selectors, bump updated_at

Design principles:
  - Pure data transform — no browser/Playwright/vendor imports
  - Uses existing SiteSkill.from_orchestration_result(), SkillStore APIs
  - Reuses tokenization pattern from SkillMatcher._tokenize()
"""

from __future__ import annotations

import string
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from netweaver.action_orchestrator import ActionPlan, OrchestrationResult, PlanStatus
from netweaver.site_skill import SiteSkill, SkillStore


class SkillLearner:
    """Learn and persist site skills from successful orchestrations.

    Takes a SkillStore and provides methods to transform successful
    OrchestrationResults into persistent SiteSkills with quality gating,
    deduplication, and merge semantics.

    Usage:
        store = SkillStore(Path("skills/"))
        learner = SkillLearner(store)
        skill, action = learner.learn_and_store(result, plan, "https://example.com")
        # action is "created", "merged", or "rejected"
    """

    # Jaccard threshold above which two skills are considered duplicates
    SIMILARITY_THRESHOLD = 0.5

    def __init__(self, store: SkillStore):
        """Initialize with a SkillStore.

        Args:
            store: The SkillStore to search and persist skills.
        """
        self.store = store

    def learn(
        self,
        result: OrchestrationResult,
        plan: ActionPlan,
        site_url: str,
        *,
        name: str = "",
        goal: str = "",
        learned_selectors: Optional[Dict[str, str]] = None,
    ) -> Optional[SiteSkill]:
        """Extract a SiteSkill from a successful orchestration result.

        Only creates a skill if the orchestration completed successfully.
        Returns None for failed or non-completed results.

        Args:
            result: The OrchestrationResult to learn from.
            plan: The ActionPlan that was executed.
            site_url: The URL where this skill was learned.
            name: Optional skill name override.
            goal: Optional goal description override.
            learned_selectors: Optional map of description → selector.

        Returns:
            A new SiteSkill, or None if result is not successful.
        """
        if result.status != PlanStatus.COMPLETED:
            return None

        plan_dict = plan.to_dict()
        result_dict = result.to_dict()

        skill = SiteSkill.from_orchestration_result(
            result_dict=result_dict,
            plan_dict=plan_dict,
            site_url=site_url,
            name=name,
            goal=goal,
            learned_selectors=learned_selectors,
        )

        return skill

    def learn_and_store(
        self,
        result: OrchestrationResult,
        plan: ActionPlan,
        site_url: str,
        *,
        name: str = "",
        goal: str = "",
        learned_selectors: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[SiteSkill], str]:
        """Learn from a result, apply quality gate, dedup/merge, and persist.

        Pipeline:
        1. Extract skill via learn() — rejects failed orchestrations
        2. Quality gate — rejects skills with empty steps, preconditions, or goal
        3. Dedup check — find similar skills at the same site (Jaccard > 0.5)
        4. If similar found → merge: bump stats, union selectors
        5. If no similar → save as new skill

        Args:
            result: The OrchestrationResult to learn from.
            plan: The ActionPlan that was executed.
            site_url: The URL where this skill was learned.
            name: Optional skill name override.
            goal: Optional goal description override.
            learned_selectors: Optional map of description → selector.

        Returns:
            Tuple of (SiteSkill or None, action string).
            Action is "created", "merged", or "rejected".
        """
        # Step 1: Extract skill
        skill = self.learn(result, plan, site_url, name=name, goal=goal,
                           learned_selectors=learned_selectors)
        if skill is None:
            return None, "rejected"

        # Step 2: Quality gate
        if not self._passes_quality_gate(skill):
            return None, "rejected"

        # Step 3: Dedup check
        existing = self._find_similar(skill, site_url)
        if existing is not None:
            # Step 4: Merge into existing skill
            self._merge(existing, skill, learned_selectors=learned_selectors)
            self.store.save(existing)
            return existing, "merged"

        # Step 5: Save as new
        self.store.save(skill)
        return skill, "created"

    def _passes_quality_gate(self, skill: SiteSkill) -> bool:
        """Check if a skill meets minimum quality requirements.

        A skill must have:
        - At least one step in its action plan
        - Non-empty preconditions list
        - Non-empty goal string

        Args:
            skill: The skill to check.

        Returns:
            True if the skill passes all quality checks.
        """
        steps = skill.action_plan.get("steps", [])
        if len(steps) == 0:
            return False
        if not skill.preconditions:
            return False
        if not skill.goal or not skill.goal.strip():
            return False
        return True

    def _find_similar(self, skill: SiteSkill, site_url: str) -> Optional[SiteSkill]:
        """Find a similar existing skill at the same site.

        Similarity is measured by Jaccard overlap on goal tokens.
        Returns the first existing skill with Jaccard > SIMILARITY_THRESHOLD.

        Args:
            skill: The new skill to compare against.
            site_url: The URL to filter existing skills by.

        Returns:
            A similar existing SiteSkill, or None.
        """
        existing_skills = self.store.find_by_site(site_url)
        new_tokens = self._tokenize(skill.goal)

        for existing in existing_skills:
            existing_tokens = self._tokenize(existing.goal)

            if not new_tokens or not existing_tokens:
                continue

            intersection = new_tokens & existing_tokens
            union = new_tokens | existing_tokens
            jaccard = len(intersection) / len(union)

            if jaccard > self.SIMILARITY_THRESHOLD:
                return existing

        return None

    def _merge(
        self,
        existing: SiteSkill,
        new_skill: SiteSkill,
        *,
        learned_selectors: Optional[Dict[str, str]] = None,
    ) -> None:
        """Merge new skill data into an existing skill.

        Merging:
        - Increments success_count on the existing skill
        - Unions learned_selectors (new overrides existing on conflict)
        - Bumps updated_at to now

        Args:
            existing: The existing skill to merge into.
            new_skill: The new skill providing updated data.
            learned_selectors: Optional selector map to merge.
        """
        # Increment success count
        existing.execution_stats["success_count"] = (
            existing.execution_stats.get("success_count", 0) + 1
        )
        existing.execution_stats["last_success_at"] = datetime.now().isoformat()
        existing.execution_stats["last_used_at"] = datetime.now().isoformat()

        # Union learned selectors (new takes precedence)
        merged_selectors = {**existing.learned_selectors, **new_skill.learned_selectors}
        if learned_selectors:
            merged_selectors.update(learned_selectors)
        existing.learned_selectors = merged_selectors

        # Bump updated_at
        existing.updated_at = datetime.now()

    @staticmethod
    def _tokenize(text: str) -> set:
        """Tokenize a string into a set of lowercase words.

        Same tokenization as SkillMatcher._tokenize() for consistency.
        Splits on whitespace, strips punctuation, filters tokens < 2 chars.

        Args:
            text: Input text to tokenize.

        Returns:
            Set of lowercase word tokens.
        """
        tokens = set()
        for word in text.lower().split():
            cleaned = word.strip(string.punctuation)
            if len(cleaned) >= 2:
                tokens.add(cleaned)
        return tokens
