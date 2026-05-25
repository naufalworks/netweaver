import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tini


class TiniTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_root = tini.ROOT
        self.old_tini_dir = tini.TINI_DIR
        self.old_current = tini.CURRENT
        self.old_dev_log = tini.DEV_LOG
        self.old_project_goal = tini.PROJECT_GOAL
        self.old_negative_cache = tini.NEGATIVE_CACHE
        self.old_read_mtimes = tini.READ_MTIMES
        tini.ROOT = self.root
        tini.TINI_DIR = self.root / ".tini"
        tini.CURRENT = tini.TINI_DIR / "current_step.md"
        tini.DEV_LOG = self.root / "DEV_LOG.md"
        tini.PROJECT_GOAL = self.root / "PROJECT_GOAL.md"
        tini.NEGATIVE_CACHE = tini.TINI_DIR / "negative-cache.md"
        tini.READ_MTIMES = tini.TINI_DIR / "read-mtimes.tsv"

    def tearDown(self):
        tini.ROOT = self.old_root
        tini.TINI_DIR = self.old_tini_dir
        tini.CURRENT = self.old_current
        tini.DEV_LOG = self.old_dev_log
        tini.PROJECT_GOAL = self.old_project_goal
        tini.NEGATIVE_CACHE = self.old_negative_cache
        tini.READ_MTIMES = self.old_read_mtimes
        self.tmp.cleanup()

    def test_validate_passes_with_explicit_scope_and_checks(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["validate passes"],
        )

        prompt = tini.validate_current_step()

        self.assertIn("Main goal", prompt)
        self.assertIn("Tiny goal", prompt)
        self.assertIn("- tini.py", prompt)
        self.assertIn("- validate passes", prompt)

    def test_prompt_requires_evidence_tags_for_changed_file_claims(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes evidence checklist"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Post-response checklist", prompt)
        self.assertIn("every changed-file claim must include a 1-line evidence tag", prompt)
        self.assertIn("[evidence: path", prompt)

    def test_prompt_includes_negative_cache_before_planning(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes negative cache"],
        )
        tini.NEGATIVE_CACHE.write_text("# TINI Negative Cache\n\n- Failed attempt: broad rewrite.\n")

        prompt = tini.build_prompt()

        self.assertIn("consult the Negative Cache", prompt)
        self.assertIn("Failed attempt: broad rewrite", prompt)

    def test_prompt_requires_key_evidence_quality_tags(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes source trust tags"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Tag key evidence quality", prompt)
        self.assertIn("runtime, source, test, doc, or user-claim", prompt)

    def test_prompt_requires_assumptions_checked_before_code_edits(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes assumptions checked block"],
        )

        prompt = tini.build_prompt()

        self.assertIn('Before code edits, include an "assumptions checked" block', prompt)
        self.assertIn("verified or unknown", prompt)

    def test_prompt_requires_repro_note_before_bug_fix_edits(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes repro note gate"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Before bug-fix edits", prompt)
        self.assertIn("one-command repro", prompt)
        self.assertIn("no repro possible because", prompt)

    def test_prompt_requires_stale_check_before_editing_or_reporting(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes stale check"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Before editing/reporting a target file", prompt)
        self.assertIn("python tini.py stale <file>", prompt)

    def test_prompt_requires_rollback_line_before_editing(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes rollback line"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Before editing, include one rollback line", prompt)
        self.assertIn("rollback: revert files X/Y or git checkout -- X Y", prompt)

    def test_prompt_limits_clarifying_questions_before_planning(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes question budget gate"],
        )

        prompt = tini.build_prompt()

        self.assertIn("ask at most one clarifying question", prompt)
        self.assertIn("only if the answer changes files or approach", prompt)
        self.assertIn("otherwise proceed with stated assumptions", prompt)

    def test_prompt_requires_verification_command_digest(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes verification digest"],
        )

        prompt = tini.build_prompt()

        self.assertIn("After each verification command", prompt)
        self.assertIn("command, exit, decisive evidence, unknowns", prompt)

    def test_prompt_requires_evidence_ttl_after_file_changes(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes evidence TTL"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Mark verification evidence stale", prompt)
        self.assertIn("relevant file changed after that command", prompt)
        self.assertIn("rerun it or label the claim `stale evidence`", prompt)

    def test_prompt_requires_scoped_success_claims(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes scoped success claims"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Final-answer success claims", prompt)
        self.assertIn("verified by <command> only", prompt)
        self.assertIn("not checked", prompt)

    def test_mark_read_and_stale_warn_when_file_changed(self):
        target = self.root / "sample.txt"
        target.write_text("before")
        tini.mark_read(["sample.txt"])
        target.write_text("after")

        warnings = tini.stale_warnings(["sample.txt"])

        self.assertIn("STALE-CHECK WARN: sample.txt changed since read", warnings)

    def test_stale_passes_when_file_unchanged_since_mark_read(self):
        target = self.root / "sample.txt"
        target.write_text("same")
        tini.mark_read(["sample.txt"])

        warnings = tini.stale_warnings(["sample.txt"])

        self.assertEqual(warnings, [])

    def test_mark_read_rejects_paths_outside_project(self):
        with self.assertRaises(SystemExit) as error:
            tini.mark_read(["../outside.txt"])

        self.assertIn("refusing path outside project", str(error.exception))

    def test_validate_fails_when_placeholder_scope_remains(self):
        tini.start("Main goal", "Tiny goal")

        with self.assertRaises(SystemExit) as error:
            tini.validate_current_step()

        self.assertIn("placeholder remains", str(error.exception))

    def test_run_fails_preflight_before_calling_claude(self):
        tini.start("Main goal", "Tiny goal")

        with patch("tini.subprocess.run") as run:
            with self.assertRaises(SystemExit):
                tini.run_claude(max_turns=1)

        run.assert_not_called()

    def test_run_invokes_claude_after_valid_preflight(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["mocked claude command is called"],
        )

        with patch("tini.subprocess.run") as run:
            tini.run_claude(max_turns=2)

        run.assert_called_once()
        args, kwargs = run.call_args
        cmd = args[0]
        self.assertEqual(cmd[0:2], ["claude", "-p"])
        self.assertIn("--max-turns", cmd)
        self.assertIn("2", cmd)
        self.assertEqual(kwargs["cwd"], self.root)
        self.assertTrue(kwargs["check"])

    def test_diff_risk_reports_low_when_no_diff_paths(self):
        def fake_run(cmd, **kwargs):
            class Result:
                stdout = ""

            return Result()

        with patch("tini.subprocess.run", side_effect=fake_run):
            level, reason = tini.diff_risk()

        self.assertEqual(level, "LOW")
        self.assertIn("no git diff paths", reason)

    def test_prompt_requires_claim_verb_lint_in_final_response(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes claim-verb lint"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Claim-verb lint", prompt)
        self.assertIn("flag strong claim verbs", prompt)
        self.assertIn("claim-verb-lint:", prompt)
        self.assertIn("downgraded: not independently verified", prompt)
        self.assertIn("two distinct evidence sources", prompt)
        self.assertIn("single-evidence:", prompt)

    def test_prompt_requires_orphan_change_check_before_final_response(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes orphan-change check"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Orphan-change check", prompt)
        self.assertIn("compare the list of changed files", prompt)
        self.assertIn("every changed file must be explicitly mentioned", prompt)
        self.assertIn("orphan change:", prompt)

    def test_prompt_requires_output_contract_check_before_final_response(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes output-contract check"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Output-contract check", prompt)
        self.assertIn("list every explicit output constraint", prompt)
        self.assertIn("output-contract:", prompt)
        self.assertIn("met|violated:", prompt)
        self.assertIn("output-contract: none specified", prompt)

    def test_prompt_requires_scope_escape_trigger_before_side_effects(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes scope-escape trigger"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Scope-escape trigger", prompt)
        self.assertIn("scope-escape:", prompt)
        self.assertIn("mode permits this: yes|no", prompt)
        self.assertIn("review", prompt)
        self.assertIn("plan", prompt)
        self.assertIn("implement", prompt)
        self.assertIn("expected side effects", prompt)
        self.assertIn("minimal-tool choice", prompt)

    def test_prompt_requires_evidence_gap_router_for_unknowns(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes evidence-gap router"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Evidence-gap router", prompt)
        self.assertIn("inspect-now", prompt)
        self.assertIn("ask-user", prompt)
        self.assertIn("defer-safe", prompt)
        self.assertIn("downgrade-claim", prompt)
        self.assertIn("evidence-gap:", prompt)
        self.assertIn("route:", prompt)
        self.assertIn("No bare", prompt)
        self.assertIn("route tag", prompt)

    def test_prompt_requires_invariant_watchlist_at_plan_time(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["prompt includes invariant watchlist"],
        )

        prompt = tini.build_prompt()

        self.assertIn("Invariant watchlist", prompt)
        self.assertIn("at plan time, list up to three invariants", prompt)
        self.assertIn("invariant:", prompt)
        self.assertIn("invariant-check:", prompt)
        self.assertIn("preserved|unknown:", prompt)
        self.assertIn("existing tests still pass", prompt)
        self.assertIn("public API signatures unchanged", prompt)
        self.assertIn("no new dependencies", prompt)

    def test_diff_risk_reports_high_for_sensitive_path(self):
        def fake_run(cmd, **kwargs):
            class Result:
                stdout = ".env\n" if "--name-only" in cmd else "+TOKEN=abc\n"

            return Result()

        with patch("tini.subprocess.run", side_effect=fake_run):
            level, reason = tini.diff_risk()

        self.assertEqual(level, "HIGH")
        self.assertIn("sensitive path changed", reason)

    def test_smoke_passes_all_rule_checks(self):
        """Self-test validates every rule artifact is present in generated prompt."""
        tini.smoke()
        # If smoke() doesn't raise SystemExit, all checks passed

    def test_check_scope_passes_when_all_changed_files_in_scope(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py", "tests/test_tini.py"],
            checks=["check-scope passes"],
        )

        def fake_run(cmd, **kwargs):
            class Result:
                stdout = ""
            if "--name-only" in cmd and "--cached" not in cmd and "ls-files" not in cmd:
                r = Result()
                r.stdout = "tini.py\n"
                return r
            return Result()

        with patch("tini.subprocess.run", side_effect=fake_run):
            tini.check_scope()
        # Should not raise

    def test_check_scope_fails_when_file_out_of_scope(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["check-scope fails on out-of-scope"],
        )

        def fake_run(cmd, **kwargs):
            class Result:
                stdout = ""
            if "--name-only" in cmd and "--cached" not in cmd and "ls-files" not in cmd:
                r = Result()
                r.stdout = "tini.py\nsecret.py\n"
                return r
            return Result()

        import io
        import sys
        captured = io.StringIO()
        with patch("tini.subprocess.run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as error:
                old_stdout = sys.stdout
                sys.stdout = captured
                try:
                    tini.check_scope()
                finally:
                    sys.stdout = old_stdout
        output = captured.getvalue()
        self.assertIn("OUT OF SCOPE", output)
        self.assertIn("secret.py", output)
        self.assertIn("file(s) changed outside declared scope", str(error.exception))

    def test_check_scope_passes_when_no_changed_files(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["check-scope passes with no diff"],
        )

        with patch("tini.subprocess.run") as run:
            run.return_value.stdout = ""
            tini.check_scope()
        # Should not raise

    def test_check_scope_fails_when_no_current_step(self):
        # Don't call start — no current_step.md exists
        with self.assertRaises(SystemExit) as error:
            tini.check_scope()
        self.assertIn("current_step.md", str(error.exception))

    def test_check_scope_detects_untracked_files(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["tini.py"],
            checks=["check-scope handles untracked"],
        )

        def fake_run(cmd, **kwargs):
            class Result:
                stdout = ""
            if "ls-files" in cmd and "--others" in cmd:
                r = Result()
                r.stdout = "new_module.py\n"
                return r
            return Result()

        import io
        import sys
        captured = io.StringIO()
        with patch("tini.subprocess.run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as error:
                old_stdout = sys.stdout
                sys.stdout = captured
                try:
                    tini.check_scope()
                finally:
                    sys.stdout = old_stdout
        output = captured.getvalue()
        self.assertIn("new_module.py", output)
        self.assertIn("OUT OF SCOPE", output)

    def test_parse_file_scope_extracts_declared_files(self):
        tini.start(
            "Main goal",
            "Tiny goal",
            files=["src/main.py", "tests/test_main.py"],
            checks=["parse scope works"],
        )
        scope = tini._parse_file_scope()
        self.assertEqual(scope, ["src/main.py", "tests/test_main.py"])

    def test_parse_file_scope_returns_empty_when_no_current_step(self):
        scope = tini._parse_file_scope()
        self.assertEqual(scope, [])


if __name__ == "__main__":
    unittest.main()
