"""Append-only event ledger — the source of truth for all agent actions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class EventLedger:
    """Append-only structured event store. Each day gets its own JSONL file.

    Replace: KANBAN/HANDOFF/DEV_LOG/REVIEW as coordination files.
    Events are the source of truth; derived views are generated from them.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.events_dir = self.root / ".tini" / "netweaver" / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)

    # ── write ────────────────────────────────────────────────────────

    def emit(
        self,
        agent: str,
        event_type: str,
        target: str,
        result: str,
        evidence: Optional[dict] = None,
        workspace: Optional[str] = None,
    ) -> str:
        """Append one event. Returns event_id."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        ts = now.isoformat(timespec="seconds")

        # Determine next event ID for today
        today_file = self.events_dir / f"{date_str}.jsonl"
        if today_file.exists():
            last_id = 0
            for line in today_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    eid = ev.get("id", "ev-0000")
                    num = int(eid.split("-")[-1])
                    last_id = max(last_id, num)
                except (json.JSONDecodeError, ValueError, IndexError):
                    pass
            event_id = f"ev-{last_id + 1:04d}"
        else:
            event_id = "ev-0001"

        event = {
            "id": event_id,
            "agent": agent,
            "type": event_type,
            "target": target,
            "result": result,
            "evidence": evidence or {},
            "ts": ts,
            "workspace": workspace or "",
        }

        with open(today_file, "a") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")

        return event_id

    # ── query ────────────────────────────────────────────────────────

    def query(
        self,
        agent: Optional[str] = None,
        event_type: Optional[str] = None,
        result: Optional[str] = None,
        target: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 50,
        reverse: bool = False,
    ) -> list[dict]:
        """Query events across all days. Returns newest-first by default."""
        events = []
        for f in sorted(self.events_dir.glob("*.jsonl"), reverse=True):
            for line in f.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if agent and ev.get("agent") != agent:
                    continue
                if event_type and ev.get("type") != event_type:
                    continue
                if result and ev.get("result") != result:
                    continue
                if target and target not in ev.get("target", ""):
                    continue
                if since and ev.get("ts", "") < since:
                    continue
                if until and ev.get("ts", "") > until:
                    continue
                events.append(ev)
            if len(events) >= limit:
                break

        events = events[:limit]
        if not reverse:
            events.reverse()
        return events

    def recent(self, limit: int = 20) -> list[dict]:
        """Most recent events, newest first."""
        return list(reversed(self.query(limit=limit)))

    def count(self, event_type: Optional[str] = None, result: Optional[str] = None) -> int:
        """Count matching events today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_file = self.events_dir / f"{today}.jsonl"
        if not today_file.exists():
            return 0
        count = 0
        for line in today_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and ev.get("type") != event_type:
                continue
            if result and ev.get("result") != result:
                continue
            count += 1
        return count

    def summary(self) -> dict:
        """High-level stats."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        types = {}
        agents = set()
        errors = 0
        for f in sorted(self.events_dir.glob("*.jsonl"), reverse=True):
            for line in f.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = ev.get("type", "unknown")
                types[t] = types.get(t, 0) + 1
                agents.add(ev.get("agent", ""))
                if ev.get("result") in ("failed", "error"):
                    errors += 1
        return {
            "total_events": sum(types.values()),
            "unique_agents": len(agents),
            "events_by_type": types,
            "today_events": self.count(),
            "errors": errors,
        }
