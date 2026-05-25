# Evidence Report Contract Benchmark

**Task**: NW-006
**Owner**: QA Benchmark
**Date**: 2026-05-23
**Status**: review

## Purpose

Define the contract for NetWeaver's evidence reports — the core output that links verifiable claims to browser observations. Every claim must be backed by observations from DOM, network, storage, or actionability evidence. Unsupported claims fail verification.

This benchmark validates the contract, not performance.

---

## Evidence Types

| Type | Source | Example Data |
|------|--------|-------------|
| DOM | Observer | `{selector, tag, visible, text}` |
| Network | Network monitor | `{url, method, status, timing}` |
| Storage | Storage probe | `{store, key, value, exists}` |
| Actionability | Observer checks | `{selector, attached, visible, enabled, editable, stable, pointer_events}` |

---

## Contract Rules

1. **Every claim links to ≥1 observation.** Claims with empty `observation_ids` fail.
2. **Linked observations must exist.** Claims referencing nonexistent observation IDs fail.
3. **Evidence types are explicit.** Each claim and observation declares its type.
4. **Verification is total.** All claims must pass → report is verified. Any failure → report is unverified.
5. **Unsupported claims are identifiable.** `get_unsupported_claims()` returns exactly the failing claims.

---

## Test Coverage

| Test | Validates |
|------|-----------|
| DOM evidence round-trip | Observation + claim for element visibility |
| Network evidence | API response claim backed by network observation |
| Storage evidence | localStorage claim backed by storage probe |
| Actionability evidence | Element state claim backed by actionability check |
| Unsupported claim (no observations) | Empty `observation_ids` → verify fails |
| Unsupported claim (missing observation) | Nonexistent `observation_id` → verify fails |
| Mixed supported/unsupported | Any unsupported → overall verify fails |
| No claims (vacuously true) | Empty claims list → verify succeeds |
| Serialization round-trip | `to_dict()` → `from_dict()` preserves all fields |
| JSON validity | `to_dict()` output is `json.dumps()`-safe |
| Summary counts | Correct claim/observation/unsupported counts |
| Factory helpers | `create_observation()`, `create_claim()` produce valid objects |

---

## Scoring

This is a contract benchmark, not performance. Pass = all tests green.

| Metric | Target |
|--------|--------|
| All evidence types supported | 4/4 |
| Unsupported claim detection | 100% |
| Serialization integrity | 100% |
| No browser/network required | Yes |

---

## Dependencies

- `netweaver/evidence.py` — evidence report module
- `pytest` — test runner
- No browser, no network, no Playwright

## Risks

- Evidence report is standalone — not yet integrated with observer (NW-001) or perspective engine (NW-005)
- Storage evidence type has no observer implementation yet
- Claim verification is binary (supported/unsupported); no partial support modeling yet
