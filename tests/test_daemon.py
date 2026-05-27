#!/usr/bin/env python3
"""Tests for daemon graceful shutdown."""

import asyncio
import signal
import sys
from pathlib import Path

import pytest

# Ensure the daemon module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import daemon


@pytest.fixture
def event_loop():
    """Create event loop for each test case."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_shutdown_signal():
    """Test that setting shutdown_event drains inflight tasks."""
    # Reset global state
    daemon.shutdown_event.clear()
    daemon.inflight_tasks.clear()

    # Create a task that simulates inflight work
    async def dummy_task():
        await asyncio.sleep(5)

    task = asyncio.create_task(dummy_task())
    daemon.inflight_tasks.add(task)

    # Schedule shutdown after a delay
    async def trigger_shutdown():
        await asyncio.sleep(0.1)
        daemon.shutdown_event.set()

    await asyncio.gather(
        daemon.drain_inflight_tasks(),
        trigger_shutdown(),
    )

    # After drain, task should be cancelled or done
    assert task.done()
    # Inflight tasks set should be empty
    assert len(daemon.inflight_tasks) == 0


@pytest.mark.asyncio
async def test_main_loop_shutdown():
    """Test that main_loop exits cleanly on shutdown event."""
    daemon.shutdown_event.clear()
    daemon.inflight_tasks.clear()

    # Schedule shutdown after a short delay
    async def trigger():
        await asyncio.sleep(0.1)
        daemon.shutdown_event.set()

    await asyncio.gather(
        daemon.main_loop(),
        trigger(),
    )

    # After exit, shutdown event should be set
    assert daemon.shutdown_event.is_set()


@pytest.mark.asyncio
async def test_drain_with_no_tasks():
    """Test drain does not hang when no tasks."""
    daemon.shutdown_event.clear()
    daemon.inflight_tasks.clear()

    await daemon.drain_inflight_tasks()  # Should return immediately
    assert True


def test_signal_handler_function():
    """Test handle_signal sets the event."""
    daemon.shutdown_event.clear()
    daemon.handle_signal(signal.SIGTERM, None)
    assert daemon.shutdown_event.is_set()
    daemon.shutdown_event.clear()
    daemon.handle_signal(signal.SIGINT, None)
    assert daemon.shutdown_event.is_set()
