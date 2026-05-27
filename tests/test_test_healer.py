"""Tests for NetWeaver Self-Healing Test Recovery — NW-027.

Covers:
  - detect_flaky() with various history patterns
  - retry_with_backoff() success/failure/backoff timing
  - quarantine/unquarantine lifecycle
  - record_result() auto-unquarantine on green
  - Persistence (save/load quarantine JSON)
  - Edge cases: empty history, threshold boundary, missing file
  - FlakyReport fields
  - History tracking and clearing
  - QuarantineEntry serialization round-trip
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, call

from netweaver.test_healer import (
    FlakyReport,
    QuarantineEntry,
    RetryResult,
    TestHealer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_quarantine(tmp_path):
    """Return a path for a temporary quarantine JSON file."""
    return str(tmp_path / ".tini" / "quarantined_tests.json")


@pytest.fixture
def healer(tmp_quarantine):
    """Create a TestHealer with no-op sleep and temp quarantine path."""
    return TestHealer(
        quarantine_path=tmp_quarantine,
        sleep_fn=lambda _: None,  # no-op sleep for fast tests
    )


@pytest.fixture
def healer_custom(tmp_quarantine):
    """Factory for TestHealer with custom settings."""
    def _make(max_attempts=3, backoff_base=1.0, quarantine_threshold=3):
        return TestHealer(
            quarantine_path=tmp_quarantine,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
            quarantine_threshold=quarantine_threshold,
            sleep_fn=lambda _: None,
        )
    return _make


# ---------------------------------------------------------------------------
# detect_flaky tests
# ---------------------------------------------------------------------------

class TestDetectFlaky:
    """Tests for TestHealer.detect_flaky()."""

    def test_empty_history_not_flaky(self, healer):
        report = healer.detect_flaky("test_empty", [])
        assert not report.is_flaky
        assert report.consecutive_failures == 0
        assert report.total_runs == 0
        assert report.failure_rate == 0.0
        assert not report.should_quarantine

    def test_all_passing_not_flaky(self, healer):
        report = healer.detect_flaky("test_pass", [True, True, True, True, True])
        assert not report.is_flaky
        assert report.consecutive_failures == 0
        assert report.failure_rate == 0.0

    def test_intermittent_failure_not_flaky(self, healer):
        """Intermittent failures (not consecutive) are not flagged."""
        report = healer.detect_flaky("test_intermittent", [True, False, True, False, True])
        assert not report.is_flaky
        assert report.consecutive_failures == 0  # last result is pass

    def test_three_consecutive_failures_is_flaky(self, healer):
        """Exactly threshold (3) consecutive failures → flaky."""
        report = healer.detect_flaky("test_flaky3", [True, False, False, False])
        assert report.is_flaky
        assert report.consecutive_failures == 3
        assert report.should_quarantine

    def test_five_consecutive_failures_is_flaky(self, healer):
        report = healer.detect_flaky("test_flaky5", [True, True, False, False, False, False, False])
        assert report.is_flaky
        assert report.consecutive_failures == 5
        assert report.failure_rate == pytest.approx(5 / 7)

    def test_two_failures_below_threshold(self, healer):
        """2 consecutive failures < threshold of 3 → not flaky."""
        report = healer.detect_flaky("test_2fail", [True, False, False])
        assert not report.is_flaky
        assert report.consecutive_failures == 2
        assert not report.should_quarantine

    def test_single_failure(self, healer):
        report = healer.detect_flaky("test_1fail", [False])
        assert not report.is_flaky
        assert report.consecutive_failures == 1

    def test_all_failures(self, healer):
        report = healer.detect_flaky("test_allfail", [False, False, False, False])
        assert report.is_flaky
        assert report.consecutive_failures == 4
        assert report.failure_rate == 1.0

    def test_custom_threshold(self, healer_custom):
        """Custom threshold of 5 requires 5+ consecutive failures."""
        h = healer_custom(quarantine_threshold=5)
        report = h.detect_flaky("test_custom", [False, False, False, False])
        assert not report.is_flaky
        report2 = h.detect_flaky("test_custom", [False, False, False, False, False])
        assert report2.is_flaky


# ---------------------------------------------------------------------------
# retry_with_backoff tests
# ---------------------------------------------------------------------------

class TestRetryWithBackoff:
    """Tests for TestHealer.retry_with_backoff()."""

    def test_success_first_attempt(self, healer):
        fn = MagicMock(return_value=None)
        result = healer.retry_with_backoff(fn)
        assert result.success
        assert result.attempts == 1
        assert result.last_error is None
        fn.assert_called_once()

    def test_success_after_failures(self, healer):
        """Succeeds on 2nd attempt."""
        fn = MagicMock(side_effect=[ValueError("fail1"), None])
        result = healer.retry_with_backoff(fn)
        assert result.success
        assert result.attempts == 2
        assert fn.call_count == 2

    def test_all_attempts_fail(self, healer):
        fn = MagicMock(side_effect=RuntimeError("always fails"))
        result = healer.retry_with_backoff(fn)
        assert not result.success
        assert result.attempts == 3  # default max_attempts
        assert "always fails" in result.last_error
        assert fn.call_count == 3

    def test_backoff_timing(self, healer):
        """Verify exponential backoff: 1s, 2s for 3 attempts."""
        sleep_mock = MagicMock()
        healer.sleep_fn = sleep_mock
        fn = MagicMock(side_effect=RuntimeError("fail"))
        healer.retry_with_backoff(fn)
        # 3 attempts → 2 sleeps: base*1=1s, base*2=2s
        assert sleep_mock.call_args_list == [call(1.0), call(2.0)]

    def test_custom_max_attempts(self, healer):
        fn = MagicMock(side_effect=RuntimeError("fail"))
        result = healer.retry_with_backoff(fn, max_attempts=5)
        assert not result.success
        assert result.attempts == 5

    def test_custom_backoff_base(self, healer):
        sleep_mock = MagicMock()
        healer.sleep_fn = sleep_mock
        fn = MagicMock(side_effect=RuntimeError("fail"))
        healer.retry_with_backoff(fn, max_attempts=3, backoff_base=0.5)
        # 0.5*1=0.5, 0.5*2=1.0
        assert sleep_mock.call_args_list == [call(0.5), call(1.0)]

    def test_durations_recorded(self, healer):
        fn = MagicMock(return_value=None)
        result = healer.retry_with_backoff(fn)
        assert len(result.durations) == 1
        assert result.durations[0] >= 0

    def test_success_no_sleep(self, healer):
        """No sleep when first attempt succeeds."""
        sleep_mock = MagicMock()
        healer.sleep_fn = sleep_mock
        fn = MagicMock(return_value=None)
        healer.retry_with_backoff(fn)
        sleep_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Quarantine management tests
# ---------------------------------------------------------------------------

class TestQuarantine:
    """Tests for quarantine/unquarantine/is_quarantined."""

    def test_quarantine_creates_entry(self, healer):
        entry = healer.quarantine("tests/test_foo.py::test_bar", reason="flaky")
        assert entry.test_name == "tests/test_foo.py::test_bar"
        assert entry.reason == "flaky"
        assert healer.is_quarantined("tests/test_foo.py::test_bar")

    def test_unquarantine_removes(self, healer):
        healer.quarantine("test_a")
        assert healer.is_quarantined("test_a")
        result = healer.unquarantine("test_a")
        assert result is True
        assert not healer.is_quarantined("test_a")

    def test_unquarantine_nonexistent(self, healer):
        assert healer.unquarantine("nonexistent") is False

    def test_list_quarantined(self, healer):
        healer.quarantine("test_a")
        healer.quarantine("test_b")
        entries = healer.list_quarantined()
        names = {e.test_name for e in entries}
        assert names == {"test_a", "test_b"}

    def test_get_quarantine_entry(self, healer):
        healer.quarantine("test_x", reason="custom reason")
        entry = healer.get_quarantine_entry("test_x")
        assert entry is not None
        assert entry.reason == "custom reason"

    def test_get_quarantine_entry_missing(self, healer):
        assert healer.get_quarantine_entry("nonexistent") is None


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestPersistence:
    """Tests for quarantine save/load."""

    def test_save_creates_file(self, healer, tmp_quarantine):
        healer.quarantine("test_save")
        assert Path(tmp_quarantine).exists()

    def test_load_restores_quarantine(self, healer, tmp_quarantine):
        healer.quarantine("test_persist", reason="persist test")
        # Create new healer loading from same path
        healer2 = TestHealer(quarantine_path=tmp_quarantine, sleep_fn=lambda _: None)
        assert healer2.is_quarantined("test_persist")
        entry = healer2.get_quarantine_entry("test_persist")
        assert entry.reason == "persist test"

    def test_load_missing_file_no_error(self, tmp_path):
        """Loading from nonexistent path doesn't crash."""
        path = str(tmp_path / "nonexistent" / "quarantine.json")
        h = TestHealer(quarantine_path=path, sleep_fn=lambda _: None)
        assert not h.is_quarantined("anything")

    def test_load_corrupt_json_no_error(self, tmp_path):
        """Corrupt JSON doesn't crash — starts fresh."""
        qpath = tmp_path / "quarantine.json"
        qpath.write_text("not valid json {{{")
        h = TestHealer(quarantine_path=str(qpath), sleep_fn=lambda _: None)
        assert not h.is_quarantined("anything")

    def test_save_load_round_trip(self, healer, tmp_quarantine):
        """Full round-trip: save → load → verify data integrity."""
        healer.quarantine("test_round", reason="round trip")
        healer.quarantine("test_round2", reason="second entry")

        healer2 = TestHealer(quarantine_path=tmp_quarantine, sleep_fn=lambda _: None)
        assert healer2.is_quarantined("test_round")
        assert healer2.is_quarantined("test_round2")
        assert len(healer2.list_quarantined()) == 2


# ---------------------------------------------------------------------------
# record_result + auto-unquarantine tests
# ---------------------------------------------------------------------------

class TestRecordResult:
    """Tests for record_result() and auto-unquarantine."""

    def test_record_pass(self, healer):
        result = healer.record_result("test_ok", passed=True)
        assert result is None
        assert healer.get_history("test_ok") == [True]

    def test_record_fail(self, healer):
        result = healer.record_result("test_fail", passed=False)
        assert result is None
        assert healer.get_history("test_fail") == [False]

    def test_auto_quarantine_after_threshold(self, healer):
        """3 consecutive failures → auto-quarantine."""
        healer.record_result("test_auto", passed=False)
        healer.record_result("test_auto", passed=False)
        assert not healer.is_quarantined("test_auto")
        result = healer.record_result("test_auto", passed=False)
        assert result == "quarantined"
        assert healer.is_quarantined("test_auto")

    def test_auto_unquarantine_on_green(self, healer):
        """Quarantined test passes → auto-unquarantine."""
        # Quarantine manually
        healer.quarantine("test_fix")
        assert healer.is_quarantined("test_fix")
        # Record pass → auto-unquarantine
        result = healer.record_result("test_fix", passed=True)
        assert result == "unquarantined"
        assert not healer.is_quarantined("test_fix")

    def test_no_auto_quarantine_below_threshold(self, healer):
        """2 failures then pass → no quarantine."""
        healer.record_result("test_recover", passed=False)
        healer.record_result("test_recover", passed=False)
        healer.record_result("test_recover", passed=True)
        assert not healer.is_quarantined("test_recover")

    def test_quarantine_updates_on_failure(self, healer):
        """Quarantined test fails again → consecutive_failures increments."""
        healer.quarantine("test_repeat")
        entry_before = healer.get_quarantine_entry("test_repeat")
        assert entry_before is not None
        fails_before = entry_before.consecutive_failures
        healer.record_result("test_repeat", passed=False)
        entry_after = healer.get_quarantine_entry("test_repeat")
        assert entry_after is not None
        assert entry_after.consecutive_failures == fails_before + 1


# ---------------------------------------------------------------------------
# History tests
# ---------------------------------------------------------------------------

class TestHistory:
    """Tests for get_history() and clear_history()."""

    def test_empty_history(self, healer):
        assert healer.get_history("nonexistent") == []

    def test_history_accumulates(self, healer):
        healer.record_result("test_h", passed=True)
        healer.record_result("test_h", passed=False)
        healer.record_result("test_h", passed=True)
        assert healer.get_history("test_h") == [True, False, True]

    def test_clear_specific_history(self, healer):
        healer.record_result("test_a", passed=True)
        healer.record_result("test_b", passed=True)
        healer.clear_history("test_a")
        assert healer.get_history("test_a") == []
        assert healer.get_history("test_b") == [True]

    def test_clear_all_history(self, healer):
        healer.record_result("test_a", passed=True)
        healer.record_result("test_b", passed=True)
        healer.clear_history()
        assert healer.get_history("test_a") == []
        assert healer.get_history("test_b") == []


# ---------------------------------------------------------------------------
# QuarantineEntry serialization tests
# ---------------------------------------------------------------------------

class TestQuarantineEntrySerialization:
    """Tests for QuarantineEntry to_dict/from_dict."""

    def test_round_trip(self):
        entry = QuarantineEntry(
            test_name="test_ser",
            quarantined_at="2026-05-27T10:00:00+00:00",
            consecutive_failures=5,
            reason="flaky",
            last_failure_at="2026-05-27T09:59:00+00:00",
        )
        d = entry.to_dict()
        restored = QuarantineEntry.from_dict(d)
        assert restored.test_name == entry.test_name
        assert restored.quarantined_at == entry.quarantined_at
        assert restored.consecutive_failures == entry.consecutive_failures
        assert restored.reason == entry.reason
        assert restored.last_failure_at == entry.last_failure_at

    def test_round_trip_no_last_failure(self):
        entry = QuarantineEntry(
            test_name="test_nolast",
            quarantined_at="2026-05-27T10:00:00+00:00",
            consecutive_failures=3,
            reason="manual",
        )
        d = entry.to_dict()
        restored = QuarantineEntry.from_dict(d)
        assert restored.last_failure_at is None


# ---------------------------------------------------------------------------
# Integration-style test: full lifecycle
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    """End-to-end lifecycle: detect → quarantine → fix → unquarantine."""

    def test_lifecycle(self, healer):
        test_name = "tests/test_api.py::test_login"

        # 1. Record failures
        healer.record_result(test_name, passed=False)
        healer.record_result(test_name, passed=False)
        assert not healer.is_quarantined(test_name)

        # 2. Third failure → auto-quarantine
        result = healer.record_result(test_name, passed=False)
        assert result == "quarantined"
        assert healer.is_quarantined(test_name)

        # 3. detect_flaky confirms
        report = healer.detect_flaky(test_name, healer.get_history(test_name))
        assert report.is_flaky
        assert report.consecutive_failures == 3

        # 4. Test fixed → record pass → auto-unquarantine
        result = healer.record_result(test_name, passed=True)
        assert result == "unquarantined"
        assert not healer.is_quarantined(test_name)

    def test_retry_then_record(self, healer):
        """Retry succeeds, then record result."""
        fn = MagicMock(side_effect=[RuntimeError("flaky"), None])
        result = healer.retry_with_backoff(fn)
        assert result.success
        assert result.attempts == 2

        healer.record_result("test_retry_record", passed=True)
        assert healer.get_history("test_retry_record") == [True]
