#!/usr/bin/env python3
"""Move completed tasks from Ready column to Done column in KANBAN.md.

Only rows containing "[x]" (checked checkbox) are considered completed
and moved. Additionally, specific task IDs (NW-A003, P2-002, P2-005)
are force-moved even if not yet checked (they get a [x] added).
Other rows remain in the Ready column.
"""

import sys
from pathlib import Path

KANBAN_PATH = Path(__file__).resolve().parent.parent / "KANBAN.md"

# Task IDs that should be moved to Done regardless of checkbox state
FORCED_TASK_IDS = {"NW-A003", "P2-002", "P2-005"}


def _force_check_row(row: str) -> str:
    """Ensure a row has a checked checkbox [x]; if missing, add it."""
    if "[x]" in row:
        return row
    if "[ ]" in row:
        # replace first unchecked checkbox with checked
        return row.replace("[ ]", "[x]", 1)
    # no checkbox at all: insert [x] at start of first cell after leading "|"
    parts = row.split("|", 2)
    if len(parts) >= 2:
        cell1 = parts[1].strip()
        if not cell1.startswith("["):
            parts[1] = " [x] " + cell1
    elif len(parts) == 1:
        # entire row is just text? unlikely, but be safe
        parts[0] = " [x] " + parts[0]
    return "|".join(parts)


def separate_section(sec_lines):
    """Return (prefix, data) for a section.
    Prefix: section header + table header + separator line.
    Data: all lines after separator.
    """
    sep_idx = None
    for i, line in enumerate(sec_lines):
        if line.startswith("|----"):
            sep_idx = i
            break
    if sep_idx is None:
        # fallback: first 3 lines form prefix, rest is data
        prefix = sec_lines[:3]
        data = sec_lines[3:]
    else:
        prefix = sec_lines[:sep_idx + 1]
        data = sec_lines[sep_idx + 1:]
    return prefix, data


def main():
    path = KANBAN_PATH
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    raw = path.read_text()
    lines = raw.splitlines(keepends=True)

    # Locate section headers
    section_names = []
    section_starts = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            section_names.append(line[3:].strip())
            section_starts.append(i)
    section_ends = section_starts[1:] + [len(lines)]

    # Build section info
    sections = []
    for name, start, end in zip(section_names, section_starts, section_ends):
        sections.append({"name": name, "lines": lines[start:end]})

    # Identify Ready and Done sections
    ready_idx = None
    done_idx = None
    for i, sec in enumerate(sections):
        if sec["name"] == "Ready":
            ready_idx = i
        elif sec["name"] == "Done":
            done_idx = i
    if ready_idx is None or done_idx is None:
        print("Error: Could not find Ready or Done section", file=sys.stderr)
        sys.exit(1)

    ready_prefix, ready_data = separate_section(sections[ready_idx]["lines"])
    done_prefix, done_data = separate_section(sections[done_idx]["lines"])

    # Extract actual data rows (lines that start with "| ")
    ready_rows = [line for line in ready_data if line.startswith("| ")]

    # Separate rows into completed, forced-completed, and remaining
    completed_rows = []
    other_rows = []
    for row in ready_rows:
        if "[x]" in row:
            completed_rows.append(row)
        elif any(tid in row for tid in FORCED_TASK_IDS):
            # force-mark as done and move
            row = _force_check_row(row)
            completed_rows.append(row)
        else:
            other_rows.append(row)

    # Keep non‑completed rows in the Ready section
    new_ready_data = [line for line in ready_data if not line.startswith("| ")] + other_rows
    new_done_data = done_data + completed_rows

    # Reconstruct section lines
    new_ready_lines = ready_prefix + new_ready_data
    new_done_lines = done_prefix + new_done_data

    # Build full file lines
    new_full_lines = []
    for sec in sections:
        if sec["name"] == "Ready":
            new_full_lines.extend(new_ready_lines)
        elif sec["name"] == "Done":
            new_full_lines.extend(new_done_lines)
        else:
            new_full_lines.extend(sec["lines"])

    path.write_text("".join(new_full_lines))
    print(f"Moved {len(completed_rows)} completed task(s) from Ready to Done.")


if __name__ == "__main__":
    main()
