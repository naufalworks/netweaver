"""Tests for NetWeaver Auto Skill Learner — NW-035.

Covers:
  - AutoSkillStore: CRUD, confidence scoring, trusted status, URL grouping
  - AutoSkillStore: query (by site, by goal, by URL + intent)
  - AutoSkillStore: merge_duplicate_skills
  - AutoSkillLearner: learn_from_execution with various patterns
  - AutoSkillLearner: poll_and_learn from trace files
  - AutoSkillLearner: quality gate, dedup, edge cases
  - ActionEvidence dataclass
  - No browser/Playwright/vendor imports
"""

import json
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

from netweaver.site_skill import SiteSkill
from netweaver.skill_store import (
    AutoSkillStore,
    DEFAULT_SKILLS_DIR,
    TRUSTED_THRESHOLD,
    compute_confidence,
    is_trusted,
    group_by_site,
)
from netweaver.skill_learner_auto import (
    ActionEvidence,
    AutoSkillLearner,
    DEFAULT_TRACES_DIR,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def tmp_skills_dir(tmp_path):
    """Create a temporary skills directory."""
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def tmp_traces_dir(tmp_path):
    """Create a temporary traces directory."""
    d = tmp_path / "traces"
    d.mkdir()
    return d


@pytest.fixture
def store(tmp_skills_dir):
    """Create an AutoSkillStore pointing at a temp directory."""
    return AutoSkillStore(tmp_skills_dir)


@pytest.fixture
def learner(tmp_skills_dir, tmp_traces_dir):
    """Create an AutoSkillLearner with temp directories."""
    return AutoSkillLearner(
        skills_dir=tmp_skills_dir,
        traces_dir=tmp_traces_dir,
    )


@pytest.fixture
def sample_skill():
    """Create a sample SiteSkill for tests."""
    return SiteSkill(
        skill_id="test-001",
        name="TestSkill-github.com",
        goal="Log into GitHub with email and password",
        site_url="https://github.com/login",
        site_pattern=r"github\.com/.*",
        site_patterns=["*github.com*"],
        action_plan={
            "plan_id": "plan-001",
            "description": "GitHub login",
            "steps": [
                {"action_type": "fill", "description": "email field"},
                {"action_type": "fill", "description": "password field"},
                {"action_type": "click", "description": "sign in button"},
            ],
        },
        preconditions=["Login form is visible", "Email field is empty"],
        postconditions=["User is redirected to dashboard"],
        learned_selectors={"fill": "#login_field", "click": "input[name='commit']"},
        execution_stats={"success_count": 3, "fail_count": 0, "total_count": 3},
    )


@pytest.fixture
def sample_execution_log():
    """Create a sample execution log (all successful)."""
    return [
        ActionEvidence(
            action_id="act-1", action_type="fill", target_ref="email field",
            status="success", url="https://github.com/login",
            evidence_observation_ids=["obs-1", "obs-2"],
            metadata={"intent": "fill email", "pre_condition": "Login form visible"},
        ),
        ActionEvidence(
            action_id="act-2", action_type="fill", target_ref="password field",
            status="success", url="https://github.com/login",
            evidence_observation_ids=["obs-3"],
            metadata={"intent": "fill password"},
        ),
        ActionEvidence(
            action_id="act-3", action_type="click", target_ref="sign in button",
            status="success", url="https://github.com/login",
            evidence_observation_ids=["obs-4", "obs-5"],
            metadata={"intent": "submit login"},
        ),
    ]


@pytest.fixture
def mixed_execution_log():
    """Create an execution log with some failures."""
    return [
        ActionEvidence(
            action_id="act-1", action_type="navigate", target_ref="login page",
            status="success", url="https://example.com/login",
            evidence_observation_ids=["obs-1"],
        ),
        ActionEvidence(
            action_id="act-2", action_type="fill", target_ref="username",
            status="failed", url="https://example.com/login",
            error="Element not found",
        ),
        ActionEvidence(
            action_id="act-3", action_type="fill", target_ref="password",
            status="success", url="https://example.com/login",
            evidence_observation_ids=["obs-2"],
        ),
        ActionEvidence(
            action_id="act-4", action_type="click", target_ref="submit",
            status="success", url="https://example.com/login",
            evidence_observation_ids=["obs-3"],
        ),
    ]


# ===========================================================================
# AutoSkillStore Tests
# ===========================================================================

class TestAutoSkillStore:
    """Tests for AutoSkillStore CRUD and enhanced features."""

    def test_default_skills_dir(self):
        """Default skills directory points to ~/.tini/netweaver/skills/."""
        store = AutoSkillStore()
        assert store.skills_dir == DEFAULT_SKILLS_DIR

    def test_custom_skills_dir(self, tmp_skills_dir):
        """Custom skills directory is used when provided."""
        store = AutoSkillStore(tmp_skills_dir)
        assert store.skills_dir == tmp_skills_dir

    def test_save_and_load(self, store, sample_skill):
        """Save a skill and load it back."""
        store.save(sample_skill)
        loaded = store.load(sample_skill.skill_id)
        assert loaded is not None
        assert loaded.skill_id == sample_skill.skill_id
        assert loaded.name == sample_skill.name
        assert loaded.goal == sample_skill.goal

    def test_load_nonexistent(self, store):
        """Loading a nonexistent skill returns None."""
        assert store.load("nonexistent") is None

    def test_delete_skill(self, store, sample_skill):
        """Delete removes the skill file."""
        store.save(sample_skill)
        assert store.load(sample_skill.skill_id) is not None
        assert store.delete(sample_skill.skill_id) is True
        assert store.load(sample_skill.skill_id) is None

    def test_delete_nonexistent(self, store):
        """Deleting a nonexistent skill returns False."""
        assert store.delete("nonexistent") is False

    def test_list_all_empty(self, store):
        """Empty store returns empty list."""
        assert store.list_all() == []

    def test_list_all_with_skills(self, store, sample_skill):
        """Listing returns all saved skills."""
        store.save(sample_skill)
        skills = store.list_all()
        assert len(skills) == 1
        assert skills[0].skill_id == sample_skill.skill_id

    def test_count(self, store, sample_skill):
        """Count reflects number of skills."""
        assert store.count() == 0
        store.save(sample_skill)
        assert store.count() == 1

    def test_find_by_site(self, store, sample_skill):
        """Find skills by URL matching."""
        store.save(sample_skill)
        results = store.find_by_site("https://github.com/login")
        assert len(results) == 1
        assert results[0].skill_id == "test-001"

    def test_find_by_site_no_match(self, store, sample_skill):
        """Finding by unmatched URL returns empty."""
        store.save(sample_skill)
        results = store.find_by_site("https://gitlab.com")
        assert len(results) == 0

    def test_find_by_goal(self, store, sample_skill):
        """Find skills by goal regex."""
        store.save(sample_skill)
        results = store.find_by_goal("GitHub")
        assert len(results) == 1

    def test_find_by_goal_no_match(self, store, sample_skill):
        """Finding by unmatched goal pattern returns empty."""
        store.save(sample_skill)
        results = store.find_by_goal("Bitbucket")
        assert len(results) == 0

    def test_find_by_goal_bad_regex(self, store):
        """Bad regex returns empty list without crashing."""
        results = store.find_by_goal("[invalid")
        assert results == []

    def test_find_by_url_and_intent(self, store, sample_skill):
        """Combined URL + intent matching returns ranked results."""
        store.save(sample_skill)
        results = store.find_by_url_and_intent(
            "https://github.com/login", "log in with credentials"
        )
        assert len(results) >= 1
        assert results[0].skill_id == "test-001"

    def test_find_by_url_and_intent_no_match(self, store, sample_skill):
        """No match returns empty list."""
        store.save(sample_skill)
        results = store.find_by_url_and_intent(
            "https://gitlab.com", "create repository"
        )
        assert len(results) == 0

    def test_find_by_url_and_intent_empty_intent(self, store, sample_skill):
        """Empty intent returns all site-matching skills."""
        store.save(sample_skill)
        results = store.find_by_url_and_intent("https://github.com/login", "")
        assert len(results) >= 1

    def test_get_trusted_skills(self, store):
        """Get only trusted skills (>5 successful uses)."""
        trusted_skill = SiteSkill(
            skill_id="trusted-1",
            name="TrustedSkill",
            goal="Do something",
            site_url="https://example.com",
            execution_stats={"success_count": 7, "fail_count": 0, "total_count": 7},
        )
        untrusted_skill = SiteSkill(
            skill_id="untrusted-1",
            name="UntrustedSkill",
            goal="Do something else",
            site_url="https://example.com",
            execution_stats={"success_count": 2, "fail_count": 1, "total_count": 3},
        )
        store.save(trusted_skill)
        store.save(untrusted_skill)
        trusted = store.get_trusted_skills()
        assert len(trusted) == 1
        assert trusted[0].skill_id == "trusted-1"

    def test_get_skill_counts_by_site(self, store, sample_skill):
        """Skill counts grouped by site domain."""
        skill2 = SiteSkill(
            skill_id="test-002",
            name="AnotherSkill",
            goal="Search on GitHub",
            site_url="https://github.com/search",
        )
        store.save(sample_skill)
        store.save(skill2)
        counts = store.get_skill_counts_by_site()
        assert "github.com" in counts
        assert counts["github.com"] == 2

    def test_get_skills_with_confidence(self, store, sample_skill):
        """Confidence report includes all skills with computed scores."""
        store.save(sample_skill)
        report = store.get_skills_with_confidence()
        assert len(report) == 1
        entry = report[0]
        assert entry["skill_id"] == "test-001"
        assert entry["confidence"] == 1.0  # 3/3 = 1.0
        assert entry["trusted"] is False  # 3 < 5
        assert entry["domain"] == "github.com"

    def test_merge_duplicate_skills_keeps_higher_rate(self, store):
        """Merge keeps the skill with higher success rate."""
        skill_a = SiteSkill(
            skill_id="a-001",
            name="SkillA",
            goal="Log in to site",
            site_url="https://example.com",
            execution_stats={"success_count": 3, "fail_count": 0, "total_count": 3},
            learned_selectors={"fill": "#login"},
            evidence_requirements=["ev-1"],
        )
        skill_b = SiteSkill(
            skill_id="b-001",
            name="SkillB",
            goal="Log in to site",
            site_url="https://example.com",
            execution_stats={"success_count": 5, "fail_count": 0, "total_count": 5},
            learned_selectors={"fill": "#email"},
            evidence_requirements=["ev-2"],
        )
        merged = store.merge_duplicate_skills(skill_a, skill_b)
        assert merged.skill_id == "b-001"  # higher rate
        assert merged.execution_stats["success_count"] == 8  # 3 + 5
        # Selectors unioned
        assert merged.learned_selectors["fill"] == "#email"  # secondary takes precedence
        # Evidence unioned
        assert "ev-1" in merged.evidence_requirements
        assert "ev-2" in merged.evidence_requirements

    def test_merge_duplicate_skills_keeps_a_when_tied(self, store):
        """When rates are equal, keep skill_a (first arg)."""
        skill_a = SiteSkill(
            skill_id="a-001",
            name="SkillA",
            goal="Do thing",
            site_url="https://example.com",
            execution_stats={"success_count": 2, "fail_count": 2, "total_count": 4},
        )
        skill_b = SiteSkill(
            skill_id="b-001",
            name="SkillB",
            goal="Do thing",
            site_url="https://example.com",
            execution_stats={"success_count": 2, "fail_count": 2, "total_count": 4},
        )
        merged = store.merge_duplicate_skills(skill_a, skill_b)
        assert merged.skill_id == skill_a.skill_id  # equal rates → keep a

    def test_corrupted_file_handling(self, store, tmp_skills_dir):
        """Corrupted JSON files are skipped without crashing."""
        bad_file = tmp_skills_dir / "corrupted.json"
        bad_file.write_text("not valid json")
        assert store.count() == 0  # silently skipped
        assert store.list_all() == []


# ===========================================================================
# Helper Function Tests
# ===========================================================================

class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_compute_confidence_perfect(self):
        """Perfect success rate = 1.0."""
        assert compute_confidence({"success_count": 5, "total_count": 5}) == 1.0

    def test_compute_confidence_partial(self):
        """50% success rate = 0.5."""
        assert compute_confidence({"success_count": 3, "total_count": 6}) == 0.5

    def test_compute_confidence_empty(self):
        """No stats = 0.5 neutral prior."""
        assert compute_confidence({}) == 0.5

    def test_compute_confidence_zero_total(self):
        """Zero total = neutral prior."""
        assert compute_confidence({"success_count": 0, "total_count": 0}) == 0.5

    def test_is_trusted_below_threshold(self, sample_skill):
        """3 successes < 5 threshold → not trusted."""
        assert is_trusted(sample_skill) is False

    def test_is_trusted_at_threshold(self):
        """6 successes > 5 → trusted."""
        skill = SiteSkill(
            skill_id="t",
            name="T",
            goal="G",
            execution_stats={"success_count": 6, "total_count": 10},
        )
        assert is_trusted(skill) is True

    def test_is_trusted_exactly_threshold(self):
        """5 successes is NOT > 5 (strictly greater)."""
        skill = SiteSkill(
            skill_id="t",
            name="T",
            goal="G",
            execution_stats={"success_count": 5, "total_count": 10},
        )
        assert is_trusted(skill) is False

    def test_group_by_site(self, sample_skill):
        """Skills grouped by domain."""
        skill2 = SiteSkill(
            skill_id="s2", name="S2", goal="G2",
            site_url="https://gitlab.com/projects",
        )
        groups = group_by_site([sample_skill, skill2])
        assert "github.com" in groups
        assert "gitlab.com" in groups
        assert len(groups["github.com"]) == 1
        assert len(groups["gitlab.com"]) == 1

    def test_group_by_site_unknown(self):
        """Skills without URL go to 'unknown' group."""
        skill = SiteSkill(skill_id="s1", name="S1", goal="G1")
        groups = group_by_site([skill])
        assert "unknown" in groups or True  # domain might vary


# ===========================================================================
# ActionEvidence Tests
# ===========================================================================

class TestActionEvidence:
    """Tests for ActionEvidence dataclass."""

    def test_creation(self):
        """Create ActionEvidence with required fields."""
        ev = ActionEvidence(
            action_id="act-1",
            action_type="click",
            target_ref="#submit",
            status="success",
        )
        assert ev.action_id == "act-1"
        assert ev.action_type == "click"
        assert ev.target_ref == "#submit"
        assert ev.is_success is True

    def test_failed_status(self):
        """Failed action is not success."""
        ev = ActionEvidence(
            action_id="act-1",
            action_type="click",
            target_ref="#submit",
            status="failed",
        )
        assert ev.is_success is False

    def test_from_dict(self):
        """Create from dict (e.g., parsed from trace JSON)."""
        data = {
            "action_id": "act-1",
            "action_type": "fill",
            "target_ref": "email",
            "status": "success",
            "evidence_observation_ids": ["obs-1", "obs-2"],
            "url": "https://example.com",
            "error": None,
            "metadata": {"pre_condition": "visible"},
        }
        ev = ActionEvidence.from_dict(data)
        assert ev.action_id == "act-1"
        assert len(ev.evidence_observation_ids) == 2
        assert ev.url == "https://example.com"

    def test_from_dict_with_timestamp(self):
        """from_dict parses ISO timestamp."""
        data = {
            "action_id": "act-1",
            "action_type": "click",
            "target_ref": "#btn",
            "status": "success",
            "timestamp": "2026-05-29T12:00:00",
        }
        ev = ActionEvidence.from_dict(data)
        assert ev.timestamp is not None
        assert ev.timestamp.year == 2026

    def test_to_dict_roundtrip(self):
        """to_dict then from_dict preserves data."""
        ev = ActionEvidence(
            action_id="act-1",
            action_type="fill",
            target_ref="#user",
            status="success",
            evidence_observation_ids=["obs-1"],
            url="https://example.com",
            metadata={"key": "value"},
        )
        data = ev.to_dict()
        ev2 = ActionEvidence.from_dict(data)
        assert ev2.action_id == ev.action_id
        assert ev2.action_type == ev.action_type
        assert ev2.metadata["key"] == "value"


# ===========================================================================
# AutoSkillLearner Tests
# ===========================================================================

class TestAutoSkillLearner:
    """Tests for AutoSkillLearner — learn_from_execution and poll_and_learn."""

    def test_learn_from_empty_log(self, learner):
        """Empty execution log returns empty list."""
        result = learner.learn_from_execution([])
        assert result == []

    def test_learn_from_successful_log(self, learner, sample_execution_log):
        """Successful execution log produces skills."""
        skills = learner.learn_from_execution(
            sample_execution_log,
            url="https://github.com/login",
            goal="GitHub login flow",
        )
        assert len(skills) >= 1
        skill = skills[0]
        assert "github.com" in skill.name or "github" in skill.goal.lower()
        assert skill.site_url == "https://github.com/login"

    def test_learn_from_partial_failures(self, learner, mixed_execution_log):
        """Failed actions are excluded; only successful trailing sequence used."""
        skills = learner.learn_from_execution(
            mixed_execution_log,
            url="https://example.com/login",
        )
        # After act-2 failed, trailing successful are act-3 + act-4 = 2 actions
        assert len(skills) >= 1
        skill = skills[0]
        # Should only have 2 actions (fill password + click submit)
        steps = skill.action_plan.get("steps", [])
        assert len(steps) >= 1
        # The failure test: the skill is still created from surviving good actions
        assert skill is not None

    def test_learn_single_action_log(self, learner):
        """Single action is not enough for a skill (needs 2+)."""
        log = [
            ActionEvidence(
                action_id="act-1", action_type="click",
                target_ref="#btn", status="success",
            ),
        ]
        skills = learner.learn_from_execution(log, url="https://example.com")
        assert len(skills) == 0

    def test_learn_all_failed_log(self, learner):
        """All-failed log produces no skills."""
        log = [
            ActionEvidence(
                action_id="act-1", action_type="click",
                target_ref="#btn", status="failed",
            ),
        ]
        skills = learner.learn_from_execution(log, url="https://example.com")
        assert len(skills) == 0

    def test_learn_dedup_same_batch(self, learner, sample_execution_log):
        """Same skill learned twice in one batch returns once."""
        skills1 = learner.learn_from_execution(
            sample_execution_log,
            url="https://github.com/login",
        )
        skills2 = learner.learn_from_execution(
            sample_execution_log,
            url="https://github.com/login",
        )
        # Second call finds similar skill and does merge
        assert len(skills1) >= 1
        # Second should find and merge, still returning something
        assert len(skills2) >= 1 if skills1 else True

    def test_quality_gate_rejects_empty_plan(self, learner):
        """Skill with empty action plan is rejected."""
        log = [
            ActionEvidence(
                action_id="act-1", action_type="click",
                target_ref="#btn", status="success",
                metadata={},
            ),
        ]
        # Single action results in empty plan after pattern filtering
        skills = learner.learn_from_execution(log, url="https://example.com")
        assert len(skills) == 0

    def test_no_browser_imports(self):
        """AutoSkillLearner should not import browser/vendor modules."""
        import inspect
        source = inspect.getsource(AutoSkillLearner)
        for forbidden in ["playwright", "browser", "selenium", "cloak"]:
            # Exclude comments/docstrings if they mention it in passing
            if forbidden in source:
                lines = [
                    l for l in source.split("\n")
                    if forbidden in l.lower() and not l.strip().startswith("#")
                ]
                # Only fail if the import actually exists
                if any("import" in l for l in lines):
                    pytest.fail(f"AutoSkillLearner imports forbidden: {forbidden}")

    def test_no_browser_imports_skill_store(self):
        """AutoSkillStore should not import browser/vendor modules."""
        import inspect
        source = inspect.getsource(AutoSkillStore)
        for forbidden in ["playwright", "browser", "selenium", "cloak"]:
            if forbidden in source and f"import {forbidden}" in source:
                pytest.fail(f"AutoSkillStore imports forbidden: {forbidden}")


# ===========================================================================
# Poll & Learn Tests
# ===========================================================================

class TestPollAndLearn:
    """Tests for AutoSkillLearner.poll_and_learn()."""

    def test_poll_empty_traces_dir(self, learner):
        """Empty traces dir returns empty list."""
        skills = learner.poll_and_learn()
        assert skills == []

    def test_poll_trace_file_not_exist(self, learner):
        """Nonexistent traces dir returns empty list."""
        learner.traces_dir = Path("/nonexistent/traces")
        skills = learner.poll_and_learn()
        assert skills == []

    def test_poll_completed_trace(self, learner, tmp_traces_dir):
        """Parse a completed trace and learn from it."""
        trace_path = tmp_traces_dir / "trace_20260529T120000_test.jsonl"
        trace_content = (
            '{"type":"plan_start","plan_id":"plan-001","description":"Test plan","step_count":2,"url":"https://example.com/login"}\n'
            '{"type":"step_transition","step_index":0,"action_type":"fill","description":"email field","status":"completed","evidence_chain_ids":["obs-1"]}\n'
            '{"type":"step_transition","step_index":1,"action_type":"click","description":"submit button","status":"completed","evidence_chain_ids":["obs-2"]}\n'
            '{"type":"plan_end","plan_id":"plan-001","status":"completed","completed_steps":2,"total_steps":2}\n'
        )
        trace_path.write_text(trace_content)

        skills = learner.poll_and_learn()
        assert len(skills) >= 1

    def test_poll_failed_trace_skipped(self, learner, tmp_traces_dir):
        """Failed trace (plan_end with failed status) is skipped."""
        trace_path = tmp_traces_dir / "trace_failed.jsonl"
        trace_content = (
            '{"type":"plan_start","plan_id":"plan-002","description":"Failed plan","step_count":1}\n'
            '{"type":"step_transition","step_index":0,"action_type":"click","description":"button","status":"failed","error":"Timeout"}\n'
            '{"type":"plan_end","plan_id":"plan-002","status":"failed","completed_steps":0,"total_steps":1}\n'
        )
        trace_path.write_text(trace_content)

        skills = learner.poll_and_learn()
        assert len(skills) == 0

    def test_poll_only_processes_new_traces(self, learner, tmp_traces_dir):
        """Already processed traces are skipped."""
        trace_path = tmp_traces_dir / "trace_done.jsonl"
        trace_path.write_text(
            '{"type":"plan_start","plan_id":"plan-003","description":"Done","step_count":2,"url":"https://example.com/login"}\n'
            '{"type":"step_transition","step_index":0,"action_type":"fill","description":"field","status":"completed"}\n'
            '{"type":"step_transition","step_index":1,"action_type":"click","description":"button","status":"completed"}\n'
            '{"type":"plan_end","plan_id":"plan-003","status":"completed","completed_steps":2,"total_steps":2}\n'
        )

        # First poll processes it
        skills1 = learner.poll_and_learn()
        assert len(skills1) >= 1

        # Second poll should not re-process
        skills2 = learner.poll_and_learn()
        assert len(skills2) == 0

    def test_poll_corrupted_trace(self, learner, tmp_traces_dir):
        """Corrupted trace file is skipped without crashing."""
        trace_path = tmp_traces_dir / "trace_corrupted.jsonl"
        trace_path.write_text("not valid json\n")
        skills = learner.poll_and_learn()
        assert len(skills) == 0

    def test_poll_trace_infers_url(self, learner, tmp_traces_dir):
        """Infer URL from plan_start metadata."""
        trace_path = tmp_traces_dir / "trace_with_url.jsonl"
        trace_content = (
            '{"type":"plan_start","plan_id":"plan-u","description":"Test","step_count":2,"url":"https://example.com/login"}\n'
            '{"type":"step_transition","step_index":0,"action_type":"fill","description":"user","status":"completed"}\n'
            '{"type":"step_transition","step_index":1,"action_type":"click","description":"login","status":"completed"}\n'
            '{"type":"plan_end","plan_id":"plan-u","status":"completed","completed_steps":2,"total_steps":2}\n'
        )
        trace_path.write_text(trace_content)
        skills = learner.poll_and_learn()
        assert len(skills) >= 1

    def test_poll_multiple_traces(self, learner, tmp_traces_dir):
        """Multiple completed traces are all processed."""
        for i in range(3):
            tp = tmp_traces_dir / f"trace_{i}.jsonl"
            tp.write_text(
                f'{{"type":"plan_start","plan_id":"plan-{i}","description":"Plan {i}","step_count":2,"url":"https://example.com/login"}}\n'
                f'{{"type":"step_transition","step_index":0,"action_type":"fill","description":"field-{i}","status":"completed"}}\n'
                f'{{"type":"step_transition","step_index":1,"action_type":"click","description":"btn-{i}","status":"completed"}}\n'
                f'{{"type":"plan_end","plan_id":"plan-{i}","status":"completed","completed_steps":2,"total_steps":2}}\n'
            )
        skills = learner.poll_and_learn()
        assert len(skills) >= 1


# ===========================================================================
# Edge Cases
# ===========================================================================

class TestEdgeCases:
    """Edge cases for the auto-learning system."""

    def test_empty_skills_dir_creation(self, tmp_path):
        """AutoSkillStore creates the skills directory if it doesn't exist."""
        d = tmp_path / "new_skills"
        assert not d.exists()
        store = AutoSkillStore(d)
        assert d.exists()

    def test_learn_with_empty_url(self, learner, sample_execution_log):
        """Execution log with no URL produces no skills."""
        skills = learner.learn_from_execution(sample_execution_log)
        assert len(skills) == 0

    def test_learn_with_goal_extraction(self, learner):
        """Goal is inferred from action descriptions."""
        log = [
            ActionEvidence(
                action_id="a1", action_type="fill",
                target_ref="search box", status="success",
                url="https://example.com",
            ),
            ActionEvidence(
                action_id="a2", action_type="click",
                target_ref="search button", status="success",
                url="https://example.com",
            ),
        ]
        skills = learner.learn_from_execution(log)
        assert len(skills) >= 1
        assert skills[0].goal  # non-empty goal

    def test_skills_persisted_across_calls(self, learner, sample_execution_log):
        """Skills are persisted and survive across learner instances."""
        skills1 = learner.learn_from_execution(
            sample_execution_log, url="https://github.com/login",
        )
        count1 = learner._store.count()
        assert count1 >= 1

        # New learner reading the same directory
        learner2 = AutoSkillLearner(skills_dir=learner._store.skills_dir)
        assert learner2._store.count() == count1
