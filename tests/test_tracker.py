"""Tests for tracker module."""

import pytest
from netweaver.tracker import Item, ItemState, Tracker


class TestItem:
    def test_initial_state(self) -> None:
        item = Item("1", "test")
        assert item.state == ItemState.BACKLOG

    def test_valid_transition(self) -> None:
        item = Item("1", "test")
        item.transition_to(ItemState.IN_PROGRESS)
        assert item.state == ItemState.IN_PROGRESS

    def test_invalid_transition(self) -> None:
        item = Item("1", "test", state=ItemState.DONE)
        with pytest.raises(ValueError):
            item.transition_to(ItemState.IN_PROGRESS)

    def test_to_dict(self) -> None:
        item = Item("2", "title", "desc")
        d = item.to_dict()
        assert d["id"] == "2"
        assert d["state"] == "backlog"


class TestTracker:
    def test_add_and_get_item(self) -> None:
        tracker = Tracker()
        item = Item("1", "test")
        tracker.add_item(item)
        assert tracker.get_item("1") is item

    def test_add_duplicate_raises(self) -> None:
        tracker = Tracker()
        tracker.add_item(Item("1", "a"))
        with pytest.raises(KeyError):
            tracker.add_item(Item("1", "b"))

    def test_move_item(self) -> None:
        tracker = Tracker()
        item = Item("1", "test")
        tracker.add_item(item)
        tracker.move_item("1", ItemState.IN_PROGRESS)
        assert item.state == ItemState.IN_PROGRESS

    def test_move_non_existent(self) -> None:
        tracker = Tracker()
        with pytest.raises(KeyError):
            tracker.move_item("nonexistent", ItemState.IN_PROGRESS)

    def test_get_items_by_state(self) -> None:
        tracker = Tracker()
        tracker.add_item(Item("1", "a", state=ItemState.BACKLOG))
        tracker.add_item(Item("2", "b", state=ItemState.IN_PROGRESS))
        tracker.add_item(Item("3", "c", state=ItemState.BACKLOG))
        backlog_items = tracker.get_items_by_state(ItemState.BACKLOG)
        assert len(backlog_items) == 2
        assert {item.id for item in backlog_items} == {"1", "3"}
