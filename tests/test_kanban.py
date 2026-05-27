import pytest
from pathlib import Path
import sys
import os

# Add scripts directory to import path for unit tests
HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import move_completed_tasks as mct

KANBAN_PATH = Path(__file__).parent.parent / "KANBAN.md"

# ---------------------------------------------------------------------------
# Existing integration tests (unchanged)
# ---------------------------------------------------------------------------

def test_moved_ids_not_in_ready():
    text = KANBAN_PATH.read_text()
    sections = text.split("## ")
    ready_section = None
    for section in sections:
        if section.startswith("Ready"):
            ready_section = section
            break
    assert ready_section is not None, "Ready section not found"
    for id_ in ["NW-A003", "P2-002", "P2-005"]:
        assert id_ not in ready_section, f"{id_} still found in Ready section"


def test_moved_ids_in_done():
    text = KANBAN_PATH.read_text()
    sections = text.split("## ")
    done_section = None
    for section in sections:
        if section.startswith("Done"):
            done_section = section
            break
    assert done_section is not None, "Done section not found"
    for id_ in ["NW-A003", "P2-002", "P2-005"]:
        assert id_ in done_section, f"{id_} not found in Done section"


def test_backlog_has_no_stale_items():
    """Backlog should not contain already-completed tasks."""
    # NW-301 was a placeholder that no longer exists — verify it's gone
    text = KANBAN_PATH.read_text()
    assert "NW-301" not in text, "Stale placeholder NW-301 should not be in root KANBAN"

# ---------------------------------------------------------------------------
# New unit tests for move logic
# ---------------------------------------------------------------------------

def test_separate_section_with_separator():
    """separate_section correctly splits on separator line."""
    lines = [
        "## Ready\n",
        "| ID | Task | Status |\n",
        "|----|------|--------|\n",
        "| T1 | Foo  | [ ]    |\n",
        "| T2 | Bar  | [x]    |\n",
    ]
    prefix, data = mct.separate_section(lines)
    assert len(prefix) == 3
    assert prefix[0] == "## Ready\n"
    assert prefix[2] == "|----|------|--------|\n"
    assert len(data) == 2
    assert "T1" in data[0]
    assert "T2" in data[1]


def test_separate_section_no_separator():
    """When no separator line, fallback uses first 3 lines as prefix."""
    lines = [
        "## Ready\n",
        "| ID | Task |\n",
        "| T1 | Foo  |\n",
        "| T2 | Bar  |\n",
    ]
    prefix, data = mct.separate_section(lines)
    assert len(prefix) == 3
    assert prefix[1] == "| ID | Task |\n"
    assert len(data) == 1  # only the last line is data
    assert "T2" in data[0]


def test_main_moves_completed_tasks(tmp_path, monkeypatch):
    """Integration test: main() moves [x] rows from Ready to Done."""
    # Create temporary KANBAN.md
    content = """# Kanban

## Ready
| ID | Task | Status |
|----|------|--------|
| T1 | Foo  | [ ]    |
| T2 | Bar  | [x]    |
| T3 | Baz  | [x]    |

## Done
| ID | Task | Status |
|----|------|--------|
| D1 | Old  | [x]    |
"""
    kanban = tmp_path / "KANBAN.md"
    kanban.write_text(content)

    # Redirect sys.exit to a no‑op so the test doesn't abort
    monkeypatch.setattr(sys, "exit", lambda x: None)
    # Replace the script's KANBAN_PATH with the temp file
    monkeypatch.setattr(mct, "KANBAN_PATH", kanban)

    # Run main logic
    mct.main()

    result = kanban.read_text()
    sections = result.split("## ")

    # Verify ready section
    ready_section = None
    for sec in sections:
        if sec.startswith("Ready"):
            ready_section = sec
            break
    assert ready_section is not None
    # T1 (unchecked) should remain in ready
    assert "T1" in ready_section, "T1 should remain in Ready"
    # T2 and T3 (checked) should be removed from ready
    assert "T2" not in ready_section, "T2 should be moved out of Ready"
    assert "T3" not in ready_section, "T3 should be moved out of Ready"

    # Verify done section
    done_section = None
    for sec in sections:
        if sec.startswith("Done"):
            done_section = sec
            break
    assert done_section is not None
    # Original done task should still be there
    assert "D1" in done_section, "D1 should remain in Done"
    # Moved tasks should appear in Done
    assert "T2" in done_section, "T2 should appear in Done"
    assert "T3" in done_section, "T3 should appear in Done"
    # Unchecked task should not be in Done
    assert "T1" not in done_section, "T1 should not be in Done"
