"""Tests for netweaver/skill_matcher.py — NW-022 Skill Matcher Engine.

Covers:
  - SkillMatch dataclass construction
  - SkillMatcher.match() with empty store
  - Single skill match
  - Multiple skills ranked by composite score
  - Site-only match scoring
  - Goal-only match scoring
  - Zero-execution neutral prior
  - top_k truncation
  - Score breakdown accuracy
  - Deterministic tie-breaking
  - Tokenization edge cases
  - Custom weights / constants
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from netweaver.site_skill import SiteSkill, SkillStore
from netweaver.skill_matcher import SkillMatch, SkillMatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(
    *,
    skill_id: str = "skill-test",
    name: str = "Test Skill",
    site_pattern: str = "",
    goal: str = "",
    success_count: int = 0,
    fail_count: int = 0,
) -> SiteSkill:
    """Create a SiteSkill with controlled execution stats."""
    skill = SiteSkill(
        skill_id=skill_id,
        name=name,
        site_pattern=site_pattern,
        goal=goal,
    )
    skill.execution_stats = {
        "success_count": success_count,
        "fail_count": fail_count,
        "last_used_at": None,
        "last_success_at": None,
    }
    return skill


def _mock_store(skills: list) -> SkillStore:
    """Create a mock SkillStore returning the given skills from list_all."""
    store = MagicMock(spec=SkillStore)
    store.list_all.return_value = skills
    return store


# ---------------------------------------------------------------------------
# TestSkillMatch
# ---------------------------------------------------------------------------

class TestSkillMatch:
    """SkillMatch dataclass construction."""

    def test_creation_defaults(self):
        skill = _make_skill()
        m = SkillMatch(
            skill=skill, score=0.5, site_match=True,
            goal_overlap=0.3, success_rate=0.8,
        )
        assert m.skill is skill
        assert m.score == 0.5
        assert m.site_match is True
        assert m.goal_overlap == 0.3
        assert m.success_rate == 0.8
        assert m.rank == 0  # default before ranking

    def test_rank_assignment(self):
        m = SkillMatch(
            skill=_make_skill(), score=1.0, site_match=True,
            goal_overlap=1.0, success_rate=1.0, rank=3,
        )
        assert m.rank == 3


# ---------------------------------------------------------------------------
# TestSkillMatcherInit
# ---------------------------------------------------------------------------

class TestSkillMatcherInit:

    def test_stores_reference(self):
        store = _mock_store([])
        matcher = SkillMatcher(store)
        assert matcher.store is store

    def test_weights_sum_to_one(self):
        total = SkillMatcher.SITE_WEIGHT + SkillMatcher.GOAL_WEIGHT + SkillMatcher.SUCCESS_WEIGHT
        assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# TestEmptyStore
# ---------------------------------------------------------------------------

class TestEmptyStore:

    def test_match_empty_store(self):
        matcher = SkillMatcher(_mock_store([]))
        result = matcher.match("https://example.com", "do something")
        assert result == []

    def test_match_empty_store_top_k(self):
        matcher = SkillMatcher(_mock_store([]))
        result = matcher.match("https://example.com", "goal", top_k=3)
        assert result == []


# ---------------------------------------------------------------------------
# TestSingleMatch
# ---------------------------------------------------------------------------

class TestSingleMatch:

    def test_single_perfect_match(self):
        skill = _make_skill(
            site_pattern="example\\.com",
            goal="login to account",
            success_count=8,
            fail_count=2,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com/login", "login to account")

        assert len(results) == 1
        m = results[0]
        assert m.skill is skill
        assert m.rank == 1
        assert m.site_match is True
        assert m.goal_overlap == 1.0
        assert m.success_rate == 0.8
        # score = 0.4*1.0 + 0.3*1.0 + 0.3*0.8 = 1.0 + 0.3 + 0.24 = nah
        # 0.4 + 0.3 + 0.24 = 0.94
        assert abs(m.score - 0.94) < 1e-9

    def test_single_no_site_no_goal_match(self):
        skill = _make_skill(
            site_pattern="other\\.com",
            goal="buy products",
            success_count=5,
            fail_count=5,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "login to account")

        assert len(results) == 1
        m = results[0]
        assert m.site_match is False
        assert m.goal_overlap == 0.0
        assert m.success_rate == 0.5
        # score = 0.4*0 + 0.3*0 + 0.3*0.5 = 0.15
        assert abs(m.score - 0.15) < 1e-9


# ---------------------------------------------------------------------------
# TestMultipleRanked
# ---------------------------------------------------------------------------

class TestMultipleRanked:

    def test_ranked_by_composite_score(self):
        """Skills ranked by descending composite score."""
        s1 = _make_skill(
            skill_id="skill-low",
            site_pattern="low\\.com",
            goal="search items",
            success_count=1,
            fail_count=9,
        )
        s2 = _make_skill(
            skill_id="skill-high",
            site_pattern="example\\.com",
            goal="login to account",
            success_count=10,
            fail_count=0,
        )
        s3 = _make_skill(
            skill_id="skill-mid",
            site_pattern="example\\.com",
            goal="sign in to account",
            success_count=5,
            fail_count=5,
        )

        matcher = SkillMatcher(_mock_store([s1, s2, s3]))
        results = matcher.match("https://example.com/login", "login to account")

        assert len(results) == 3
        # s2: site=1, goal=1.0, success=1.0 → 0.4+0.3+0.3 = 1.0
        assert results[0].skill.skill_id == "skill-high"
        assert results[0].rank == 1
        # s3: site=1, goal=Jaccard("login to account"/"sign in to account") = overlap
        # tokens: {"login","to","account"} vs {"sign","in","to","account"}
        # intersection: {"to","account"} = 2, union: {"login","to","account","sign","in"} = 5
        # goal_overlap = 2/5 = 0.4
        # success_rate = 0.5
        # score = 0.4*1 + 0.3*0.4 + 0.3*0.5 = 0.4 + 0.12 + 0.15 = 0.67
        assert results[1].skill.skill_id == "skill-mid"
        assert results[1].rank == 2
        # s1: site=0, goal overlap varies, success=0.1
        assert results[2].skill.skill_id == "skill-low"
        assert results[2].rank == 3

        # Verify strict descending order
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_deterministic_tie_breaking(self):
        """Tied scores broken by skill_id alphabetically."""
        s_a = _make_skill(
            skill_id="skill-alpha",
            site_pattern="example\\.com",
            goal="do thing",
            success_count=5,
            fail_count=5,
        )
        s_b = _make_skill(
            skill_id="skill-beta",
            site_pattern="example\\.com",
            goal="do thing",
            success_count=5,
            fail_count=5,
        )

        matcher = SkillMatcher(_mock_store([s_b, s_a]))
        results = matcher.match("https://example.com", "do thing")

        assert len(results) == 2
        assert results[0].skill.skill_id == "skill-alpha"
        assert results[1].skill.skill_id == "skill-beta"
        assert results[0].score == results[1].score


# ---------------------------------------------------------------------------
# TestSiteOnlyMatch
# ---------------------------------------------------------------------------

class TestSiteOnlyMatch:

    def test_site_match_no_goal_overlap(self):
        skill = _make_skill(
            site_pattern="example\\.com",
            goal="buy groceries online",
            success_count=3,
            fail_count=7,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com/shop", "login to account")

        assert len(results) == 1
        m = results[0]
        assert m.site_match is True
        assert m.goal_overlap == 0.0
        # success_rate = 3/10 = 0.3
        # score = 0.4*1 + 0.3*0 + 0.3*0.3 = 0.49
        assert abs(m.score - 0.49) < 1e-9

    def test_site_mismatch_zero_site_score(self):
        skill = _make_skill(
            site_pattern="other\\.com",
            goal="login to account",
            success_count=10,
            fail_count=0,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "login to account")

        m = results[0]
        assert m.site_match is False
        assert m.goal_overlap == 1.0
        # score = 0.4*0 + 0.3*1.0 + 0.3*1.0 = 0.6
        assert abs(m.score - 0.6) < 1e-9


# ---------------------------------------------------------------------------
# TestGoalOnlyMatch
# ---------------------------------------------------------------------------

class TestGoalOnlyMatch:

    def test_goal_overlap_partial(self):
        skill = _make_skill(
            site_pattern="",
            goal="search for items in catalog",
            success_count=4,
            fail_count=6,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "search for products")

        m = results[0]
        assert m.site_match is False
        # tokens: {"search","for","items","in","catalog"} vs {"search","for","products"}
        # intersection: {"search","for"} = 2
        # union: {"search","for","items","in","catalog","products"} = 6
        # overlap = 2/6 ≈ 0.333
        assert abs(m.goal_overlap - 2.0 / 6.0) < 1e-9

    def test_goal_overlap_identical(self):
        skill = _make_skill(
            site_pattern="nomatch\\.com",
            goal="login to account",
            success_count=0,
            fail_count=0,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "login to account")

        m = results[0]
        assert m.goal_overlap == 1.0

    def test_goal_overlap_empty_strings(self):
        skill = _make_skill(site_pattern="", goal="")
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "")

        m = results[0]
        assert m.goal_overlap == 0.0

    def test_goal_overlap_one_empty(self):
        skill = _make_skill(site_pattern="", goal="login to account")
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "")

        m = results[0]
        assert m.goal_overlap == 0.0


# ---------------------------------------------------------------------------
# TestNeutralPrior
# ---------------------------------------------------------------------------

class TestNeutralPrior:

    def test_zero_executions_gets_neutral_prior(self):
        skill = _make_skill(
            site_pattern="example\\.com",
            goal="login",
            success_count=0,
            fail_count=0,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "login")

        m = results[0]
        assert m.success_rate == 0.5
        # score = 0.4*1 + 0.3*1.0 + 0.3*0.5 = 0.85
        assert abs(m.score - 0.85) < 1e-9

    def test_one_success_no_failures(self):
        skill = _make_skill(
            site_pattern="example\\.com",
            goal="login",
            success_count=1,
            fail_count=0,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "login")

        m = results[0]
        assert m.success_rate == 1.0

    def test_all_failures(self):
        skill = _make_skill(
            site_pattern="example\\.com",
            goal="login",
            success_count=0,
            fail_count=5,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "login")

        m = results[0]
        assert m.success_rate == 0.0


# ---------------------------------------------------------------------------
# TestTopKTruncation
# ---------------------------------------------------------------------------

class TestTopKTruncation:

    def test_top_k_limits_results(self):
        skills = [
            _make_skill(
                skill_id=f"skill-{i}",
                site_pattern="example\\.com",
                goal="login",
                success_count=10 - i,
                fail_count=i,
            )
            for i in range(10)
        ]
        matcher = SkillMatcher(_mock_store(skills))
        results = matcher.match("https://example.com", "login", top_k=3)

        assert len(results) == 3
        assert results[0].rank == 1
        assert results[1].rank == 2
        assert results[2].rank == 3

    def test_top_k_larger_than_store(self):
        skills = [_make_skill(skill_id="skill-1", site_pattern="example\\.com")]
        matcher = SkillMatcher(_mock_store(skills))
        results = matcher.match("https://example.com", "goal", top_k=10)

        assert len(results) == 1

    def test_top_k_one(self):
        skills = [
            _make_skill(skill_id="skill-a", site_pattern="example\\.com", success_count=10, fail_count=0),
            _make_skill(skill_id="skill-b", site_pattern="example\\.com", success_count=1, fail_count=9),
        ]
        matcher = SkillMatcher(_mock_store(skills))
        results = matcher.match("https://example.com", "goal", top_k=1)

        assert len(results) == 1
        assert results[0].skill.skill_id == "skill-a"


# ---------------------------------------------------------------------------
# TestScoreBreakdown
# ---------------------------------------------------------------------------

class TestScoreBreakdown:

    def test_perfect_score_breakdown(self):
        """All components max → score = 1.0."""
        skill = _make_skill(
            site_pattern="example\\.com",
            goal="login to account",
            success_count=10,
            fail_count=0,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "login to account")

        m = results[0]
        assert m.site_match is True
        assert m.goal_overlap == 1.0
        assert m.success_rate == 1.0
        assert abs(m.score - 1.0) < 1e-9

    def test_zero_score_breakdown(self):
        """No site, no goal overlap, all failures → score = 0.0."""
        skill = _make_skill(
            site_pattern="other\\.com",
            goal="buy groceries",
            success_count=0,
            fail_count=10,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com", "login to account")

        m = results[0]
        assert m.site_match is False
        assert m.goal_overlap == 0.0
        assert m.success_rate == 0.0
        assert abs(m.score - 0.0) < 1e-9

    def test_mixed_components(self):
        """Verify each component contributes independently."""
        skill = _make_skill(
            site_pattern="example\\.com",
            goal="search for items",
            success_count=7,
            fail_count=3,
        )
        matcher = SkillMatcher(_mock_store([skill]))
        results = matcher.match("https://example.com/search", "search for items")

        m = results[0]
        assert m.site_match is True
        assert m.goal_overlap == 1.0
        assert abs(m.success_rate - 0.7) < 1e-9
        # score = 0.4*1 + 0.3*1 + 0.3*0.7 = 0.91
        expected = 0.4 + 0.3 + 0.3 * 0.7
        assert abs(m.score - expected) < 1e-9


# ---------------------------------------------------------------------------
# TestTokenization
# ---------------------------------------------------------------------------

class TestTokenization:

    def test_basic_tokenization(self):
        tokens = SkillMatcher._tokenize("Login to Account")
        assert tokens == {"login", "to", "account"}

    def test_punctuation_stripped(self):
        tokens = SkillMatcher._tokenize("search, filter & sort!")
        assert "search" in tokens
        assert "filter" in tokens
        assert "sort" in tokens
        assert "&" not in tokens

    def test_short_tokens_filtered(self):
        tokens = SkillMatcher._tokenize("a I to do go")
        # "to" and "do" are >= 2 chars, "a", "I" are not
        assert "a" not in tokens
        assert "i" not in tokens
        assert "to" in tokens
        assert "do" in tokens
        assert "go" in tokens

    def test_empty_string(self):
        tokens = SkillMatcher._tokenize("")
        assert tokens == set()

    def test_only_punctuation(self):
        tokens = SkillMatcher._tokenize("!!! ... ---")
        assert tokens == set()

    def test_mixed_case(self):
        tokens = SkillMatcher._tokenize("Login LOGIN login")
        assert tokens == {"login"}

    def test_numbers_preserved(self):
        tokens = SkillMatcher._tokenize("step 1 of 99")
        assert "step" in tokens
        assert "of" in tokens
        assert "99" in tokens


# ---------------------------------------------------------------------------
# TestInternalScoring
# ---------------------------------------------------------------------------

class TestInternalScoring:

    def test_site_score_match(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(site_pattern="example\\.com")
        assert matcher._site_score(skill, "https://example.com/page") == 1.0

    def test_site_score_no_match(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(site_pattern="other\\.com")
        assert matcher._site_score(skill, "https://example.com") == 0.0

    def test_site_score_empty_pattern(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(site_pattern="")
        assert matcher._site_score(skill, "https://example.com") == 0.0

    def test_goal_score_identical(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(goal="login to account")
        assert matcher._goal_score(skill, "login to account") == 1.0

    def test_goal_score_no_overlap(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(goal="buy groceries")
        assert matcher._goal_score(skill, "login to account") == 0.0

    def test_success_score_with_data(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(success_count=7, fail_count=3)
        assert abs(matcher._success_score(skill) - 0.7) < 1e-9

    def test_success_score_neutral_prior(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(success_count=0, fail_count=0)
        assert matcher._success_score(skill) == 0.5

    def test_success_score_all_success(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(success_count=10, fail_count=0)
        assert matcher._success_score(skill) == 1.0

    def test_success_score_all_failure(self):
        matcher = SkillMatcher(_mock_store([]))
        skill = _make_skill(success_count=0, fail_count=10)
        assert matcher._success_score(skill) == 0.0
