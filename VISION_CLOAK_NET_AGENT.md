# Cloak Net Agent — Novel Browser-Native AI Architecture

## Main Goal
Build a browser-native AI agent architecture that beats generic LLM agents at web automation by understanding the web as a live system: DOM, JS runtime, network, storage, events, visual state, user intent.

Target runtime: CloakBrowser  
Repo: https://github.com/CloakHQ/CloakBrowser

## Core Thesis
LLMs fail at browser automation because they treat websites as text/screenshots. A stronger agent should treat the web as a structured, observable, executable environment.

This is not “LLM + browser”. It is a **web cognition engine** with:

- its own web-native language
- multi-graph world model
- verifier
- recovery engine
- site memory
- specialist swarm

Working name: **NetWeaver**.

---

## Novel Idea
Create a **Web-Native Agent Language**: `WNAL`.

WNAL represents:

- user intent
- page state
- actions
- network evidence
- verification
- recovery
- learned site skills

Example:

```wnal
GOAL authenticate(site)
OBSERVE dom.interactive, network.auth, storage.cookies
PLAN
  NAVIGATE login_surface
  FILL credential_fields verified_by(labels+autocomplete+form_role)
  SUBMIT form
VERIFY
  url !~ /login/
  network.status in [200,204,302]
  cookie.exists(session|auth|token)
  dom.contains(user_identity|dashboard)
RECOVER
  if captcha -> escalate
  if 2fa -> ask_user
  if field_mismatch -> rescan_semantics
```

## Why This Can Beat LLMs On Web Automation

Generic LLM browser agents:

- guess from screenshots/text
- hallucinate selectors
- forget hidden JS/network state
- click without proving results
- fail on dynamic SPAs
- recover poorly

NetWeaver:

- builds multi-layer page model
- reasons over DOM + JS + network + storage + visual state
- uses typed actions with pre/postconditions
- verifies every step with browser evidence
- stores reusable site skills
- learns stable web interaction patterns

---

## Architecture

```text
Natural language request
↓
Intent Compiler
↓
WNAL task graph
↓
Web World Model
  - DOM semantic graph
  - Accessibility graph
  - Visual layout graph
  - JS runtime facts
  - Network graph
  - Storage/session graph
↓
Planner Swarm
↓
Action Executor via CloakBrowser
↓
Verifier
↓
Recovery / Learning
```

---

## Swarm Roles

### 1. Intent Compiler
Converts natural language into WNAL.

Output:

- goal
- entities
- success criteria
- risk class
- allowed actions
- ambiguity questions

### 2. DOM Cartographer
Builds semantic DOM map.

Understands:

- forms
- buttons
- labels
- ARIA roles
- hidden fields
- shadow DOM
- iframes
- SPA routes

Output:

- stable element candidates
- semantic selectors
- confidence scores

### 3. JS Runtime Analyst
Inspects runtime state safely.

Understands:

- React/Vue/Svelte/Next/Nuxt hints
- hydration state
- route state
- event handlers
- client stores
- disabled/loading states

Output:

- runtime readiness
- event dependencies
- likely side effects

### 4. Network Intelligence Agent
Models traffic.

Understands:

- fetch/XHR
- REST
- GraphQL
- auth flows
- redirects
- status codes
- websockets
- rate limits

Output:

- action → network causality
- API affordances
- verification evidence

### 5. Visual Grounder
Used when DOM is insufficient.

Understands:

- overlays
- modals
- occlusion
- canvas-heavy UI
- visual positions

Output:

- clickable regions
- obstruction alerts
- visual verification

### 6. Planner
Creates robust action plan.

Rules:

- minimal actions
- explicit preconditions
- fallback paths
- reversible when possible
- ask user for secrets/2FA/captcha

### 7. Executor
Runs actions through CloakBrowser.

Actions:

- navigate
- click
- type
- select
- upload
- wait_for
- read network
- evaluate safe JS
- screenshot

### 8. Verifier
Checks success from evidence.

Evidence:

- DOM changed
- URL changed
- network status
- storage/cookies
- visual state
- app state
- actionability evidence envelope (`attached`, `visible`, `enabled`, `editable`, `stable`, `pointer_events`) from CloakBrowser pre/post checks for typed actions

### 9. Recovery Agent
If failure:

- classify failure
- rescan state
- choose fallback
- avoid retry loops

### 10. Site Memory Agent
Stores reusable site skills.

Examples:

- login flow for site X
- stable selectors
- API pattern
- rate-limit behavior

---

## WNAL Core

```wnal
GOAL <verb>(<entity>)
CONTEXT <facts>
OBSERVE <layers>
PLAN <steps>
ACTION <typed_action>
VERIFY <conditions>
RECOVER <fallbacks>
MEMORIZE <site_skill>
```

Typed action:

```wnal
ACTION click(element)
  pre: element.visible && element.enabled && confidence > 0.8
  do: browser.click(element.selector)
  post: dom.changed || network.request || url.changed
```

Typed fill:

```wnal
ACTION fill(field, value)
  pre: field.input_like && field.editable
  do: browser.type(field.selector, value)
  post: field.value == value
```

Typed wait:

```wnal
ACTION wait(signal)
  signal: network.idle || dom.ready || selector.visible || route.changed
  timeout: 10s
  recover: rescan
```

---

## Key Technical Innovations

### 1. Multi-Graph Web World Model
A page becomes connected graphs:

```text
DOM graph
A11y graph
Visual graph
Network graph
JS state graph
Storage graph
```

Edges:

- element triggers request
- button belongs to form
- request updates DOM node
- cookie/session affects route
- visual box maps to DOM node

This gives causal understanding.

### 2. Action Causality Ledger
Every action records:

```json
{
  "action": "click Login",
  "before": {"url": "/login", "dom_hash": "..."},
  "events": ["click", "submit"],
  "network": [{"POST": "/api/auth/login", "status": 200}],
  "after": {"url": "/dashboard", "cookie": "session"},
  "verified": true
}
```

No claim is accepted without browser evidence.

### 3. Selector Ensemble
Never trust one selector.

Ranked evidence:

- role/name
- label association
- autocomplete
- placeholder
- text
- CSS path
- XPath fallback
- visual coordinate fallback

### 4. Internet Perspective Memory
Learns web archetypes:

- login flows
- checkout flows
- dashboards
- consent modals
- SPA loading states
- anti-bot/captcha detection

---

## Natural Language Boundary
Natural language is ambiguous. The Intent Compiler must ask questions when missing:

- target site
- exact user goal
- success criteria
- credential/permission boundary
- destructive/remote side effects

The agent should compile broad NL into small WNAL tasks.

---

## Limitations

Hard limits:

- Captcha/anti-bot should not be bypassed illegally.
- 2FA/secrets require user input.
- Cross-origin iframes restrict introspection.
- Obfuscated/canvas-heavy apps need visual grounding.
- Some sites block automation fingerprints.
- Legal/ToS boundaries matter.

Frontend understanding limit:

- It can understand observable/runtime behavior, not true developer intent unless source/source maps are available.

Network understanding limit:

- It can infer API semantics from traffic, but must not exfiltrate secrets or bypass access controls.

---

## Safety Policy

Require confirmation for:

- purchase/payment
- sending messages/posts/emails
- deleting/modifying remote data
- account/security changes
- credential submission unless explicitly authorized
- private data scraping

Auto-approve:

- navigation
- reading public pages
- filling non-sensitive search/filter fields
- UI inspection
- local logs

---

## MVP Path

### MVP 1 — Cloak Observer
Use CloakBrowser to collect:

- DOM snapshot
- accessibility tree
- visible text
- screenshot
- network log
- storage/cookies metadata

Output: `world_model.json`.

### MVP 2 — WNAL Compiler
Convert NL task into WNAL plan.

### MVP 3 — Verified Actions
Implement `click`, `type`, `wait` with pre/post verification.

### MVP 4 — Network-Aware Verification
Map actions to network events.

### MVP 5 — Site Skills
Persist successful flows.

---

## First Tiny Goal
Research CloakBrowser API surface and identify how to access:

- DOM
- screenshots
- network logs
- JS evaluation
- storage/cookies
- automation commands

Then create `CLOAK_RESEARCH.md`.

---

## Success Metrics

- task success rate
- retries per task
- hallucinated-success rate
- recovery rate
- time to complete
- tokens per completed task

## Benchmark Tasks

- login form
- search/filter product
- fill multi-step form
- navigate SPA dashboard
- extract table data
- handle modal/consent banner
- recover from wrong selector
- detect failed network request

## Principle
LLM is only the language/reasoning layer. Browser-native evidence is authority.

**No claim is true unless verified by browser evidence.**

## Novelty Thesis
NetWeaver is an Evidence-native web cognition engine, not a Playwright wrapper. CloakBrowser/Playwright is the body; WebSceneGraph + WNAL + Verifier + Perspective Engine are the cognitive layer.

Core invention: understand and verify web state transitions across DOM, visual, JS, network, storage, and user intent.
