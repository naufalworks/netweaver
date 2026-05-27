"""Tests for NetWeaver Alert System."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from netweaver import alerts


class TestAlertState:
    """Test alert state management."""
    
    def test_load_state_no_file(self, tmp_path):
        """Test loading state when file missing."""
        with patch.object(alerts, "ALERTS_STATE", tmp_path / "alerts.json"):
            state = alerts.load_state()
            assert "last_sent" in state
            assert "suppressed" in state
    
    def test_load_state_with_data(self, tmp_path):
        """Test loading state with existing data."""
        state_file = tmp_path / "alerts.json"
        state_file.write_text(json.dumps({
            "last_sent": {"test": 123456},
            "suppressed": {},
        }))
        
        with patch.object(alerts, "ALERTS_STATE", state_file):
            state = alerts.load_state()
            assert state["last_sent"]["test"] == 123456
    
    def test_save_state(self, tmp_path):
        """Test saving state."""
        state_file = tmp_path / "alerts.json"
        state = {"last_sent": {"test": 999}, "suppressed": {}}
        
        with patch.object(alerts, "ALERTS_STATE", state_file):
            alerts.save_state(state)
            assert state_file.exists()
            loaded = json.loads(state_file.read_text())
            assert loaded["last_sent"]["test"] == 999
    
    def test_should_send_first_time(self):
        """Test should_send returns True for first alert."""
        state = {"last_sent": {}, "suppressed": {}}
        assert alerts.should_send("test_alert", state, cooldown=300) is True
    
    def test_should_send_within_cooldown(self):
        """Test should_send returns False within cooldown."""
        state = {"last_sent": {"test_alert": time.time()}, "suppressed": {}}
        assert alerts.should_send("test_alert", state, cooldown=300) is False
    
    def test_should_send_after_cooldown(self):
        """Test should_send returns True after cooldown."""
        state = {"last_sent": {"test_alert": time.time() - 400}, "suppressed": {}}
        assert alerts.should_send("test_alert", state, cooldown=300) is True
    
    def test_mark_sent(self):
        """Test marking alert as sent."""
        state = {"last_sent": {}, "suppressed": {}}
        alerts.mark_sent("test_alert", state)
        assert "test_alert" in state["last_sent"]
        assert state["last_sent"]["test_alert"] > 0


class TestAlertSending:
    """Test alert sending functions."""
    
    def test_send_telegram_no_requests(self):
        """Test Telegram send when requests not available."""
        with patch.object(alerts, "HAS_REQUESTS", False):
            result = alerts.send_telegram("test", "token", "chat")
            assert result is False
    
    @patch("netweaver.alerts.requests.post")
    def test_send_telegram_success(self, mock_post):
        """Test successful Telegram send."""
        mock_post.return_value.status_code = 200
        
        with patch.object(alerts, "HAS_REQUESTS", True):
            result = alerts.send_telegram("test message", "token123", "chat456")
            assert result is True
            mock_post.assert_called_once()
    
    @patch("netweaver.alerts.requests.post")
    def test_send_telegram_failure(self, mock_post):
        """Test failed Telegram send."""
        mock_post.return_value.status_code = 400
        
        with patch.object(alerts, "HAS_REQUESTS", True):
            result = alerts.send_telegram("test", "token", "chat")
            assert result is False
    
    def test_send_slack_no_requests(self):
        """Test Slack send when requests not available."""
        with patch.object(alerts, "HAS_REQUESTS", False):
            result = alerts.send_slack("test", "https://hook")
            assert result is False
    
    @patch("netweaver.alerts.requests.post")
    def test_send_slack_success(self, mock_post):
        """Test successful Slack send."""
        mock_post.return_value.status_code = 200
        
        with patch.object(alerts, "HAS_REQUESTS", True):
            result = alerts.send_slack("test message", "https://hooks.slack.com/xxx")
            assert result is True
    
    def test_send_alert_no_channels(self, tmp_path):
        """Test send_alert with no channels configured."""
        with patch.object(alerts, "ALERTS_STATE", tmp_path / "alerts.json"):
            result = alerts.send_alert("test", "Title", "Message", cooldown=0)
            # Should return False (no channels) but still log
            assert result is False
    
    @patch.dict(os.environ, {"NETWEAVER_TELEGRAM_TOKEN": "token", "NETWEAVER_TELEGRAM_CHAT": "chat"})
    @patch("netweaver.alerts.send_telegram")
    def test_send_alert_with_telegram(self, mock_telegram, tmp_path):
        """Test send_alert with Telegram configured."""
        mock_telegram.return_value = True
        
        with patch.object(alerts, "ALERTS_STATE", tmp_path / "alerts.json"):
            result = alerts.send_alert("test", "Title", "Message", cooldown=0)
            assert result is True
            mock_telegram.assert_called_once()
    
    def test_send_alert_respects_cooldown(self, tmp_path):
        """Test that send_alert respects cooldown."""
        state_file = tmp_path / "alerts.json"
        state_file.write_text(json.dumps({
            "last_sent": {"test_alert": time.time()},
            "suppressed": {},
        }))
        
        with patch.object(alerts, "ALERTS_STATE", state_file):
            result = alerts.send_alert("test_alert", "Title", "Message", cooldown=300)
            assert result is False


class TestAlertHelpers:
    """Test alert helper functions."""
    
    def test_alert_daemon_dead(self, tmp_path):
        """Test daemon dead alert."""
        with patch.object(alerts, "ALERTS_STATE", tmp_path / "alerts.json"):
            with patch.object(alerts, "send_alert") as mock_send:
                mock_send.return_value = True
                result = alerts.alert_daemon_dead(600.0)
                mock_send.assert_called_once()
                call_args = mock_send.call_args
                assert call_args[0][0] == "daemon_dead"
                assert call_args[1]["severity"] == "critical"
    
    def test_alert_circuit_breaker_tripped(self, tmp_path):
        """Test circuit breaker alert."""
        with patch.object(alerts, "ALERTS_STATE", tmp_path / "alerts.json"):
            with patch.object(alerts, "send_alert") as mock_send:
                mock_send.return_value = True
                result = alerts.alert_circuit_breaker_tripped(["daemon", "worker"])
                call_args = mock_send.call_args
                assert call_args[0][0] == "circuit_breaker"
                assert "daemon, worker" in call_args[0][2]
    
    def test_alert_tests_failing(self, tmp_path):
        """Test tests failing alert."""
        with patch.object(alerts, "ALERTS_STATE", tmp_path / "alerts.json"):
            with patch.object(alerts, "send_alert") as mock_send:
                mock_send.return_value = True
                result = alerts.alert_tests_failing(42)
                call_args = mock_send.call_args
                assert "42 tests failing" in call_args[0][2]
    
    def test_alert_stuck_task(self, tmp_path):
        """Test stuck task alert."""
        with patch.object(alerts, "ALERTS_STATE", tmp_path / "alerts.json"):
            with patch.object(alerts, "send_alert") as mock_send:
                mock_send.return_value = True
                result = alerts.alert_stuck_task("NW-123", 5)
                call_args = mock_send.call_args
                assert "NW-123" in call_args[0][0]
                assert "5 times" in call_args[0][2]
    
    def test_alert_plan_rejected(self, tmp_path):
        """Test plan rejected alert."""
        with patch.object(alerts, "ALERTS_STATE", tmp_path / "alerts.json"):
            with patch.object(alerts, "send_alert") as mock_send:
                mock_send.return_value = True
                result = alerts.alert_plan_rejected("NW-045", "scope too broad")
                call_args = mock_send.call_args
                assert "NW-045" in call_args[0][0]
                assert "scope too broad" in call_args[0][2]


class TestAlertCLI:
    """Test alert CLI interface."""
    
    def test_cli_status(self, tmp_path, capsys):
        """Test status command."""
        state_file = tmp_path / "alerts.json"
        state_file.write_text(json.dumps({
            "last_sent": {"test": time.time() - 100},
            "suppressed": {},
        }))
        
        with patch.object(alerts, "ALERTS_STATE", state_file):
            with patch("sys.argv", ["alerts.py", "status"]):
                alerts.main()
        
        captured = capsys.readouterr()
        assert "Alert State" in captured.out
        assert "test" in captured.out
