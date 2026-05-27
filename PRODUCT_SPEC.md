# NetWeaver Product Specification

## Phase 1: Graph-Driven Action Resolution (NW-015)
The executor supports graph-native target resolution via `resolve_target()`. When a scene graph is provided, actions can use natural-language descriptions instead of raw CSS selectors. The graph ensures targets are evidence-backed and safety-checked before execution proceeds.

## Phase 2: Live Executor Integration (NW-016)
The executor now supports real CloakBrowser actions via `cloak_bridge`. Mode: `'live'` uses real browser actions; `'mock'` uses testing stubs. The live mode integrates with CloakBrowser to perform actual browser automation while maintaining evidence-first verification across all phases: PRE, PERSPECTIVE, EXECUTE, POST, VERIFY.

### Executor Component Status

| Component | Status | Description |
|-----------|--------|-------------|
| CloakBridge | Implemented | Interfaces with CloakBrowser for real or mock execution. |
| Mode Switching | Implemented | Seamlessly switch between live and mock modes. |
| Phase Verification | Implemented | Enforces evidence-first lifecycle: PRE → PERSPECTIVE → EXECUTE → POST → VERIFY. |

## Future Phases
To be defined.
