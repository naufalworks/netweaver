"""Test module imports for netweaver package."""

import pytest


def test_import_netweaver_package():
    """Ensure netweaver package is importable."""
    import netweaver
    assert netweaver is not None


def test_import_planner_module():
    """Ensure netweaver.planner module is importable."""
    from netweaver import planner
    assert planner is not None


def test_import_planner_classes():
    """Ensure key planner classes are importable."""
    from netweaver.planner import PlanTemplate, PlanResult
    assert PlanTemplate is not None
    assert PlanResult is not None
