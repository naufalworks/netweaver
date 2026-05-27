"""Unified Item + State Machine tracker, merging Kanban and Roadmap."""

import enum
from datetime import datetime
from typing import Any, Dict, List, Optional


class ItemState(enum.Enum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"

    @classmethod
    def valid_transitions(cls) -> Dict["ItemState", List["ItemState"]]:
        return {
            cls.BACKLOG: [cls.IN_PROGRESS],
            cls.IN_PROGRESS: [cls.REVIEW, cls.BACKLOG],
            cls.REVIEW: [cls.DONE, cls.IN_PROGRESS],
            cls.DONE: [cls.BACKLOG],
        }


class Item:
    """A work item with state machine."""

    def __init__(self, item_id: str, title: str, description: str = "",
                 state: Optional[ItemState] = None) -> None:
        self.id = item_id
        self.title = title
        self.description = description
        self.state = state or ItemState.BACKLOG
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at

    def transition_to(self, new_state: ItemState) -> None:
        """Move item to new_state if valid according to state machine."""
        valid_next = ItemState.valid_transitions().get(self.state, [])
        if new_state not in valid_next:
            raise ValueError(
                f"Cannot transition from {self.state.value} to {new_state.value}"
            )
        self.state = new_state
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Tracker:
    """Manages a collection of Items."""

    def __init__(self) -> None:
        self.items: Dict[str, Item] = {}

    def add_item(self, item: Item) -> None:
        if item.id in self.items:
            raise KeyError(f"Item with id '{item.id}' already exists")
        self.items[item.id] = item

    def get_item(self, item_id: str) -> Optional[Item]:
        return self.items.get(item_id)

    def move_item(self, item_id: str, new_state: ItemState) -> Item:
        item = self.items.get(item_id)
        if item is None:
            raise KeyError(f"Item '{item_id}' not found")
        item.transition_to(new_state)
        return item

    def get_items_by_state(self, state: ItemState) -> List[Item]:
        return [item for item in self.items.values() if item.state == state]

    def all_items(self) -> List[Item]:
        return list(self.items.values())
