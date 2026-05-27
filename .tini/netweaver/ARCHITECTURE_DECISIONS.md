# NetWeaver Architecture Decisions

## ADR-001: CloakBrowser as Playwright-compatible executor
CloakBrowser returns Playwright Browser/Page objects. NetWeaver should build on Playwright APIs first, using CloakBrowser launch as stealth runtime.

## ADR-002: Evidence-first automation
No action is considered successful unless verified by DOM/URL/network/storage/visual evidence.

## ADR-003: LLM bounded to compilation/ambiguity
LLM converts natural language to WNAL/BASIL and resolves ambiguity; executor/verifier owns truth.

