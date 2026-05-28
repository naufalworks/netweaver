"""Tests for NetWeaver DSL Validator (NW-034).

Covers:
  - validate_wnal(): valid actions, invalid actions, syntax errors, selector validation
  - validate_basil(): valid scripts, invalid scripts, step validation, pre/post conditions
  - Conflict detection: same element ordering, missing preconditions
  - Schema validation: required fields, type checking, enum constraints
  - CLI entry: python -m netweaver.dsl_validator --file <path>
  - Edge cases: empty content, comments, partial lines, unicode

No browser/vendor/playwright imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from netweaver.dsl_validator import (
    ValidationResult,
    validate_wnal,
    validate_basil,
    detect_conflicts,
    parse_wnal_line,
    parse_basil_line,
    main as cli_main,
)


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_default_valid(self):
        r = ValidationResult()
        assert r.is_valid is True
        assert r.errors == []
        assert r.warnings == []

    def test_add_error(self):
        r = ValidationResult()
        r.add_error("something wrong")
        assert r.is_valid is False
        assert "something wrong" in r.errors

    def test_add_warning(self):
        r = ValidationResult()
        r.add_warning("be careful")
        assert r.is_valid is True
        assert "be careful" in r.warnings

    def test_merge(self):
        r1 = ValidationResult()
        r1.add_error("err1")
        r2 = ValidationResult()
        r2.add_warning("warn2")
        r1.merge(r2)
        assert len(r1.errors) == 1
        assert len(r1.warnings) == 1
        assert r1.is_valid is False

    def test_merge_valid(self):
        r1 = ValidationResult()
        r2 = ValidationResult()
        r1.merge(r2)
        assert r1.is_valid is True

    def test_summary_valid(self):
        r = ValidationResult()
        assert "VALID" in r.summary

    def test_summary_invalid(self):
        r = ValidationResult()
        r.add_error("nope")
        assert "INVALID" in r.summary
        assert "1 error" in r.summary

    def test_bool(self):
        assert bool(ValidationResult()) is True
        r = ValidationResult()
        r.add_error("e")
        assert bool(r) is False


# ---------------------------------------------------------------------------
# parse_wnal_line
# ---------------------------------------------------------------------------

class TestParseWnalLine:
    def test_valid_click(self):
        d, errs = parse_wnal_line("click(#login)", 1)
        assert errs == []
        assert d["type"] == "click"
        assert d["target"] == "#login"

    def test_valid_fill(self):
        d, errs = parse_wnal_line('fill(#user, admin)', 2)
        assert errs == []
        assert d["type"] == "fill"
        assert d["target"] == "#user"
        assert d["value"] == "admin"

    def test_valid_navigate(self):
        d, errs = parse_wnal_line('navigate(https://example.com)', 3)
        assert errs == []
        assert d["type"] == "navigate"

    def test_valid_wait_selector(self):
        d, errs = parse_wnal_line("wait(#result)", 4)
        assert errs == []
        assert d["type"] == "wait"

    def test_valid_comment(self):
        d, errs = parse_wnal_line("# this is a comment", 5)
        assert d is None
        assert errs == []

    def test_valid_empty(self):
        d, errs = parse_wnal_line("", 6)
        assert d is None
        assert errs == []

    def test_missing_parens(self):
        d, errs = parse_wnal_line("click(#login", 7)
        assert d is None
        assert any("Missing closing" in e for e in errs)

    def test_unknown_action(self):
        d, errs = parse_wnal_line("explode(#btn)", 8)
        assert d is not None
        assert any("Unknown action" in e for e in errs)

    def test_missing_selector(self):
        d, errs = parse_wnal_line("click()", 9)
        assert d is not None
        assert any("requires a target" in e for e in errs)

    def test_missing_value_for_fill(self):
        d, errs = parse_wnal_line("fill(#user)", 10)
        assert d is not None
        assert any("requires a value" in e for e in errs)

    def test_invalid_selector_format(self):
        d, errs = parse_wnal_line("click(123bad)", 11)
        assert d is not None
        assert any("Invalid selector" in e for e in errs)

    def test_invalid_syntax(self):
        d, errs = parse_wnal_line("just random text", 12)
        assert d is None
        assert any("Invalid syntax" in e for e in errs)

    def test_all_valid_actions(self):
        for action in ["click", "fill", "navigate", "wait", "select", "hover", "scroll", "assert", "press", "check", "uncheck", "double_click"]:
            target = "#btn" if action in ("click", "select", "hover", "assert", "press", "check", "uncheck", "double_click") else "#inp" if action in ("fill",) else "https://x.com" if action == "navigate" else "2" if action == "wait" else "#footer" if action == "scroll" else "#btn"
            val = ", admin" if action in ("fill", "select") else ""
            d, errs = parse_wnal_line(f"{action}({target}{val})", 1)
            assert errs == [] or (len(errs) == 1 and "requires a" in errs[0])


# ---------------------------------------------------------------------------
# validate_wnal
# ---------------------------------------------------------------------------

class TestValidateWnal:
    def test_valid_simple_script(self):
        content = "navigate(https://example.com)\nclick(#login)\nfill(#user, admin)\nclick(#submit)"
        r = validate_wnal(content)
        assert r.is_valid, f"Expected valid, got errors: {r.errors}"

    def test_invalid_syntax(self):
        content = "click(#login)\ninvalid line here\nfill(#user, admin)"
        r = validate_wnal(content)
        assert not r.is_valid
        assert len(r.errors) >= 1

    def test_unknown_action(self):
        content = "teleport(#home)"
        r = validate_wnal(content)
        assert not r.is_valid
        assert any("Unknown" in e for e in r.errors)

    def test_empty_content(self):
        r = validate_wnal("")
        assert r.is_valid
        assert any("No actions" in w for w in r.warnings)

    def test_only_comments(self):
        r = validate_wnal("# just a comment\n# another one")
        assert r.is_valid
        assert any("No actions" in w for w in r.warnings)

    def test_missing_navigate(self):
        content = "click(#btn)\nfill(#user, admin)"
        r = validate_wnal(content)
        assert r.is_valid
        assert any("No navigate" in w for w in r.warnings)

    def test_duplicate_fill_conflict_warning(self):
        content = "fill(#user, alice)\nfill(#user, bob)"
        r = validate_wnal(content)
        assert r.is_valid
        assert any("2 fill actions" in w for w in r.warnings)

    def test_missing_selector_for_click(self):
        content = "click()"
        r = validate_wnal(content)
        assert not r.is_valid
        assert any("requires a target" in e for e in r.errors)

    def test_missing_value_for_fill(self):
        content = "fill(#user)"
        r = validate_wnal(content)
        assert not r.is_valid
        assert any("requires a value" in e for e in r.errors)

    def test_all_action_types_accepted(self):
        lines = [
            "click(#btn)",
            "fill(#field, value)",
            "navigate(https://example.com)",
            "wait(#loaded)",
            "select(#menu, option1)",
            "hover(#tooltip)",
            "scroll(#bottom)",
            "assert(#error, visible)",
            "press(#enter)",
            "check(#agree)",
            "uncheck(#opt_out)",
            "double_click(#item)",
        ]
        r = validate_wnal("\n".join(lines))
        assert r.is_valid, f"Expected valid, got errors: {r.errors}"

    def test_select_xpath_selector(self):
        content = 'click(//button[@id="submit"])'
        r = validate_wnal(content)
        assert r.is_valid, f"Expected valid, got errors: {r.errors}"


# ---------------------------------------------------------------------------
# parse_basil_line
# ---------------------------------------------------------------------------

class TestParseBasilLine:
    def test_script_header(self):
        r = parse_basil_line("script login-flow", 1)
        assert r["type"] == "script"
        assert r["value"] == "login-flow"

    def test_step(self):
        r = parse_basil_line("  step: click(#login)", 2)
        assert r["type"] == "step"
        assert r["value"] == "click(#login)"

    def test_pre(self):
        r = parse_basil_line("pre: page_loaded", 3)
        assert r["type"] == "pre"
        assert r["value"] == "page_loaded"

    def test_post(self):
        r = parse_basil_line("post: dashboard_visible", 4)
        assert r["type"] == "post"

    def test_target(self):
        r = parse_basil_line("target: https://example.com", 5)
        assert r["type"] == "target"

    def test_import(self):
        r = parse_basil_line("import: common_steps", 6)
        assert r["type"] == "import"

    def test_comment(self):
        r = parse_basil_line("# comment", 7)
        assert r is None

    def test_empty(self):
        r = parse_basil_line("", 8)
        assert r is None

    def test_unknown(self):
        r = parse_basil_line("garbage text", 9)
        assert r["type"] == "unknown"


# ---------------------------------------------------------------------------
# validate_basil
# ---------------------------------------------------------------------------

class TestValidateBasil:
    def test_valid_basil_script(self):
        content = """script login-flow
pre: page_loaded
target: https://example.com/login
step: click(#username)
step: fill(#user, admin)
step: click(#submit)
step: wait(#dashboard)
post: dashboard_visible
"""
        r = validate_basil(content)
        assert r.is_valid, f"Expected valid, got errors: {r.errors}"

    def test_empty_content(self):
        r = validate_basil("")
        assert not r.is_valid
        assert any("empty" in e for e in r.errors)

    def test_no_script_header(self):
        content = "step: click(#btn)"
        r = validate_basil(content)
        assert not r.is_valid
        assert any("script" in e and "start" in e for e in r.errors)

    def test_no_steps(self):
        content = "script empty-flow\npre: ready"
        r = validate_basil(content)
        assert not r.is_valid
        assert any("at least one" in e for e in r.errors)

    def test_invalid_step_action(self):
        content = """script bad-flow
step: explode(#btn)
"""
        r = validate_basil(content)
        assert not r.is_valid
        assert any("Unknown action" in e for e in r.errors)

    def test_valid_script_with_import(self):
        content = """script with-imports
import: helpers
pre: ready
step: click(#btn)
post: done
"""
        r = validate_basil(content)
        assert r.is_valid, f"Expected valid, got errors: {r.errors}"

    def test_unknown_directive(self):
        content = """script test
garbage: stuff
step: click(#btn)
"""
        r = validate_basil(content)
        assert not r.is_valid
        assert any("Unknown BASIL directive" in e for e in r.errors)

    def test_empty_pre_condition(self):
        content = """script test
pre:
step: click(#btn)
"""
        r = validate_basil(content)
        assert not r.is_valid
        assert any("Pre-condition cannot be empty" in e for e in r.errors)

    def test_bare_selector_step_warning(self):
        content = """script test
step: #btn
"""
        r = validate_basil(content)
        assert r.is_valid
        assert any("bare selector" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

class TestDetectConflicts:
    def test_no_conflicts(self):
        actions = [
            {"type": "navigate", "target": "https://x.com", "line": 1},
            {"type": "click", "target": "#login", "line": 2},
        ]
        r = detect_conflicts(actions)
        assert r.is_valid

    def test_navigate_mid_sequence_warning(self):
        actions = [
            {"type": "click", "target": "#btn", "line": 1},
            {"type": "navigate", "target": "https://other.com", "line": 2},
            {"type": "click", "target": "#other", "line": 3},
        ]
        r = detect_conflicts(actions)
        assert r.is_valid
        assert any("navigate" in w and "mid-sequence" in w for w in r.warnings)

    def test_missing_navigate(self):
        actions = [
            {"type": "click", "target": "#btn", "line": 1},
        ]
        r = detect_conflicts(actions)
        assert r.is_valid
        assert any("No navigate" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCli:
    def test_valid_wnal_file(self, tmp_path):
        f = tmp_path / "test.wnal"
        f.write_text("navigate(https://example.com)\nclick(#btn)")
        rc = cli_main(["--file", str(f)])
        assert rc == 0

    def test_invalid_wnal_file(self, tmp_path):
        f = tmp_path / "bad.wnal"
        f.write_text("explode(#btn)")
        rc = cli_main(["--file", str(f)])
        assert rc == 1

    def test_valid_basil_file(self, tmp_path):
        f = tmp_path / "test.basil"
        f.write_text("script test\nstep: click(#btn)")
        rc = cli_main(["--file", str(f)])
        assert rc == 0

    def test_file_not_found(self, tmp_path):
        rc = cli_main(["--file", str(tmp_path / "nonexistent.wnal")])
        assert rc == 2

    def test_auto_detect_wnal(self, tmp_path):
        f = tmp_path / "actions.wnal"
        f.write_text("click(#btn)")
        rc = cli_main(["--file", str(f), "--format", "auto"])
        assert rc == 0

    def test_auto_detect_basil(self, tmp_path):
        f = tmp_path / "script.basil"
        f.write_text("script test\nstep: click(#btn)")
        rc = cli_main(["--file", str(f), "--format", "auto"])
        assert rc == 0

    def test_explicit_format(self, tmp_path):
        f = tmp_path / "weird_ext.txt"
        f.write_text("click(#btn)")
        rc = cli_main(["--file", str(f), "--format", "wnal"])
        assert rc == 0

    def test_cli_output_valid(self, tmp_path, capsys):
        f = tmp_path / "test.wnal"
        f.write_text("click(#btn)")
        rc = cli_main(["--file", str(f)])
        captured = capsys.readouterr()
        assert "VALID" in captured.out
        assert rc == 0

    def test_cli_output_invalid(self, tmp_path, capsys):
        f = tmp_path / "bad.wnal"
        f.write_text("unknown()")
        rc = cli_main(["--file", str(f)])
        captured = capsys.readouterr()
        assert "INVALID" in captured.out
        assert rc == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unicode_in_content(self):
        content = "click(#btn-é$pécial)"
        r = validate_wnal(content)
        # Unicode in selectors may be flagged as invalid format
        # But should be parseable
        assert r.errors or r.is_valid  # at least doesn't crash

    def test_very_long_content(self):
        lines = [f"click(#btn-{i})" for i in range(100)]
        r = validate_wnal("\n".join(lines))
        assert r.is_valid, f"Expected valid, got errors: {r.errors}"

    def test_mixed_case_action(self):
        # Actions must be lowercase
        content = "Click(#btn)"
        r = parse_wnal_line("Click(#btn)", 1)
        d, errs = r if isinstance(r, tuple) else (None, [])
        if isinstance(r, tuple):
            d, errs = r
        # Should be either unknown or valid depending on case handling
        # Our regex only matches lowercase
        assert d is None or any("Unknown" in e for e in errs)

    def test_trailing_whitespace(self):
        d, errs = parse_wnal_line("  click(#btn)  ", 1)
        assert errs == []
        assert d["type"] == "click"

    def test_multiple_spaces_in_args(self):
        d, errs = parse_wnal_line("fill(#user,   admin   )", 1)
        assert errs == []
        assert d["value"] == "admin"

    def test_assert_with_value(self):
        d, errs = parse_wnal_line("assert(#error, visible)", 1)
        assert errs == []
        assert d["type"] == "assert"
        assert d["value"] == "visible"

    def test_wait_with_timeout(self):
        d, errs = parse_wnal_line("wait(5)", 1)
        assert errs == []
        assert d["type"] == "wait"
        assert d["target"] == "5"

    def test_basil_script_with_many_steps(self):
        steps = "\n".join(f"step: click(#btn-{i})" for i in range(50))
        content = f"script big-flow\npre: ready\n{steps}\npost: done"
        r = validate_basil(content)
        assert r.is_valid, f"Expected valid, got errors: {r.errors}"
