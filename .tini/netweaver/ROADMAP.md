# NetWeaver Roadmap

## Strategy
Move fast from architecture docs to executable browser evidence.

## Development Loop
1. Architect chooses one tiny, testable step.
2. Implement builds minimal working artifact.
3. Review validates against evidence-first principle.
4. Repeat.

## Priorities

### Phase 0 — Foundation
- Keep architecture docs short and actionable.
- Avoid modifying CloakBrowser vendor code.
- Use CloakBrowser as Playwright-compatible runtime.

### Phase 1 — MVP Observer
Goal: turn any page into a compact browser-native world model.

Target command:

```bash
python -m netweaver.observer https://example.com
```

Output:

```json
{
  "url": "...",
  "title": "...",
  "interactive_elements": [],
  "actionability": [],
  "network": []
}
```

### Phase 2 — WNAL Typed Actions
Define click/fill/wait schema with preconditions and verification.

### Phase 3 — Verified Executor
Implement one safe action: click with before/after evidence.

### Phase 4 — Network Evidence
Capture request/response events and link action → network result.

### Phase 5 — Site Skills
Persist successful flows as reusable WNAL/BASIL snippets.

## Efficiency Rules
- Prefer working prototype over large docs.
- One tiny step per scheduler run.
- Tests or runnable demo required for code changes.
- If blocked, write exact blocker + next unblock step.
