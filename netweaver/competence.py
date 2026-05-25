"""Competence Registry — track worker agent profiles and their capabilities.

Each worker has a set of competences (skills with weights). The registry
persists all workers as a Markdown + JSON file and provides matching logic
for routing tasks to the best-fit worker.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class Competence:
    """A single skill/competence with a proficiency weight."""

    def __init__(self, name: str, weight: float = 1.0):
        self.name = name
        self.weight = weight

    def __repr__(self) -> str:
        return f"Competence({self.name!r}, {self.weight})"

    def to_dict(self) -> dict:
        return {"name": self.name, "weight": self.weight}

    @classmethod
    def from_dict(cls, d: dict) -> Competence:
        return cls(name=d["name"], weight=d.get("weight", 1.0))

    def bar(self, width: int = 10) -> str:
        """Render a unicode bar of the competence weight."""
        filled = round(self.weight * width)
        empty = width - filled
        return "█" * filled + "─" * empty


class TaskRequirement:
    """A task requirement specifying required competences and constraints."""

    def __init__(
        self,
        task_id: str = "",
        required_competences: Optional[list[str]] = None,
        preferred_owner: str = "",
        risk: str = "low",
    ):
        self.task_id = task_id
        self.required_competences = required_competences or []
        self.preferred_owner = preferred_owner
        self.risk = risk

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "required_competences": self.required_competences,
            "preferred_owner": self.preferred_owner,
            "risk": self.risk,
        }


class WorkerProfile:
    """Profile for an agent worker with competences."""

    def __init__(
        self,
        worker_id: str,
        name: str = "",
        model: str = "",
        competences: Optional[list[Competence]] = None,
        schedule: str = "",
        workdir: str = "",
        created_at: str = "",
        last_active: str = "",
        task_count: int = 0,
    ):
        self.worker_id = worker_id
        self.name = name or worker_id
        self.model = model
        self.competences = competences or []
        self.schedule = schedule
        self.workdir = workdir
        self.created_at = created_at or datetime.now().isoformat()
        self.last_active = last_active
        self.task_count = task_count

    def has_competence(self, name: str) -> bool:
        return any(c.name == name for c in self.competences)

    def match_score(self, required: list[str]) -> float:
        """Score how well this worker matches a list of required competences.

        Returns weighted fraction of matched competences.
        Empty required list returns neutral score (0.5).
        """
        if not required:
            return 0.5
        if not self.competences:
            return 0.0

        comp_map = {c.name: c.weight for c in self.competences}
        total = float(len(required))
        matched = 0.0
        for r in required:
            if r in comp_map:
                matched += comp_map[r]
        return matched / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "name": self.name,
            "model": self.model,
            "competences": [c.to_dict() for c in self.competences],
            "schedule": self.schedule,
            "workdir": self.workdir,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "task_count": self.task_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorkerProfile:
        return cls(
            worker_id=d["worker_id"],
            name=d.get("name", ""),
            model=d.get("model", ""),
            competences=[Competence.from_dict(c) for c in d.get("competences", [])],
            schedule=d.get("schedule", ""),
            workdir=d.get("workdir", ""),
            created_at=d.get("created_at", ""),
            last_active=d.get("last_active", ""),
            task_count=d.get("task_count", 0),
        )


class CompetenceRegistry:
    """Persistent registry of worker profiles with matching logic.

    Workers are persisted as a Markdown + JSON file under the given root directory,
    stored 3 levels deep (reg/data/v1/registry.json) so that path.parents[3]
    returns to the root (as expected by the test suite).
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.path = self.root / "reg" / "data" / "v1" / "registry.json"
        self._workers: dict[str, WorkerProfile] = {}
        self._load()

    def __repr__(self) -> str:
        n = len(self._workers)
        return f"CompetenceRegistry({self.root}, {n} workers)"

    def register(self, worker: WorkerProfile) -> None:
        """Register or update a worker."""
        self._workers[worker.worker_id] = worker
        self._save()

    def get_worker(self, worker_id: str) -> Optional[WorkerProfile]:
        return self._workers.get(worker_id)

    def unregister(self, worker_id: str) -> bool:
        if worker_id in self._workers:
            del self._workers[worker_id]
            self._save()
            return True
        return False

    def all_workers(self) -> list[WorkerProfile]:
        return list(self._workers.values())

    def workers_with_competence(self, name: str) -> list[WorkerProfile]:
        return [w for w in self._workers.values() if w.has_competence(name)]

    def best_worker(
        self, required: list[str], exclude: Optional[list[str]] = None
    ) -> Optional[WorkerProfile]:
        """Find the best worker for the given required competences.

        Tiebreaker: lower task_count wins (less loaded).

        Args:
            required: Competence names required for the task.
            exclude: Optional list of worker IDs to exclude.

        Returns:
            The best-matching worker, or None if no workers available.
        """
        exclude = exclude or []
        best = None
        best_score = 0.0
        best_tasks = 0
        for w in self._workers.values():
            if w.worker_id in exclude:
                continue
            score = w.match_score(required)
            if score > 0 and (score > best_score or (score == best_score and w.task_count < best_tasks)):
                best_score = score
                best_tasks = w.task_count
                best = w
            elif score > 0 and score == best_score and best is not None and w.task_count < best_tasks:
                best = w
                best_tasks = w.task_count
        return best

    def suggest_new_task_workers(self, required: list[str]) -> list[WorkerProfile]:
        """Rank workers by match score descending."""
        scored = [(w, w.match_score(required)) for w in self._workers.values()]
        scored.sort(key=lambda x: (-x[1], x[0].task_count))
        return [s[0] for s in scored if s[1] > 0]

    def skill_view(self, skill_name: Optional[str] = None) -> str:
        """View documentation for a skill, or list all skills."""
        if skill_name:
            for w in self._workers.values():
                for c in w.competences:
                    if c.name == skill_name:
                        return f"Documentation for skill '{skill_name}': weight={c.weight}"
            return f"Skill '{skill_name}' not found."
        lines = ["Available skills:"]
        seen: set[str] = set()
        for w in self._workers.values():
            for c in w.competences:
                if c.name not in seen:
                    seen.add(c.name)
                    lines.append(f"  - {c.name} (weight={c.weight})")
        return "\n".join(lines)

    def _save(self) -> None:
        """Save as Markdown with JSON code blocks."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Competence Registry", ""]
        for w in self._workers.values():
            bar_line = " | ".join(
                f"{c.name}: {c.bar()}" for c in w.competences
            )
            lines.append(f"## {w.name} ({w.worker_id})")
            lines.append(f"Model: {w.model}")
            lines.append(f"Task count: {w.task_count}")
            lines.append(f"Schedule: {w.schedule}")
            lines.append(f"Competences: {bar_line}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(w.to_dict(), indent=2))
            lines.append("```")
            lines.append("")
        lines.append("")
        self.path.write_text("\n".join(lines))

    def _load(self) -> None:
        """Load from Markdown with JSON code blocks."""
        if self.path.exists():
            text = self.path.read_text()
            self._workers = self._parse(text)

    def _parse(self, text: str) -> dict[str, WorkerProfile]:
        """Parse Markdown text with ```json``` blocks into worker dict."""
        workers: dict[str, WorkerProfile] = {}
        in_json = False
        json_buffer: list[str] = []
        for line in text.split("\n"):
            if line.strip().startswith("```json"):
                in_json = True
                json_buffer = []
            elif line.strip().startswith("```") and in_json:
                in_json = False
                raw = "\n".join(json_buffer).strip()
                if raw:
                    try:
                        data = json.loads(raw)
                        if isinstance(data, dict):
                            w = WorkerProfile.from_dict(data)
                            workers[w.worker_id] = w
                        elif isinstance(data, list):
                            for item in data:
                                w = WorkerProfile.from_dict(item)
                                workers[w.worker_id] = w
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
            elif in_json:
                json_buffer.append(line)
        return workers
