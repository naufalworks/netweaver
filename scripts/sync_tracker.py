"""Unified sync entry point for tracker (Kanban + Roadmap).

Reads kanban_state.json and updates ROADMAP.md and product_spec.md.
Integrates state machine transitions from netweaver/tracker.py.

Usage:
    python scripts/sync_tracker.py <kanban_state.json>
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from netweaver.tracker import ItemState

ROADMAP = Path(__file__).resolve().parent.parent / "ROADMAP.md"
PRODUCT_SPEC = Path(__file__).resolve().parent.parent / "product_spec.md"


def parse_roadmap() -> list[tuple[int, str]]:
    """Return list of (line_index, line_text) for checklist items."""
    items = []
    with open(ROADMAP, "r") as f:
        for i, line in enumerate(f):
            stripped = line.strip()
            if stripped.startswith("- [") or stripped.startswith("* ["):
                items.append((i, line))
    return items


def _update_checklist(lines: list[str], kanban_data: dict) -> int:
    """Update checklist brackets in a list of lines. Returns number of changes."""
    changes = 0
    for i, line in enumerate(lines):
        match = re.search(r"(NW-\d+)", line)
        if match:
            task_id = match.group(1)
            if "tasks" in kanban_data:
                for task in kanban_data["tasks"]:
                    if task.get("id") == task_id:
                        desired = "x" if task.get("status") == "done" else " "
                        start_idx = line.find("- [")
                        if start_idx == -1:
                            start_idx = line.find("* [")
                        if start_idx != -1:
                            new_line = line[:start_idx+3] + desired + line[start_idx+4:]
                            if new_line != line:
                                lines[i] = new_line
                                changes += 1
                        break
    return changes


def update_roadmap(kanban_data: dict) -> int:
    """Update ROADMAP.md with statuses from kanban data. Returns number of changes."""
    lines = Path(ROADMAP).read_text().splitlines(keepends=True)
    changes = _update_checklist(lines, kanban_data)
    if changes > 0:
        Path(ROADMAP).write_text("".join(lines))
    return changes


def _move_tasks_between_columns(kanban_data: dict, source: str, target: str, status_value: str) -> int:
    """Move tasks from `source` column to `target` column if their status matches `status_value`."""
    if source not in kanban_data or target not in kanban_data:
        return 0
    source_list = kanban_data[source]
    target_list = kanban_data[target]
    moved = []
    remaining = []
    for task in source_list:
        if task.get("status") == status_value:
            moved.append(task)
        else:
            remaining.append(task)
    if not moved:
        return 0
    kanban_data[source] = remaining
    kanban_data[target] = target_list + moved
    # Rebuild flat tasks list
    all_tasks = []
    for col_key in ("todo", "in-progress", "ready", "done"):
        if col_key in kanban_data:
            all_tasks.extend(kanban_data[col_key])
    if all_tasks:
        kanban_data["tasks"] = all_tasks
    return len(moved)


def move_ready_to_done(kanban_data: dict) -> int:
    """Move tasks from 'ready' column to 'done' column if their status is 'done'."""
    return _move_tasks_between_columns(kanban_data, "ready", "done", "done")


def update_product_spec(kanban_data: dict) -> int:
    """Update product_spec.md with kanban statuses. Also detect phase completion."""
    if not PRODUCT_SPEC.is_file():
        return 0
    lines = Path(PRODUCT_SPEC).read_text().splitlines(keepends=True)
    changes = _update_checklist(lines, kanban_data)
    if changes > 0:
        Path(PRODUCT_SPEC).write_text("".join(lines))
    return changes


def validate_states(kanban_data: dict) -> list[str]:
    """Check if all task statuses are valid ItemState values. Returns list of invalid IDs."""
    invalid = []
    valid_values = ItemState._VALID_STATES
    tasks = list(kanban_data.get("tasks", []))
    for col_key in ("todo", "in-progress", "ready", "done"):
        tasks.extend(kanban_data.get(col_key, []))
    for task in tasks:
        status = task.get("status")
        if status and status not in valid_values:
            invalid.append(task.get("id", "unknown"))
    return invalid


def sync_tracker(kanban_data: dict) -> dict:
    """Run all sync operations on the tracker data.

    Args:
        kanban_data: Dict with kanban state (tasks, columns, etc.)

    Returns:
        A summary dict with counts of changes for each step.
    """
    result = {}
    result["invalid_states"] = validate_states(kanban_data)
    result["ready_to_done_moved"] = move_ready_to_done(kanban_data)
    result["roadmap_changes"] = update_roadmap(kanban_data)
    result["product_spec_changes"] = update_product_spec(kanban_data)
    return result


def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python scripts/sync_tracker.py <kanban_state.json>")
        sys.exit(1)
    kanban_path = Path(sys.argv[1])
    if not kanban_path.is_file():
        print(f"File not found: {kanban_path}")
        sys.exit(1)
    with open(kanban_path, "r") as f:
        kanban_data = json.load(f)
    result = sync_tracker(kanban_data)
    print(json.dumps(result, indent=2))
    with open(kanban_path, "w") as f:
        json.dump(kanban_data, f, indent=2)
    print(f"Kanban state written to {kanban_path}")


if __name__ == "__main__":
    main()
