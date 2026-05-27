# NetWeaver Agent Communication Protocol

Source of truth: company/KANBAN.md

Each worker must:
1. Read KANBAN.md, HANDOFF.md, STATUS.md, BLOCKERS.md.
2. Pick only tasks assigned to its role/model.
3. Move one task: ready -> in_progress -> review.
4. Write handoff note:
   - task id
   - changed files
   - verification
   - risks
   - next owner
5. Reviewer moves review -> done or blocked.

Rules:
- One task per worker per run.
- No touching another lane's files unless task says so.
- No vendor/CloakBrowser modifications.
- No secrets/env/auth/deploy/git push.
- If conflict or ambiguity, write BLOCKERS.md not broad edits.
