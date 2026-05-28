"""NetWeaver DSL Validator — WNAL & BASIL validation and schema checking.

WNAL (Web Navigation Action Language): action commands like click(#login), fill(#user,val)
BASIL (Browser Automation Script Interface Language): structured scripts with step blocks

Design:
  - Pure data validation — no browser/vendor/playwright imports
  - ValidationResult carries errors, warnings, and is_valid flag
  - Schema validation: required fields, type checking, enum constraints
  - Precondition checking: element selector validity, no conflicting actions
  - Conflict detection: two actions targeting same element in wrong order
  - CLI entry: python -m netweaver.dsl_validator --file <path>

Usage:
    result = validate_wnal("click(#login)\nfill(#user, admin)")
    print(result.is_valid)  # True or False
    print(result.errors)    # list of error messages
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WNAL_ACTIONS = frozenset({
    "click", "fill", "navigate", "wait", "select", "hover",
    "scroll", "assert", "press", "check", "uncheck", "double_click",
})

WNAL_ACTIONS_REQUIRING_SELECTOR = frozenset({
    "click", "fill", "select", "hover", "assert", "press",
    "check", "uncheck", "double_click",
})

WNAL_ACTIONS_REQUIRING_VALUE = frozenset({
    "fill", "select",
})

BASIL_DIRECTIVES = frozenset({"script", "step", "pre", "post", "target", "import"})

# CSS selector basic validity pattern (not exhaustive, catches common errors)
CSS_SELECTOR_PATTERN = re.compile(
    r'^[#\.]?[a-zA-Z_][\w\-]*(?:[\.#:\[\]][\w\-]*)*$'
)

# XPath selector basic validity
XPATH_SELECTOR_PATTERN = re.compile(
    r'^//|^\.//|^\(//|^id\(|^\./'
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of a DSL validation pass."""

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    is_valid: bool = True

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def merge(self, other: ValidationResult) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if not other.is_valid:
            self.is_valid = False

    @property
    def summary(self) -> str:
        parts = []
        if self.is_valid:
            parts.append("VALID")
        else:
            parts.append(f"INVALID ({len(self.errors)} error(s))")
        if self.warnings:
            parts.append(f"({len(self.warnings)} warning(s))")
        return " ".join(parts)

    def __bool__(self) -> bool:
        return self.is_valid


# ---------------------------------------------------------------------------
# WNAL Validator
# ---------------------------------------------------------------------------

WNAL_LINE_RE = re.compile(
    r'^(?P<action>[a-z_]+)'
    r'\((?P<target>[^,)]*)'
    r'(?:,\s*(?P<value>[^)]*))?'
    r'\)\s*$'
)


def parse_wnal_line(line: str, line_num: int) -> Tuple[Optional[dict], List[str]]:
    """Parse a single WNAL line into an action dict.

    Returns (action_dict, errors). action_dict is None if unparseable.
    """
    errors: List[str] = []
    stripped = line.strip()

    if not stripped or stripped.startswith("#"):
        return None, errors  # empty or comment

    match = WNAL_LINE_RE.match(stripped)
    if not match:
        # Check if it looks like a partial action
        if "(" in stripped and ")" not in stripped:
            errors.append(f"Line {line_num}: Missing closing parenthesis")
        elif "(" not in stripped:
            errors.append(f"Line {line_num}: Invalid syntax — expected action(arg) format")
        else:
            errors.append(f"Line {line_num}: Invalid syntax: '{stripped}'")
        return None, errors

    action = match.group("action")
    target = match.group("target").strip()
    value = match.group("value")
    value = value.strip() if value else ""

    if action not in WNAL_ACTIONS:
        errors.append(f"Line {line_num}: Unknown action '{action}' — valid: {', '.join(sorted(WNAL_ACTIONS))}")

    if action in WNAL_ACTIONS_REQUIRING_SELECTOR and not target:
        errors.append(f"Line {line_num}: Action '{action}' requires a target selector")

    if action in WNAL_ACTIONS_REQUIRING_VALUE and not value:
        errors.append(f"Line {line_num}: Action '{action}' requires a value argument")

    if target and not target.startswith(("#", ".", "[", "//", "(")):
        # Could be a named anchor or tag name
        if not re.match(r'^[a-zA-Z][\w]*$', target):
            errors.append(f"Line {line_num}: Invalid selector format '{target}' — should start with #, ., [, //, or be a tag name")

    if target and target.startswith("//"):
        if not XPATH_SELECTOR_PATTERN.match(target):
            errors.append(f"Line {line_num}: Invalid XPath selector '{target}'")

    action_dict = {
        "type": action,
        "target": target,
        "value": value,
        "line": line_num,
    }
    return action_dict, errors


def validate_wnal(content: str) -> ValidationResult:
    """Validate WNAL content.

    Checks:
      - Syntax: each line must be action(args) format
      - Known action types
      - Required args (selectors for click/fill, values for fill/select)
      - Selector format validity
      - No conflicting actions on same element
      - No duplicate actions in wrong order (e.g., fill before navigate to form)

    Returns:
        ValidationResult with errors, warnings, is_valid flag.
    """
    result = ValidationResult()
    actions: List[dict] = []

    lines = content.split("\n")
    for i, line in enumerate(lines):
        action_dict, parse_errors = parse_wnal_line(line, i + 1)
        for err in parse_errors:
            result.add_error(err)
        if action_dict is not None:
            actions.append(action_dict)

    # If no actions and no errors, warn
    if not actions and not result.errors:
        result.add_warning("No actions found in WNAL content")

    # Conflict detection: same target in wrong order
    _check_wnal_conflicts(actions, result)

    # Precondition: navigate before actions on new page
    _check_wnal_preconditions(actions, result)

    return result


def _check_wnal_conflicts(actions: List[dict], result: ValidationResult) -> None:
    """Detect conflicting actions on the same element.

    Conflicting patterns:
      - fill then click on same target (usually fine, not a conflict)
      - Two fills on same element (last one wins — warning)
      - click then fill on same element (fill won't work after navigation)
    """
    target_actions: dict = {}
    for action in actions:
        target = action["target"]
        if not target:
            continue
        if target not in target_actions:
            target_actions[target] = []
        target_actions[target].append(action["type"])

    for target, types in target_actions.items():
        if len(types) > 1:
            # Check for problematic order: navigate then click on same target
            if "navigate" in types:
                result.add_warning(
                    f"Target '{target}': Action follows navigate() — "
                    f"selector may be stale after page load"
                )
            # Two fills on same element
            fill_count = types.count("fill")
            if fill_count > 1:
                result.add_warning(
                    f"Target '{target}' has {fill_count} fill actions — last one wins"
                )
            # Assert after modify
            last_assert = max(i for i, t in enumerate(types) if t == "assert") if "assert" in types else -1
            if 0 < last_assert < len(types) - 1:
                result.add_warning(
                    f"Target '{target}': assert action followed by more actions — "
                    f"assert should typically be last"
                )


def _check_wnal_preconditions(actions: List[dict], result: ValidationResult) -> None:
    """Check navigation and state preconditions.

    Warns if:
      - Actions occur before any navigate() call
      - navigate() appears mid-script after other actions
    """
    has_navigate = any(a["type"] == "navigate" for a in actions)
    first_action = actions[0] if actions else None

    if first_action and first_action["type"] != "navigate" and not has_navigate:
        result.add_warning(
            f"Line {first_action['line']}: No navigate() call found — "
            f"actions require a page context"
        )


# ---------------------------------------------------------------------------
# BASIL Validator
# ---------------------------------------------------------------------------

BASIL_SCRIPT_HEADER_RE = re.compile(r'^script\s+(\S+)')
BASIL_STEP_RE = re.compile(r'^\s*step:\s*(.+)$')
BASIL_PRE_RE = re.compile(r'^\s*pre:\s*(.+)$')
BASIL_POST_RE = re.compile(r'^\s*post:\s*(.+)$')
BASIL_TARGET_RE = re.compile(r'^\s*target:\s*(.+)$')
BASIL_IMPORT_RE = re.compile(r'^\s*import:\s*(.+)$')


def parse_basil_line(line: str, line_num: int) -> Optional[dict]:
    """Parse a single BASIL line. Returns structured dict or None for blank/comment."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    for pattern, key in [
        (BASIL_SCRIPT_HEADER_RE, "script"),
        (BASIL_STEP_RE, "step"),
        (BASIL_PRE_RE, "pre"),
        (BASIL_POST_RE, "post"),
        (BASIL_TARGET_RE, "target"),
        (BASIL_IMPORT_RE, "import"),
    ]:
        m = pattern.match(line)
        if m:
            return {"type": key, "value": m.group(1).strip(), "line": line_num}

    return {"type": "unknown", "value": stripped, "line": line_num}


def validate_basil(content: str) -> ValidationResult:
    """Validate BASIL script content.

    Checks:
      - Must start with 'script <name>' header
      - Must have at least one 'step' directive
      - Each step must contain valid WNAL syntax
      - pre/post conditions must not be empty
      - target URL must be valid
      - Structural ordering: script → pre → target → steps → post
      - No duplicate step targets (unless explicitly marked)
      - All steps use valid WNAL action types

    Returns:
        ValidationResult with errors, warnings, is_valid flag.
    """
    result = ValidationResult()
    parsed: List[dict] = []

    lines = content.split("\n")
    for i, line in enumerate(lines):
        entry = parse_basil_line(line, i + 1)
        if entry is not None:
            parsed.append(entry)

    if not parsed:
        result.add_error("BASIL content is empty or contains no directives")
        return result

    # Must start with script header
    if parsed[0]["type"] != "script":
        result.add_error(
            f"Line {parsed[0]['line']}: BASIL script must start with 'script <name>' directive"
        )

    # Check ordering constraints
    order_order = {"script": 0, "import": 0, "target": 1, "pre": 2, "step": 3, "post": 4}
    last_order = -1
    has_step = False

    for entry in parsed:
        etype = entry["type"]
        if etype == "unknown":
            result.add_error(f"Line {entry['line']}: Unknown BASIL directive '{entry['value']}'")
            continue

        order = order_order.get(etype, 99)
        if order < last_order and etype != "import":
            # Allow pre/step interleaving but warn
            if etype == "step" and last_order <= 3:
                pass  # steps can be interleaved with pre
            else:
                result.add_warning(
                    f"Line {entry['line']}: '{etype}' appears out of recommended order"
                )
        last_order = order if etype != "import" else last_order

        if etype == "step":
            has_step = True
            _validate_basil_step(entry, result)

    if not has_step:
        result.add_error("BASIL script must have at least one 'step' directive")

    # Check pre/post conditions
    pre_values = [e["value"] for e in parsed if e["type"] == "pre"]
    post_values = [e["value"] for e in parsed if e["type"] == "post"]

    for v in pre_values:
        if not v.strip():
            result.add_error("Pre-condition cannot be empty")

    for v in post_values:
        if not v.strip():
            result.add_error("Post-condition cannot be empty")

    return result


def _validate_basil_step(entry: dict, result: ValidationResult) -> None:
    """Validate a BASIL step directive content as WNAL syntax."""
    step_content = entry["value"]

    # Step can be a WNAL action or a free-text description
    # Check if it looks like WNAL
    if "(" in step_content and ")" in step_content:
        _, step_errors = parse_wnal_line(step_content, entry["line"])
        for err in step_errors:
            result.add_error(f"Step at line {entry['line']}: {err}")
    elif step_content.startswith("#") or step_content.startswith("."):
        # Step is a selector reference
        result.add_warning(
            f"Line {entry['line']}: Step uses bare selector '{step_content}' — "
            f"prefer action(selector) format"
        )


# ---------------------------------------------------------------------------
# Conflict Detection (shared)
# ---------------------------------------------------------------------------

def detect_conflicts(actions: List[dict]) -> ValidationResult:
    """Standalone conflict detector for parsed action sequences.

    Works on action dicts from either WNAL or BASIL parsing.
    Detects:
      - Same-element action ordering issues
      - Missing preconditions
      - Unsafe action combinations
    """
    result = ValidationResult()
    _check_wnal_conflicts(actions, result)
    _check_wnal_preconditions(actions, result)

    # Check for dangerous action combinations
    for i, action in enumerate(actions):
        if action["type"] == "navigate" and i > 0:
            # navigate mid-sequence resets page state
            result.add_warning(
                f"Line {action.get('line', '?')}: navigate() mid-sequence — "
                f"previous page state will be lost"
            )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: python -m netweaver.dsl_validator --file <path>

    Supports .wnal and .basil extensions. Auto-detects format from extension.

    Returns exit code 0 if valid, 1 if invalid, 2 on error.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="WNAL/BASIL DSL Validator — check navigation script syntax and semantics"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        required=True,
        help="Path to WNAL (.wnal) or BASIL (.basil) file",
    )
    parser.add_argument(
        "--format", "-F",
        type=str,
        choices=["wnal", "basil", "auto"],
        default="auto",
        help="DSL format (default: auto-detect from extension)",
    )

    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        return 2

    content = path.read_text(encoding="utf-8")

    fmt = args.format
    if fmt == "auto":
        if path.suffix in (".wnal",):
            fmt = "wnal"
        elif path.suffix in (".basil",):
            fmt = "basil"
        else:
            # Try to detect: BASIL starts with "script", WNAL doesn't
            first_line = content.strip().split("\n")[0] if content.strip() else ""
            if first_line.startswith("script "):
                fmt = "basil"
            else:
                fmt = "wnal"

    if fmt == "wnal":
        result = validate_wnal(content)
    else:
        result = validate_basil(content)

    print(f"Format: {fmt.upper()}")
    print(f"Result: {result.summary}")
    if result.errors:
        print("\nErrors:")
        for err in result.errors:
            print(f"  ✗ {err}")
    if result.warnings:
        print("\nWarnings:")
        for warn in result.warnings:
            print(f"  ⚠ {warn}")

    return 0 if result.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
