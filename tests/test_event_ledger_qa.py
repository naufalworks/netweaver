"""QA coverage expansion for event_ledger.py — filter, corruption, workspace, edge cases."""
import json
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

from netweaver.event_ledger import EventLedger


@pytest.fixture
def ledger():
    with tempfile.TemporaryDirectory() as tmp:
        yield EventLedger(tmp)


def _write_event(ledger, agent, etype, target, result, ts=None, workspace="", evidence=None):
    """Helper to write a raw event with a specific timestamp."""
    now = datetime.now(timezone.utc) if ts is None else ts
    date_str = now.strftime("%Y-%m-%d")
    event = {
        "id": "ev-0001",
        "agent": agent,
        "type": etype,
        "target": target,
        "result": result,
        "evidence": evidence or {},
        "ts": now.isoformat(timespec="seconds"),
        "workspace": workspace,
    }
    fpath = ledger.events_dir / f"{date_str}.jsonl"
    with open(fpath, "a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


# ── Workspace field ────────────────────────────────────────────────

def test_emit_with_workspace(ledger):
    eid = ledger.emit("agent", "task", "NW-001", "ok", workspace="/mydir")
    ev = ledger.recent(1)[0]
    assert ev["workspace"] == "/mydir"


def test_emit_default_workspace_empty(ledger):
    ledger.emit("agent", "task", "NW-001", "ok")
    ev = ledger.recent(1)[0]
    assert ev["workspace"] == ""


# ── Query: target filter (substring match) ─────────────────────────

def test_query_by_target_substring(ledger):
    ledger.emit("a", "task", "NW-001-login", "ok")
    ledger.emit("a", "task", "NW-002-search", "ok")
    results = ledger.query(target="NW-001")
    assert len(results) == 1
    assert "NW-001" in results[0]["target"]


def test_query_by_target_no_match(ledger):
    ledger.emit("a", "task", "NW-001", "ok")
    results = ledger.query(target="nonexistent")
    assert len(results) == 0


# ── Query: since/until time filters ────────────────────────────────

def test_query_since_filter(ledger):
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)
    old_ts = yesterday.isoformat(timespec="seconds")
    # Write an old event manually
    yday = yesterday.strftime("%Y-%m-%d")
    old_event = {
        "id": "ev-0001", "agent": "a", "type": "hb", "target": "old",
        "result": "ok", "evidence": {}, "ts": old_ts, "workspace": "",
    }
    (ledger.events_dir / f"{yday}.jsonl").write_text(
        json.dumps(old_event, sort_keys=True) + "\n"
    )
    # Write a new event normally
    ledger.emit("a", "hb", "new", "ok")

    cutoff = today.replace(hour=0, minute=0, second=0).isoformat(timespec="seconds")
    results = ledger.query(since=cutoff, limit=10)
    # The old event should be filtered out
    assert all(r["ts"] >= cutoff for r in results)


def test_query_until_filter(ledger):
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)
    old_ts = yesterday.replace(hour=12, minute=0, second=0).isoformat(timespec="seconds")
    yday = yesterday.strftime("%Y-%m-%d")
    old_event = {
        "id": "ev-0001", "agent": "a", "type": "hb", "target": "old",
        "result": "ok", "evidence": {}, "ts": old_ts, "workspace": "",
    }
    (ledger.events_dir / f"{yday}.jsonl").write_text(
        json.dumps(old_event, sort_keys=True) + "\n"
    )
    ledger.emit("a", "hb", "new", "ok")

    cutoff = yesterday.replace(hour=23, minute=59, second=59).isoformat(timespec="seconds")
    results = ledger.query(until=cutoff, limit=10)
    # Only the old event should appear
    assert all(r["ts"] <= cutoff for r in results)


# ── Corrupt JSONL handling ─────────────────────────────────────────

def test_query_skips_corrupt_lines(ledger):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fpath = ledger.events_dir / f"{today}.jsonl"
    # Write mixed valid and invalid lines
    fpath.write_text(
        "{invalid json}\n"
        + json.dumps({
            "id": "ev-0001", "agent": "a", "type": "hb", "target": "ok",
            "result": "ok", "evidence": {}, "ts": "2026-01-01T00:00:00", "workspace": "",
        }, sort_keys=True) + "\n"
        + "not json at all\n"
        + json.dumps({
            "id": "ev-0002", "agent": "a", "type": "task", "target": "NW-001",
            "result": "done", "evidence": {}, "ts": "2026-01-01T00:00:01", "workspace": "",
        }, sort_keys=True) + "\n"
    )
    results = ledger.query(limit=10)
    assert len(results) == 2


def test_count_skips_corrupt_lines(ledger):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fpath = ledger.events_dir / f"{today}.jsonl"
    fpath.write_text("corrupt\n" + json.dumps({
        "id": "ev-0001", "agent": "a", "type": "hb", "target": "ok",
        "result": "ok", "evidence": {}, "ts": "2026-01-01T00:00:00", "workspace": "",
    }, sort_keys=True) + "\n")
    assert ledger.count() == 1


def test_summary_skips_corrupt_lines(ledger):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fpath = ledger.events_dir / f"{today}.jsonl"
    fpath.write_text("corrupt\n" + json.dumps({
        "id": "ev-0001", "agent": "a", "type": "hb", "target": "ok",
        "result": "ok", "evidence": {}, "ts": "2026-01-01T00:00:00", "workspace": "",
    }, sort_keys=True) + "\n")
    s = ledger.summary()
    assert s["total_events"] == 1


# ── Empty edge cases ───────────────────────────────────────────────

def test_query_empty_ledger(ledger):
    assert ledger.query() == []


def test_recent_empty_ledger(ledger):
    assert ledger.recent() == []


def test_count_empty_ledger(ledger):
    assert ledger.count() == 0


def test_summary_empty_ledger(ledger):
    s = ledger.summary()
    assert s["total_events"] == 0
    assert s["unique_agents"] == 0
    assert s["errors"] == 0


# ── Summary error counting ─────────────────────────────────────────

def test_summary_counts_errors(ledger):
    ledger.emit("a", "task", "NW-001", "ok")
    ledger.emit("a", "task", "NW-002", "failed")
    ledger.emit("a", "task", "NW-003", "error")
    ledger.emit("a", "task", "NW-004", "ok")
    s = ledger.summary()
    assert s["errors"] == 2  # "failed" + "error"


# ── Event ID increment across same day ─────────────────────────────

def test_emit_id_increments_correctly_with_existing_file(ledger):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fpath = ledger.events_dir / f"{today}.jsonl"
    # Pre-populate with ev-0005
    fpath.write_text(json.dumps({
        "id": "ev-0005", "agent": "x", "type": "hb", "target": "none",
        "result": "ok", "evidence": {}, "ts": "2026-01-01T00:00:00", "workspace": "",
    }, sort_keys=True) + "\n")
    eid = ledger.emit("a", "hb", "none", "ok")
    assert eid == "ev-0006"


def test_emit_id_handles_malformed_ids(ledger):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fpath = ledger.events_dir / f"{today}.jsonl"
    # Pre-populate with malformed IDs
    fpath.write_text(
        json.dumps({"id": "bad-id", "agent": "x", "type": "hb", "target": "none",
                     "result": "ok", "evidence": {}, "ts": "2026-01-01T00:00:00", "workspace": ""}, sort_keys=True) + "\n"
        + json.dumps({"id": "ev-0003", "agent": "x", "type": "hb", "target": "none",
                       "result": "ok", "evidence": {}, "ts": "2026-01-01T00:00:01", "workspace": ""}, sort_keys=True) + "\n"
    )
    eid = ledger.emit("a", "hb", "none", "ok")
    assert eid == "ev-0004"


# ── Evidence field ─────────────────────────────────────────────────

def test_emit_default_evidence_empty_dict(ledger):
    ledger.emit("a", "task", "NW-001", "ok")
    ev = ledger.recent(1)[0]
    assert ev["evidence"] == {}


def test_emit_evidence_complex(ledger):
    complex_ev = {"files": ["a.py", "b.py"], "metrics": {"tests": 42, "loc": 500}, "nested": {"deep": True}}
    ledger.emit("a", "task", "NW-001", "ok", evidence=complex_ev)
    ev = ledger.recent(1)[0]
    assert ev["evidence"]["metrics"]["tests"] == 42
    assert ev["evidence"]["nested"]["deep"] is True


# ── Query combined filters ─────────────────────────────────────────

def test_query_multiple_filters(ledger):
    ledger.emit("a", "task", "NW-001", "ok")
    ledger.emit("a", "task", "NW-002", "failed")
    ledger.emit("b", "task", "NW-001", "ok")
    results = ledger.query(agent="a", result="ok")
    assert len(results) == 1
    assert results[0]["target"] == "NW-001"


def test_query_limit_zero(ledger):
    ledger.emit("a", "hb", "none", "ok")
    results = ledger.query(limit=0)
    assert len(results) == 0
