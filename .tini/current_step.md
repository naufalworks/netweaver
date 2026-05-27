# Current TINI Step

## Main Goal
Build Claude Code anti-hallucination wrapper

## Tiny Goal
Add tests for validate/run preflight behavior without real Claude CLI

## Why this matters
This step must move the project toward the main goal without broad, unfocused edits.

## Plan
1. Inspect only relevant files.
2. Modify only files needed for the tiny goal.
3. Run the smallest useful verification.

## Files to touch
- tests/test_tini.py
- .tini/current_step.md
- DEV_LOG.md

## Acceptance checks
- unit tests cover validate success and placeholder failure
- unit tests cover run preflight blocks before subprocess
- unit tests cover run invokes mocked claude after valid preflight

## Status
started
