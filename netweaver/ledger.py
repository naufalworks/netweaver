"""NetWeaver Action Ledger — Append-only JSONL event log.

Durable ledger that records task events as JSONL lines under
.tini/netweaver/ledger.jsonl. Every agent action (state transition,
file change, test run, evidence attachment) is recorded as a ledger
event with timestamp, agent identity, and structured payload.

Design:
- Append-only: events are never deleted or modified
- JSONL format: one JSON object per line for streaming/audit
- EvidenceBundle integration: bundles are validated before append
- Missing-evidence rejection: bundles without evidence are rejected
"""

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from netweaver.evidence import (
    BundleStatus,
    EvidenceBundle,
    EvidenceReport,
)


class LedgerEventType(Enum):
    """Types of events recorded in the action ledger."""
    TASK_START = "task_start"
    TASK_STATE_CHANGE = "task_state_change"
    FILE_CHANGED = "file_changed"
    COMMAND_RUN = "command_run"
    TEST_RESULT = "test_result"
    EVIDENCE_BUNDLE = "evidence_bundle"
    HANDOFF = "handoff"
    BLOCKER = "blocker"
    REVIEW = "review"
    NOTE = "note"


@dataclass
class LedgerEvent:
    """A single event in the action ledger.

    Attributes:
        event_id: Unique identifier for this event.
        event_type: Type of event.
        timestamp: When the event occurred.
        agent: Agent role that produced this event.
        task_id: KANBAN task ID (e.g. "NW-010").
        payload: Structured data specific to the event type.
        metadata: Additional context (model, session, etc.).
    """
    event_id: str
    event_type: LedgerEventType
    timestamp: datetime
    agent: str
    task_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "agent": self.agent,
            "task_id": self.task_id,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict) -> "LedgerEvent":
        return cls(
            event_id=data["event_id"],
            event_type=LedgerEventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            agent=data["agent"],
            task_id=data["task_id"],
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_jsonl(cls, line: str) -> "LedgerEvent":
        """Deserialize from a JSONL line."""
        return cls.from_dict(json.loads(line.strip()))


class LedgerError(Exception):
    """Raised when a ledger operation fails."""
    pass


class MissingEvidenceError(LedgerError):
    """Raised when an EvidenceBundle fails validation on append."""
    pass


def _default_ledger_path() -> Path:
    """Return the default ledger file path."""
    return Path.home() / ".hermes" / ".tini" / "netweaver" / "ledger.jsonl"


class ActionLedger:
    """Append-only JSONL action ledger.

    Records task events with EvidenceBundle validation. Bundles with
    missing evidence are rejected at append time.

    Usage:
        ledger = ActionLedger()
        ledger.append_event(
            event_type=LedgerEventType.TASK_START,
            agent="WNAL Engineer",
            task_id="NW-010",
            payload={"scope": ["netweaver/ledger.py"]},
        )
        ledger.append_bundle(bundle)  # validates before append
    """

    def __init__(self, ledger_path: Optional[Path] = None):
        self.ledger_path = ledger_path or _default_ledger_path()
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Create ledger directory if it doesn't exist."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def _make_event_id(self) -> str:
        return f"evt-{uuid.uuid4().hex[:12]}"

    def append_event(
        self,
        event_type: LedgerEventType,
        agent: str,
        task_id: str,
        payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> LedgerEvent:
        """Append a single event to the ledger.

        Args:
            event_type: Type of event.
            agent: Agent role.
            task_id: KANBAN task ID.
            payload: Event-specific data.
            metadata: Additional context.
            event_id: Override auto-generated ID (for testing).
            timestamp: Override auto-generated timestamp.

        Returns:
            The created LedgerEvent.
        """
        event = LedgerEvent(
            event_id=event_id or self._make_event_id(),
            event_type=event_type,
            timestamp=timestamp or datetime.now(),
            agent=agent,
            task_id=task_id,
            payload=payload or {},
            metadata=metadata or {},
        )
        self._write_line(event.to_jsonl())
        return event

    def append_bundle(
        self,
        bundle: EvidenceBundle,
        validate: bool = True,
    ) -> LedgerEvent:
        """Append an EvidenceBundle to the ledger.

        Args:
            bundle: The EvidenceBundle to record.
            validate: If True, reject bundles with missing evidence.

        Returns:
            The created LedgerEvent.

        Raises:
            MissingEvidenceError: If validate=True and bundle has
                missing evidence.
        """
        if validate:
            is_valid = bundle.validate()
            if not is_valid:
                raise MissingEvidenceError(
                    f"Bundle {bundle.bundle_id} rejected: "
                    f"{'; '.join(bundle.rejection_reasons)}"
                )

        payload = bundle.to_dict()
        return self.append_event(
            event_type=LedgerEventType.EVIDENCE_BUNDLE,
            agent=bundle.agent,
            task_id=bundle.task_id,
            payload=payload,
            metadata={"validate": validate, "bundle_status": bundle.status.value},
        )

    def _write_line(self, line: str) -> None:
        """Append a single line to the ledger file."""
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_events(
        self,
        task_id: Optional[str] = None,
        event_type: Optional[LedgerEventType] = None,
        agent: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[LedgerEvent]:
        """Read events from the ledger with optional filtering.

        Args:
            task_id: Filter by task ID.
            event_type: Filter by event type.
            agent: Filter by agent role.
            limit: Maximum number of events to return.

        Returns:
            List of matching LedgerEvents, newest first.
        """
        if not self.ledger_path.exists():
            return []

        events: List[LedgerEvent] = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = LedgerEvent.from_jsonl(line)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

                if task_id and event.task_id != task_id:
                    continue
                if event_type and event.event_type != event_type:
                    continue
                if agent and event.agent != agent:
                    continue
                events.append(event)

        # Return newest first
        events.reverse()

        if limit:
            events = events[:limit]

        return events

    def event_count(self, task_id: Optional[str] = None) -> int:
        """Count events, optionally filtered by task_id."""
        return len(self.read_events(task_id=task_id))

    def clear(self) -> None:
        """Clear the ledger file (for testing only)."""
        if self.ledger_path.exists():
            self.ledger_path.write_text("")
