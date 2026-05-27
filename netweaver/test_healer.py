"""NetWeaver Self-Healing Test Recovery — NW-027.

Detects flaky tests, auto-retries with exponential backoff, and quarantines
tests that fail >3 consecutive runs. Integrates with pytest via plugin hook.

Key components:
- TestHealer: main class for flaky detection, retry, and quarantine management
- QuarantineEntry: dataclass for quarantined test metadata
- PytestPlugin: hook that skips quarantined tests with @quarantined marker

No browser/vendor/playwright imports.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class QuarantineEntry:
    """A quarantined test with metadata."""
    test_name: str
    quarantined_at: str  # ISO timestamp
    consecutive_failures: int
    reason: str
    last_failure_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "quarantined_at": self.quarantined_at,
            "consecutive_failures": self.consecutive_failures,
            "reason": self.reason,
            "last_failure_at": self.last_failure_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuarantineEntry":
        return cls(
            test_name=data["test_name"],
            quarantined_at=data["quarantined_at"],
            consecutive_failures=data["consecutive_failures"],
            reason=data["reason"],
            last_failure_at=data.get("last_failure_at"),
        )


@dataclass
class RetryResult:
    """Result of a retry attempt."""
    success: bool
    attempts: int
    last_error: Optional[str] = None
    durations: List[float] = field(default_factory=list)


@dataclass
class FlakyReport:
    """Report from flaky test detection."""
    test_name: str
    is_flaky: bool
    consecutive_failures: int
    total_runs: int
    failure_rate: float
    should_quarantine: bool


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class TestHealer:
    """Self-healing test recovery: detect flaky tests, retry, quarantine.

    Usage:
        healer = TestHealer(quarantine_path=".tini/quarantined_tests.json")
        report = healer.detect_flaky("test_login", history=[True, False, False, False, False])
        if report.should_quarantine:
            healer.quarantine("test_login", reason=report.reason())
    """

    DEFAULT_MAX_ATTEMPTS = 3
    DEFAULT_BACKOFF_BASE = 1.0  # seconds
    DEFAULT_QUARANTINE_THRESHOLD = 3  # consecutive failures to quarantine

    def __init__(
        self,
        quarantine_path: Optional[str] = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        quarantine_threshold: int = DEFAULT_QUARANTINE_THRESHOLD,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ):
        self.quarantine_path = Path(quarantine_path) if quarantine_path else Path(".tini/quarantined_tests.json")
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.quarantine_threshold = quarantine_threshold
        self.sleep_fn = sleep_fn or time.sleep
        self._quarantine: Dict[str, QuarantineEntry] = {}
        self._history: Dict[str, List[bool]] = {}  # test_name -> [passed, ...]
        self._load_quarantine()

    # -----------------------------------------------------------------------
    # Flaky detection
    # -----------------------------------------------------------------------

    def detect_flaky(self, test_name: str, history: List[bool]) -> FlakyReport:
        """Analyze test history to detect flakiness.

        Args:
            test_name: Fully qualified test name (e.g. "tests/test_foo.py::test_bar")
            history: List of pass/fail results (True=pass, False=fail), oldest first.

        Returns:
            FlakyReport with detection results.
        """
        if not history:
            return FlakyReport(
                test_name=test_name,
                is_flaky=False,
                consecutive_failures=0,
                total_runs=0,
                failure_rate=0.0,
                should_quarantine=False,
            )

        # Count consecutive failures from the end (most recent)
        consecutive_failures = 0
        for result in reversed(history):
            if result:
                break
            consecutive_failures += 1

        total_runs = len(history)
        failures = sum(1 for r in history if not r)
        failure_rate = failures / total_runs if total_runs > 0 else 0.0

        is_flaky = consecutive_failures >= self.quarantine_threshold
        should_quarantine = is_flaky

        return FlakyReport(
            test_name=test_name,
            is_flaky=is_flaky,
            consecutive_failures=consecutive_failures,
            total_runs=total_runs,
            failure_rate=failure_rate,
            should_quarantine=should_quarantine,
        )

    # -----------------------------------------------------------------------
    # Auto-retry with exponential backoff
    # -----------------------------------------------------------------------

    def retry_with_backoff(
        self,
        test_fn: Callable[[], Any],
        max_attempts: Optional[int] = None,
        backoff_base: Optional[float] = None,
    ) -> RetryResult:
        """Retry a test function with exponential backoff.

        Backoff schedule: base * 2^(attempt-1) → 1s, 2s, 4s for base=1.

        Args:
            test_fn: Callable that raises on failure, returns on success.
            max_attempts: Override default max attempts.
            backoff_base: Override default backoff base.

        Returns:
            RetryResult with success status, attempt count, and error info.
        """
        attempts = max_attempts or self.max_attempts
        base = backoff_base or self.backoff_base
        durations: List[float] = []
        last_error: Optional[str] = None

        for attempt in range(1, attempts + 1):
            start = time.monotonic()
            try:
                test_fn()
                durations.append(time.monotonic() - start)
                return RetryResult(
                    success=True,
                    attempts=attempt,
                    last_error=None,
                    durations=durations,
                )
            except Exception as e:
                durations.append(time.monotonic() - start)
                last_error = str(e)
                if attempt < attempts:
                    delay = base * (2 ** (attempt - 1))
                    self.sleep_fn(delay)

        return RetryResult(
            success=False,
            attempts=attempts,
            last_error=last_error,
            durations=durations,
        )

    # -----------------------------------------------------------------------
    # Quarantine management
    # -----------------------------------------------------------------------

    def quarantine(self, test_name: str, reason: str = "flaky: exceeded consecutive failure threshold") -> QuarantineEntry:
        """Quarantine a test — exclude from default pytest runs.

        Args:
            test_name: Fully qualified test name.
            reason: Why the test was quarantined.

        Returns:
            The created QuarantineEntry.
        """
        now = datetime.now(timezone.utc).isoformat()
        consecutive = self._count_recent_failures(test_name)
        entry = QuarantineEntry(
            test_name=test_name,
            quarantined_at=now,
            consecutive_failures=consecutive,
            reason=reason,
            last_failure_at=now,
        )
        self._quarantine[test_name] = entry
        self._save_quarantine()
        return entry

    def unquarantine(self, test_name: str) -> bool:
        """Remove a test from quarantine.

        Args:
            test_name: Fully qualified test name.

        Returns:
            True if test was quarantined and removed, False if not found.
        """
        if test_name in self._quarantine:
            del self._quarantine[test_name]
            self._save_quarantine()
            return True
        return False

    def is_quarantined(self, test_name: str) -> bool:
        """Check if a test is currently quarantined."""
        return test_name in self._quarantine

    def get_quarantine_entry(self, test_name: str) -> Optional[QuarantineEntry]:
        """Get quarantine entry for a test, or None."""
        return self._quarantine.get(test_name)

    def list_quarantined(self) -> List[QuarantineEntry]:
        """List all quarantined tests."""
        return list(self._quarantine.values())

    # -----------------------------------------------------------------------
    # Result recording + auto-unquarantine
    # -----------------------------------------------------------------------

    def record_result(self, test_name: str, passed: bool) -> Optional[str]:
        """Record a test result and auto-unquarantine if fixed.

        Args:
            test_name: Fully qualified test name.
            passed: Whether the test passed.

        Returns:
            "unquarantined" if test was auto-unquarantined,
            "quarantined" if test was just quarantined,
            None otherwise.
        """
        if test_name not in self._history:
            self._history[test_name] = []
        self._history[test_name].append(passed)

        if passed and self.is_quarantined(test_name):
            # Auto-unquarantine: test passed after quarantine → fixed
            self.unquarantine(test_name)
            return "unquarantined"

        if not passed:
            # Update quarantine entry if exists
            if test_name in self._quarantine:
                entry = self._quarantine[test_name]
                entry.consecutive_failures += 1
                entry.last_failure_at = datetime.now(timezone.utc).isoformat()
                self._save_quarantine()

            # Check if should quarantine
            history = self._history[test_name]
            report = self.detect_flaky(test_name, history)
            if report.should_quarantine and not self.is_quarantined(test_name):
                self.quarantine(test_name, reason=f"flaky: {report.consecutive_failures} consecutive failures")
                return "quarantined"

        return None

    # -----------------------------------------------------------------------
    # History access
    # -----------------------------------------------------------------------

    def get_history(self, test_name: str) -> List[bool]:
        """Get recorded history for a test."""
        return list(self._history.get(test_name, []))

    def clear_history(self, test_name: Optional[str] = None) -> None:
        """Clear history for one or all tests."""
        if test_name:
            self._history.pop(test_name, None)
        else:
            self._history.clear()

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _load_quarantine(self) -> None:
        """Load quarantine list from disk."""
        if self.quarantine_path.exists():
            try:
                data = json.loads(self.quarantine_path.read_text())
                if isinstance(data, dict):
                    for name, entry_data in data.items():
                        self._quarantine[name] = QuarantineEntry.from_dict(entry_data)
            except (json.JSONDecodeError, KeyError, TypeError):
                self._quarantine = {}

    def _save_quarantine(self) -> None:
        """Persist quarantine list to disk."""
        self.quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: entry.to_dict() for name, entry in self._quarantine.items()}
        self.quarantine_path.write_text(json.dumps(data, indent=2))

    def _count_recent_failures(self, test_name: str) -> int:
        """Count consecutive failures from most recent for a test."""
        history = self._history.get(test_name, [])
        count = 0
        for result in reversed(history):
            if result:
                break
            count += 1
        return count


# ---------------------------------------------------------------------------
# Pytest plugin
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    """Pytest hook: skip quarantined tests unless --run-quarantined is passed.

    Add to conftest.py:
        from netweaver.test_healer import pytest_collection_modifyitems
    """
    if config.getoption("--run-quarantined", default=False):
        return

    # Load quarantine list
    quarantine_path = config.getoption("--quarantine-path", default=".tini/quarantined_tests.json")
    healer = TestHealer(quarantine_path=quarantine_path)

    skip_quarantined = pytest.mark.skip(reason="quarantined: flaky test, auto-excluded by TestHealer")

    for item in items:
        node_id = item.nodeid
        if healer.is_quarantined(node_id):
            item.add_marker(skip_quarantined)


def pytest_addoption(parser):
    """Add --run-quarantined and --quarantine-path options to pytest."""
    group = parser.getgroup("test-healer", "NetWeaver self-healing test recovery")
    group.addoption(
        "--run-quarantined",
        action="store_true",
        default=False,
        help="Run quarantined (flaky) tests even if quarantined",
    )
    group.addoption(
        "--quarantine-path",
        default=".tini/quarantined_tests.json",
        help="Path to quarantined tests JSON file",
    )
