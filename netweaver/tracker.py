"""Unified Item + State Machine tracker, merging Kanban and Roadmap.

Provides Item state machines with event tracking, query interface,
and JSON persistence for work items.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class ItemState:
    """Item state constants using string values for serialization simplicity."""

    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"

    _VALID_STATES = {BACKLOG, IN_PROGRESS, REVIEW, DONE}

    _VALID_TRANSITIONS: Dict[str, List[str]] = {
        BACKLOG: [IN_PROGRESS],
        IN_PROGRESS: [REVIEW, BACKLOG],
        REVIEW: [DONE, IN_PROGRESS],
        DONE: [BACKLOG],
    }

    @classmethod
    def is_valid(cls, state: str) -> bool:
        """Check if state string is a valid ItemState."""
        return state in cls._VALID_STATES

    @classmethod
    def valid_transitions(cls, state: str) -> List[str]:
        """Get valid next states from current state."""
        return cls._VALID_TRANSITIONS.get(state, [])

    @classmethod
    def can_transition(cls, current: str, target: str) -> bool:
        """Check if a transition from current to target is valid."""
        return target in cls.valid_transitions(current)


class TrackerEvent:
    """An event recorded during tracker operations."""

    def __init__(
        self,
        event_type: str,
        item_id: str,
        data: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        self.event_type = event_type
        self.item_id = item_id
        self.data = data or {}
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "item_id": self.item_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrackerEvent":
        return cls(
            event_type=d["event_type"],
            item_id=d.get("item_id", ""),
            data=d.get("data"),
            timestamp=d.get("timestamp"),
        )


class Item:
    """A work item with state machine."""

    def __init__(
        self,
        item_id: str,
        title: str,
        description: str = "",
        state: Optional[str] = None,
        tags: Optional[List[str]] = None,
        assignee: str = "",
        priority: int = 0,
    ) -> None:
        if not item_id:
            raise ValueError("item_id must not be empty")
        if not title:
            raise ValueError("title must not be empty")
        self.id = item_id
        self.title = title
        self.description = description
        self.state = state if state and ItemState.is_valid(state) else ItemState.BACKLOG
        self.tags = tags or []
        self.assignee = assignee
        self.priority = priority
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.updated_at = self.created_at

    def transition_to(self, new_state: str) -> None:
        """Move item to new_state if valid according to state machine.

        Args:
            new_state: Target state string.

        Raises:
            ValueError: If transition is not valid.
        """
        if not ItemState.is_valid(new_state):
            raise ValueError(f"Invalid state: {new_state}")
        if not ItemState.can_transition(self.state, new_state):
            raise ValueError(
                f"Cannot transition from {self.state} to {new_state}"
            )
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def matches_query(self, query: str) -> bool:
        """Check if item matches a text query string.

        Searches title, description, tags, and assignee.
        Case-insensitive substring matching.
        """
        query_lower = query.lower()
        return (
            query_lower in self.title.lower()
            or query_lower in self.description.lower()
            or any(query_lower in tag.lower() for tag in self.tags)
            or query_lower in self.assignee.lower()
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "state": self.state,
            "tags": self.tags,
            "assignee": self.assignee,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Item":
        return cls(
            item_id=d["id"],
            title=d["title"],
            description=d.get("description", ""),
            state=d.get("state"),
            tags=d.get("tags", []),
            assignee=d.get("assignee", ""),
            priority=d.get("priority", 0),
        )


class QueryFilter:
    """Filter for querying items in a Tracker."""

    def __init__(
        self,
        state: Optional[str] = None,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        min_priority: Optional[int] = None,
        max_priority: Optional[int] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> None:
        self.state = state
        self.query = query
        self.tags = tags
        self.assignee = assignee
        self.min_priority = min_priority
        self.max_priority = max_priority
        self.created_after = created_after
        self.created_before = created_before

    def matches(self, item: Item) -> bool:
        """Check if an item matches all active filter criteria."""
        if self.state and item.state != self.state:
            return False
        if self.query and not item.matches_query(self.query):
            return False
        if self.tags and not any(tag in item.tags for tag in self.tags):
            return False
        if self.assignee and item.assignee != self.assignee:
            return False
        if self.min_priority is not None and item.priority < self.min_priority:
            return False
        if self.max_priority is not None and item.priority > self.max_priority:
            return False
        if self.created_after and item.created_at < self.created_after:
            return False
        if self.created_before and item.created_at > self.created_before:
            return False
        return True


class Tracker:
    """Manages a collection of Items with event tracking and persistence."""

    def __init__(self, storage_path: Optional[str] = None) -> None:
        self.items: Dict[str, Item] = {}
        self.events: List[TrackerEvent] = []
        self.storage_path = storage_path

    # ── item CRUD ────────────────────────────────────────────────────

    def add_item(self, item: Item) -> Item:
        """Add an item to the tracker.

        Args:
            item: Item to add.

        Returns:
            The added item.

        Raises:
            KeyError: If item_id already exists.
        """
        if item.id in self.items:
            raise KeyError(f"Item with id '{item.id}' already exists")
        self.items[item.id] = item
        self._record_event("item_added", item.id, {"title": item.title})
        return item

    def get_item(self, item_id: str) -> Optional[Item]:
        return self.items.get(item_id)

    def update_item(
        self,
        item_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> Item:
        """Update item metadata fields.

        Args:
            item_id: ID of the item to update.
            title: New title (None = no change).
            description: New description (None = no change).
            tags: New tags list (None = no change).
            assignee: New assignee (None = no change).
            priority: New priority (None = no change).

        Returns:
            The updated item.

        Raises:
            KeyError: If item not found.
        """
        item = self.items.get(item_id)
        if item is None:
            raise KeyError(f"Item '{item_id}' not found")
        changes: Dict[str, Any] = {}
        if title is not None:
            item.title = title
            changes["title"] = title
        if description is not None:
            item.description = description
            changes["description"] = description
        if tags is not None:
            item.tags = tags
            changes["tags"] = tags
        if assignee is not None:
            item.assignee = assignee
            changes["assignee"] = assignee
        if priority is not None:
            item.priority = priority
            changes["priority"] = priority
        if changes:
            item.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._record_event("item_updated", item_id, changes)
        return item

    def remove_item(self, item_id: str) -> None:
        """Remove an item from the tracker.

        Args:
            item_id: ID of the item to remove.

        Raises:
            KeyError: If item not found.
        """
        if item_id not in self.items:
            raise KeyError(f"Item '{item_id}' not found")
        del self.items[item_id]
        self._record_event("item_removed", item_id)

    # ── state transitions ────────────────────────────────────────────

    def move_item(self, item_id: str, new_state: str) -> Item:
        """Move an item to a new state.

        Args:
            item_id: ID of the item to move.
            new_state: Target state string.

        Returns:
            The moved item.

        Raises:
            KeyError: If item not found.
            ValueError: If transition is invalid.
        """
        item = self.items.get(item_id)
        if item is None:
            raise KeyError(f"Item '{item_id}' not found")
        old_state = item.state
        item.transition_to(new_state)
        self._record_event(
            "item_transitioned", item_id,
            {"from": old_state, "to": new_state},
        )
        return item

    # ── query interface ──────────────────────────────────────────────

    def query(self, filter_obj: QueryFilter) -> List[Item]:
        """Query items using a QueryFilter.

        Args:
            filter_obj: QueryFilter with criteria.

        Returns:
            List of matching items.
        """
        return [item for item in self.items.values() if filter_obj.matches(item)]

    def get_items_by_state(self, state: str) -> List[Item]:
        return self.query(QueryFilter(state=state))

    def get_items_by_assignee(self, assignee: str) -> List[Item]:
        return self.query(QueryFilter(assignee=assignee))

    def search(self, query: str) -> List[Item]:
        """Text search across all items.

        Args:
            query: Text to search for in titles, descriptions, tags, assignees.

        Returns:
            List of matching items.
        """
        return self.query(QueryFilter(query=query))

    def all_items(self) -> List[Item]:
        return list(self.items.values())

    def item_count(self) -> int:
        return len(self.items)

    # ── event tracking ───────────────────────────────────────────────

    def _record_event(
        self, event_type: str, item_id: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        event = TrackerEvent(event_type, item_id, data)
        self.events.append(event)

    def get_events(
        self,
        event_type: Optional[str] = None,
        item_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[TrackerEvent]:
        """Query events with optional filtering.

        Args:
            event_type: Filter by event type.
            item_id: Filter by item ID.
            limit: Maximum events to return (most recent first).

        Returns:
            List of matching TrackerEvent objects.
        """
        result = self.events
        if event_type:
            result = [e for e in result if e.event_type == event_type]
        if item_id:
            result = [e for e in result if e.item_id == item_id]
        return result[-limit:]

    def clear_events(self) -> None:
        """Clear all recorded events."""
        self.events.clear()

    # ── persistence ──────────────────────────────────────────────────

    def save(self, path: Optional[str] = None) -> str:
        """Save tracker state to a JSON file.

        Args:
            path: File path. Falls back to storage_path.

        Returns:
            The path where data was saved.
        """
        save_path = path or self.storage_path
        if not save_path:
            raise ValueError("No save path specified")
        data = {
            "items": [item.to_dict() for item in self.items.values()],
            "events": [event.to_dict() for event in self.events],
        }
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w") as f:
            json.dump(data, f, indent=2)
        return save_path

    @classmethod
    def load(cls, path: str) -> "Tracker":
        """Load tracker state from a JSON file.

        Args:
            path: File path to load from.

        Returns:
            Tracker instance with restored state.

        Raises:
            FileNotFoundError: If path does not exist.
            json.JSONDecodeError: If file is invalid JSON.
        """
        tracker = cls(storage_path=path)
        with open(path) as f:
            data = json.load(f)
        for item_dict in data.get("items", []):
            item = Item.from_dict(item_dict)
            tracker.items[item.id] = item
        for event_dict in data.get("events", []):
            tracker.events.append(TrackerEvent.from_dict(event_dict))
        return tracker
