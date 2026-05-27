# Observer Benchmark Plan

## Overview
Benchmark suite for the NetWeaver Observer module (`netweaver/observer.py`).
Tests validate observer output shape, actionability evidence completeness,
and scoring against fixture-defined expected results.

No browser download required — fixtures are static JSON.

## Benchmark Tasks

### B-001: Static Page
- **Fixture:** `tests/fixtures/static_page.json`
- **Input:** 3 interactive elements, 0 network events
- **Expected:** All elements visible/enabled/attached/stable/pointer_events
- **Score weight:** 15%

### B-002: Form Page
- **Fixture:** `tests/fixtures/form_page.json`
- **Input:** 5 form elements (input, password, textarea, select, button)
- **Expected:** Editable/password checks, submit button enabled
- **Score weight:** 20%

### B-003: SPA Page
- **Fixture:** `tests/fixtures/spa_page.json`
- **Input:** 12 elements, shadow DOM, hidden elements, disabled elements, 2 network events
- **Expected:** Mixed visibility/state, network timing
- **Score weight:** 25%

### B-004: Error Page
- **Fixture:** `tests/fixtures/error_page.json`
- **Input:** 1 element, 404 network response, degraded state
- **Expected:** Error detection, limited interactivity
- **Score weight:** 15%

### B-005: Heavy Page
- **Fixture:** `tests/fixtures/heavy_page.json`
- **Input:** 51 elements, 10 network events, mixed visibility/state (4 hidden, 3 disabled, 3 no-pointer-events)
- **Expected:** Actionability classification, performance within bounds
- **Score weight:** 25%

## Success Metrics

| Metric | Target |
|--------|--------|
| Element detection recall | ≥ 95% |
| Actionability accuracy | ≥ 90% |
| Network event capture | ≥ 80% |
| Shadow DOM coverage | ≥ 50% |
| Processing latency (51 elements) | ≤ 500ms |

## Scoring Formula

```
score = Σ(task_weight × task_accuracy)
task_accuracy = correct_classifications / total_classifications
```

**Pass threshold:** score ≥ 0.85

## Fixture Format

Each fixture is a JSON file with the observer output shape:

```json
{
  "url": "https://example.com/page",
  "title": "Page Title",
  "interactive_elements": [
    {
      "selector": "css-selector",
      "tag": "button",
      "text": "Click Me",
      "actionability": {
        "visible": true,
        "enabled": true,
        "attached": true,
        "stable": true,
        "pointer_events": true
      }
    }
  ],
  "actionability": {
    "total": 3,
    "actionable": 2,
    "blocked": 1
  },
  "network": []
}
```
