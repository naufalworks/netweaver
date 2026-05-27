"""Tests for NetWeaver Auto-Backlog Generator (NW-028).

Covers:
- scan_todos(): TODO/FIXME/HACK detection in Python files
- scan_coverage(): module test coverage gap identification
- scan_docstrings(): missing docstring detection
- generate_entries(): deduplication and formatting
- BacklogGenerator: full pipeline orchestration
- BacklogEntry: data model serialization

No browser/vendor/playwright imports.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List

import pytest

from netweaver.backlog_generator import (
    BacklogEntry,
    BacklogGenerator,
    CoverageGap,
    DocstringGap,
    TodoFinding,
    _assess_risk,
    _count_loc,
    _generate_id,
    _get_test_file_names,
    _parse_existing_backlog_ids,
    generate_entries,
    render_backlog_addendum,
    scan_coverage,
    scan_docstrings,
    scan_todos,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project structure."""
    netweaver = tmp_path / "netweaver"
    tests = tmp_path / "tests"
    netweaver.mkdir()
    tests.mkdir()
    return tmp_path, netweaver, tests


@pytest.fixture
def sample_module(tmp_project):
    """Create a sample module with TODO/FIXME/HACK comments."""
    _, netweaver, tests = tmp_project
    module = netweaver / "example.py"
    module.write_text(
        '"""Example module with markers."""\n'
        "\n"
        "# TODO: implement caching\n"
        "def compute():\n"
        "    # FIXME: handle edge case\n"
        "    pass\n"
        "\n"
        "# HACK: temporary workaround\n"
        "def workaround():\n"
        "    pass\n"
        "\n"
        "def clean():\n"
        "    # Normal comment, no marker\n"
        "    return True\n"
    )
    return module


@pytest.fixture
def sample_untested_module(tmp_project):
    """Create a module without a corresponding test file."""
    _, netweaver, tests = tmp_project
    module = netweaver / "orphantool.py"
    module.write_text(
        '"""Orphan module without tests."""\n'
        "\n"
        "class OrphanTool:\n"
        "    def do_thing(self):\n"
        "        return 42\n"
        "\n"
        "    def do_other(self):\n"
        "        return 99\n"
    )
    return module


@pytest.fixture
def sample_tested_module(tmp_project):
    """Create a module with a corresponding test file."""
    _, netweaver, tests = tmp_project
    module = netweaver / "calculator.py"
    module.write_text(
        '"""Calculator module."""\n'
        "\n"
        "def add(a, b):\n"
        "    return a + b\n"
    )
    test_file = tests / "test_calculator.py"
    test_file.write_text(
        "from netweaver.calculator import add\n"
        "\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
    )
    return module


# ---------------------------------------------------------------------------
# TodoFinding tests
# ---------------------------------------------------------------------------

class TestTodoFinding:
    """Tests for TodoFinding dataclass."""

    def test_create(self):
        f = TodoFinding(
            file_path="netweaver/foo.py",
            line_number=10,
            tag="TODO",
            text="implement feature",
            context="# TODO: implement feature",
        )
        assert f.tag == "TODO"
        assert f.line_number == 10
        assert f.text == "implement feature"

    def test_to_dict(self):
        f = TodoFinding("a.py", 1, "FIXME", "broken", "# FIXME: broken")
        d = f.to_dict()
        assert d["tag"] == "FIXME"
        assert d["line_number"] == 1
        assert d["file_path"] == "a.py"

    def test_all_tags(self):
        for tag in ("TODO", "FIXME", "HACK"):
            f = TodoFinding("x.py", 1, tag, "msg", f"# {tag}: msg")
            assert f.tag == tag


# ---------------------------------------------------------------------------
# scan_todos tests
# ---------------------------------------------------------------------------

class TestScanTodos:
    """Tests for scan_todos function."""

    def test_finds_todo(self, sample_module, tmp_project):
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver)
        tags = [f.tag for f in findings]
        assert "TODO" in tags

    def test_finds_fixme(self, sample_module, tmp_project):
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver)
        tags = [f.tag for f in findings]
        assert "FIXME" in tags

    def test_finds_hack(self, sample_module, tmp_project):
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver)
        tags = [f.tag for f in findings]
        assert "HACK" in tags

    def test_correct_count(self, sample_module, tmp_project):
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver)
        assert len(findings) == 3  # TODO, FIXME, HACK

    def test_line_numbers(self, sample_module, tmp_project):
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver)
        lines = {f.line_number for f in findings}
        assert 3 in lines  # # TODO (line 3)
        assert 5 in lines  # # FIXME (line 5, indented)
        assert 8 in lines  # # HACK (line 8)

    def test_text_extracted(self, sample_module, tmp_project):
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver)
        todo = next(f for f in findings if f.tag == "TODO")
        assert "implement caching" in todo.text

    def test_no_false_positives(self, sample_module, tmp_project):
        """Normal comments should not trigger."""
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver)
        # "Normal comment, no marker" should not be found
        assert not any("Normal" in f.text for f in findings)

    def test_nonexistent_dir(self):
        findings = scan_todos("/nonexistent/path/xyz")
        assert findings == []

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        findings = scan_todos(empty)
        assert findings == []

    def test_case_insensitive(self, tmp_project):
        """todo/fixme/hack in lowercase should match."""
        _, netweaver, _ = tmp_project
        module = netweaver / "lower.py"
        module.write_text("# todo: lowercase\n# fixme: also lower\n")
        findings = scan_todos(netweaver, glob_pattern="lower.py")
        assert len(findings) == 2

    def test_exclude_patterns(self, sample_module, tmp_project):
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver, exclude_patterns=["example"])
        assert len(findings) == 0

    def test_file_path_stored(self, sample_module, tmp_project):
        _, netweaver, _ = tmp_project
        findings = scan_todos(netweaver)
        assert all("example.py" in f.file_path for f in findings)


# ---------------------------------------------------------------------------
# CoverageGap tests
# ---------------------------------------------------------------------------

class TestCoverageGap:
    """Tests for CoverageGap dataclass."""

    def test_create(self):
        g = CoverageGap("netweaver/x.py", "x", 100, False, 0.0)
        assert g.module_name == "x"
        assert g.loc == 100
        assert g.has_test_file is False
        assert g.estimated_coverage == 0.0

    def test_to_dict(self):
        g = CoverageGap("p.py", "p", 50, True, 0.7)
        d = g.to_dict()
        assert d["module_name"] == "p"
        assert d["estimated_coverage"] == 0.7


# ---------------------------------------------------------------------------
# scan_coverage tests
# ---------------------------------------------------------------------------

class TestScanCoverage:
    """Tests for scan_coverage function."""

    def test_detects_untested_module(self, sample_untested_module, tmp_project):
        _, netweaver, tests = tmp_project
        gaps = scan_coverage(netweaver, tests)
        names = [g.module_name for g in gaps]
        assert "orphantool" in names

    def test_tested_module_not_flagged(self, sample_tested_module, tmp_project):
        _, netweaver, tests = tmp_project
        gaps = scan_coverage(netweaver, tests)
        names = [g.module_name for g in gaps]
        assert "calculator" not in names

    def test_loc_counted(self, sample_untested_module, tmp_project):
        _, netweaver, tests = tmp_project
        gaps = scan_coverage(netweaver, tests)
        orphan = next(g for g in gaps if g.module_name == "orphantool")
        assert orphan.loc > 0

    def test_threshold_customizable(self, sample_untested_module, tmp_project):
        _, netweaver, tests = tmp_project
        gaps_low = scan_coverage(netweaver, tests, threshold=0.1)
        gaps_high = scan_coverage(netweaver, tests, threshold=0.9)
        assert len(gaps_high) >= len(gaps_low)

    def test_init_excluded(self, tmp_project):
        _, netweaver, tests = tmp_project
        (netweaver / "__init__.py").write_text("# init\n")
        gaps = scan_coverage(netweaver, tests)
        assert not any(g.module_name == "__init__" for g in gaps)

    def test_nonexistent_dir(self):
        gaps = scan_coverage("/nonexistent", "/nonexistent2")
        assert gaps == []

    def test_estimated_coverage_zero_for_no_tests(self, sample_untested_module, tmp_project):
        _, netweaver, tests = tmp_project
        gaps = scan_coverage(netweaver, tests)
        orphan = next(g for g in gaps if g.module_name == "orphantool")
        assert orphan.estimated_coverage == 0.0


# ---------------------------------------------------------------------------
# DocstringGap & scan_docstrings tests
# ---------------------------------------------------------------------------

class TestScanDocstrings:
    """Tests for scan_docstrings function."""

    def test_detects_missing_module_docstring(self, tmp_project):
        _, netweaver, _ = tmp_project
        (netweaver / "nodoc.py").write_text(
            "def big_function(x):\n"
            "    a = x + 1\n"
            "    b = a * 2\n"
            "    c = a + b\n"
            "    d = c * x\n"
            "    e = d - a\n"
            "    f = e + b\n"
            "    g = f * c\n"
            "    h = g - d\n"
            "    return h\n"
        )
        gaps = scan_docstrings(netweaver, min_loc_for_check=1)
        module_gaps = [g for g in gaps if g.scope == "module"]
        assert any(g.name == "nodoc" for g in module_gaps)

    def test_module_with_docstring_not_flagged(self, tmp_project):
        _, netweaver, _ = tmp_project
        (netweaver / "has_doc.py").write_text(
            '"""This module has a docstring."""\n'
            "\n"
            "def small():\n"
            "    pass\n"
        )
        gaps = scan_docstrings(netweaver)
        module_gaps = [g for g in gaps if g.scope == "module" and g.name == "has_doc"]
        assert len(module_gaps) == 0

    def test_detects_missing_class_docstring(self, tmp_project):
        _, netweaver, _ = tmp_project
        (netweaver / "noclass_doc.py").write_text(
            '"""Module doc."""\n'
            "\n"
            "class MyClass:\n"
            "    def method(self):\n"
            "        a = 1\n"
            "        b = 2\n"
            "        return a + b\n"
            "\n"
            "    def another(self):\n"
            "        x = 10\n"
            "        y = 20\n"
            "        return x + y\n"
        )
        gaps = scan_docstrings(netweaver, min_loc_for_check=1)
        class_gaps = [g for g in gaps if g.scope == "class"]
        assert any(g.name == "MyClass" for g in class_gaps)

    def test_detects_missing_function_docstring(self, tmp_project):
        _, netweaver, _ = tmp_project
        (netweaver / "nofn_doc.py").write_text(
            '"""Module doc."""\n'
            "\n"
            "def complex_function(x, y, z):\n"
            "    a = x + y\n"
            "    b = a * z\n"
            "    c = b - a\n"
            "    return c\n"
        )
        gaps = scan_docstrings(netweaver, min_loc_for_check=1)
        fn_gaps = [g for g in gaps if g.scope == "function"]
        assert any(g.name == "complex_function" for g in fn_gaps)

    def test_small_functions_skipped(self, tmp_project):
        _, netweaver, _ = tmp_project
        (netweaver / "small_fns.py").write_text(
            '"""Module doc."""\n'
            "\n"
            "def tiny(x):\n"
            "    return x\n"
        )
        gaps = scan_docstrings(netweaver)
        fn_gaps = [g for g in gaps if g.scope == "function" and g.name == "tiny"]
        assert len(fn_gaps) == 0

    def test_dunder_methods_skipped(self, tmp_project):
        _, netweaver, _ = tmp_project
        (netweaver / "dunders.py").write_text(
            '"""Module doc."""\n'
            "\n"
            "class Foo:\n"
            "    def __str__(self):\n"
            "        return 'foo'\n"
        )
        gaps = scan_docstrings(netweaver)
        fn_gaps = [g for g in gaps if g.name == "__str__"]
        assert len(fn_gaps) == 0

    def test_min_loc_filter(self, tmp_project):
        _, netweaver, _ = tmp_project
        (netweaver / "tiny_module.py").write_text("x = 1\ny = 2\n")
        gaps = scan_docstrings(netweaver, min_loc_for_check=100)
        assert not any(g.name == "tiny_module" for g in gaps)

    def test_nonexistent_dir(self):
        gaps = scan_docstrings("/nonexistent/path")
        assert gaps == []


# ---------------------------------------------------------------------------
# BacklogEntry tests
# ---------------------------------------------------------------------------

class TestBacklogEntry:
    """Tests for BacklogEntry dataclass."""

    def test_to_markdown(self):
        entry = BacklogEntry(
            id="AUTO-001",
            title="Test Entry",
            tiny_goal="Do a thing",
            files_to_touch=["netweaver/foo.py", "tests/test_foo.py"],
            risk_level="LOW",
            acceptance_checks=["Check A", "Check B"],
            source="todo_scan",
        )
        md = entry.to_markdown()
        assert "## AUTO-001 Test Entry" in md
        assert "tiny_goal: Do a thing" in md
        assert "files_to_touch: netweaver/foo.py, tests/test_foo.py" in md
        assert "- Check A" in md
        assert "- Check B" in md

    def test_to_dict(self):
        entry = BacklogEntry(
            id="AUTO-002",
            title="T",
            tiny_goal="G",
            files_to_touch=["a.py"],
            risk_level="MEDIUM",
            acceptance_checks=["C"],
            source="coverage_scan",
        )
        d = entry.to_dict()
        assert d["id"] == "AUTO-002"
        assert d["risk_level"] == "MEDIUM"
        assert d["source"] == "coverage_scan"

    def test_from_dict(self):
        d = {
            "id": "X-001",
            "title": "T",
            "tiny_goal": "G",
            "files_to_touch": ["a.py"],
            "risk_level": "HIGH",
            "acceptance_checks": ["C"],
            "source": "docstring_scan",
        }
        entry = BacklogEntry.from_dict(d)
        assert entry.id == "X-001"
        assert entry.risk_level == "HIGH"

    def test_round_trip(self):
        original = BacklogEntry(
            id="RT-001",
            title="Round Trip",
            tiny_goal="Test serialization",
            files_to_touch=["x.py", "y.py"],
            risk_level="MEDIUM",
            acceptance_checks=["C1", "C2", "C3"],
            source="todo_scan",
        )
        restored = BacklogEntry.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.files_to_touch == original.files_to_touch
        assert restored.acceptance_checks == original.acceptance_checks


# ---------------------------------------------------------------------------
# generate_entries tests
# ---------------------------------------------------------------------------

class TestGenerateEntries:
    """Tests for generate_entries function."""

    def test_todo_entries(self):
        todos = [
            TodoFinding("netweaver/foo.py", 5, "TODO", "do thing", "# TODO: do thing"),
            TodoFinding("netweaver/foo.py", 10, "FIXME", "fix thing", "# FIXME: fix thing"),
        ]
        entries = generate_entries(todo_findings=todos)
        assert len(entries) == 1  # Grouped by file
        assert entries[0].source == "todo_scan"
        assert "foo.py" in entries[0].title

    def test_coverage_entries(self):
        gaps = [
            CoverageGap("netweaver/orphan.py", "orphan", 150, False, 0.0),
        ]
        entries = generate_entries(coverage_gaps=gaps)
        assert len(entries) == 1
        assert entries[0].source == "coverage_scan"
        assert "orphan.py" in entries[0].title

    def test_docstring_entries(self):
        gaps = [
            DocstringGap("netweaver/mod.py", "module", "mod", 1),
            DocstringGap("netweaver/mod.py", "function", "func", 10),
        ]
        entries = generate_entries(docstring_gaps=gaps)
        assert len(entries) == 1  # Grouped by file
        assert entries[0].source == "docstring_scan"

    def test_deduplication_against_existing(self):
        todos = [
            TodoFinding("netweaver/foo.py", 5, "TODO", "x", "# TODO: x"),
        ]
        existing = "## NW-099 Resolve 1 TODO/FIXME/HACK in foo.py\n\ntiny_goal: ...\n"
        entries = generate_entries(todo_findings=todos, existing_backlog=existing)
        assert len(entries) == 0  # Deduped

    def test_empty_findings(self):
        entries = generate_entries()
        assert entries == []

    def test_each_entry_has_required_fields(self):
        todos = [TodoFinding("netweaver/a.py", 1, "TODO", "t", "# TODO: t")]
        gaps = [CoverageGap("netweaver/b.py", "b", 50, False, 0.0)]
        docgaps = [DocstringGap("netweaver/c.py", "module", "c", 1)]
        entries = generate_entries(
            todo_findings=todos,
            coverage_gaps=gaps,
            docstring_gaps=docgaps,
        )
        for entry in entries:
            assert entry.id
            assert entry.title
            assert entry.tiny_goal
            assert entry.files_to_touch
            assert entry.risk_level in ("LOW", "MEDIUM", "HIGH")
            assert entry.acceptance_checks


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelpers:
    """Tests for helper functions."""

    def test_parse_existing_backlog_ids(self):
        content = "## NW-001 First\n\n## NW-002 Second\n\n## NW-003 Third\n"
        titles = _parse_existing_backlog_ids(content)
        assert "first" in titles
        assert "second" in titles
        assert "third" in titles

    def test_generate_id_unique(self):
        existing = {"AUTO-001", "AUTO-002"}
        new_id = _generate_id(existing)
        assert new_id == "AUTO-003"

    def test_generate_id_custom_prefix(self):
        new_id = _generate_id(set(), prefix="BG")
        assert new_id == "BG-001"

    def test_assess_risk_high(self):
        assert _assess_risk(500, True) == "HIGH"

    def test_assess_risk_medium(self):
        assert _assess_risk(150, True) == "MEDIUM"

    def test_assess_risk_low(self):
        assert _assess_risk(50, True) == "LOW"

    def test_assess_risk_no_tests_medium(self):
        assert _assess_risk(50, False) == "MEDIUM"

    def test_count_loc(self, tmp_path):
        f = tmp_path / "loc.py"
        f.write_text("# comment\n\ndef foo():\n    pass\n")
        assert _count_loc(f) == 2  # def foo(): and pass

    def test_get_test_file_names(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_foo.py").write_text("")
        (tests / "test_bar.py").write_text("")
        (tests / "helper.py").write_text("")
        names = _get_test_file_names(tests)
        assert "foo" in names
        assert "bar" in names
        assert "helper" not in names


# ---------------------------------------------------------------------------
# render_backlog_addendum tests
# ---------------------------------------------------------------------------

class TestRenderAddendum:
    """Tests for render_backlog_addendum."""

    def test_renders_entries(self):
        entries = [
            BacklogEntry("A-1", "Title1", "Goal1", ["f.py"], "LOW", ["C1"], "todo_scan"),
            BacklogEntry("A-2", "Title2", "Goal2", ["g.py"], "MED", ["C2"], "coverage_scan"),
        ]
        md = render_backlog_addendum(entries)
        assert "## A-1 Title1" in md
        assert "## A-2 Title2" in md

    def test_empty_returns_empty(self):
        assert render_backlog_addendum([]) == ""


# ---------------------------------------------------------------------------
# BacklogGenerator integration tests
# ---------------------------------------------------------------------------

class TestBacklogGenerator:
    """Integration tests for BacklogGenerator class."""

    def test_scan_returns_findings(self, tmp_project):
        tmp, netweaver, tests = tmp_project
        (netweaver / "example.py").write_text(
            '"""Module."""\n# TODO: something\ndef foo():\n    pass\n'
        )
        gen = BacklogGenerator(
            netweaver_dir=netweaver,
            tests_dir=tests,
            backlog_path=tmp / "BACKLOG.md",
        )
        findings = gen.scan()
        assert "todos" in findings
        assert "coverage_gaps" in findings
        assert "docstring_gaps" in findings
        assert len(findings["todos"]) >= 1

    def test_run_produces_entries(self, tmp_project):
        tmp, netweaver, tests = tmp_project
        (netweaver / "todo_mod.py").write_text(
            '"""Module."""\n# TODO: fix this\ndef foo():\n    pass\n'
        )
        gen = BacklogGenerator(
            netweaver_dir=netweaver,
            tests_dir=tests,
            backlog_path=tmp / "BACKLOG.md",
        )
        entries = gen.run()
        assert len(entries) >= 1

    def test_append_to_backlog(self, tmp_project):
        tmp, netweaver, tests = tmp_project
        backlog = tmp / "BACKLOG.md"
        backlog.write_text("# Existing Backlog\n\n## NW-001 Old\n")
        (netweaver / "new_mod.py").write_text(
            '"""Module."""\n# TODO: new thing\ndef bar():\n    pass\n'
        )
        gen = BacklogGenerator(
            netweaver_dir=netweaver,
            tests_dir=tests,
            backlog_path=backlog,
        )
        entries = gen.run()
        count = gen.append_to_backlog(entries)
        assert count >= 1
        content = backlog.read_text()
        assert "AUTO-" in content

    def test_deduplication_in_pipeline(self, tmp_project):
        tmp, netweaver, tests = tmp_project
        backlog = tmp / "BACKLOG.md"
        # Pre-populate with matching entry
        backlog.write_text(
            "# Backlog\n\n## NW-099 Resolve 1 TODO/FIXME/HACK in existing.py\n"
        )
        (netweaver / "existing.py").write_text(
            '"""Module."""\n# TODO: already tracked\ndef baz():\n    pass\n'
        )
        gen = BacklogGenerator(
            netweaver_dir=netweaver,
            tests_dir=tests,
            backlog_path=backlog,
        )
        entries = gen.run()
        # Should be deduped
        todo_entries = [e for e in entries if e.source == "todo_scan"]
        assert len(todo_entries) == 0

    def test_summary(self, tmp_project):
        tmp, netweaver, tests = tmp_project
        gen = BacklogGenerator(
            netweaver_dir=netweaver,
            tests_dir=tests,
            backlog_path=tmp / "BL.md",
        )
        entries = [
            BacklogEntry("A", "T1", "G", ["f"], "L", ["C"], "todo_scan"),
            BacklogEntry("B", "T2", "G", ["f"], "L", ["C"], "todo_scan"),
            BacklogEntry("C", "T3", "G", ["f"], "L", ["C"], "coverage_scan"),
        ]
        summary = gen.summary(entries)
        assert summary["todo_scan"] == 2
        assert summary["coverage_scan"] == 1
        assert summary["total"] == 3

    def test_no_entries_appends_nothing(self, tmp_project):
        tmp, netweaver, tests = tmp_project
        backlog = tmp / "BL.md"
        backlog.write_text("# Empty\n")
        gen = BacklogGenerator(
            netweaver_dir=netweaver,
            tests_dir=tests,
            backlog_path=backlog,
        )
        count = gen.append_to_backlog([])
        assert count == 0

    def test_coverage_threshold(self, tmp_project):
        tmp, netweaver, tests = tmp_project
        (netweaver / "half.py").write_text('"""M."""\ndef x():\n    pass\n')
        gen = BacklogGenerator(
            netweaver_dir=netweaver,
            tests_dir=tests,
            backlog_path=tmp / "BL.md",
            coverage_threshold=0.9,
        )
        findings = gen.scan()
        # With 0.9 threshold, even tested modules might gap
        assert "coverage_gaps" in findings


# ---------------------------------------------------------------------------
# No browser/vendor import verification
# ---------------------------------------------------------------------------

class TestNoBrowserImports:
    """Verify no browser/vendor/playwright imports in module."""

    def test_no_playwright_import(self):
        import netweaver.backlog_generator as mod
        source = Path(mod.__file__).read_text()
        # Check actual import lines, not docstring mentions
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert "playwright" not in stripped.lower()

    def test_no_browser_import(self):
        import netweaver.backlog_generator as mod
        source = Path(mod.__file__).read_text()
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert "browser" not in stripped.lower()

    def test_no_vendor_import(self):
        import netweaver.backlog_generator as mod
        source = Path(mod.__file__).read_text()
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert "vendor" not in stripped.lower()
