"""Tests for NetWeaver Site Skills — SiteSkill dataclass + SkillStore persistence.

Covers:
  - SiteSkill construction and defaults
  - from_orchestration_result factory
  - to_dict / from_dict round-trip
  - matches_site URL pattern matching
  - SkillStore save, load, delete, list_all, find_by_site
  - Edge cases: empty fields, missing files, malformed JSON
"""

import json
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from netweaver.site_skill import SiteSkill, SkillStore


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def skill():
    return SiteSkill(
        skill_id="test001",
        name="Test Skill",
        goal="Log into the admin panel",
        site_url="https://admin.example.com",
        action_plan={"steps": [{"action": "click", "target": "#login"}]},
        preconditions=["page loaded"],
        learned_selectors={"login_button": "#login"},
    )


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        yield SkillStore(Path(tmp))


# ── SiteSkill construction ────────────────────────────────────────────────────

def test_default_skill_id():
    s = SiteSkill()
    assert len(s.skill_id) == 8


def test_default_execution_stats():
    s = SiteSkill()
    assert s.execution_stats["success_count"] == 0
    assert s.execution_stats["fail_count"] == 0


def test_default_preconditions():
    s = SiteSkill()
    assert s.preconditions == []


def test_default_learned_selectors():
    s = SiteSkill()
    assert s.learned_selectors == {}


# ── from_orchestration_result ────────────────────────────────────────────────

def test_from_orchestration_result():
    result = {"preconditions": ["page loaded"], "url": "https://example.com"}
    plan = {"goal": "Click the button", "steps": [{"action": "click"}]}

    skill = SiteSkill.from_orchestration_result(
        result_dict=result,
        plan_dict=plan,
        site_url="https://example.com",
        goal="Click the button",
    )

    assert skill.goal == "Click the button"
    assert skill.site_url == "https://example.com"
    assert skill.action_plan["goal"] == "Click the button"
    assert skill.preconditions == ["page loaded"]
    assert skill.execution_stats["success_count"] == 1
    assert len(skill.site_patterns) == 1


# ── to_dict / from_dict ──────────────────────────────────────────────────────

def test_to_dict_round_trip(skill):
    d = skill.to_dict()
    assert d["skill_id"] == "test001"
    assert d["goal"] == "Log into the admin panel"
    assert d["learned_selectors"]["login_button"] == "#login"

    restored = SiteSkill.from_dict(d)
    assert restored.skill_id == "test001"
    assert restored.goal == "Log into the admin panel"
    assert restored.learned_selectors["login_button"] == "#login"


def test_from_dict_empty():
    d = {}
    s = SiteSkill.from_dict(d)
    assert s.skill_id == ""
    assert s.goal == ""


# ── matches_site ─────────────────────────────────────────────────────────────

def test_matches_site_exact(skill):
    assert skill.matches_site("https://admin.example.com")


def test_matches_site_wildcard(skill):
    skill.site_patterns = ["https://admin.example.com/*"]
    assert skill.matches_site("https://admin.example.com/dashboard")
    assert not skill.matches_site("https://other.example.com")


def test_matches_site_no_match(skill):
    assert not skill.matches_site("https://evil.com")


def test_matches_site_empty_pattern():
    s = SiteSkill()
    assert not s.matches_site("https://example.com")


# ── SkillStore ───────────────────────────────────────────────────────────────

def test_store_save_and_load(skill, store):
    store.save(skill)
    loaded = store.load(skill.skill_id)
    assert loaded is not None
    assert loaded.goal == skill.goal
    assert loaded.skill_id == skill.skill_id
    # Attributes that were there
    assert loaded.learned_selectors["login_button"] == "#login"


def test_store_load_nonexistent(store):
    assert store.load("nonexistent") is None


def test_store_delete(store):
    s = SiteSkill(skill_id="delme")
    store.save(s)
    assert store.load("delme") is not None
    assert store.delete("delme") is True
    assert store.load("delme") is None


def test_store_delete_nonexistent(store):
    assert store.delete("ghost") is False


def test_store_list_all(store):
    s1 = SiteSkill(skill_id="a", name="A")
    s2 = SiteSkill(skill_id="b", name="B")
    store.save(s1)
    store.save(s2)
    all_skills = store.list_all()
    assert len(all_skills) == 2


def test_store_list_all_empty(store):
    assert store.list_all() == []


def test_store_find_by_site(store):
    s1 = SiteSkill(skill_id="s1", site_url="https://alpha.com")
    s2 = SiteSkill(skill_id="s2", site_url="https://beta.com")
    store.save(s1)
    store.save(s2)

    found = store.find_by_site("https://alpha.com/admin")
    assert len(found) == 1
    assert found[0].skill_id == "s1"


def test_store_find_by_site_no_match(store):
    s = SiteSkill(skill_id="s", site_url="https://example.com")
    store.save(s)
    assert store.find_by_site("https://other.com") == []


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_malformed_json_file(store):
    path = store.skills_dir / "bad.json"
    path.write_text("{not json}")
    assert store.load("bad") is None


def test_store_count(store):
    assert store.count() == 0
    store.save(SiteSkill(skill_id="c1"))
    assert store.count() == 1
