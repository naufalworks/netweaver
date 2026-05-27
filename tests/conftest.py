"""pytest configuration for NetWeaver test suite."""

import pytest


def pytest_configure(config):
    """Register custom marks to suppress PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers",
        "live: marks tests that require live browser (Playwright) — excluded from default runs.",
    )
