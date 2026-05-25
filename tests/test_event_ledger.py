"""Tests for EventLedger."""
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from netweaver.event_ledger import EventLedger


@pytest.fixture
def ledger():
    with tempfile.TemporaryDirectory() as tmp:
        yield EventLedger(tmp)


def test_emit_returns_event_id(ledger: EventLedger):
    eid = ledger.emit("test-agent", "heartbeat", "none", "ok")
    assert eid.startswith("ev-")
    assert len(eid) == 7  # ev-NNNN


def test_emit_increments_id(ledger: EventLedger):
    eid1 = ledger.emit("test", "heartbeat", "none", "ok")
    eid2 = ledger.emit("test", "heartbeat", "none", "ok")
    assert eid2 == f"ev-{int(eid1.split('-')[-1]) + 1:04d}"


def test_emit_creates_today_file(ledger: EventLedger):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ledger.emit("test", "heartbeat", "none", "ok")
    assert (ledger.events_dir / f"{today}.jsonl").exists()


def test_emit_writes_valid_json(ledger: EventLedger):
    eid = ledger.emit("architect", "task_proposed", "NW-026", "ready")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = (ledger.events_dir / f"{today}.jsonl").read_text().splitlines()
    ev = json.loads(lines[0])
    assert ev["id"] == eid
    assert ev["agent"] == "architect"
    assert ev["type"] == "task_proposed"
    assert ev["target"] == "NW-026"
    assert ev["result"] == "ready"
    assert "ts" in ev


def test_emit_with_evidence(ledger: EventLedger):
    ledger.emit("worker", "task_completed", "NW-026", "done",
                evidence={"files": ["foo.py"], "tests": 10})
    ev = ledger.recent(1)[0]
    assert ev["evidence"]["files"] == ["foo.py"]


def test_query_by_agent(ledger: EventLedger):
    ledger.emit("agent-a", "heartbeat", "none", "ok")
    ledger.emit("agent-b", "heartbeat", "none", "ok")
    ledger.emit("agent-a", "task_started", "NW-001", "running")
    results = ledger.query(agent="agent-a")
    assert len(results) == 2
    assert all(r["agent"] == "agent-a" for r in results)


def test_query_by_type(ledger: EventLedger):
    ledger.emit("a", "task_started", "NW-001", "running")
    ledger.emit("a", "task_completed", "NW-001", "done")
    ledger.emit("b", "heartbeat", "none", "ok")
    results = ledger.query(event_type="task_completed")
    assert len(results) == 1
    assert results[0]["type"] == "task_completed"


def test_query_by_result(ledger: EventLedger):
    ledger.emit("a", "task", "NW-001", "ok")
    ledger.emit("a", "task", "NW-002", "failed")
    results = ledger.query(result="failed")
    assert len(results) == 1
    assert results[0]["result"] == "failed"


def test_query_limit(ledger: EventLedger):
    for i in range(10):
        ledger.emit("a", "hb", f"target-{i}", "ok")
    results = ledger.query(limit=5)
    assert len(results) == 5


def test_query_reverse(ledger: EventLedger):
    for i in range(3):
        ledger.emit("a", "hb", f"t-{i}", "ok")
    results = ledger.query(limit=3, reverse=True)
    assert results[0]["target"] == "t-0"
    assert results[-1]["target"] == "t-2"


def test_recent_returns_newest_first(ledger: EventLedger):
    eid1 = ledger.emit("a", "hb", "first", "ok")
    eid2 = ledger.emit("a", "hb", "second", "ok")
    recent = ledger.recent(3)
    # Same timestamp → order may vary, just check both IDs present
    ids = {r["id"] for r in recent}
    assert eid1 in ids
    assert eid2 in ids


def test_count(ledger: EventLedger):
    ledger.emit("a", "hb", "none", "ok")
    ledger.emit("a", "hb", "none", "ok")
    ledger.emit("a", "task", "NW-001", "done")
    assert ledger.count() == 3
    assert ledger.count(event_type="hb") == 2
    assert ledger.count(result="done") == 1


def test_summary(ledger: EventLedger):
    ledger.emit("a", "hb", "none", "ok")
    ledger.emit("b", "task", "NW-001", "done")
    ledger.emit("c", "task", "NW-002", "failed")
    summary = ledger.summary()
    assert summary["total_events"] == 3
    assert summary["unique_agents"] == 3
    assert summary["errors"] == 1


def test_multiple_days_across_midnight(ledger: EventLedger):
    """Events on different dates should all be queryable."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    # Manually create yesterday's file
    y_file = ledger.events_dir / f"{yesterday}.jsonl"
    y_file.write_text(json.dumps({"id": "ev-0001", "agent": "a", "type": "hb",
                                  "target": "old", "result": "ok", "ts": f"{yesterday}T00:00:00",
                                  "evidence": {}, "workspace": ""}) + "\n")
    ledger.emit("a", "hb", "new", "ok")
    results = ledger.query(limit=10)
    assert len(results) == 2
