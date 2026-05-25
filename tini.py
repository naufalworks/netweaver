#!/usr/bin/env python3
"""TINI: tiny goal-aligned wrapper for Claude Code.

Minimal MVP:
- start: write main/tiny goal into .tini/current_step.md
- prompt: print a Claude Code prompt constrained to the current tiny goal
- done: append a completion note template to DEV_LOG.md
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TINI_DIR = ROOT / ".tini"
CURRENT = TINI_DIR / "current_step.md"
DEV_LOG = ROOT / "DEV_LOG.md"
PROJECT_GOAL = ROOT / "PROJECT_GOAL.md"
NEGATIVE_CACHE = TINI_DIR / "negative-cache.md"
READ_MTIMES = TINI_DIR / "read-mtimes.tsv"

HIGH_RISK_PATH_PARTS = (".env", "auth", "secret", "credential", "migrations")
MEDIUM_RISK_PATH_PARTS = ("config", "settings", "deploy", "docker", "requirements")
HIGH_RISK_KEYWORDS = ("password", "token", "api_key", "secret", "drop table", "delete from")
MEDIUM_RISK_KEYWORDS = ("todo", "fixme", "subprocess", "requests", "permission")


def ensure_files() -> None:
    TINI_DIR.mkdir(exist_ok=True)
    if not DEV_LOG.exists():
        DEV_LOG.write_text("# Development Log\n")
    if not PROJECT_GOAL.exists():
        PROJECT_GOAL.write_text("# Project Goal\n\n## Main Goal\nTBD\n")
    if not NEGATIVE_CACHE.exists():
        NEGATIVE_CACHE.write_text("# TINI Negative Cache\n\nFailed attempts to consult before planning.\n")
    if not READ_MTIMES.exists():
        READ_MTIMES.write_text("")


def format_bullets(items: list[str] | None, fallback: str = "TBD after inspection") -> str:
    values = [item.strip() for item in (items or []) if item.strip()]
    if not values:
        values = [fallback]
    return "\n".join(f"- {item}" for item in values)


def start(
    main_goal: str,
    tiny_goal: str,
    files: list[str] | None = None,
    checks: list[str] | None = None,
) -> None:
    ensure_files()
    file_scope = format_bullets(files)
    acceptance_checks = format_bullets(
        checks,
        "Tiny goal is complete; scope is limited; verification is recorded; next tiny goal is proposed.",
    )
    content = f"""# Current TINI Step

## Main Goal
{main_goal}

## Tiny Goal
{tiny_goal}

## Why this matters
This step must move the project toward the main goal without broad, unfocused edits.

## Plan
1. Inspect only relevant files.
2. Modify only files needed for the tiny goal.
3. Run the smallest useful verification.

## Files to touch
{file_scope}

## Acceptance checks
{acceptance_checks}

## Status
started
"""
    CURRENT.write_text(content)
    print(f"started: {tiny_goal}")


def build_prompt() -> str:
    ensure_files()
    if not CURRENT.exists():
        raise SystemExit("No .tini/current_step.md. Run: python tini.py start ...")
    step = CURRENT.read_text()
    negative_cache = NEGATIVE_CACHE.read_text()
    return f"""You are Claude Code working under the TINI anti-hallucination protocol.

Rules:
1. Do NOT broaden scope beyond the Tiny Goal.
2. Before editing, restate Main Goal, Tiny Goal, files likely touched, acceptance checks.
3. Prefer minimal surgical edits.
4. Before code edits, include an "assumptions checked" block listing each assumption as verified or unknown.
5. Before bug-fix edits, include either a one-command repro or `no repro possible because ...`.
6. Before editing/reporting a target file, run `python tini.py stale <file>` and stop if it warns that the file changed since read.
7. Before planning, ask at most one clarifying question only if the answer changes files or approach; otherwise proceed with stated assumptions.
8. Before editing, include one rollback line: `rollback: revert files X/Y or git checkout -- X Y`.
9. After each verification command, write one compact digest line: command, exit, decisive evidence, unknowns.
10. Mark verification evidence stale if any relevant file changed after that command; rerun it or label the claim `stale evidence`.
11. Final-answer success claims must include scope words like `verified by <command> only` or `not checked`.
12. Orphan-change check: before final response, compare the list of changed files (git diff, new files) to your summary bullets — every changed file must be explicitly mentioned in the summary or reverted; if any changed file is unmentioned, add a line `orphan change: <file> — <reason or revert>`.
13. Claim-verb lint: in the final response, flag strong claim verbs (fixed, solved, confirmed, proven, ensured, guaranteed, verified, validated, completed) unless the sentence also names a specific command, file path, test name, or an explicit limitation (e.g. "not checked", "only in X scope"). Replace flagged bare claims with scoped wording: `claim-verb-lint: <verb> — <evidence or "downgraded: not independently verified">`. At least two distinct evidence sources (runtime, source, test, doc, user-claim) must back each strong claim about correctness; if fewer, prepend `single-evidence:` or downgrade the verb.
14. Output-contract check: before the final response, list every explicit output constraint from the task prompt (format, delivery channel, length limits, required sections, content rules like `[SILENT]`, headers/footers). Then confirm each with `output-contract: <constraint> — met|violated: <detail>`. If any constraint is violated, fix the response before sending. If no explicit constraints exist, write `output-contract: none specified`.
15. Scope-escape trigger: before any write, file edit, shell command with side effects, or tool call that changes state, write `scope-escape: <action> — mode permits this: yes|no — <reason>`. The mode is determined by the task stage: `review` (read-only), `plan` (read + planning text only), `implement` (read + write + run). If mode does not permit the action, STOP and state why. Include expected side effects and confirm minimal-tool choice (no broader tool than needed).
16. Evidence-gap router: for each important unknown or assumption marked unknown in the assumptions-checked block, assign exactly one deterministic route tag: `inspect-now` (run a command to resolve immediately), `ask-user` (answer changes files/approach and cannot be resolved otherwise), `defer-safe` (unknown is irrelevant to current tiny goal), or `downgrade-claim` (cannot resolve, so weaken any claim depending on this unknown). Write one line per gap: `evidence-gap: <unknown> — route: <tag> — <justification>`. Before the final response, confirm every gap has been routed or resolved. No bare "unknown" or "TBD" gaps may remain without a route tag.
17. Invariant watchlist: at plan time, list up to three invariants that must remain true during this step (e.g., existing tests still pass, public API signatures unchanged, no new dependencies). Write one line per invariant: `invariant: <statement>`. In the final check, revisit each invariant and mark it `invariant-check: <statement> — preserved|unknown: <reason>`. If any invariant is marked unknown, state what evidence would be needed to confirm it and whether the risk is acceptable.
19. After editing, report changed files, verification command/result, risks, next tiny goal.
20. Post-response checklist: every changed-file claim must include a 1-line evidence tag like `[evidence: path — command/result proving the claim]`.
21. Tag key evidence quality as one of: runtime, source, test, doc, or user-claim.
22. Before plan generation, consult the Negative Cache below and avoid repeating listed failed attempts.
23. If context/files conflict with the goal, stop and ask.

Current step:

{step}

Negative Cache:

{negative_cache}
"""


def prompt() -> None:
    print(build_prompt())


def validate_current_step() -> str:
    """Return the generated prompt, or fail when the current step is not ready."""
    step = build_prompt()
    missing: list[str] = []
    required_sections = ["## Main Goal", "## Tiny Goal", "## Files to touch", "## Acceptance checks"]
    for section in required_sections:
        if section not in step:
            missing.append(f"missing section: {section}")
    # Only check for placeholders in the "Current step:" section, not in rules
    current_step_start = step.find("Current step:")
    check_region = step[current_step_start:] if current_step_start >= 0 else step
    placeholders = ["TBD", "TBD after inspection"]
    for placeholder in placeholders:
        if placeholder in check_region:
            missing.append(f"placeholder remains: {placeholder}")
    if missing:
        raise SystemExit("Current TINI step is not ready:\n- " + "\n- ".join(missing))
    return step


def validate() -> None:
    """Fail fast when the current step still has placeholder scope/checks."""
    validate_current_step()
    print("current step valid")


def diff_risk() -> tuple[str, str]:
    """Return LOW/MED/HIGH risk plus concise reasons from git diff + untracked files.

    Robust for fresh repos with no initial commit: `git diff` is empty for
    untracked files, so include `git status --porcelain` paths as risk input.
    """
    diff_paths = subprocess.run(
        ["git", "diff", "--name-only"], cwd=ROOT, check=False, capture_output=True, text=True
    ).stdout
    untracked_paths = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    staged_paths = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    paths = "\n".join([diff_paths, staged_paths, untracked_paths]).lower()
    diff = subprocess.run(
        ["git", "diff"], cwd=ROOT, check=False, capture_output=True, text=True
    ).stdout.lower()
    staged_diff = subprocess.run(
        ["git", "diff", "--cached"], cwd=ROOT, check=False, capture_output=True, text=True
    ).stdout.lower()
    diff = "\n".join([diff, staged_diff])
    reasons: list[str] = []
    level = "LOW"
    if untracked_paths.strip():
        reasons.append("untracked files present")
    if any(part in paths for part in HIGH_RISK_PATH_PARTS):
        level = "HIGH"
        reasons.append("sensitive path changed")
    elif any(part in paths for part in MEDIUM_RISK_PATH_PARTS):
        level = "MED"
        reasons.append("config/deploy dependency path changed")
    if any(word in diff for word in HIGH_RISK_KEYWORDS):
        level = "HIGH"
        reasons.append("sensitive/destructive keyword in diff")
    elif level == "LOW" and any(word in diff for word in MEDIUM_RISK_KEYWORDS):
        level = "MED"
        reasons.append("behavior-affecting keyword in diff")
    if not paths.strip():
        reasons.append("no git diff paths")
    return level, "; ".join(reasons or ["ordinary source/docs diff"])


def risk() -> None:
    level, reason = diff_risk()
    print(f"diff risk: {level} — {reason}")


def _tracked_path(path: str) -> Path:
    candidate = (ROOT / path).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SystemExit(f"refusing path outside project: {path}") from exc
    return candidate


def _read_mtimes() -> dict[str, float]:
    ensure_files()
    mtimes: dict[str, float] = {}
    for line in READ_MTIMES.read_text().splitlines():
        if not line.strip() or "\t" not in line:
            continue
        name, value = line.split("\t", 1)
        try:
            mtimes[name] = float(value)
        except ValueError:
            continue
    return mtimes


def mark_read(paths: list[str]) -> None:
    mtimes = _read_mtimes()
    for path in paths:
        target = _tracked_path(path)
        if not target.exists():
            raise SystemExit(f"missing file: {path}")
        rel = target.relative_to(ROOT.resolve()).as_posix()
        mtimes[rel] = target.stat().st_mtime
    READ_MTIMES.write_text("".join(f"{name}\t{mtime}\n" for name, mtime in sorted(mtimes.items())))
    print(f"marked read: {', '.join(paths)}")


def stale_warnings(paths: list[str]) -> list[str]:
    mtimes = _read_mtimes()
    warnings: list[str] = []
    for path in paths:
        target = _tracked_path(path)
        rel = target.relative_to(ROOT.resolve()).as_posix()
        old = mtimes.get(rel)
        if old is None:
            warnings.append(f"STALE-CHECK UNKNOWN: {rel} was not marked read")
        elif not target.exists():
            warnings.append(f"STALE-CHECK WARN: {rel} was deleted since read")
        elif target.stat().st_mtime != old:
            warnings.append(f"STALE-CHECK WARN: {rel} changed since read")
    return warnings


def stale(paths: list[str]) -> None:
    warnings = stale_warnings(paths)
    if warnings:
        print("\n".join(warnings))
        raise SystemExit(1)
    print("stale check passed")


def run_claude(max_turns: int = 5) -> None:
    claude_prompt = validate_current_step()
    cmd = [
        "claude",
        "-p",
        claude_prompt,
        "--max-turns",
        str(max_turns),
        "--allowedTools",
        "Read,Edit,Write,Bash",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)


def done(summary: str = "TBD", verification: str = "TBD", next_goal: str = "TBD") -> None:
    ensure_files()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"""

## {now} — TINI step completed

### Summary
{summary}

### Verification
{verification}

### Goal alignment
Step reviewed against current Main Goal + Tiny Goal.

### Risks / unknowns
- TBD

### Next tiny goal
{next_goal}
"""
    with DEV_LOG.open("a") as f:
        f.write(entry)
    print("logged completion")


def _smoke_checks() -> list[tuple[str, str, str]]:
    """Return (id, marker, description) for every rule artifact detectable in the prompt."""
    return [
        ("evidence-tag", "[evidence:", "Rule 20: changed-file evidence tags"),
        ("rollback-line", "rollback: revert files", "Rule 8: rollback plan line"),
        ("scope-wording", "verified by", "Rule 11: scoped success claims"),
        ("claim-verb-lint", "claim-verb-lint:", "Rule 13: claim-verb lint"),
        ("orphan-change", "orphan change:", "Rule 12: orphan change check"),
        ("output-contract", "output-contract:", "Rule 14: output contract check"),
        ("scope-escape", "scope-escape:", "Rule 15: scope-escape trigger"),
        ("evidence-gap", "evidence-gap:", "Rule 16: evidence-gap router"),
        ("invariant", "invariant:", "Rule 17: invariant watchlist"),
        ("assumptions", "assumptions checked", "Rule 4: assumptions checked block"),
        ("repro-note", "one-command repro", "Rule 5: one-command repro note"),
        ("stale-check", "python tini.py stale", "Rule 6: stale file check"),
        ("verification-digest", "decisive evidence", "Rule 9: verification digest"),
        ("evidence-ttl", "stale evidence", "Rule 10: evidence TTL labeling"),
        ("source-trust", "runtime, source, test, doc", "Rule 21: evidence quality tags"),
        ("question-budget", "ask at most one", "Rule 7: question budget gate"),
        ("negative-cache", "consult the Negative Cache", "Rule 22: negative cache consult"),
        ("post-response-chklst", "Post-response checklist", "Rule 20 heading header"),
    ]


def smoke() -> None:
    """Run self-test: generate minimal prompt and verify all rule artifacts present.

    Works by redirecting module paths to a temp dir, creating a minimal step,
    building the full prompt, then scanning for known rule markers.
    """
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    tmp_root = Path(tmp.name)
    tmp_tini = tmp_root / ".tini"

    # Save originals
    orig = {
        "ROOT": ROOT,
        "TINI_DIR": TINI_DIR,
        "CURRENT": CURRENT,
        "DEV_LOG": DEV_LOG,
        "PROJECT_GOAL": PROJECT_GOAL,
        "NEGATIVE_CACHE": NEGATIVE_CACHE,
        "READ_MTIMES": READ_MTIMES,
    }

    try:
        # Redirect module paths to temp
        import sys as _sys

        _sys.modules[__name__].ROOT = tmp_root  # type: ignore[attr-defined]
        _sys.modules[__name__].TINI_DIR = tmp_tini  # type: ignore[attr-defined]
        _sys.modules[__name__].CURRENT = tmp_tini / "current_step.md"  # type: ignore[attr-defined]
        _sys.modules[__name__].DEV_LOG = tmp_root / "DEV_LOG.md"  # type: ignore[attr-defined]
        _sys.modules[__name__].PROJECT_GOAL = tmp_root / "PROJECT_GOAL.md"  # type: ignore[attr-defined]
        _sys.modules[__name__].NEGATIVE_CACHE = tmp_tini / "negative-cache.md"  # type: ignore[attr-defined]
        _sys.modules[__name__].READ_MTIMES = tmp_tini / "read-mtimes.tsv"  # type: ignore[attr-defined]

        ensure_files()
        start(
            "Smoke test main goal",
            "Smoke test tiny goal",
            files=["tini.py"],
            checks=["smoke test passes"],
        )
        prompt = build_prompt()

        checks = _smoke_checks()
        passed = 0
        failed = 0
        results: list[str] = []
        for cid, marker, desc in checks:
            if marker in prompt:
                passed += 1
                results.append(f"  ✓ {cid} — {desc}")
            else:
                failed += 1
                results.append(f"  ✗ {cid} — {desc}")

        print(f"TINI Smoke Test: {passed} passed, {failed} failed / {len(checks)} total")
        for r in results:
            print(r)

        if failed:
            raise SystemExit(f"smoke test: {failed} rule(s) missing from prompt")
        print("smoke test passed")
    finally:
        for attr, val in orig.items():
            setattr(_sys.modules[__name__], attr, val)
        tmp.cleanup()


def _parse_file_scope() -> list[str]:
    """Parse declared file scope from current step's ## Files to touch section."""
    if not CURRENT.exists():
        return []
    content = CURRENT.read_text()
    section_start = content.find("## Files to touch")
    if section_start < 0:
        return []
    next_section = content.find("\n## ", section_start + 1)
    if next_section < 0:
        section = content[section_start:]
    else:
        section = content[section_start:next_section]
    files: list[str] = []
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("- "):
            files.append(line[2:].strip())
    return files


def check_scope() -> None:
    """Compare git changed files against declared scope; exit 1 if any out of scope."""
    if not CURRENT.exists():
        raise SystemExit("No .tini/current_step.md. Run: python tini.py start ...")

    declared = _parse_file_scope()
    if not declared:
        raise SystemExit("No files declared in current step scope (## Files to touch section is empty).")

    # Normalize declared paths for matching
    declared_normalized = set()
    for d in declared:
        p = Path(d).as_posix()
        declared_normalized.add(p)
        # Also add without leading ./ if present
        declared_normalized.add(p.lstrip("./"))

    # Gather all changed files: unstaged diff, staged diff, untracked
    diff_result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=ROOT, check=False, capture_output=True, text=True
    )
    staged_result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=ROOT, check=False, capture_output=True, text=True
    )
    untracked_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT, check=False, capture_output=True, text=True
    )

    changed: set[str] = set()
    for output in (diff_result.stdout, staged_result.stdout, untracked_result.stdout):
        for line in output.splitlines():
            line = line.strip()
            if line:
                changed.add(Path(line).as_posix())

    if not changed:
        print("check-scope: no changed files — scope clean")
        return

    in_scope: list[str] = []
    out_of_scope: list[str] = []
    for f in sorted(changed):
        if f in declared_normalized or any(f.startswith(d.rstrip("*") if d.endswith("*") else d + "/") for d in declared_normalized):
            in_scope.append(f)
        else:
            # Also check basename match (declared might use relative path)
            matched = False
            for d in declared_normalized:
                if f.endswith(d) or d.endswith(f):
                    matched = True
                    break
            if matched:
                in_scope.append(f)
            else:
                out_of_scope.append(f)

    print(f"check-scope: {len(in_scope)} in scope, {len(out_of_scope)} out of scope")
    for f in in_scope:
        print(f"  ✓ {f} — in scope")
    for f in out_of_scope:
        print(f"  ✗ {f} — OUT OF SCOPE")

    if out_of_scope:
        raise SystemExit(f"check-scope: {len(out_of_scope)} file(s) changed outside declared scope")


def main() -> None:
    parser = argparse.ArgumentParser(description="TINI tiny goal-aligned Claude Code wrapper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="start a new tiny goal")
    p_start.add_argument("main_goal")
    p_start.add_argument("tiny_goal")
    p_start.add_argument(
        "--file",
        action="append",
        dest="files",
        help="allowed file/scope entry; repeat for multiple entries",
    )
    p_start.add_argument(
        "--check",
        action="append",
        dest="checks",
        help="acceptance check; repeat for multiple checks",
    )

    sub.add_parser("prompt", help="print Claude Code prompt for current tiny goal")

    sub.add_parser("validate", help="fail if current tiny goal has placeholder scope/checks")

    sub.add_parser("risk", help="print rule-based LOW/MED/HIGH risk for current git diff")

    p_mark_read = sub.add_parser("mark-read", help="record current file mtimes after inspection")
    p_mark_read.add_argument("paths", nargs="+")

    p_stale = sub.add_parser("stale", help="warn if files changed since mark-read")
    p_stale.add_argument("paths", nargs="+")

    sub.add_parser("smoke", help="self-test: verify all rule artifacts present in generated prompt")

    sub.add_parser("check-scope", help="compare git diff against declared --file scope")

    p_run = sub.add_parser("run", help="run Claude Code print-mode for current tiny goal")
    p_run.add_argument("--max-turns", type=int, default=5)

    p_done = sub.add_parser("done", help="append completion note")
    p_done.add_argument("--summary", default="TBD")
    p_done.add_argument("--verification", default="TBD")
    p_done.add_argument("--next", default="TBD")

    args = parser.parse_args()
    if args.cmd == "start":
        start(args.main_goal, args.tiny_goal, args.files, args.checks)
    elif args.cmd == "prompt":
        prompt()
    elif args.cmd == "validate":
        validate()
    elif args.cmd == "risk":
        risk()
    elif args.cmd == "mark-read":
        mark_read(args.paths)
    elif args.cmd == "stale":
        stale(args.paths)
    elif args.cmd == "smoke":
        smoke()
    elif args.cmd == "check-scope":
        check_scope()
    elif args.cmd == "run":
        run_claude(args.max_turns)
    elif args.cmd == "done":
        done(args.summary, args.verification, getattr(args, "next"))


if __name__ == "__main__":
    main()
