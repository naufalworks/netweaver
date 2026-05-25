#!/usr/bin/env python3
"""NetWeaver lightweight event watchdog.

Checks project state frequently and emits compact dispatch recommendations only when
state changes or an urgent condition exists. Cron no_agent can deliver stdout;
empty stdout = silent.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".tini/netweaver/watchdog_state.json"
WATCH = [
    ".tini/netweaver/company/KANBAN.md",
    ".tini/netweaver/HANDOFF.md",
    ".tini/netweaver/BLOCKERS.md",
    ".tini/netweaver/REVIEW.md",
    ".tini/netweaver/DEV_LOG.md",
]


def sha(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr).strip()


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            return {}
    return {}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2, sort_keys=True))


def kanban_counts(text: str) -> dict[str, int]:
    counts = {"ready": 0, "in_progress": 0, "review": 0, "blocked": 0, "done": 0}
    section = None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            section = name if name in counts else None
        elif section and line.startswith("### "):
            counts[section] += 1
    return counts


def duplicate_ids(text: str) -> list[str]:
    ids = []
    for line in text.splitlines():
        if line.startswith("### NW-"):
            ids.append(line.split()[1])
    return sorted({x for x in ids if ids.count(x) > 1})


def main() -> int:
    prev = load_state()
    hashes = {p: sha(ROOT / p) for p in WATCH}
    changed = [p for p, h in hashes.items() if prev.get("hashes", {}).get(p) != h]

    kanban_path = ROOT / ".tini/netweaver/company/KANBAN.md"
    kanban = kanban_path.read_text() if kanban_path.exists() else ""
    counts = kanban_counts(kanban)
    dups = duplicate_ids(kanban)

    test_code, test_out = run(["python", "-m", "unittest", "discover", "-s", "tests", "-q"])
    test_sig = hashlib.sha256(test_out.encode()).hexdigest()[:16]
    tests_changed = prev.get("test_code") != test_code or prev.get("test_sig") != test_sig

    urgent = []
    if test_code != 0:
        urgent.append("tests_failed")
    if dups:
        urgent.append("duplicate_task_ids:" + ",".join(dups))
    if counts.get("blocked", 0) > 0:
        urgent.append(f"blocked_tasks:{counts['blocked']}")
    if counts.get("review", 0) > 3:
        urgent.append(f"review_backlog:{counts['review']}")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_state({"hashes": hashes, "test_code": test_code, "test_sig": test_sig, "last": now})

    # Silent if nothing changed and no urgent condition.
    if not changed and not urgent and not tests_changed:
        return 0

    print("NetWeaver watchdog event")
    print(f"time: {now}")
    if changed:
        print("changed: " + ", ".join(changed))
    if urgent:
        print("urgent: " + ", ".join(urgent))
    print(f"kanban: {counts}")
    print(f"tests: {'PASS' if test_code == 0 else 'FAIL'}")
    if test_code != 0:
        print(test_out[-2000:])
    print("dispatch: run review/architect sooner if urgent; workers should prioritize cleanup before new feature work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
