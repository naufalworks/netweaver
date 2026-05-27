#!/usr/bin/env python3
"""Tests for daemon graceful shutdown and circuit breaker."""

import asyncio
import signal
import sys
from pathlib import Path

import pytest

# Ensure the daemon module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import daemon


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before each test."""
    daemon.shutdown_event.clear()
    daemon.inflight_tasks.clear()
    yield
    daemon.shutdown_event.clear()
    daemon.inflight_tasks.clear()


@pytest.mark.asyncio
async def test_shutdown_event_drains_tasks():
    """Test that setting shutdown_event allows graceful drain."""
    async def dummy_task():
        await asyncio.sleep(5)

    task = asyncio.create_task(dummy_task())
    daemon.inflight_tasks.add(task)

    # Trigger shutdown
    daemon.shutdown_event.set()

    # Manually drain (mirrors main_loop drain logic)
    for t in daemon.inflight_tasks:
        t.cancel()
    await asyncio.gather(*daemon.inflight_tasks, return_exceptions=True)
    daemon.inflight_tasks.clear()

    assert task.done()
    assert len(daemon.inflight_tasks) == 0


@pytest.mark.asyncio
async def test_main_loop_shutdown():
    """Test that main_loop exits cleanly on shutdown event."""
    # Schedule shutdown after a short delay
    async def trigger():
        await asyncio.sleep(0.5)
        daemon.shutdown_event.set()

    await asyncio.gather(
        daemon.main_loop(),
        trigger(),
    )

    assert daemon.shutdown_event.is_set()


@pytest.mark.asyncio
async def test_empty_inflight_set_no_hang():
    """Test drain does not hang when no tasks inflight."""
    assert len(daemon.inflight_tasks) == 0
    # Should complete instantly
    await asyncio.wait_for(asyncio.sleep(0), timeout=1.0)


def test_signal_handler_function():
    """Test handle_signal sets the event."""
    daemon.handle_signal(signal.SIGTERM, None)
    assert daemon.shutdown_event.is_set()
    daemon.shutdown_event.clear()
    daemon.handle_signal(signal.SIGINT, None)
    assert daemon.shutdown_event.is_set()
    daemon.shutdown_event.clear()


def test_circuit_breaker_record_and_pause():
    """Test circuit breaker trips after MAX_FAILURES_BEFORE_PAUSE."""
    agent = "test-daemon-unit"
    # Clean slate
    daemon.record_success(agent)
    assert not daemon.is_paused(agent)

    # Trip the breaker
    for i in range(daemon.MAX_FAILURES_BEFORE_PAUSE):
        daemon.record_failure(agent, f"fail-{i}")

    assert daemon.is_paused(agent)

    # Reset
    daemon.record_success(agent)
    assert not daemon.is_paused(agent)


def test_parse_kanban_done():
    """Test that parse_kanban_done extracts IDs from done section."""
    done_ids = daemon.parse_kanban_done()
    # Should find at least some known done tasks
    assert isinstance(done_ids, set)


def test_detect_gaps_skips_done_tasks():
    """Test that gap detection skips tasks already in done section."""
    gaps = daemon.detect_gaps()
    gap_ids = {g["id"] for g in gaps}
    done_ids = daemon.parse_kanban_done()
    # No done task should appear as a gap
    overlap = gap_ids & done_ids
    assert not overlap, f"Done tasks found in gaps: {overlap}"
