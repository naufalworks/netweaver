"""Sync ROADMAP.md and product_spec.md with kanban progress.

Usage:
    python scripts/sync_roadmap.py <kanban_state.json>

Assumes kanban_state.json has one of:
  - {"tasks": [{"id": "NW-102", "status": "done"}, ...]}
  - {"ready": [...], "done": [...], ...}  (columns with tasks)

move_ready_to_done(): moves outdated tasks from "ready" to "done" if their status=="done".
"""

import json
import re
from pathlib import Path

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

def update_roadmap(kanban_data: dict) -> int:
    """Update ROADMAP.md with statuses from kanban data. Returns number of changes."""
    items = parse_roadmap()
    lines = Path(ROADMAP).read_text().splitlines(keepends=True)
    changes = 0
    for idx, line in items:
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
                                lines[idx] = new_line
                                changes += 1
                        break
    if changes > 0:
        Path(ROADMAP).write_text("".join(lines))
    return changes

def move_ready_to_done(kanban_data: dict) -> int:
    """Move tasks from 'ready' column to 'done' column if their status is 'done'."""
    if "ready" not in kanban_data or "done" not in kanban_data:
        return 0
    ready = kanban_data["ready"]
    done = kanban_data["done"]
    moved = []
    remaining = []
    for task in ready:
        if task.get("status") == "done":
            moved.append(task)
            task["status"] = "done"
        else:
            remaining.append(task)
    if not moved:
        return 0
    kanban_data["ready"] = remaining
    kanban_data["done"] = done + moved
    all_tasks = []
    for col_key in ("todo", "in-progress", "ready", "done"):
        if col_key in kanban_data:
            all_tasks.extend(kanban_data[col_key])
    if all_tasks:
        kanban_data["tasks"] = all_tasks
    return len(moved)

def update_product_spec(kanban_data: dict) -> int:
    """Update product_spec.md with kanban statuses. Also detect phase completion."""
    if not PRODUCT_SPEC.is_file():
        return 0
    lines = Path(PRODUCT_SPEC).read_text().splitlines(keepends=True)
    changes = 0

    # Update task brackets
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

    # Phase completion detection
    phase_pattern = re.compile(r"^(#{2,3})\s+(Phase\s+\d+)", re.IGNORECASE)
    phase_indices = []
    for i, line in enumerate(lines):
        if phase_pattern.match(line.strip()):
            phase_indices.append(i)

    for idx, start in enumerate(phase_indices):
        end = len(lines)
        if idx + 1 < len(phase_indices):
            end = phase_indices[idx + 1]

        all_done = True
        has_items = False
        for j in range(start + 1, end):
            stripped = lines[j].strip()
            if stripped.startswith("- [") or stripped.startswith("* ["):
                has_items = True
                if not (stripped.startswith("- [x]") or stripped.startswith("* [x]")):
                    all_done = False
                    break
        if has_items and all_done:
            header = lines[start]
            if "(completed)" not in header:
                lines[start] = header.rstrip() + " (completed)\n"
                changes += 1

    if changes > 0:
        Path(PRODUCT_SPEC).write_text("".join(lines))
    return changes

def main():
    import sys
    if len(sys.argv) != 2:
        print("Usage: python scripts/sync_roadmap.py <kanban_state.json>")
        sys.exit(1)
    kanban_file = sys.argv[1]
    with open(kanban_file, "r") as f:
        data = json.load(f)
    moved = move_ready_to_done(data)
    if moved:
        print(f"Moved {moved} tasks from ready to done.")
        with open(kanban_file, "w") as f:
            json.dump(data, f, indent=2)
    changes_roadmap = update_roadmap(data)
    print(f"Updated ROADMAP.md: {changes_roadmap} changes made.")
    changes_product_spec = update_product_spec(data)
    print(f"Updated product_spec.md: {changes_product_spec} changes made.")

if __name__ == "__main__":
    main()
