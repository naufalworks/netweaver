# NetWeaver Project Goal

## Mission

Build a **browser-native AI OS** — an evidence-first web cognition engine that understands the web as a live system: DOM, JS runtime, network, storage, events, visual state, user intent.

Not an LLM+Playwright wrapper. The novelty is the **cognitive layer**: WebSceneGraph + WNAL/BASIL DSL + evidence verifier + perspective engine + site skill learning.

## Principles

1. **Evidence-first** — every action has pre/post evidence. Claims are verified, not assumed.
2. **Deterministic where possible** — typed actions (WNAL), graph queries, deterministic verification. LLM only where reasoning is needed.
3. **Self-healing** — fail gracefully, revert cleanly, learn from recovery.
4. **User-friendly** — hide DOM/selectors/WNAL internals. Show goal, plan, approvals, evidence receipt.

## Architecture

- **WebSceneGraph** — live model of page (DOM + intent + accessibility + JS state)
- **WNAL** — typed action language (click, fill, wait, navigate)
- **Executor** — plan → resolve → verify → execute → verify loop
- **Perspective Engine** — safety check, risk analysis, user approval
- **Skill Learner** — extract reusable patterns from successful runs
- **Evidence Report** — receipts for every action, verifiable claims

## Current Status

**Phase 1 (Data Layer):** Complete ✅
**Phase 2 (Live Integration):** In progress — executor.py healthy (1380 tests ✅), daemon active
**Phase 3 (Intelligence):** Not started
**Phase 4 (Production):** Not started
