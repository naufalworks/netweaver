"""Skill Learning Benchmark — SiteSkill, SkillStore, SkillMatcher.

Benchmark tasks SK-001 through SK-010.
Validates the full skill learning layer: data model, persistence,
scoring, ranking, and end-to-end lifecycle.

No browser/Playwright/vendor imports. All file I/O uses tmpdir.
"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from netweaver.site_skill import SiteSkill, SkillStore
from netweaver.skill_matcher import SkillMatch, SkillMatcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def skills_dir(tmp_path):
    """Provide a clean temporary directory for SkillStore."""
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def store(skills_dir):
    """Provide a SkillStore backed by tmpdir."""
    return SkillStore(skills_dir)


@pytest.fixture
def github_skill():
    """A skill for GitHub login."""
    return SiteSkill(
        name="GitHub Login",
        site_pattern=r"github\.com.*",
        goal="sign in to github account",
        action_plan={"steps": [
            {"action": "fill", "selector": "#login_field", "value": "user"},
            {"action": "fill", "selector": "#password", "value": "pass"},
            {"action": "click", "selector": "input[type=submit]"},
        ]},
        preconditions=["login form visible"],
        postconditions=["user is authenticated"],
        evidence_requirements=["dom:login_form", "network:session_cookie"],
        learned_selectors={"username": "#login_field", "password": "#password"},
    )


@pytest.fixture
def google_skill():
    """A skill for Google search."""
    return SiteSkill(
        name="Google Search",
        site_pattern=r"google\.com.*",
        goal="search for information online",
        action_plan={"steps": [
            {"action": "fill", "selector": "input[name=q]", "value": "query"},
            {"action": "click", "selector": "input[name=btnK]"},
        ]},
        preconditions=["search box visible"],
        postconditions=["results displayed"],
        evidence_requirements=["dom:search_box"],
        execution_stats={"success_count": 8, "fail_count": 2, "last_used_at": None, "last_success_at": None},
    )


@pytest.fixture
def populated_store(store, github_skill, google_skill):
    """A store with two skills saved."""
    store.save(github_skill)
    store.save(google_skill)
    return store


# ===========================================================================
# SK-001: SiteSkill Data Model
# ===========================================================================

class TestSK001SiteSkillDataModel:
    """Verify SiteSkill dataclass creation, defaults, field integrity."""

    def test_auto_generated_skill_id(self):
        skill = SiteSkill(name="test")
        assert len(skill.skill_id) == 8
        assert skill.skill_id.isalnum()

    def test_explicit_skill_id(self):
        skill = SiteSkill(skill_id="my-custom-id", name="test")
        assert skill.skill_id == "my-custom-id"

    def test_default_timestamps(self):
        before = datetime.now()
        skill = SiteSkill(name="test")
        after = datetime.now()
        assert before <= skill.created_at <= after
        assert before <= skill.updated_at <= after

    def test_default_execution_stats(self):
        skill = SiteSkill(name="test")
        assert skill.execution_stats["success_count"] == 0
        assert skill.execution_stats["fail_count"] == 0
        assert skill.execution_stats["last_used_at"] is None
        assert skill.execution_stats["last_success_at"] is None

    def test_default_empty_collections(self):
        skill = SiteSkill(name="test")
        assert skill.preconditions == []
        assert skill.postconditions == []
        assert skill.evidence_requirements == []
        assert skill.learned_selectors == {}
        assert skill.action_plan == {}

    def test_fields_accessible_and_mutable(self):
        skill = SiteSkill(name="test")
        skill.name = "renamed"
        skill.goal = "new goal"
        assert skill.name == "renamed"
        assert skill.goal == "new goal"


# ===========================================================================
# SK-002: SiteSkill Serialization Round-Trip
# ===========================================================================

class TestSK002SerializationRoundTrip:
    """Verify to_dict() / from_dict() produce identical SiteSkill objects."""

    def test_round_trip_minimal(self):
        original = SiteSkill(name="minimal")
        data = original.to_dict()
        restored = SiteSkill.from_dict(data)
        assert restored.name == original.name
        assert restored.skill_id == original.skill_id

    def test_round_trip_full(self, github_skill):
        data = github_skill.to_dict()
        restored = SiteSkill.from_dict(data)
        assert restored.skill_id == github_skill.skill_id
        assert restored.name == github_skill.name
        assert restored.site_pattern == github_skill.site_pattern
        assert restored.goal == github_skill.goal
        assert restored.action_plan == github_skill.action_plan
        assert restored.preconditions == github_skill.preconditions
        assert restored.postconditions == github_skill.postconditions
        assert restored.evidence_requirements == github_skill.evidence_requirements
        assert restored.learned_selectors == github_skill.learned_selectors

    def test_round_trip_datetime_serialization(self):
        skill = SiteSkill(name="test")
        data = skill.to_dict()
        # Datetimes should be ISO strings
        assert isinstance(data["created_at"], str)
        assert isinstance(data["updated_at"], str)
        restored = SiteSkill.from_dict(data)
        assert isinstance(restored.created_at, datetime)
        assert isinstance(restored.updated_at, datetime)

    def test_round_trip_preserves_execution_stats(self, google_skill):
        data = google_skill.to_dict()
        restored = SiteSkill.from_dict(data)
        assert restored.execution_stats["success_count"] == 8
        assert restored.execution_stats["fail_count"] == 2

    def test_json_dumps_safe(self, github_skill):
        data = github_skill.to_dict()
        text = json.dumps(data)
        assert isinstance(text, str)
        parsed = json.loads(text)
        assert parsed["name"] == "GitHub Login"


# ===========================================================================
# SK-003: SiteSkill Site Matching
# ===========================================================================

class TestSK003SiteMatching:
    """Verify regex-based URL matching against site_pattern."""

    def test_exact_domain(self):
        skill = SiteSkill(site_pattern=r"github\.com")
        assert skill.matches_site("https://github.com/login") is True
        assert skill.matches_site("https://gitlab.com") is False

    def test_wildcard_pattern(self):
        skill = SiteSkill(site_pattern=r".*\.example\.com")
        assert skill.matches_site("https://api.example.com/v1") is True
        assert skill.matches_site("https://www.example.com/page") is True
        assert skill.matches_site("https://other.com") is False

    def test_path_pattern(self):
        skill = SiteSkill(site_pattern=r"github\.com/login")
        assert skill.matches_site("https://github.com/login") is True
        assert skill.matches_site("https://github.com/logout") is False

    def test_invalid_regex_no_crash(self):
        skill = SiteSkill(site_pattern=r"[invalid(")
        assert skill.matches_site("https://example.com") is False

    def test_empty_pattern(self):
        skill = SiteSkill(site_pattern="")
        assert skill.matches_site("https://github.com") is False

    def test_none_url_handled(self):
        skill = SiteSkill(site_pattern=r"github\.com")
        # URL is a string; passing empty string
        assert skill.matches_site("") is False

    def test_partial_match(self):
        skill = SiteSkill(site_pattern=r"github")
        assert skill.matches_site("https://github.com") is True


# ===========================================================================
# SK-004: SiteSkill Execution Stats
# ===========================================================================

class TestSK004ExecutionStats:
    """Verify record_success() and record_failure() mutation."""

    def test_record_success_increments(self):
        skill = SiteSkill(name="test")
        assert skill.execution_stats["success_count"] == 0
        skill.record_success()
        assert skill.execution_stats["success_count"] == 1
        skill.record_success()
        assert skill.execution_stats["success_count"] == 2

    def test_record_failure_increments(self):
        skill = SiteSkill(name="test")
        assert skill.execution_stats["fail_count"] == 0
        skill.record_failure()
        assert skill.execution_stats["fail_count"] == 1

    def test_success_updates_last_used(self):
        skill = SiteSkill(name="test")
        assert skill.execution_stats["last_used_at"] is None
        skill.record_success()
        assert skill.execution_stats["last_used_at"] is not None

    def test_success_updates_last_success(self):
        skill = SiteSkill(name="test")
        assert skill.execution_stats["last_success_at"] is None
        skill.record_success()
        assert skill.execution_stats["last_success_at"] is not None

    def test_failure_updates_last_used_not_success(self):
        skill = SiteSkill(name="test")
        skill.record_failure()
        assert skill.execution_stats["last_used_at"] is not None
        assert skill.execution_stats["last_success_at"] is None

    def test_updated_at_changes(self):
        skill = SiteSkill(name="test")
        before = skill.updated_at
        skill.record_success()
        assert skill.updated_at >= before

    def test_stats_accumulate(self):
        skill = SiteSkill(name="test")
        for _ in range(5):
            skill.record_success()
        for _ in range(3):
            skill.record_failure()
        assert skill.execution_stats["success_count"] == 5
        assert skill.execution_stats["fail_count"] == 3


# ===========================================================================
# SK-005: SkillStore Persistence
# ===========================================================================

class TestSK005SkillStorePersistence:
    """Verify SkillStore CRUD operations against tmpdir."""

    def test_save_creates_file(self, store, github_skill):
        path = store.save(github_skill)
        assert path.exists()
        assert path.suffix == ".json"

    def test_save_load_round_trip(self, store, github_skill):
        store.save(github_skill)
        loaded = store.load(github_skill.skill_id)
        assert loaded is not None
        assert loaded.name == github_skill.name
        assert loaded.goal == github_skill.goal

    def test_load_nonexistent(self, store):
        result = store.load("nonexistent-id")
        assert result is None

    def test_delete_removes_file(self, store, github_skill):
        store.save(github_skill)
        assert store.delete(github_skill.skill_id) is True
        assert store.load(github_skill.skill_id) is None

    def test_delete_nonexistent(self, store):
        assert store.delete("no-such-id") is False

    def test_find_by_site(self, populated_store):
        matches = populated_store.find_by_site("https://github.com/login")
        assert len(matches) == 1
        assert matches[0].name == "GitHub Login"

    def test_find_by_site_no_match(self, populated_store):
        matches = populated_store.find_by_site("https://twitter.com")
        assert len(matches) == 0

    def test_find_by_goal(self, populated_store):
        matches = populated_store.find_by_goal(r"sign in")
        assert len(matches) == 1
        assert matches[0].name == "GitHub Login"

    def test_find_by_goal_case_insensitive(self, populated_store):
        matches = populated_store.find_by_goal(r"SIGN IN")
        assert len(matches) == 1

    def test_find_by_goal_invalid_regex(self, populated_store):
        matches = populated_store.find_by_goal(r"[invalid(")
        assert matches == []

    def test_list_all(self, populated_store):
        all_skills = populated_store.list_all()
        assert len(all_skills) == 2

    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_save_caches_result(self, store, github_skill):
        store.save(github_skill)
        # Second load should come from cache
        loaded = store.load(github_skill.skill_id)
        assert loaded.skill_id == github_skill.skill_id

    def test_saved_file_is_valid_json(self, store, github_skill):
        path = store.save(github_skill)
        with open(path) as f:
            data = json.load(f)
        assert data["name"] == "GitHub Login"


# ===========================================================================
# SK-006: SkillStore Factory Method
# ===========================================================================

class TestSK006FactoryMethod:
    """Verify SiteSkill.from_orchestration_result() factory."""

    def test_site_pattern_from_url(self):
        result = {"steps": []}
        plan = {"steps": [], "description": "Login flow"}
        skill = SiteSkill.from_orchestration_result(result, plan, "https://github.com/login")
        assert "github.com" in skill.site_pattern

    def test_preconditions_from_plan(self):
        result = {"steps": []}
        plan = {"steps": [
            {"pre_condition": "form visible"},
            {"pre_condition": "not authenticated"},
        ]}
        skill = SiteSkill.from_orchestration_result(result, plan, "https://example.com")
        assert "form visible" in skill.preconditions
        assert len(skill.preconditions) == 2

    def test_postconditions_from_plan(self):
        result = {"steps": []}
        plan = {"steps": [
            {"post_condition": "logged in"},
        ]}
        skill = SiteSkill.from_orchestration_result(result, plan, "https://example.com")
        assert "logged in" in skill.postconditions

    def test_evidence_from_result_steps(self):
        result = {"steps": [
            {"evidence_chain_ids": ["ev-1", "ev-2"]},
            {"evidence_chain_ids": ["ev-3"]},
            {"evidence_chain_ids": ["ev-1"]},  # duplicate
        ]}
        plan = {"steps": []}
        skill = SiteSkill.from_orchestration_result(result, plan, "https://example.com")
        assert len(skill.evidence_requirements) == 3
        assert "ev-1" in skill.evidence_requirements

    def test_name_auto_generated(self):
        result = {"steps": []}
        plan = {"steps": []}
        skill = SiteSkill.from_orchestration_result(result, plan, "https://example.com")
        assert "example.com" in skill.name or "Skill" in skill.name

    def test_explicit_name(self):
        result = {"steps": []}
        plan = {"steps": []}
        skill = SiteSkill.from_orchestration_result(result, plan, "https://example.com", name="Custom")
        assert skill.name == "Custom"

    def test_goal_from_plan_description(self):
        result = {"steps": []}
        plan = {"steps": [], "description": "Login to the portal"}
        skill = SiteSkill.from_orchestration_result(result, plan, "https://example.com")
        assert skill.goal == "Login to the portal"

    def test_learned_selectors(self):
        result = {"steps": []}
        plan = {"steps": []}
        selectors = {"submit": "#btn"}
        skill = SiteSkill.from_orchestration_result(
            result, plan, "https://example.com", learned_selectors=selectors
        )
        assert skill.learned_selectors == {"submit": "#btn"}


# ===========================================================================
# SK-007: SkillMatcher Scoring Accuracy
# ===========================================================================

class TestSK007ScoringAccuracy:
    """Verify SkillMatcher composite scoring formula."""

    def test_perfect_match_score(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://github.com/login", "sign in to github account")
        # GitHub skill: site=1.0, goal should have high overlap
        github_match = [m for m in matches if m.skill.name == "GitHub Login"][0]
        assert github_match.site_match is True
        assert github_match.score > 0.7  # site alone = 0.4, plus goal overlap

    def test_no_match_low_score(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://reddit.com", "browse funny memes")
        assert len(matches) == 2  # Still returns all skills
        # Both should have site_match=False and low goal overlap
        for m in matches:
            assert m.site_match is False
            assert m.score < 0.5

    def test_neutral_prior_for_new_skill(self, store):
        # Skill with no executions
        skill = SiteSkill(name="new", site_pattern="test.com", goal="test goal")
        store.save(skill)
        matcher = SkillMatcher(store)
        matches = matcher.match("https://test.com", "test goal")
        assert len(matches) == 1
        assert matches[0].success_rate == 0.5

    def test_all_success_rate(self, store):
        skill = SiteSkill(name="perfect", site_pattern="test.com", goal="test",
                          execution_stats={"success_count": 10, "fail_count": 0,
                                           "last_used_at": None, "last_success_at": None})
        store.save(skill)
        matcher = SkillMatcher(store)
        matches = matcher.match("https://test.com", "test")
        assert matches[0].success_rate == 1.0

    def test_all_fail_rate(self, store):
        skill = SiteSkill(name="broken", site_pattern="test.com", goal="test",
                          execution_stats={"success_count": 0, "fail_count": 5,
                                           "last_used_at": None, "last_success_at": None})
        store.save(skill)
        matcher = SkillMatcher(store)
        matches = matcher.match("https://test.com", "test")
        assert matches[0].success_rate == 0.0

    def test_mixed_rate(self, store):
        skill = SiteSkill(name="mixed", site_pattern="test.com", goal="test",
                          execution_stats={"success_count": 7, "fail_count": 3,
                                           "last_used_at": None, "last_success_at": None})
        store.save(skill)
        matcher = SkillMatcher(store)
        matches = matcher.match("https://test.com", "test")
        assert abs(matches[0].success_rate - 0.7) < 0.01

    def test_component_weights_sum_to_one(self):
        assert abs(SkillMatcher.SITE_WEIGHT + SkillMatcher.GOAL_WEIGHT + SkillMatcher.SUCCESS_WEIGHT - 1.0) < 0.001

    def test_site_match_component(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://github.com/login", "unrelated xyz")
        github = [m for m in matches if m.skill.name == "GitHub Login"][0]
        assert github.site_match is True
        # Score should include 0.4 for site
        assert github.score >= 0.4

    def test_goal_overlap_jaccard(self, populated_store):
        matcher = SkillMatcher(populated_store)
        # "sign in to github account" vs "sign in to github account" → Jaccard = 1.0
        matches = matcher.match("https://unknown.com", "sign in to github account")
        github = [m for m in matches if m.skill.name == "GitHub Login"][0]
        assert abs(github.goal_overlap - 1.0) < 0.01

    def test_partial_goal_overlap(self, populated_store):
        matcher = SkillMatcher(populated_store)
        # "sign in" vs "sign in to github account" → partial overlap
        matches = matcher.match("https://unknown.com", "sign in")
        github = [m for m in matches if m.skill.name == "GitHub Login"][0]
        assert 0.0 < github.goal_overlap < 1.0


# ===========================================================================
# SK-008: SkillMatcher Ranking & Determinism
# ===========================================================================

class TestSK008RankingDeterminism:
    """Verify result ordering, tie-breaking, and top_k truncation."""

    def test_sorted_descending_by_score(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://github.com/login", "sign in to github account")
        scores = [m.score for m in matches]
        assert scores == sorted(scores, reverse=True)

    def test_github_ranks_higher_for_github_url(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://github.com/login", "sign in to github account")
        assert matches[0].skill.name == "GitHub Login"

    def test_google_ranks_higher_for_google_url(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://google.com/search", "search for information online")
        assert matches[0].skill.name == "Google Search"

    def test_ranks_assigned_sequentially(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://github.com/login", "sign in")
        ranks = [m.rank for m in matches]
        assert ranks == list(range(1, len(matches) + 1))

    def test_top_k_truncation(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://github.com/login", "sign in", top_k=1)
        assert len(matches) == 1

    def test_top_k_larger_than_store(self, populated_store):
        matcher = SkillMatcher(populated_store)
        matches = matcher.match("https://github.com/login", "sign in", top_k=100)
        assert len(matches) == 2

    def test_empty_store_returns_empty(self, store):
        matcher = SkillMatcher(store)
        matches = matcher.match("https://example.com", "test")
        assert matches == []

    def test_tie_breaking_by_skill_id(self, store):
        """Two skills with identical scores → alphabetical by skill_id.

        SkillStore.list_all() uses glob("skill-*.json"), so skill IDs
        must start with "skill-" to be discoverable.
        """
        s1 = SiteSkill(skill_id="skill-aaa", name="A", site_pattern="", goal="same goal",
                       execution_stats={"success_count": 0, "fail_count": 0,
                                        "last_used_at": None, "last_success_at": None})
        s2 = SiteSkill(skill_id="skill-zzz", name="Z", site_pattern="", goal="same goal",
                       execution_stats={"success_count": 0, "fail_count": 0,
                                        "last_used_at": None, "last_success_at": None})
        store.save(s1)
        store.save(s2)
        matcher = SkillMatcher(store)
        matches = matcher.match("https://example.com", "same goal")
        assert len(matches) == 2
        assert matches[0].skill.skill_id == "skill-aaa"

    def test_deterministic_results(self, populated_store):
        """Same query always produces same results."""
        matcher = SkillMatcher(populated_store)
        m1 = matcher.match("https://github.com/login", "sign in")
        m2 = matcher.match("https://github.com/login", "sign in")
        assert [m.skill.skill_id for m in m1] == [m.skill.skill_id for m in m2]
        assert [m.score for m in m1] == [m.score for m in m2]


# ===========================================================================
# SK-009: SkillMatcher Tokenization
# ===========================================================================

class TestSK009Tokenization:
    """Verify _tokenize() produces correct word token sets."""

    def test_basic_tokenization(self):
        tokens = SkillMatcher._tokenize("hello world test")
        assert tokens == {"hello", "world", "test"}

    def test_lowercasing(self):
        tokens = SkillMatcher._tokenize("Hello World")
        assert "hello" in tokens
        assert "world" in tokens

    def test_punctuation_stripped(self):
        tokens = SkillMatcher._tokenize("hello, world! test.")
        assert tokens == {"hello", "world", "test"}

    def test_short_tokens_filtered(self):
        tokens = SkillMatcher._tokenize("a I to the big")
        # Tokens must be >= 2 chars: "a" (1) and "I" (1) filtered out
        assert "a" not in tokens
        assert "I" not in tokens
        assert "to" in tokens  # exactly 2 chars, passes filter
        assert "the" in tokens
        assert "big" in tokens

    def test_empty_string(self):
        tokens = SkillMatcher._tokenize("")
        assert tokens == set()

    def test_numbers_preserved(self):
        tokens = SkillMatcher._tokenize("test 123 abc456")
        assert "123" in tokens
        assert "abc456" in tokens

    def test_mixed_case_punctuation(self):
        tokens = SkillMatcher._tokenize("Sign-In To GitHub!!")
        assert "sign-in" in tokens
        assert "to" in tokens
        assert "github" in tokens


# ===========================================================================
# SK-010: End-to-End Skill Lifecycle
# ===========================================================================

class TestSK010EndToEndLifecycle:
    """Verify full lifecycle: learn → store → match → retrieve → delete."""

    def test_full_lifecycle(self, store):
        # 1. Create skill from orchestration result
        result = {
            "steps": [
                {"evidence_chain_ids": ["ev-1"]},
                {"evidence_chain_ids": ["ev-2"]},
            ],
        }
        plan = {
            "steps": [
                {"action": "fill", "pre_condition": "form visible", "post_condition": "fields filled"},
                {"action": "click", "pre_condition": "button visible", "post_condition": "submitted"},
            ],
            "description": "Login to example site",
        }
        skill = SiteSkill.from_orchestration_result(
            result, plan, "https://example.com/login",
            name="Example Login",
            learned_selectors={"username": "#user", "submit": "#btn"},
        )

        # 2. Save to store → retrieve by ID
        store.save(skill)
        loaded = store.load(skill.skill_id)
        assert loaded is not None
        assert loaded.name == "Example Login"

        # 3. Match against original URL → skill found
        matcher = SkillMatcher(store)
        matches = matcher.match("https://example.com/login", "Login to example site")
        assert len(matches) >= 1
        assert matches[0].skill.name == "Example Login"
        assert matches[0].site_match is True

        # 4. Match against different URL → appropriate ranking
        matches2 = matcher.match("https://other.com", "Login to example site")
        assert len(matches2) >= 1
        # Same skill but no site match
        example_match = [m for m in matches2 if m.skill.name == "Example Login"][0]
        assert example_match.site_match is False
        assert example_match.score < matches[0].score

        # 5. Record success/failure → re-match with updated score
        skill.record_success()
        skill.record_success()
        store.save(skill)  # Re-save with updated stats

        matcher2 = SkillMatcher(store)
        matches3 = matcher2.match("https://example.com/login", "Login to example site")
        updated = [m for m in matches3 if m.skill.name == "Example Login"][0]
        assert updated.success_rate == 1.0  # 2 success, 0 fail

        # 6. Delete skill → no longer in match results
        store.delete(skill.skill_id)
        matches4 = matcher2.match("https://example.com/login", "Login to example site")
        assert all(m.skill.name != "Example Login" for m in matches4)

    def test_multi_skill_lifecycle(self, store):
        """Multiple skills interact correctly in store and matcher."""
        skills = []
        for i in range(5):
            s = SiteSkill(
                name=f"Skill {i}",
                site_pattern=f"site{i}\\.com",
                goal=f"perform action {i} on site",
                execution_stats={"success_count": i, "fail_count": 5 - i,
                                 "last_used_at": None, "last_success_at": None},
            )
            store.save(s)
            skills.append(s)

        # Match against site2 → Skill 2 should rank highest (site match)
        matcher = SkillMatcher(store)
        matches = matcher.match("https://site2.com/page", "perform action 2 on site")
        assert matches[0].skill.name == "Skill 2"
        assert matches[0].site_match is True

        # All skills present in results
        assert len(matches) == 5

        # Delete one → no longer in results
        store.delete(skills[2].skill_id)
        matches2 = matcher.match("https://site2.com/page", "perform action 2 on site")
        assert len(matches2) == 4
        assert all(m.skill.name != "Skill 2" for m in matches2)

    def test_factory_to_orchestration_round_trip(self, store):
        """Factory-created skill survives full store/match cycle."""
        result = {"steps": [{"evidence_chain_ids": ["e1"]}]}
        plan = {"steps": [{"pre_condition": "a", "post_condition": "b"}], "description": "test goal"}
        skill = SiteSkill.from_orchestration_result(result, plan, "https://myapp.com")

        store.save(skill)
        loaded = store.load(skill.skill_id)
        assert loaded is not None

        # Verify factory-extracted fields persisted
        assert "myapp.com" in loaded.site_pattern
        assert loaded.preconditions == ["a"]
        assert loaded.postconditions == ["b"]
        assert loaded.evidence_requirements == ["e1"]
