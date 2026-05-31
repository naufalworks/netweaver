"""Tests for Roadmap."""
import pytest
from netweaver.tracker import ItemState
from netweaver.roadmap import Roadmap


class TestRoadmap:
    def setup_method(self):
        self.roadmap = Roadmap()

    def test_create_roadmap_item(self):
        item = self.roadmap.create_roadmap_item("1", "Feature X", "Description")
        assert item.id == "1"
        assert item.title == "Feature X"
        assert item.state == ItemState.BACKLOG

    def test_create_roadmap_item_with_milestone(self):
        item = self.roadmap.create_roadmap_item("2", "Feature Y", milestone="v2.0")
        assert item.id == "2"
        items = self.roadmap.get_items_by_milestone("v2.0")
        assert item in items

    def test_move_item(self):
        self.roadmap.create_roadmap_item("3", "Feature Z")
        item = self.roadmap.move_item("3", ItemState.IN_PROGRESS)
        assert item.state == ItemState.IN_PROGRESS

    def test_move_item_invalid(self):
        self.roadmap.create_roadmap_item("4", "Invalid", state=ItemState.DONE)
        with pytest.raises(ValueError):
            self.roadmap.move_item("4", ItemState.IN_PROGRESS)

    def test_get_item_not_found(self):
        assert self.roadmap.get_item("non_existent") is None

    def test_get_all_items(self):
        self.roadmap.create_roadmap_item("a", "Item A")
        self.roadmap.create_roadmap_item("b", "Item B")
        assert len(self.roadmap.get_all_items()) == 2

    def test_item_initial_state_default(self):
        item = self.roadmap.create_roadmap_item("5", "Default state")
        assert item.state == ItemState.BACKLOG

    def test_get_items_by_milestone_empty(self):
        items = self.roadmap.get_items_by_milestone("nonexistent")
        assert items == []

    def test_item_transition_closure(self):
        self.roadmap.create_roadmap_item("6", "Closure test")
        self.roadmap.move_item("6", ItemState.IN_PROGRESS)
        self.roadmap.move_item("6", ItemState.REVIEW)
        self.roadmap.move_item("6", ItemState.DONE)
        item = self.roadmap.get_item("6")
        assert item.state == ItemState.DONE
