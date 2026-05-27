"""Roadmap module using tracker.Item for unified item management."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from netweaver.tracker import Item, ItemState, Tracker


class Roadmap:
    """A roadmap that manages items with milestones using a Tracker."""

    def __init__(self) -> None:
        self.tracker = Tracker()
        self.milestones: Dict[str, List[str]] = {}  # milestone name -> item ids

    def create_roadmap_item(
        self, item_id: str, title: str, description: str = "",
        state: Optional[ItemState] = None, milestone: Optional[str] = None
    ) -> Item:
        """Create a roadmap item, optionally associated with a milestone."""
        item = Item(item_id, title, description, state)
        self.tracker.add_item(item)
        if milestone:
            self._add_to_milestone(milestone, item_id)
        return item

    def move_item(self, item_id: str, new_state: ItemState) -> Item:
        """Move an item to a new state via tracker."""
        return self.tracker.move_item(item_id, new_state)

    def get_item(self, item_id: str) -> Optional[Item]:
        return self.tracker.get_item(item_id)

    def get_items_by_milestone(self, milestone: str) -> List[Item]:
        """Get all items associated with a milestone."""
        item_ids = self.milestones.get(milestone, [])
        # Return items in order they were added
        return [self.tracker.get_item(id) for id in item_ids if self.tracker.get_item(id)]

    def get_all_items(self) -> List[Item]:
        return self.tracker.all_items()

    # Internal helpers
    def _add_to_milestone(self, milestone: str, item_id: str) -> None:
        if milestone not in self.milestones:
            self.milestones[milestone] = []
        self.milestones[milestone].append(item_id)

    def _remove_from_milestone(self, milestone: str, item_id: str) -> None:
        if milestone in self.milestones:
            if item_id in self.milestones[milestone]:
                self.milestones[milestone].remove(item_id)
