"""Product specification management with validation, schema, and versioning.

Defines the ProductSpec data model for tracking executor phases,
component status, and managing specification versions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ── phase constants ──────────────────────────────────────────────────

PHASE2_TITLE = "Phase 2: Live Executor Integration"
PHASE2_REFERENCE = "NW-016"
PHASE2_STATUS = "in_progress"

EXECUTOR_COMPONENT_STATUS = {
    "CloakBridge": "implemented",
    "Mode Switching": "implemented",
    "Phase Verification": "implemented",
}

# ── schema ───────────────────────────────────────────────────────────

COMPONENT_SCHEMA = {
    "type": "object",
    "required": ["name", "status"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "status": {"type": "string", "enum": ["planned", "in_progress", "implemented", "tested", "deployed"]},
        "description": {"type": "string"},
        "owner": {"type": "string"},
        "dependencies": {"type": "array", "items": {"type": "string"}},
    },
}

PHASE_SCHEMA = {
    "type": "object",
    "required": ["title", "reference", "status"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "reference": {"type": "string"},
        "status": {"type": "string", "enum": ["planned", "in_progress", "completed", "blocked"]},
        "description": {"type": "string"},
        "components": {"type": "array", "items": COMPONENT_SCHEMA},
    },
}


class ValidationError(Exception):
    """Raised when product spec validation fails."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class SpecComponent:
    """A component within a product specification phase."""

    def __init__(
        self,
        name: str,
        status: str = "planned",
        description: str = "",
        owner: str = "",
        dependencies: Optional[List[str]] = None,
    ) -> None:
        self.name = name
        self.status = status
        self.description = description
        self.owner = owner
        self.dependencies = dependencies or []

    def is_implemented(self) -> bool:
        return self.status in ("implemented", "tested", "deployed")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "description": self.description,
            "owner": self.owner,
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SpecComponent":
        return cls(
            name=d["name"],
            status=d.get("status", "planned"),
            description=d.get("description", ""),
            owner=d.get("owner", ""),
            dependencies=d.get("dependencies", []),
        )


class SpecPhase:
    """A phase within a product specification."""

    def __init__(
        self,
        title: str,
        reference: str = "",
        status: str = "planned",
        description: str = "",
        components: Optional[List[SpecComponent]] = None,
    ) -> None:
        self.title = title
        self.reference = reference
        self.status = status
        self.description = description
        self.components = components or []

    def add_component(self, component: SpecComponent) -> None:
        self.components.append(component)

    def completion_percentage(self) -> float:
        if not self.components:
            return 0.0
        implemented = sum(1 for c in self.components if c.is_implemented())
        return implemented / len(self.components)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "reference": self.reference,
            "status": self.status,
            "description": self.description,
            "components": [c.to_dict() for c in self.components],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SpecPhase":
        components = [SpecComponent.from_dict(c) for c in d.get("components", [])]
        return cls(
            title=d["title"],
            reference=d.get("reference", ""),
            status=d.get("status", "planned"),
            description=d.get("description", ""),
            components=components,
        )


class ProductSpec:
    """Product specification with validation, schema, and versioning."""

    def __init__(
        self,
        title: str = "",
        version: str = "1.0.0",
        phases: Optional[List[SpecPhase]] = None,
    ) -> None:
        self.title = title
        self.version = version
        self.phases = phases or []
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.updated_at = self.created_at
        self.version_log: List[Dict[str, Any]] = []

    def add_phase(self, phase: SpecPhase) -> None:
        self.phases.append(phase)

    def get_phase(self, title: str) -> Optional[SpecPhase]:
        for phase in self.phases:
            if phase.title == title:
                return phase
        return None

    def set_version(self, version: str, reason: str = "") -> None:
        """Set a new version with optional change reason."""
        old_version = self.version
        self.version = version
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.version_log.append({
            "old_version": old_version,
            "new_version": version,
            "reason": reason,
            "timestamp": self.updated_at,
        })

    def validate(self) -> List[str]:
        """Validate spec against schema.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors: List[str] = []
        if not self.title:
            errors.append("Spec title is required")
        if not self.version:
            errors.append("Spec version is required")
        for i, phase in enumerate(self.phases):
            if not phase.title:
                errors.append(f"Phase at index {i} has no title")
            if phase.status not in ("planned", "in_progress", "completed", "blocked"):
                errors.append(f"Phase '{phase.title}' has invalid status '{phase.status}'")
            for j, comp in enumerate(phase.components):
                if not comp.name:
                    errors.append(f"Component at phase {i}, index {j} has no name")
                if comp.status not in ("planned", "in_progress", "implemented", "tested", "deployed"):
                    errors.append(
                        f"Component '{comp.name}' has invalid status '{comp.status}'"
                    )
        return errors

    def is_valid(self) -> bool:
        return len(self.validate()) == 0

    def overall_completion(self) -> float:
        if not self.phases:
            return 0.0
        return sum(p.completion_percentage() for p in self.phases) / len(self.phases)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "version": self.version,
            "phases": [p.to_dict() for p in self.phases],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version_log": self.version_log,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProductSpec":
        phases = [SpecPhase.from_dict(p) for p in d.get("phases", [])]
        spec = cls(
            title=d.get("title", ""),
            version=d.get("version", "1.0.0"),
            phases=phases,
        )
        spec.created_at = d.get("created_at", spec.created_at)
        spec.updated_at = d.get("updated_at", spec.updated_at)
        spec.version_log = d.get("version_log", [])
        return spec

    def save(self, path: str) -> str:
        """Save product spec to JSON file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def load(cls, path: str) -> "ProductSpec":
        """Load product spec from JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)
