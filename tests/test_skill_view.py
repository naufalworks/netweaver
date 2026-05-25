"""Tests for skill_view() function — extracts inline skill docs from prompts."""

from __future__ import annotations

import pytest

from netweaver.prompt_manager import skill_view


class TestSkillView:
    """Test skill_view() extracts and returns skill documentation."""

    def test_skill_view_returns_string(self):
        """skill_view() must return a non-empty string."""
        result = skill_view()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_skill_view_default_no_agent(self):
        """Default call (no agent) returns generic skill doc."""
        result = skill_view()
        assert "Skill doc" in result

    def test_skill_view_with_agent(self):
        """With agent param, returns agent-specific doc."""
        result = skill_view(agent="cron")
        assert "cron" in result
        assert "Skill doc" in result

    def test_skill_view_empty_agent_string(self):
        """Empty string treated same as no agent."""
        result = skill_view(agent="")
        assert "Skill doc content" in result

    def test_skill_view_token_efficiency(self):
        """Extracted skill_view() should be smaller than inline 25K doc."""
        result = skill_view()
        token_est = len(result) // 4
        assert token_est < 10000  # Must be < 10K tokens, well under 25K

    def test_skill_view_module_level_importable(self):
        """skill_view must be importable from prompt_manager module."""
        import netweaver.prompt_manager as pm
        assert hasattr(pm, "skill_view")
        assert callable(pm.skill_view)

    def test_skill_view_consistency(self):
        """Multiple calls return same content (deterministic)."""
        a = skill_view(agent="test")
        b = skill_view(agent="test")
        assert a == b

    def test_skill_view_covers_available_skills(self):
        """Skill doc should mention skills are available."""
        result = skill_view()
        # Either references skills explicitly or provides doc content
        assert any(kw in result.lower() for kw in ["skill", "available", "doc", "content"])

    @pytest.mark.parametrize("agent", ["cron", "scheduler", "task_runner", "any-agent"])
    def test_skill_view_parametrized_agents(self, agent: str):
        """Works for various agent names."""
        result = skill_view(agent=agent)
        assert isinstance(result, str)
        assert len(result) > 0
