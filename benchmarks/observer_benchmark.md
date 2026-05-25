# Observer Benchmark Plan

**Task**: NW-003
**Owner**: QA Benchmark
**Date**: 2026-05-23
**Status**: review

## Purpose

Define repeatable benchmark tasks and success metrics for the NetWeaver Observer (`python -m netweaver.observer`). The observer must turn any page into a compact JSON world model with keys: `url`, `title`, `interactive_elements`, `actionability`, `network`.

All benchmarks use **mocked page fixtures** — no browser download, no Playwright, no network access required.

---

## Benchmark Tasks (5)

### B-001: Static HTML Page — Basic Observation

**Fixture**: `tests/fixtures/static_page.json`

A simple static HTML page with:
- Title: "Test Page"
- 3 interactive elements (button, link, input)
- No JS, no network events
- All elements visible, enabled, attached

**Pass criteria**:
- Observer output contains all 5 required JSON keys
- `interactive_elements` count = 3
- Each element has `selector`, `tag`, `role`, `text` fields
- `actionability` entries all report `attached: true`, `visible: true`, `enabled: true`
- `network` array is empty
- Output is valid JSON

**Metric**: structural accuracy — all required keys present, element count matches, field types correct.

---

### B-002: Form Page — Interactive Element Discovery

**Fixture**: `tests/fixtures/form_page.json`

A login form page with:
- Title: "Login"
- 5 interactive elements: username input, password input, submit button, "forgot password" link, checkbox
- Password input: `editable: true` but `type: password`
- Checkbox: `editable: true`
- Submit button: `enabled: true`

**Pass criteria**:
- Observer discovers all 5 interactive elements
- Each element has correct `tag` and `role`
- Form inputs have `editable: true`
- Button has `editable: false`
- `actionability` correctly marks password field as `editable`
- `url` and `title` populated

**Metric**: element discovery recall (5/5 = 100%), actionability field accuracy.

---

### B-003: SPA with Dynamic Content — State Observation

**Fixture**: `tests/fixtures/spa_page.json`

A single-page app snapshot with:
- Title: "Dashboard"
- 8 interactive elements across nav, sidebar, main content
- Some elements inside shadow DOM (2 elements)
- 1 hidden element (`visible: false`)
- 1 disabled button (`enabled: false`)
- 2 network entries (API fetch responses)

**Pass criteria**:
- All 8 interactive elements discovered (including shadow DOM)
- Hidden element correctly marked `visible: false` in actionability
- Disabled button correctly marked `enabled: false`
- `network` array contains 2 entries with `url`, `method`, `status` fields
- Shadow DOM elements have `shadow_root: true` flag

**Metric**: shadow DOM coverage, hidden/disabled detection accuracy, network event capture count.

---

### B-004: Error Page — Degraded State Handling

**Fixture**: `tests/fixtures/error_page.json`

A 404/error page with:
- Title: "Not Found"
- 1 interactive element (home link)
- 1 network entry (404 response)
- Minimal content

**Pass criteria**:
- Observer handles degraded page without error
- Output still contains all 5 required keys
- `interactive_elements` count = 1
- `network` entry shows `status: 404`
- `actionability` for the single element is complete

**Metric**: graceful degradation — no crash, all keys present, correct minimal content.

---

### B-005: Heavy Page — Performance Observation

**Fixture**: `tests/fixtures/heavy_page.json`

A complex page with:
- Title: "E-Commerce Store"
- 51 interactive elements (products, filters, buttons, links)
- 10 network entries (product API, images, analytics)
- Mix of enabled/disabled, visible/hidden elements
- Some elements with `pointer_events: false` (overlaid)

**Pass criteria**:
- Observer processes fixture without timeout (mocked, so instant)
- All 51 interactive elements discovered
- `actionability` correctly identifies:
  - 3 disabled elements
  - 4 hidden elements
  - 3 with `pointer_events: false`
- `network` array has 10 entries
- JSON output is valid and complete

**Metric**: element count accuracy, actionability flag precision, network capture completeness.

---

## Success Metrics Summary

| Metric | Target | Measurement |
|--------|--------|-------------|
| JSON structure validity | 100% | All 5 keys present in every output |
| Element discovery recall | ≥ 95% | Elements found / total elements in fixture |
| Actionability flag accuracy | ≥ 90% | Correct flags / total flags across elements |
| Network event capture | ≥ 95% | Network entries found / entries in fixture |
| Shadow DOM coverage | ≥ 80% | Shadow elements found / total shadow elements |
| Degraded state handling | 100% | No crash on error/minimal pages |
| Valid JSON output | 100% | `json.loads()` succeeds on every output |

## Scoring

Each benchmark task scores 0–100:

```
task_score = (structural_accuracy * 0.3) + (element_recall * 0.25) + (actionability_accuracy * 0.25) + (network_capture * 0.2)
```

**Overall benchmark score** = mean of 5 task scores.

| Score | Rating |
|-------|--------|
| 90–100 | Excellent |
| 75–89 | Good |
| 60–74 | Acceptable |
| < 60 | Needs work |

---

## Test Execution

Benchmarks run as standard pytest tests against mocked page fixtures. No browser download, no network, no Playwright required.

```bash
# Run all observer benchmarks
python -m pytest tests/benchmarks/ -v

# Run specific benchmark
python -m pytest tests/benchmarks/test_observer_benchmark.py::test_b001_static_page -v
```

## Fixture Format

Each fixture is a JSON file representing a mocked page snapshot:

```json
{
  "url": "https://example.com/page",
  "title": "Page Title",
  "html": "<html>...</html>",
  "interactive_elements": [
    {
      "selector": "button#submit",
      "tag": "button",
      "role": "button",
      "text": "Submit",
      "shadow_root": false,
      "actionability": {
        "attached": true,
        "visible": true,
        "enabled": true,
        "editable": false,
        "stable": true,
        "pointer_events": true
      }
    }
  ],
  "network": [
    {
      "url": "https://api.example.com/data",
      "method": "GET",
      "status": 200,
      "type": "fetch"
    }
  ]
}
```

The observer under test receives the fixture as input and must produce output matching the expected shape from the Roadmap Phase 1 spec:

```json
{
  "url": "...",
  "title": "...",
  "interactive_elements": [...],
  "actionability": [...],
  "network": [...]
}
```

---

## Dependencies

- `netweaver.observer` module (NW-001, not yet implemented)
- `pytest` for test runner
- Fixtures are self-contained JSON files

## Risks

- Observer module (NW-001) not yet implemented — benchmarks serve as **acceptance tests** for that module
- Shadow DOM handling may require Playwright features; mocked fixtures test the interface contract
- Scoring weights may need adjustment after first implementation run
