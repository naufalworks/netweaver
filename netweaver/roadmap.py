"""Roadmap module using tracker.Item for unified item management.

Provides phase tracking, dependency resolution, and status queries
for roadmap items organized by milestones and phases.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from netweaver.tracker import Item, ItemState, QueryFilter, Tracker


class RoadmapPhase:
    """A phase within a roadmap with start/end dates and status."""

    def __init__(
        self,
        name: str,
        status: str = "planned",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        description: str = "",
    ) -> None:
        self.name = name
        self.status = status
        self.start_date = start_date
        self.end_date = end_date
        self.description = description
        self.item_ids: List[str] = []

    def add_item(self, item_id: str) -> None:
        if item_id not in self.item_ids:
            self.item_ids.append(item_id)

    def remove_item(self, item_id: str) -> None:
        if item_id in self.item_ids:
            self.item_ids.remove(item_id)

    def is_active(self) -> bool:
        return self.status == "in_progress"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "description": self.description,
            "item_ids": self.item_ids,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RoadmapPhase":
        phase = cls(
            name=d["name"],
            status=d.get("status", "planned"),
            start_date=d.get("start_date"),
            end_date=d.get("end_date"),
            description=d.get("description", ""),
        )
        phase.item_ids = d.get("item_ids", [])
        return phase


class Dependency:
    """A dependency between two roadmap items."""

    def __init__(self, source_id: str, target_id: str, dep_type: str = "blocks") -> None:
        self.source_id = source_id  # source depends ON target
        self.target_id = target_id
        self.dep_type = dep_type  # "blocks", "relates_to", "duplicates"

    def to_dict(self) -> Dict[str, str]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "dep_type": self.dep_type,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "Dependency":
        return cls(
            source_id=d["source_id"],
            target_id=d["target_id"],
            dep_type=d.get("dep_type", "blocks"),
        )


class Roadmap:
    """A roadmap that manages items, milestones, phases, and dependencies."""

    def __init__(self) -> None:
        self.tracker = Tracker()
        self.milestones: Dict[str, List[str]] = {}  # milestone name -> item ids
        self.phases: Dict[str, RoadmapPhase] = {}  # phase name -> phase
        self.dependencies: List[Dependency] = []

    # ── item management ──────────────────────────────────────────────

    def create_roadmap_item(
        self,
        item_id: str,
        title: str,
        description: str = "",
        state: Optional[str] = None,
        milestone: Optional[str] = None,
        phase: Optional[str] = None,
        tags: Optional[List[str]] = None,
        assignee: str = "",
        priority: int = 0,
    ) -> Item:
        """Create a roadmap item, optionally associated with a milestone/phase.

        Args:
            item_id: Unique item identifier.
            title: Item title.
            description: Item description.
            state: Initial state (defaults to BACKLOG).
            milestone: Optional milestone name.
            phase: Optional phase name.
            tags: Optional list of tags.
            assignee: Optional assignee name.
            priority: Priority level (higher = more important).

        Returns:
            The created Item.
        """
        item = Item(item_id, title, description, state,
                    tags=tags, assignee=assignee, priority=priority)
        self.tracker.add_item(item)
        if milestone:
            self._add_to_milestone(milestone, item_id)
        if phase:
            self._add_to_phase(phase, item_id)
        return item

    def update_roadmap_item(
        self,
        item_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> Item:
        """Update metadata on a roadmap item."""
        return self.tracker.update_item(item_id, title, description, tags, assignee, priority)

    def remove_roadmap_item(self, item_id: str) -> None:
        """Remove a roadmap item from tracker, milestones, and phases."""
        for milestone in self.milestones.values():
            if item_id in milestone:
                milestone.remove(item_id)
        for phase in self.phases.values():
            phase.remove_item(item_id)
        self.dependencies = [d for d in self.dependencies
                             if d.source_id != item_id and d.target_id != item_id]
        self.tracker.remove_item(item_id)

    def move_item(self, item_id: str, new_state: str) -> Item:
        """Move an item to a new state via tracker."""
        return self.tracker.move_item(item_id, new_state)

    def get_item(self, item_id: str) -> Optional[Item]:
        return self.tracker.get_item(item_id)

    def get_all_items(self) -> List[Item]:
        return self.tracker.all_items()

    # ── phase tracking ───────────────────────────────────────────────

    def add_phase(self, phase: RoadmapPhase) -> None:
        """Add a phase to the roadmap."""
        self.phases[phase.name] = phase

    def get_phase(self, name: str) -> Optional[RoadmapPhase]:
        return self.phases.get(name)

    def get_phase_status(self, name: str) -> Optional[str]:
        phase = self.phases.get(name)
        return phase.status if phase else None

    def set_phase_status(self, name: str, status: str) -> None:
        phase = self.phases.get(name)
        if phase:
            phase.status = status

    def get_items_by_phase(self, phase_name: str) -> List[Item]:
        phase = self.phases.get(phase_name)
        if not phase:
            return []
        return [item for item in self.tracker.all_items()
                if item.id in phase.item_ids]

    def _add_to_phase(self, phase_name: str, item_id: str) -> None:
        if phase_name not in self.phases:
            self.phases[phase_name] = RoadmapPhase(name=phase_name)
        self.phases[phase_name].add_item(item_id)

    # ── milestone management ─────────────────────────────────────────

    def get_items_by_milestone(self, milestone: str) -> List[Item]:
        """Get all items associated with a milestone."""
        item_ids = self.milestones.get(milestone, [])
        return [self.tracker.get_item(iid)
                for iid in item_ids
                if self.tracker.get_item(iid)]

    def _add_to_milestone(self, milestone: str, item_id: str) -> None:
        if milestone not in self.milestones:
            self.milestones[milestone] = []
        self.milestones[milestone].append(item_id)

    # ── dependency resolution ────────────────────────────────────────

    def add_dependency(self, source_id: str, target_id: str, dep_type: str = "blocks") -> None:
        """Add a dependency: source depends ON target.

        Args:
            source_id: Item that depends on the target.
            target_id: Item that the source depends on.
            dep_type: Type of dependency ("blocks", "relates_to", "duplicates").
        """
        self.dependencies.append(Dependency(source_id, target_id, dep_type))

    def remove_dependency(self, source_id: str, target_id: str) -> None:
        self.dependencies = [
            d for d in self.dependencies
            if not (d.source_id == source_id and d.target_id == target_id)
        ]

    def get_dependencies(self, item_id: str) -> List[Dependency]:
        """Get all dependencies where item_id is the source (things it depends on)."""
        return [d for d in self.dependencies if d.source_id == item_id]

    def get_dependents(self, item_id: str) -> List[Dependency]:
        """Get all dependencies where item_id is the target (things that depend on it)."""
        return [d for d in self.dependencies if d.target_id == item_id]

    def get_blocked_items(self) -> List[str]:
        """Get item IDs that are blocked by unresolved dependencies."""
        blocked: Set[str] = set()
        for dep in self.dependencies:
            if dep.dep_type == "blocks":
                target = self.tracker.get_item(dep.target_id)
                if target and target.state != ItemState.DONE:
                    blocked.add(dep.source_id)
        return list(blocked)

    def is_item_blocked(self, item_id: str) -> bool:
        """Check if an item is blocked by dependencies."""
        return item_id in self.get_blocked_items()

    def resolve_dependency_chain(self, item_id: str) -> List[Item]:
        """Get the dependency chain for an item (items it transitively depends on).

        Args:
            item_id: Item to resolve dependencies for.

        Returns:
            Ordered list of items this item depends on (direct then transitive).
        """
        resolved: List[Item] = []
        visited: Set[str] = set()

        def _resolve(current_id: str) -> None:
            if current_id in visited:
                return
            visited.add(current_id)
            for dep in self.get_dependencies(current_id):
                target = self.tracker.get_item(dep.target_id)
                if target and target.id not in visited:
                    _resolve(target.id)
                    if target not in resolved:
                        resolved.append(target)

        _resolve(item_id)
        return resolved

    # ── status queries ───────────────────────────────────────────────

    def query_items(
        self,
        state: Optional[str] = None,
        assignee: Optional[str] = None,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        phase: Optional[str] = None,
    ) -> List[Item]:
        """Query items by various criteria.

        Args:
            state: Filter by state.
            assignee: Filter by assignee.
            query: Text search query.
            tags: Filter by tags (any match).
            phase: Filter by phase.

        Returns:
            List of matching items.
        """
        items = self.tracker.query(QueryFilter(
            state=state,
            assignee=assignee,
            query=query,
            tags=tags,
        ))
        if phase:
            phase_obj = self.phases.get(phase)
            if phase_obj:
                items = [item for item in items if item.id in phase_obj.item_ids]
        return items

    def get_items_by_state(self, state: str) -> List[Item]:
        return self.tracker.query(QueryFilter(state=state))

    def get_items_by_assignee(self, assignee: str) -> List[Item]:
        return self.tracker.query(QueryFilter(assignee=assignee))

    def search(self, query: str) -> List[Item]:
        return self.tracker.query(QueryFilter(query=query))

    def get_phase_statistics(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for each phase.

        Returns:
            Dict mapping phase name to stats dict with item counts per state.
        """
        stats: Dict[str, Dict[str, Any]] = {}
        for phase_name, phase in self.phases.items():
            items = self.get_items_by_phase(phase_name)
            state_counts: Dict[str, int] = {}
            for item in items:
                state_counts[item.state] = state_counts.get(item.state, 0) + 1
            stats[phase_name] = {
                "status": phase.status,
                "total_items": len(items),
                "state_counts": state_counts,
            }
        return stats

    def summary(self) -> Dict[str, Any]:
        """Generate a summary of the roadmap state."""
        all_items = self.get_all_items()
        state_counts = {}
        for item in all_items:
            state_counts[item.state] = state_counts.get(item.state, 0) + 1
        return {
            "total_items": len(all_items),
            "milestones": len(self.milestones),
            "phases": len(self.phases),
            "dependencies": len(self.dependencies),
            "blocked_items": self.get_blocked_items(),
            "state_distribution": state_counts,
        }

    # ── persistence ──────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "milestones": self.milestones,
            "phases": {k: v.to_dict() for k, v in self.phases.items()},
            "dependencies": [d.to_dict() for d in self.dependencies],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any], tracker: Tracker) -> "Roadmap":
        roadmap = cls()
        roadmap.tracker = tracker
        roadmap.milestones = d.get("milestones", {})
        roadmap.phases = {
            k: RoadmapPhase.from_dict(v) for k, v in d.get("phases", {}).items()
        }
        roadmap.dependencies = [Dependency.from_dict(dep) for dep in d.get("dependencies", [])]
        return roadmap
