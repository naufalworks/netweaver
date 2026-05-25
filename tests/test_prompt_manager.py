import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from netweaver.prompt_manager import PromptManager, PromptVersion


class TestPromptVersion:
    def test_from_dict(self):
        d = {
            "version": 1,
            "agent": "test",
            "content": "Hello",
            "success_rate": 0.9,
            "avg_tokens": 100,
            "failures": ["err1"],
            "parent": None,
            "author": "user",
            "reason": "init",
            "created_at": "2024-01-01T00:00:00+00:00",
            "token_estimate": 125,
        }
        v = PromptVersion.from_dict(d)
        assert v.version == 1
        assert v.agent == "test"
        assert v.success_rate == 0.9
        assert v.token_estimate == len("Hello") // 4


class TestPromptManager:
    @pytest.fixture
    def temp_root(self, tmp_path):
        return tmp_path

    def test_save_and_load(self, temp_root):
        mgr = PromptManager(temp_root)
        v = mgr.save_version("agent1", "prompt content", "initial")
        assert v.version == 1
        assert v.content == "prompt content"

        loaded = mgr.current_version("agent1")
        assert loaded is not None
        assert loaded.content == "prompt content"
        assert loaded.version == 1

    def test_version_increment(self, temp_root):
        mgr = PromptManager(temp_root)
        v1 = mgr.save_version("agent1", "v1")
        v2 = mgr.save_version("agent1", "v2")
        assert v2.version == 2
        assert v2.parent == 1

        versions = mgr.load_registry("agent1")
        assert len(versions) == 2

    @patch("netweaver.prompt_manager.skill_view")
    def test_build_cron_prompt_uses_skill_view(self, mock_skill_view, temp_root):
        mock_skill_view.return_value = "Skill doc content"
        mgr = PromptManager(temp_root)
        prompt = mgr.build_cron_prompt("cron-agent", "do something")
        assert "Skill doc content" in prompt
        mock_skill_view.assert_called_once_with("cron-agent")  # Updated to check argument

    @patch("netweaver.prompt_manager.skill_view")
    def test_build_cron_prompt_structure(self, mock_skill_view, temp_root):
        mock_skill_view.return_value = "Skill"
        mgr = PromptManager(temp_root)
        prompt = mgr.build_cron_prompt("myagent", "task")
        assert "Cron Task for myagent" in prompt
        assert "Task: task" in prompt
        assert "Skill" in prompt
        assert "Execute the above task" in prompt
        mock_skill_view.assert_called_once_with("myagent")  # Added argument check
