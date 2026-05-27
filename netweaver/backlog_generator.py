"""NetWeaver Auto-Backlog Generator — NW-028.

Scans the codebase for TODO/FIXME/HACK comments, untested modules,
and missing docstrings, then auto-generates backlog entries in BACKLOG.md
format. Designed to run as a daemon sub-task every N cycles.

Key components:
- BacklogEntry: dataclass representing a single backlog item
- TodoFinding: dataclass for a discovered TODO/FIXME/HACK comment
- CoverageGap: dataclass for a module lacking sufficient test coverage
- DocstringGap: dataclass for a module/function missing docstrings
- BacklogGenerator: main orchestrator — scan, deduplicate, format

No browser/vendor/playwright imports.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TodoFinding:
    """A TODO/FIXME/HACK comment discovered in source code."""
    file_path: str
    line_number: int
    tag: str  # TODO, FIXME, HACK
    text: str
    context: str  # surrounding code context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "tag": self.tag,
            "text": self.text,
            "context": self.context,
        }


@dataclass
class CoverageGap:
    """A module lacking sufficient test coverage."""
    module_path: str
    module_name: str
    loc: int  # lines of code
    has_test_file: bool
    estimated_coverage: float  # 0.0 = no tests, 1.0 = fully tested

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_path": self.module_path,
            "module_name": self.module_name,
            "loc": self.loc,
            "has_test_file": self.has_test_file,
            "estimated_coverage": self.estimated_coverage,
        }


@dataclass
class DocstringGap:
    """A module or function missing docstrings."""
    file_path: str
    scope: str  # "module" or "function" or "class"
    name: str
    line_number: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "scope": self.scope,
            "name": self.name,
            "line_number": self.line_number,
        }


@dataclass
class BacklogEntry:
    """A generated backlog entry in BACKLOG.md format."""
    id: str
    title: str
    tiny_goal: str
    files_to_touch: List[str]
    risk_level: str  # LOW, MEDIUM, HIGH
    acceptance_checks: List[str]
    source: str  # "todo_scan", "coverage_scan", "docstring_scan"

    def to_markdown(self) -> str:
        """Render as BACKLOG.md formatted entry."""
        lines = [
            f"## {self.id} {self.title}",
            "",
            f"tiny_goal: {self.tiny_goal}",
            "",
            f"files_to_touch: {', '.join(self.files_to_touch)}",
            "",
            "acceptance_checks:",
        ]
        for check in self.acceptance_checks:
            lines.append(f"- {check}")
        lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "tiny_goal": self.tiny_goal,
            "files_to_touch": self.files_to_touch,
            "risk_level": self.risk_level,
            "acceptance_checks": self.acceptance_checks,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BacklogEntry":
        return cls(
            id=data["id"],
            title=data["title"],
            tiny_goal=data["tiny_goal"],
            files_to_touch=data["files_to_touch"],
            risk_level=data["risk_level"],
            acceptance_checks=data["acceptance_checks"],
            source=data["source"],
        )


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches TODO, FIXME, HACK in comments (case-insensitive)
TODO_PATTERN = re.compile(
    r"#\s*(TODO|FIXME|HACK)\b[:\s]*(.*)",
    re.IGNORECASE,
)

# Pattern to extract module name from test filename
TEST_FILE_PATTERN = re.compile(r"^test_(.+)\.py$")


# ---------------------------------------------------------------------------
# Scanning functions
# ---------------------------------------------------------------------------

def scan_todos(
    root_dir: str | Path,
    glob_pattern: str = "*.py",
    exclude_patterns: Optional[List[str]] = None,
) -> List[TodoFinding]:
    """Scan Python files for TODO/FIXME/HACK comments.

    Args:
        root_dir: Directory to scan recursively.
        glob_pattern: File glob pattern (default: *.py).
        exclude_patterns: List of filename patterns to exclude.

    Returns:
        List of TodoFinding objects.
    """
    root = Path(root_dir)
    if not root.exists():
        return []

    excludes = set(exclude_patterns or [])
    findings: List[TodoFinding] = []

    for py_file in sorted(root.rglob(glob_pattern)):
        # Skip excluded patterns
        if any(pat in str(py_file) for pat in excludes):
            continue

        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            continue

        lines = content.split("\n")
        for i, line in enumerate(lines, start=1):
            match = TODO_PATTERN.search(line)
            if match:
                tag = match.group(1).upper()
                text = match.group(2).strip()
                # Get context: the line itself
                context = line.strip()
                findings.append(TodoFinding(
                    file_path=str(py_file),
                    line_number=i,
                    tag=tag,
                    text=text,
                    context=context,
                ))

    return findings


def _count_loc(file_path: Path) -> int:
    """Count non-empty, non-comment lines of code in a Python file."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return 0

    count = 0
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def _get_test_file_names(tests_dir: Path) -> Set[str]:
    """Get set of module names that have corresponding test files.

    Maps test_foo.py → foo, test_netweaver_observer.py → netweaver_observer, etc.
    """
    test_modules: Set[str] = set()
    if not tests_dir.exists():
        return test_modules

    for test_file in tests_dir.rglob("test_*.py"):
        name = test_file.stem  # e.g. test_executor → test_executor
        # Strip test_ prefix to get module name
        if name.startswith("test_"):
            module_name = name[5:]  # e.g. executor
            test_modules.add(module_name)

    return test_modules


def scan_coverage(
    netweaver_dir: str | Path,
    tests_dir: str | Path,
    threshold: float = 0.5,
) -> List[CoverageGap]:
    """Identify modules with less than threshold test coverage.

    Uses heuristic: if a test file exists for a module, estimates ~70% coverage.
    If no test file exists, estimates 0% coverage.

    Args:
        netweaver_dir: Directory containing source modules.
        tests_dir: Directory containing test files.
        threshold: Coverage threshold below which a gap is reported.

    Returns:
        List of CoverageGap objects for modules below threshold.
    """
    src_dir = Path(netweaver_dir)
    tst_dir = Path(tests_dir)

    if not src_dir.exists():
        return []

    tested_modules = _get_test_file_names(tst_dir)
    gaps: List[CoverageGap] = []

    for py_file in sorted(src_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue

        module_name = py_file.stem
        has_test = module_name in tested_modules
        loc = _count_loc(py_file)

        # Heuristic coverage estimation
        if has_test:
            estimated = 0.7  # Has tests → assume reasonable coverage
        else:
            estimated = 0.0  # No tests → 0% coverage

        if estimated < threshold:
            gaps.append(CoverageGap(
                module_path=str(py_file),
                module_name=module_name,
                loc=loc,
                has_test_file=has_test,
                estimated_coverage=estimated,
            ))

    return gaps


def scan_docstrings(
    root_dir: str | Path,
    glob_pattern: str = "*.py",
    check_classes: bool = True,
    check_functions: bool = True,
    min_loc_for_check: int = 10,
) -> List[DocstringGap]:
    """Scan Python files for missing docstrings on modules, classes, and functions.

    Args:
        root_dir: Directory to scan.
        glob_pattern: File glob pattern.
        check_classes: Whether to check class docstrings.
        check_functions: Whether to check function docstrings.
        min_loc_for_check: Minimum LOC to bother checking.

    Returns:
        List of DocstringGap objects.
    """
    root = Path(root_dir)
    if not root.exists():
        return []

    gaps: List[DocstringGap] = []

    for py_file in sorted(root.rglob(glob_pattern)):
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            continue

        loc = _count_loc(py_file)
        if loc < min_loc_for_check:
            continue

        try:
            tree = ast.parse(content, filename=str(py_file))
        except SyntaxError:
            continue

        # Check module docstring
        if not ast.get_docstring(tree):
            gaps.append(DocstringGap(
                file_path=str(py_file),
                scope="module",
                name=py_file.stem,
                line_number=1,
            ))

        # Walk AST for classes and functions
        for node in ast.walk(tree):
            if check_classes and isinstance(node, ast.ClassDef):
                if not ast.get_docstring(node):
                    gaps.append(DocstringGap(
                        file_path=str(py_file),
                        scope="class",
                        name=node.name,
                        line_number=node.lineno,
                    ))

            if check_functions and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip dunder methods except __init__
                if node.name.startswith("_") and node.name != "__init__":
                    continue
                # Skip very small functions (< 3 body statements)
                if len(node.body) < 3:
                    continue
                if not ast.get_docstring(node):
                    gaps.append(DocstringGap(
                        file_path=str(py_file),
                        scope="function",
                        name=node.name,
                        line_number=node.lineno,
                    ))

    return gaps


# ---------------------------------------------------------------------------
# Backlog generation
# ---------------------------------------------------------------------------

def _parse_existing_backlog_ids(backlog_content: str) -> Set[str]:
    """Extract existing entry titles from BACKLOG.md content for dedup."""
    titles: Set[str] = set()
    for line in backlog_content.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            # Extract title portion after ID (e.g. "## NW-028 Auto-Backlog" → "Auto-Backlog")
            parts = line[3:].split(" ", 1)
            if len(parts) == 2:
                titles.add(parts[1].strip().lower())
            elif len(parts) == 1:
                titles.add(parts[0].strip().lower())
    return titles


def _generate_id(existing_ids: Set[str], prefix: str = "AUTO") -> str:
    """Generate a unique backlog entry ID."""
    counter = 1
    while True:
        candidate = f"{prefix}-{counter:03d}"
        if candidate not in existing_ids:
            return candidate
        counter += 1


def _assess_risk(loc: int, has_tests: bool) -> str:
    """Assess risk level based on module size and test status."""
    if loc > 300:
        return "HIGH"
    elif loc > 100 or not has_tests:
        return "MEDIUM"
    return "LOW"


def _todos_to_entries(
    findings: List[TodoFinding],
    existing_ids: Set[str],
    existing_titles: Set[str],
) -> List[BacklogEntry]:
    """Convert TODO findings into grouped backlog entries."""
    # Group by file
    by_file: Dict[str, List[TodoFinding]] = {}
    for f in findings:
        by_file.setdefault(f.file_path, []).append(f)

    entries: List[BacklogEntry] = []
    for file_path, file_findings in by_file.items():
        module_name = Path(file_path).stem
        title = f"Resolve {len(file_findings)} TODO/FIXME/HACK in {module_name}.py"

        # Dedup: skip if similar title exists
        if title.lower() in existing_titles:
            continue

        entry_id = _generate_id(existing_ids)
        existing_ids.add(entry_id)
        existing_titles.add(title.lower())

        # Build acceptance checks from individual findings
        checks = []
        for finding in file_findings[:10]:  # Cap at 10
            checks.append(
                f"{finding.tag} L{finding.line_number}: {finding.text or '(no description)'}"
            )
        if len(file_findings) > 10:
            checks.append(f"... and {len(file_findings) - 10} more")
        checks.append("All existing tests remain green")

        # Determine risk based on tag severity
        has_fixme = any(f.tag == "FIXME" for f in file_findings)
        has_hack = any(f.tag == "HACK" for f in file_findings)
        risk = "HIGH" if has_hack else ("MEDIUM" if has_fixme else "LOW")

        entries.append(BacklogEntry(
            id=entry_id,
            title=title,
            tiny_goal=f"Resolve {len(file_findings)} TODO/FIXME/HACK comments in {module_name}.py. "
                      f"Address each item or document why it should remain.",
            files_to_touch=[file_path],
            risk_level=risk,
            acceptance_checks=checks,
            source="todo_scan",
        ))

    return entries


def _coverage_gaps_to_entries(
    gaps: List[CoverageGap],
    existing_ids: Set[str],
    existing_titles: Set[str],
) -> List[BacklogEntry]:
    """Convert coverage gaps into backlog entries."""
    entries: List[BacklogEntry] = []

    for gap in gaps:
        title = f"Add tests for {gap.module_name}.py ({gap.loc} LOC, 0% coverage)"

        if title.lower() in existing_titles:
            continue

        entry_id = _generate_id(existing_ids)
        existing_ids.add(entry_id)
        existing_titles.add(title.lower())

        risk = _assess_risk(gap.loc, gap.has_test_file)

        entries.append(BacklogEntry(
            id=entry_id,
            title=title,
            tiny_goal=f"Add comprehensive tests for {gap.module_name}.py "
                      f"({gap.loc} LOC, currently no test file). "
                      f"Target ≥80% coverage with mocked dependencies.",
            files_to_touch=[gap.module_path, f"tests/test_{gap.module_name}.py"],
            risk_level=risk,
            acceptance_checks=[
                f"tests/test_{gap.module_name}.py created with 15+ tests",
                f"Coverage ≥80% for {gap.module_name}.py",
                "All existing tests remain green",
                "No browser/vendor imports",
            ],
            source="coverage_scan",
        ))

    return entries


def _docstring_gaps_to_entries(
    gaps: List[DocstringGap],
    existing_ids: Set[str],
    existing_titles: Set[str],
) -> List[BacklogEntry]:
    """Convert docstring gaps into grouped backlog entries (by file)."""
    by_file: Dict[str, List[DocstringGap]] = {}
    for g in gaps:
        by_file.setdefault(g.file_path, []).append(g)

    entries: List[BacklogEntry] = []
    for file_path, file_gaps in by_file.items():
        module_name = Path(file_path).stem
        n_missing = len(file_gaps)
        title = f"Add docstrings to {module_name}.py ({n_missing} missing)"

        if title.lower() in existing_titles:
            continue

        entry_id = _generate_id(existing_ids)
        existing_ids.add(entry_id)
        existing_titles.add(title.lower())

        checks = []
        for g in file_gaps[:8]:
            checks.append(f"{g.scope} '{g.name}' at L{g.line_number}")
        if len(file_gaps) > 8:
            checks.append(f"... and {len(file_gaps) - 8} more")
        checks.append("All existing tests remain green")

        entries.append(BacklogEntry(
            id=entry_id,
            title=title,
            tiny_goal=f"Add missing docstrings to {n_missing} items in {module_name}.py. "
                      f"Include purpose, args, returns, and usage examples.",
            files_to_touch=[file_path],
            risk_level="LOW",
            acceptance_checks=checks,
            source="docstring_scan",
        ))

    return entries


def generate_entries(
    todo_findings: Optional[List[TodoFinding]] = None,
    coverage_gaps: Optional[List[CoverageGap]] = None,
    docstring_gaps: Optional[List[DocstringGap]] = None,
    existing_backlog: str = "",
) -> List[BacklogEntry]:
    """Generate backlog entries from scan findings with deduplication.

    Args:
        todo_findings: Results from scan_todos().
        coverage_gaps: Results from scan_coverage().
        docstring_gaps: Results from scan_docstrings().
        existing_backlog: Current BACKLOG.md content for deduplication.

    Returns:
        List of new BacklogEntry objects (deduplicated against existing).
    """
    existing_titles = _parse_existing_backlog_ids(existing_backlog)
    existing_ids: Set[str] = set()

    # Also parse existing IDs
    for line in existing_backlog.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            parts = line[3:].split(" ", 1)
            if parts:
                existing_ids.add(parts[0].strip())

    entries: List[BacklogEntry] = []

    if todo_findings:
        entries.extend(_todos_to_entries(todo_findings, existing_ids, existing_titles))

    if coverage_gaps:
        entries.extend(_coverage_gaps_to_entries(coverage_gaps, existing_ids, existing_titles))

    if docstring_gaps:
        entries.extend(_docstring_gaps_to_entries(docstring_gaps, existing_ids, existing_titles))

    return entries


def render_backlog_addendum(entries: List[BacklogEntry]) -> str:
    """Render a list of backlog entries as a markdown addendum.

    Args:
        entries: List of BacklogEntry objects.

    Returns:
        Markdown string suitable for appending to BACKLOG.md.
    """
    if not entries:
        return ""

    parts = []
    for entry in entries:
        parts.append(entry.to_markdown())

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

class BacklogGenerator:
    """Orchestrates the full backlog generation pipeline.

    Scans for TODOs, coverage gaps, and docstring gaps, then produces
    deduplicated backlog entries in BACKLOG.md format.

    Usage:
        gen = BacklogGenerator(
            netweaver_dir="netweaver/",
            tests_dir="tests/",
            backlog_path=".tini/netweaver/BACKLOG.md",
        )
        entries = gen.run()
        gen.append_to_backlog(entries)
    """

    def __init__(
        self,
        netweaver_dir: str | Path = "netweaver",
        tests_dir: str | Path = "tests",
        backlog_path: str | Path = ".tini/netweaver/BACKLOG.md",
        coverage_threshold: float = 0.5,
    ):
        self.netweaver_dir = Path(netweaver_dir)
        self.tests_dir = Path(tests_dir)
        self.backlog_path = Path(backlog_path)
        self.coverage_threshold = coverage_threshold

    def scan(self) -> Dict[str, Any]:
        """Run all scans and return raw findings."""
        return {
            "todos": scan_todos(self.netweaver_dir),
            "coverage_gaps": scan_coverage(
                self.netweaver_dir,
                self.tests_dir,
                threshold=self.coverage_threshold,
            ),
            "docstring_gaps": scan_docstrings(self.netweaver_dir),
        }

    def run(self) -> List[BacklogEntry]:
        """Run full pipeline: scan → generate → deduplicate."""
        findings = self.scan()
        existing_content = ""
        if self.backlog_path.exists():
            try:
                existing_content = self.backlog_path.read_text(encoding="utf-8")
            except (OSError, PermissionError):
                pass

        return generate_entries(
            todo_findings=findings["todos"],
            coverage_gaps=findings["coverage_gaps"],
            docstring_gaps=findings["docstring_gaps"],
            existing_backlog=existing_content,
        )

    def append_to_backlog(self, entries: List[BacklogEntry]) -> int:
        """Append new entries to BACKLOG.md. Returns count of entries added."""
        if not entries:
            return 0

        addendum = render_backlog_addendum(entries)
        if not addendum:
            return 0

        # Ensure parent dir exists
        self.backlog_path.parent.mkdir(parents=True, exist_ok=True)

        # Append
        with open(self.backlog_path, "a", encoding="utf-8") as f:
            f.write("\n")
            f.write(addendum)

        return len(entries)

    def summary(self, entries: List[BacklogEntry]) -> Dict[str, int]:
        """Return summary counts by source type."""
        counts: Dict[str, int] = {}
        for entry in entries:
            counts[entry.source] = counts.get(entry.source, 0) + 1
        counts["total"] = len(entries)
        return counts
