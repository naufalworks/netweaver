"""Tests for scripts/sync_tracker."""
import json
import pytest
from pathlib import Path


@pytest.fixture
def kanban_data_tasks():
    return {
        "tasks": [
            {"id": "NW-101", "status": "done"},
            {"id": "NW-102", "status": "in_progress"},
        ]
    }


@pytest.fixture
def kanban_data_columns():
    return {
        "ready": [
            {"id": "NW-101", "status": "done"},
            {"id": "NW-102", "status": "in_progress"},
        ],
        "done": [],
        "todo": [],
        "in-progress": [],
    }


@pytest.fixture
def roadmap_lines():
    return [
        "# Roadmap\n",
        "- [ ] NW-101 Task A\n",
        "- [ ] NW-102 Task B\n",
    ]


@pytest.fixture
def product_spec_lines():
    return [
        "# Product Spec\n",
        "- [ ] NW-101 Task A\n",
        "- [ ] NW-102 Task B\n",
    ]


def test_update_roadmap(tmp_path, kanban_data_tasks, roadmap_lines):
    import scripts.sync_tracker as st

    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("".join(roadmap_lines))
    st.ROADMAP = roadmap

    changes = st.update_roadmap(kanban_data_tasks)
    assert changes == 1

    content = roadmap.read_text()
    assert "- [x] NW-101 Task A" in content
    assert "- [ ] NW-102 Task B" in content


def test_move_ready_to_done(kanban_data_columns):
    import scripts.sync_tracker as st

    data = kanban_data_columns.copy()
    moved = st.move_ready_to_done(data)
    assert moved == 1
    assert len(data["ready"]) == 1
    assert data["ready"][0]["id"] == "NW-102"
    assert len(data["done"]) == 1
    assert data["done"][0]["id"] == "NW-101"


def test_update_product_spec(tmp_path, kanban_data_tasks, product_spec_lines):
    import scripts.sync_tracker as st

    spec = tmp_path / "product_spec.md"
    spec.write_text("".join(product_spec_lines))
    st.PRODUCT_SPEC = spec

    changes = st.update_product_spec(kanban_data_tasks)
    assert changes == 1

    content = spec.read_text()
    assert "- [x] NW-101 Task A" in content
    assert "- [ ] NW-102 Task B" in content


def test_sync_tracker(tmp_path, kanban_data_columns, roadmap_lines, product_spec_lines):
    import scripts.sync_tracker as st

    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("".join(roadmap_lines))
    st.ROADMAP = roadmap

    spec = tmp_path / "product_spec.md"
    spec.write_text("".join(product_spec_lines))
    st.PRODUCT_SPEC = spec

    result = st.sync_tracker(kanban_data_columns)
    assert result["ready_to_done_moved"] == 1
    assert result["roadmap_changes"] == 1
    assert result["product_spec_changes"] == 1
