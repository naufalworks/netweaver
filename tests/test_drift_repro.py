"""Drift reproduction test: verifies sync_roadmap correctly applies kanban state to ROADMAP."""
import json
from pathlib import Path
import pytest
from scripts import sync_roadmap


def test_drift_repro(monkeypatch, tmp_path):
    """Simulate a scenario where ROADMAP and kanban_state are out of sync."""
    # Create a temporary ROADMAP with checklist items
    roadmap_file = tmp_path / "ROADMAP.md"
    roadmap_file.write_text(
        "- [ ] NW-101 Setup logging\n"
        "- [x] NW-102 Write tests\n"
        "- [ ] NW-103 Deploy app\n"
    )

    # Create kanban state where NW-101 is done, NW-102 is pending, NW-103 missing
    kanban_state = {
        "tasks": [
            {"id": "NW-101", "status": "done"},
            {"id": "NW-102", "status": "pending"},
            # NW-103 absent → state unchanged
        ]
    }

    # Patch sync_roadmap's ROADMAP path to our temporary file
    monkeypatch.setattr(sync_roadmap, 'ROADMAP', roadmap_file)

    # Execute sync
    changes = sync_roadmap.update_roadmap(kanban_state)

    # Assert results
    updated = roadmap_file.read_text()
    assert "[x] NW-101" in updated, "NW-101 should be marked done"
    assert "[ ] NW-102" in updated, "NW-102 should be pending (was done, reverted)"
    assert "[ ] NW-103" in updated, "NW-103 should remain pending (not in kanban)"
    assert changes == 2, "Two checkboxes changed (NW-101 pending→done, NW-102 done→pending)"
