"""Tests for NetWeaver Dashboard."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Import dashboard functions
from netweaver import dashboard


class TestDashboardHelpers:
    """Test dashboard helper functions."""
    
    def test_get_daemon_status_no_file(self, tmp_path):
        """Test daemon status when heartbeat file missing."""
        with patch.object(dashboard, "TINI", tmp_path):
            status, msg = dashboard.get_daemon_status()
            assert status == "dead"
            assert "No heartbeat" in msg
    
    def test_get_daemon_status_stopped(self, tmp_path):
        """Test daemon status when heartbeat is 0."""
        hb_file = tmp_path / "daemon_heartbeat.txt"
        hb_file.write_text("0")
        
        with patch.object(dashboard, "TINI", tmp_path):
            status, msg = dashboard.get_daemon_status()
            assert status == "stopped"
            assert "stopped" in msg.lower()
    
    def test_get_daemon_status_alive(self, tmp_path):
        """Test daemon status when heartbeat is fresh."""
        hb_file = tmp_path / "daemon_heartbeat.txt"
        hb_file.write_text(str(time.time()))
        
        with patch.object(dashboard, "TINI", tmp_path):
            status, msg = dashboard.get_daemon_status()
            assert status == "alive"
            assert "Heartbeat" in msg
    
    def test_get_daemon_status_stale(self, tmp_path):
        """Test daemon status when heartbeat is old."""
        hb_file = tmp_path / "daemon_heartbeat.txt"
        hb_file.write_text(str(time.time() - 600))  # 10 min ago
        
        with patch.object(dashboard, "TINI", tmp_path):
            status, msg = dashboard.get_daemon_status()
            assert status == "stale"
    
    def test_get_circuit_breaker_no_file(self, tmp_path):
        """Test circuit breaker when file missing."""
        with patch.object(dashboard, "TINI", tmp_path):
            status, count, agents = dashboard.get_circuit_breaker()
            assert status == "clear"
            assert count == 0
    
    def test_get_circuit_breaker_clear(self, tmp_path):
        """Test circuit breaker when all clear."""
        cb_file = tmp_path / "circuit_breaker.json"
        cb_file.write_text(json.dumps({"daemon": {"consecutive_failures": 0}}))
        
        with patch.object(dashboard, "TINI", tmp_path):
            status, count, agents = dashboard.get_circuit_breaker()
            assert status == "clear"
            assert count == 0
    
    def test_get_circuit_breaker_tripped(self, tmp_path):
        """Test circuit breaker when tripped."""
        cb_file = tmp_path / "circuit_breaker.json"
        cb_file.write_text(json.dumps({
            "daemon": {"paused_until": time.time() + 600},
            "worker": {"paused_until": time.time() + 600},
        }))
        
        with patch.object(dashboard, "TINI", tmp_path):
            status, count, agents = dashboard.get_circuit_breaker()
            assert status == "tripped"
            assert count == 2
            assert "daemon" in agents
    
    def test_get_test_count_no_events(self, tmp_path):
        """Test test count when events file missing."""
        with patch.object(dashboard, "TINI", tmp_path):
            count, status = dashboard.get_test_count()
            assert count == 0
            assert status == "unknown"
    
    def test_get_test_count_passing(self, tmp_path):
        """Test test count when tests passing."""
        events_file = tmp_path / "events.jsonl"
        events_file.write_text(json.dumps({
            "type": "periodic_test_ok",
            "summary": "1446 passed in 7.23s",
        }) + "\n")
        
        with patch.object(dashboard, "TINI", tmp_path):
            count, status = dashboard.get_test_count()
            assert count == 1446
            assert status == "passing"
    
    def test_get_kanban_counts(self, tmp_path):
        """Test Kanban column counts."""
        netweaver_dir = tmp_path / "netweaver"
        company_dir = netweaver_dir / "company"
        company_dir.mkdir(parents=True)
        kanban_file = company_dir / "KANBAN.md"
        kanban_file.write_text("""# Kanban

## Ready
### Task 1
### Task 2

## In Progress
### Task 3

## Blocked

## Done
### Task 4
### Task 5
### Task 6
""")
        
        with patch.object(dashboard, "TINI", tmp_path), \
             patch.object(dashboard, "COMPANY", company_dir):
            counts = dashboard.get_kanban_counts()
            assert counts["ready"] == 2
            assert counts["in_progress"] == 1
            assert counts["blocked"] == 0
            assert counts["done"] == 3
    
    def test_get_queue_counts(self, tmp_path):
        """Test review queue counts."""
        company_dir = tmp_path / "netweaver" / "company"
        company_dir.mkdir(parents=True)
        queue_file = company_dir / "REVIEW_QUEUE.md"
        queue_file.write_text("""# Review Queue

Set **Status** to **APPROVED** or **BLOCKED**.

## Plan 1
**Status**: PENDING

## Plan 2
**Status**: APPROVED

## Plan 3
**Status**: APPROVED
""")
        
        with patch.object(dashboard, "TINI", tmp_path), \
             patch.object(dashboard, "COMPANY", company_dir):
            counts = dashboard.get_queue_counts()
            assert counts["pending"] == 1
            assert counts["approved"] == 2
            assert counts["blocked"] == 0
    
    def test_get_metrics_no_file(self, tmp_path):
        """Test metrics when file missing."""
        with patch.object(dashboard, "TINI", tmp_path):
            metrics = dashboard.get_metrics()
            assert metrics == {}
    
    def test_get_metrics_with_data(self, tmp_path):
        """Test metrics parsing."""
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps({
            "series": {
                "plan_gen_time_s": [
                    {"v": 0.1, "ts": "2026-01-01"},
                    {"v": 0.2, "ts": "2026-01-02"},
                ]
            }
        }))
        
        with patch.object(dashboard, "TINI", tmp_path):
            metrics = dashboard.get_metrics()
            assert "plan_gen_time_s" in metrics
            assert metrics["plan_gen_time_s"]["count"] == 2
            assert abs(metrics["plan_gen_time_s"]["avg"] - 0.15) < 0.01
    
    def test_get_recent_events(self, tmp_path):
        """Test recent events retrieval."""
        events_file = tmp_path / "events.jsonl"
        events = [
            {"type": "event1", "ts": "2026-01-01T00:00:00"},
            {"type": "event2", "ts": "2026-01-01T00:01:00"},
            {"type": "event3", "ts": "2026-01-01T00:02:00"},
        ]
        events_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        
        with patch.object(dashboard, "TINI", tmp_path):
            result = dashboard.get_recent_events(2)
            assert len(result) == 2
            assert result[0]["type"] == "event2"
            assert result[1]["type"] == "event3"


class TestDashboardLayout:
    """Test dashboard layout building."""
    
    def test_build_dashboard(self):
        """Test dashboard layout creation."""
        layout = dashboard.build_dashboard()
        assert layout is not None
        # Rich Layout uses __getitem__ for named access — just verify no crash
        # and that it has children
        assert hasattr(layout, "get")
        assert layout.get("header") is not None or layout.get("body") is not None


class TestDashboardIntegration:
    """Integration tests for dashboard."""
    
    def test_dashboard_with_real_data(self, tmp_path):
        """Test dashboard update with real data structure."""
        # Create minimal data structure
        (tmp_path / "daemon_heartbeat.txt").write_text(str(time.time()))
        (tmp_path / "circuit_breaker.json").write_text("{}")
        (tmp_path / "events.jsonl").write_text("")
        
        company_dir = tmp_path / "netweaver" / "company"
        company_dir.mkdir(parents=True)
        (company_dir / "KANBAN.md").write_text("# Kanban\n\n## Ready\n\n## Done\n")
        (company_dir / "REVIEW_QUEUE.md").write_text("# Queue\n")
        
        with patch.object(dashboard, "TINI", tmp_path):
            layout = dashboard.build_dashboard()
            # Should not raise
            dashboard.update_dashboard(layout)
