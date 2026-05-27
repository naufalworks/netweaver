# Audit Checklist

Run periodically or before major changes.

## Repo Boundary
- `git rev-parse --show-toplevel` equals project root.
- `git status --short` shows only project files.

## Tests
- `python -m unittest discover -s tests -v` passes.

## TINI Ideas
- every reviewed idea exists in inbox.
- every executed idea exists in reviewed.
- approved backlog is not growing unbounded.

## NetWeaver Kanban
- every task has ID/owner/model/status/scope/acceptance.
- done tasks have disk files present.
- done tasks have DEV_LOG/HANDOFF/REVIEW references.
- no stale in_progress/review task.

## Safety
- no `.env`/secrets tracked.
- no vendor edits unless explicit task.
- no parent repo pollution.
