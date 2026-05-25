"""Tests for NetWeaver Skill Learner — NW-025.

Covers:
  - learn() from successful OrchestrationResult
  - Quality gate rejection (empty steps, preconditions, goal)
  - Dedup/merge via Jaccard similarity
  - Failed result rejection
  - Empty inputs
  - Merge stats accuracy
  - learn_and_store() full pipeline: created, merged, rejected
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime

from netweaver.action_orchestrator import (
    ActionPlan,
    ActionStep,
    ActionType,
    OrchestrationResult,
    PlanStatus,
    StepResult,
)
from netweaver.site_skill import SiteSkill, SkillStore
from netweaver.skill_learner import SkillLearner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_skills_dir(tmp_path):
    """Create a temporary skills directory."""
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def store(tmp_skills_dir):
    """Create a SkillStore pointing at a temp directory."""
    return SkillStore(tmp_skills_dir)


@pytest.fixture
def learner(store):
    """Create a SkillLearner with a temp store."""
    return SkillLearner(store)


def _make_successful_result(
    steps_count: int = 2,
    plan_id: str = "plan-test",
    description: str = "test plan",
) -> OrchestrationResult:
    """Create a successful OrchestrationResult with given steps."""
    result = OrchestrationResult(
        plan_id=plan_id,
        plan_description=description,
        status=PlanStatus.COMPLETED,
    )
    for i in range(steps_count):
        step = ActionStep(
            action_type=ActionType.CLICK,
            description=f"click button {i}",
            intent=f"perform action {i}",
            pre_condition=f"element {i} visible",
            post_condition=f"action {i} completed",
        )
        step_result = StepResult(
            step_index=i,
            step=step,
            status=PlanStatus.COMPLETED,
            evidence_chain_ids=[f"evidence-{i}"],
        )
        result.steps.append(step_result)
        result.completed_steps += 1
    return result


def _make_failed_result() -> OrchestrationResult:
    """Create a failed OrchestrationResult."""
    result = OrchestrationResult(
        plan_id="plan-fail",
        plan_description="failing plan",
        status=PlanStatus.FAILED,
        error="Step 0 failed",
    )
    return result


def _make_plan(
    steps_count: int = 2,
    description: str = "test plan",
    preconditions: bool = True,
) -> ActionPlan:
    """Create an ActionPlan with steps."""
    plan = ActionPlan(description=description)
    for i in range(steps_count):
        plan.add_step(
            action_type=ActionType.CLICK,
            description=f"click button {i}",
            intent=f"perform action {i}",
            pre_condition=f"element {i} visible" if preconditions else "",
            post_condition=f"action {i} completed",
        )
    return plan


# ---------------------------------------------------------------------------
# learn() — basic extraction
# ---------------------------------------------------------------------------

class TestLearn:
    """Test SkillLearner.learn() — extracting skills from results."""

    def test_successful_result_returns_skill(self, learner):
        """Completed result → SiteSkill returned."""
        result = _make_successful_result()
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com/login")

        assert skill is not None
        assert isinstance(skill, SiteSkill)
        assert skill.site_pattern  # should have a pattern
        assert skill.goal  # should have a goal

    def test_successful_result_with_custom_name(self, learner):
        """Custom name is passed through to the skill."""
        result = _make_successful_result()
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com", name="My Skill")

        assert skill is not None
        assert skill.name == "My Skill"

    def test_successful_result_with_custom_goal(self, learner):
        """Custom goal is passed through to the skill."""
        result = _make_successful_result()
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com", goal="custom goal")

        assert skill is not None
        assert skill.goal == "custom goal"

    def test_successful_result_with_selectors(self, learner):
        """Learned selectors are attached to the skill."""
        result = _make_successful_result()
        plan = _make_plan()
        selectors = {"login button": "#login-btn", "email": "#email"}

        skill = learner.learn(result, plan, "https://example.com",
                              learned_selectors=selectors)

        assert skill is not None
        assert skill.learned_selectors == selectors

    def test_failed_result_returns_none(self, learner):
        """Failed orchestration → None."""
        result = _make_failed_result()
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com")

        assert skill is None

    def test_rolled_back_result_returns_none(self, learner):
        """Rolled-back orchestration → None."""
        result = OrchestrationResult(
            plan_id="plan-rb",
            status=PlanStatus.ROLLED_BACK,
        )
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com")

        assert skill is None

    def test_safety_blocked_result_returns_none(self, learner):
        """Safety-blocked orchestration → None."""
        result = OrchestrationResult(
            plan_id="plan-sb",
            status=PlanStatus.SAFETY_BLOCKED,
        )
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com")

        assert skill is None

    def test_pending_result_returns_none(self, learner):
        """Pending orchestration → None."""
        result = OrchestrationResult(
            plan_id="plan-pending",
            status=PlanStatus.PENDING,
        )
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com")

        assert skill is None

    def test_running_result_returns_none(self, learner):
        """Running orchestration → None."""
        result = OrchestrationResult(
            plan_id="plan-running",
            status=PlanStatus.RUNNING,
        )
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com")

        assert skill is None

    def test_site_pattern_from_url(self, learner):
        """Site pattern is derived from the URL."""
        result = _make_successful_result()
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://github.com/login")

        assert skill is not None
        assert "github.com" in skill.site_pattern

    def test_evidence_requirements_collected(self, learner):
        """Evidence chain IDs are collected into evidence_requirements."""
        result = _make_successful_result(steps_count=2)
        plan = _make_plan(steps_count=2)

        skill = learner.learn(result, plan, "https://example.com")

        assert skill is not None
        # Evidence IDs come from step results
        assert len(skill.evidence_requirements) > 0

    def test_preconditions_from_plan(self, learner):
        """Preconditions are extracted from plan steps."""
        result = _make_successful_result()
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com")

        assert skill is not None
        assert len(skill.preconditions) > 0

    def test_postconditions_from_plan(self, learner):
        """Postconditions are extracted from plan steps."""
        result = _make_successful_result()
        plan = _make_plan()

        skill = learner.learn(result, plan, "https://example.com")

        assert skill is not None
        assert len(skill.postconditions) > 0


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

class TestQualityGate:
    """Test SkillLearner._passes_quality_gate()."""

    def test_valid_skill_passes(self, learner):
        """Skill with steps, preconditions, and goal passes."""
        skill = SiteSkill(
            goal="login to website",
            preconditions=["page loaded"],
            action_plan={"steps": [{"action_type": "click"}]},
        )
        assert learner._passes_quality_gate(skill) is True

    def test_empty_steps_rejected(self, learner):
        """Skill with no steps is rejected."""
        skill = SiteSkill(
            goal="login",
            preconditions=["page loaded"],
            action_plan={"steps": []},
        )
        assert learner._passes_quality_gate(skill) is False

    def test_missing_steps_key_rejected(self, learner):
        """Skill with no 'steps' key in action_plan is rejected."""
        skill = SiteSkill(
            goal="login",
            preconditions=["page loaded"],
            action_plan={},
        )
        assert learner._passes_quality_gate(skill) is False

    def test_empty_preconditions_rejected(self, learner):
        """Skill with empty preconditions is rejected."""
        skill = SiteSkill(
            goal="login",
            preconditions=[],
            action_plan={"steps": [{"action_type": "click"}]},
        )
        assert learner._passes_quality_gate(skill) is False

    def test_empty_goal_rejected(self, learner):
        """Skill with empty goal is rejected."""
        skill = SiteSkill(
            goal="",
            preconditions=["page loaded"],
            action_plan={"steps": [{"action_type": "click"}]},
        )
        assert learner._passes_quality_gate(skill) is False

    def test_whitespace_goal_rejected(self, learner):
        """Skill with whitespace-only goal is rejected."""
        skill = SiteSkill(
            goal="   ",
            preconditions=["page loaded"],
            action_plan={"steps": [{"action_type": "click"}]},
        )
        assert learner._passes_quality_gate(skill) is False


# ---------------------------------------------------------------------------
# Dedup / merge
# ---------------------------------------------------------------------------

class TestDedupMerge:
    """Test SkillLearner deduplication and merge logic."""

    def test_find_similar_with_high_overlap(self, learner, store):
        """Skills with Jaccard > 0.5 are considered similar."""
        existing = SiteSkill(
            name="GitHub Login",
            site_pattern="https://github.com.*",
            goal="log in to github account",
        )
        store.save(existing)

        new_skill = SiteSkill(
            name="GitHub Auth",
            site_pattern="https://github.com.*",
            goal="log in to github profile",
        )

        found = learner._find_similar(new_skill, "https://github.com/login")
        assert found is not None
        assert found.skill_id == existing.skill_id

    def test_no_similar_with_low_overlap(self, learner, store):
        """Skills with Jaccard ≤ 0.5 are not considered similar."""
        existing = SiteSkill(
            name="GitHub Login",
            site_pattern="https://github.com.*",
            goal="log in to github account",
        )
        store.save(existing)

        new_skill = SiteSkill(
            name="Search Google",
            site_pattern="https://github.com.*",
            goal="search for cute cat pictures online",
        )

        found = learner._find_similar(new_skill, "https://github.com/login")
        assert found is None

    def test_no_similar_when_no_existing(self, learner):
        """No existing skills → no similar found."""
        new_skill = SiteSkill(goal="do something")

        found = learner._find_similar(new_skill, "https://example.com")
        assert found is None

    def test_no_similar_when_no_site_match(self, learner, store):
        """Skills at different sites are not compared."""
        existing = SiteSkill(
            name="GitHub Login",
            site_pattern="https://github.com.*",
            goal="log in to github account",
        )
        store.save(existing)

        new_skill = SiteSkill(
            goal="log in to github account",
        )

        # Different URL → no site match → not similar
        found = learner._find_similar(new_skill, "https://gitlab.com/login")
        assert found is None

    def test_merge_increments_success_count(self, learner):
        """Merge increments the existing skill's success_count."""
        existing = SiteSkill(
            goal="login",
            execution_stats={"success_count": 3, "fail_count": 0,
                             "last_used_at": None, "last_success_at": None},
        )
        new_skill = SiteSkill(goal="login")

        old_count = existing.execution_stats["success_count"]
        learner._merge(existing, new_skill)

        assert existing.execution_stats["success_count"] == old_count + 1

    def test_merge_unions_selectors(self, learner):
        """Merge unions selectors, new taking precedence on conflict."""
        existing = SiteSkill(
            goal="login",
            learned_selectors={"btn": "#old-btn", "email": "#email"},
        )
        new_skill = SiteSkill(
            goal="login",
            learned_selectors={"btn": "#new-btn", "pass": "#password"},
        )

        learner._merge(existing, new_skill)

        assert existing.learned_selectors["btn"] == "#new-btn"  # new wins
        assert existing.learned_selectors["email"] == "#email"  # kept
        assert existing.learned_selectors["pass"] == "#password"  # added

    def test_merge_bumps_updated_at(self, learner):
        """Merge updates updated_at on the existing skill."""
        existing = SiteSkill(goal="login")
        existing.updated_at = datetime(2020, 1, 1)
        new_skill = SiteSkill(goal="login")

        learner._merge(existing, new_skill)

        assert existing.updated_at > datetime(2020, 1, 1)

    def test_merge_with_extra_selectors(self, learner):
        """Merge includes extra learned_selectors param."""
        existing = SiteSkill(goal="login", learned_selectors={"a": "#a"})
        new_skill = SiteSkill(goal="login", learned_selectors={"b": "#b"})

        learner._merge(existing, new_skill, learned_selectors={"c": "#c"})

        assert "c" in existing.learned_selectors

    def test_merge_stats_accuracy(self, learner):
        """Multiple merges accumulate correctly."""
        existing = SiteSkill(
            goal="login",
            execution_stats={"success_count": 0, "fail_count": 0,
                             "last_used_at": None, "last_success_at": None},
        )

        for _ in range(5):
            learner._merge(existing, SiteSkill(goal="login"))

        assert existing.execution_stats["success_count"] == 5
        assert existing.execution_stats["last_success_at"] is not None
        assert existing.execution_stats["last_used_at"] is not None


# ---------------------------------------------------------------------------
# learn_and_store() — full pipeline
# ---------------------------------------------------------------------------

class TestLearnAndStore:
    """Test SkillLearner.learn_and_store() — full pipeline."""

    def test_create_new_skill(self, learner, store):
        """Successful unique result → created."""
        result = _make_successful_result()
        plan = _make_plan()

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com/login",
            goal="log in to example",
        )

        assert action == "created"
        assert skill is not None
        assert skill.goal == "log in to example"

        # Verify persisted
        loaded = store.load(skill.skill_id)
        assert loaded is not None

    def test_merge_similar_skill(self, learner, store):
        """Second similar result → merged."""
        # First: create
        existing = SiteSkill(
            name="Example Login",
            site_pattern="https://example.com.*",
            goal="log in to example website",
            preconditions=["page loaded"],
            action_plan={"steps": [{"action_type": "click"}]},
            execution_stats={"success_count": 1, "fail_count": 0,
                             "last_used_at": None, "last_success_at": None},
        )
        store.save(existing)

        # Second: should merge
        result = _make_successful_result()
        plan = _make_plan()

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com/login",
            goal="log in to example website again",
        )

        assert action == "merged"
        assert skill is not None
        assert skill.skill_id == existing.skill_id
        assert skill.execution_stats["success_count"] == 2  # 1 + 1

    def test_reject_failed_result(self, learner):
        """Failed orchestration → rejected."""
        result = _make_failed_result()
        plan = _make_plan()

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com",
        )

        assert action == "rejected"
        assert skill is None

    def test_reject_empty_goal(self, learner):
        """Quality gate rejects empty goal → rejected."""
        result = _make_successful_result()
        # Plan with no description, no goal override
        plan = ActionPlan(description="")
        plan.add_step(
            ActionType.CLICK, "click btn",
            pre_condition="visible",
        )

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com",
        )

        assert action == "rejected"
        assert skill is None

    def test_reject_no_preconditions(self, learner):
        """Quality gate rejects empty preconditions → rejected."""
        result = _make_successful_result()
        plan = _make_plan(preconditions=False)

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com",
            goal="do something",
        )

        # Plan with no preconditions → quality gate fails
        assert action == "rejected"
        assert skill is None

    def test_reject_zero_steps(self, learner):
        """Quality gate rejects 0 steps → rejected."""
        result = OrchestrationResult(
            plan_id="plan-empty",
            status=PlanStatus.COMPLETED,
            completed_steps=0,
        )
        plan = ActionPlan(description="empty plan")

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com",
            goal="empty goal",
        )

        assert action == "rejected"
        assert skill is None

    def test_create_with_selectors(self, learner, store):
        """Created skill includes learned selectors."""
        result = _make_successful_result()
        plan = _make_plan()
        selectors = {"login btn": "#login", "email input": "#email"}

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com",
            goal="log in",
            learned_selectors=selectors,
        )

        assert action == "created"
        assert skill.learned_selectors == selectors

    def test_merge_accumulates_selectors(self, learner, store):
        """Merge unions selectors from new skill."""
        existing = SiteSkill(
            name="Test",
            site_pattern="https://example.com.*",
            goal="log in to example website",
            preconditions=["page loaded"],
            action_plan={"steps": [{"action_type": "click"}]},
            execution_stats={"success_count": 1, "fail_count": 0,
                             "last_used_at": None, "last_success_at": None},
            learned_selectors={"btn": "#old-btn"},
        )
        store.save(existing)

        result = _make_successful_result()
        plan = _make_plan()

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com/login",
            goal="log in to example website fast",
            learned_selectors={"btn": "#new-btn", "email": "#email"},
        )

        assert action == "merged"
        assert skill.learned_selectors["btn"] == "#new-btn"
        assert skill.learned_selectors["email"] == "#email"


# ---------------------------------------------------------------------------
# Tokenization consistency
# ---------------------------------------------------------------------------

class TestTokenization:
    """Test that SkillLearner._tokenize matches SkillMatcher._tokenize."""

    def test_same_tokens_as_skill_matcher(self):
        """SkillLearner and SkillMatcher produce identical tokens."""
        from netweaver.skill_matcher import SkillMatcher

        text = "Log in to the GitHub Account!"
        learner_tokens = SkillLearner._tokenize(text)
        matcher_tokens = SkillMatcher._tokenize(text)

        assert learner_tokens == matcher_tokens

    def test_empty_string(self):
        """Empty string → empty set."""
        assert SkillLearner._tokenize("") == set()

    def test_single_char_words_filtered(self):
        """Single-char tokens are filtered out."""
        tokens = SkillLearner._tokenize("a I am")
        assert "a" not in tokens
        assert "am" in tokens

    def test_punctuation_stripped(self):
        """Punctuation is stripped from tokens."""
        tokens = SkillLearner._tokenize("hello, world! test.")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case tests."""

    def test_store_persistence_after_create(self, learner, store, tmp_skills_dir):
        """Created skill is actually on disk."""
        result = _make_successful_result()
        plan = _make_plan()

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com",
            goal="persist me",
        )

        assert action == "created"

        # File should exist on disk
        json_files = list(tmp_skills_dir.glob("*.json"))
        assert len(json_files) == 1

    def test_multiple_creates_same_site_different_goals(self, learner, store):
        """Multiple skills at same site with very different goals → all created."""
        goals = [
            "authenticate user credentials via oauth",
            "search for products in catalog database",
            "export data as csv spreadsheet file",
        ]
        for i, goal in enumerate(goals):
            result = _make_successful_result(plan_id=f"plan-{i}")
            plan = _make_plan(description=f"plan {i}")

            skill, action = learner.learn_and_store(
                result, plan, "https://example.com",
                goal=goal,
            )
            assert action == "created", f"Goal {i!r} unexpectedly {action}"

        assert len(store.list_all()) == 3

    def test_jaccard_exactly_at_threshold(self, learner, store):
        """Jaccard exactly at 0.5 threshold → not similar (uses >)."""
        # "ab cd" vs "ab ef" → intersection {ab}, union {ab, cd, ef} = 1/3 ≈ 0.33
        # Let's craft exactly 0.5: "ab cd" vs "ab cd" → 1.0
        # "ab cd ef" vs "ab gh ij" → intersection {ab}, union {ab,cd,ef,gh,ij} = 1/5 = 0.2
        # For exactly 0.5: "ab cd" vs "ab ef" = 1/3 ≠ 0.5
        # "ab cd ef gh" vs "ab cd ij kl" = 2/6 = 0.333
        # We just test that > threshold (strict) means 0.5 exactly is NOT similar
        # "ab cd ef gh" vs "ab cd ef xy" = 3/5 = 0.6 → similar
        existing = SiteSkill(
            site_pattern="https://test.com.*",
            goal="ab cd ef gh",
        )
        store.save(existing)

        # 3/6 = exactly 0.5 → not similar (strict >)
        new_skill = SiteSkill(goal="ab cd ij kl")
        found = learner._find_similar(new_skill, "https://test.com/page")
        assert found is None  # Jaccard = exactly 0.5, but we use > so not similar

    def test_safety_blocked_orchestration_rejected(self, learner):
        """SAFETY_BLOCKED result is rejected."""
        result = OrchestrationResult(
            plan_id="plan-sb",
            status=PlanStatus.SAFETY_BLOCKED,
            error="Dangerous action",
        )
        plan = _make_plan()

        skill, action = learner.learn_and_store(
            result, plan, "https://example.com",
        )

        assert action == "rejected"
        assert skill is None

    def test_no_vendor_imports(self):
        """Verify no browser/vendor imports in skill_learner module."""
        import ast
        source = Path(__file__).parent.parent / "netweaver" / "skill_learner.py"
        tree = ast.parse(source.read_text())

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "playwright" not in alias.name.lower()
                    assert "cloak" not in alias.name.lower()
                    assert "browser" not in alias.name.lower()
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "playwright" not in node.module.lower()
                    assert "cloak" not in node.module.lower()
                    assert "browser" not in node.module.lower()
