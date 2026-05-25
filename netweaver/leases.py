"""File Lease System — Coordinated file access for multi-agent NetWeaver swarm.

Agents claim scoped files with TTL metadata so concurrent workers don't
clobber each other's edits. Leases are stored as JSON in the project's
.tini/netweaver/ directory.

Key design:
- FileLease: agent_id → scoped file paths with TTL and metadata
- LeaseManager: acquire/release/renew leases, conflict detection,
  expired lease reclamation
- No external deps; stdlib only (dataclasses, json, time, uuid)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
import json
import os
import time
import uuid


@dataclass
class FileLease:
    """A lease granting an agent exclusive access to scoped file paths.

    Attributes:
        lease_id: Unique lease identifier.
        agent_id: The agent or role holding the lease.
        file_paths: Set of file paths this lease covers (globs not supported).
        acquired_at: ISO-8601 timestamp when lease was acquired.
        ttl_seconds: Time-to-live in seconds. Lease expires after this.
        task_id: Optional KANBAN task ID this lease is associated with.
        metadata: Optional extra key-value pairs.
    """

    lease_id: str
    agent_id: str
    file_paths: Set[str]
    acquired_at: str
    ttl_seconds: float
    task_id: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Check if lease has exceeded its TTL."""
        if now is None:
            now = time.time()
        acquired_ts = datetime.fromisoformat(self.acquired_at).timestamp()
        return (now - acquired_ts) > self.ttl_seconds

    def remaining_seconds(self, now: Optional[float] = None) -> float:
        """Remaining time before lease expires."""
        if now is None:
            now = time.time()
        acquired_ts = datetime.fromisoformat(self.acquired_at).timestamp()
        elapsed = now - acquired_ts
        return max(0.0, self.ttl_seconds - elapsed)

    def covers_path(self, path: str) -> bool:
        """Check if a specific file path is within this lease's scope."""
        return path in self.file_paths

    def to_dict(self) -> dict:
        """Serialize to dict (file_paths sorted for determinism)."""
        return {
            "lease_id": self.lease_id,
            "agent_id": self.agent_id,
            "file_paths": sorted(self.file_paths),
            "acquired_at": self.acquired_at,
            "ttl_seconds": self.ttl_seconds,
            "task_id": self.task_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileLease":
        """Deserialize from dict."""
        paths = data.get("file_paths", [])
        if isinstance(paths, str):
            paths = [paths]
        return cls(
            lease_id=data["lease_id"],
            agent_id=data["agent_id"],
            file_paths=set(paths),
            acquired_at=data["acquired_at"],
            ttl_seconds=float(data["ttl_seconds"]),
            task_id=data.get("task_id"),
            metadata=data.get("metadata", {}),
        )


class LeaseConflictError(Exception):
    """Raised when a lease cannot be acquired due to a conflict."""

    def __init__(self, conflicting_leases: List[FileLease], requested_paths: Set[str]):
        self.conflicting_leases = conflicting_leases
        self.requested_paths = requested_paths
        agents = [l.agent_id for l in conflicting_leases]
        paths = sorted(requested_paths & set().union(*(l.file_paths for l in conflicting_leases)))
        super().__init__(
            f"Lease conflict: paths {paths} already held by {agents}"
        )


class LeaseNotFoundError(Exception):
    """Raised when a lease operation targets a non-existent lease."""
    pass


class LeaseExpiredError(Exception):
    """Raised when trying to operate on an expired lease."""
    pass


def _now_iso() -> str:
    """Current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


class LeaseManager:
    """Manages file leases for multi-agent coordination.

    Thread safety: NOT thread-safe. Intended for single-process cron jobs
    where agents serialize through a shared JSON file.

    Attributes:
        leases: Dict of lease_id → FileLease.
        store_path: Optional path to persist leases to JSON file.
    """

    def __init__(self, store_path: Optional[str] = None):
        self.leases: Dict[str, FileLease] = {}
        self.store_path = store_path
        if store_path and os.path.exists(store_path):
            self._load()

    # ── Core operations ──

    def acquire(
        self,
        agent_id: str,
        file_paths: Set[str],
        ttl_seconds: float = 300.0,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> FileLease:
        """Acquire a lease on file paths.

        Reclaims any expired conflicting leases before checking.

        Args:
            agent_id: The agent or role requesting the lease.
            file_paths: Set of file paths to claim.
            ttl_seconds: Time-to-live in seconds (default 5 minutes).
            task_id: Optional KANBAN task ID.
            metadata: Optional extra metadata.

        Returns:
            The acquired FileLease.

        Raises:
            LeaseConflictError: If any path is held by a non-expired lease
                owned by a different agent.
        """
        # Reclaim expired leases first
        self._reclaim_expired()

        # Check for conflicts with active leases
        conflicts = self._find_conflicts(agent_id, file_paths)
        if conflicts:
            raise LeaseConflictError(conflicts, file_paths)

        lease = FileLease(
            lease_id=uuid.uuid4().hex[:16],
            agent_id=agent_id,
            file_paths=set(file_paths),
            acquired_at=_now_iso(),
            ttl_seconds=ttl_seconds,
            task_id=task_id,
            metadata=metadata or {},
        )
        self.leases[lease.lease_id] = lease
        self._save()
        return lease

    def release(self, lease_id: str) -> None:
        """Release a lease by ID.

        Args:
            lease_id: The lease to release.

        Raises:
            LeaseNotFoundError: If lease_id doesn't exist.
        """
        if lease_id not in self.leases:
            raise LeaseNotFoundError(f"Lease {lease_id} not found")
        del self.leases[lease_id]
        self._save()

    def renew(self, lease_id: str, additional_ttl: Optional[float] = None) -> FileLease:
        """Renew a lease, resetting its acquired_at timestamp and optionally extending TTL.

        Args:
            lease_id: The lease to renew.
            additional_ttl: If provided, adds this to current TTL. If None,
                TTL stays the same but acquired_at resets to now.

        Returns:
            The renewed FileLease.

        Raises:
            LeaseNotFoundError: If lease_id doesn't exist.
            LeaseExpiredError: If lease has already expired.
        """
        if lease_id not in self.leases:
            raise LeaseNotFoundError(f"Lease {lease_id} not found")

        lease = self.leases[lease_id]
        if lease.is_expired():
            raise LeaseExpiredError(
                f"Lease {lease_id} expired, cannot renew"
            )

        lease.acquired_at = _now_iso()
        if additional_ttl is not None:
            lease.ttl_seconds += additional_ttl
        self._save()
        return lease

    def get(self, lease_id: str) -> FileLease:
        """Get a lease by ID.

        Raises:
            LeaseNotFoundError: If lease_id doesn't exist.
        """
        if lease_id not in self.leases:
            raise LeaseNotFoundError(f"Lease {lease_id} not found")
        return self.leases[lease_id]

    # ── Query operations ──

    def list_active(self, now: Optional[float] = None) -> List[FileLease]:
        """List all non-expired leases."""
        if now is None:
            now = time.time()
        return [l for l in self.leases.values() if not l.is_expired(now)]

    def list_expired(self, now: Optional[float] = None) -> List[FileLease]:
        """List all expired leases."""
        if now is None:
            now = time.time()
        return [l for l in self.leases.values() if l.is_expired(now)]

    def list_by_agent(self, agent_id: str) -> List[FileLease]:
        """List all leases (active + expired) for an agent."""
        return [l for l in self.leases.values() if l.agent_id == agent_id]

    def list_by_task(self, task_id: str) -> List[FileLease]:
        """List all leases for a specific task."""
        return [l for l in self.leases.values() if l.task_id == task_id]

    def find_for_path(self, path: str, active_only: bool = True) -> List[FileLease]:
        """Find all leases covering a specific path.

        Args:
            path: File path to search for.
            active_only: If True, only return non-expired leases.
        """
        now = time.time()
        results = []
        for lease in self.leases.values():
            if lease.covers_path(path):
                if not active_only or not lease.is_expired(now):
                    results.append(lease)
        return results

    def check_available(self, file_paths: Set[str]) -> Tuple[bool, List[FileLease]]:
        """Check if file paths are available (no active conflicting leases).

        Returns:
            (available, conflicting_leases) tuple.
        """
        self._reclaim_expired()
        conflicts = []
        for path in file_paths:
            for lease in self.leases.values():
                if lease.covers_path(path) and not lease.is_expired():
                    conflicts.append(lease)
        # Deduplicate
        seen = set()
        unique_conflicts = []
        for c in conflicts:
            if c.lease_id not in seen:
                seen.add(c.lease_id)
                unique_conflicts.append(c)
        return len(unique_conflicts) == 0, unique_conflicts

    # ── Reclamation ──

    def reclaim_expired(self) -> int:
        """Remove all expired leases.

        Returns:
            Number of leases reclaimed.
        """
        return self._reclaim_expired()

    def _reclaim_expired(self) -> int:
        """Internal: remove expired leases and save."""
        expired_ids = [
            lid for lid, lease in self.leases.items() if lease.is_expired()
        ]
        for lid in expired_ids:
            del self.leases[lid]
        if expired_ids:
            self._save()
        return len(expired_ids)

    # ── Conflict detection ──

    def _find_conflicts(
        self, agent_id: str, file_paths: Set[str]
    ) -> List[FileLease]:
        """Find active leases that conflict with requested paths.

        Same-agent leases are NOT conflicts (agent can stack claims).
        """
        conflicts = []
        for lease in self.leases.values():
            if lease.is_expired():
                continue
            if lease.agent_id == agent_id:
                continue
            if lease.file_paths & file_paths:
                conflicts.append(lease)
        return conflicts

    # ── Persistence ──

    def _save(self) -> None:
        """Persist leases to JSON file if store_path is set."""
        if not self.store_path:
            return
        data = {
            "version": 1,
            "updated_at": _now_iso(),
            "leases": {
                lid: lease.to_dict() for lid, lease in self.leases.items()
            },
        }
        tmp_path = self.store_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.store_path)

    def _load(self) -> None:
        """Load leases from JSON file."""
        try:
            with open(self.store_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        leases_data = data.get("leases", {})
        for lid, ldata in leases_data.items():
            try:
                self.leases[lid] = FileLease.from_dict(ldata)
            except (KeyError, TypeError, ValueError):
                continue

    def to_dict(self) -> dict:
        """Serialize entire manager state."""
        return {
            "version": 1,
            "updated_at": _now_iso(),
            "lease_count": len(self.leases),
            "active_count": len(self.list_active()),
            "expired_count": len(self.list_expired()),
            "leases": {
                lid: lease.to_dict() for lid, lease in self.leases.items()
            },
        }
