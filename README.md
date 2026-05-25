# NetWeaver

A goal-to-plan translator and browser observer for web automation.

## Overview

NetWeaver translates natural language goals into deterministic action plans using template-based matching with graph validation. It includes a browser observer for extracting page metadata, interactive elements, and network activity.

## Modules

- `netweaver/planner.py` - Goal-to-plan translation via keyword matching and template validation
- `netweaver/observer.py` - Browser page inspection with actionability evidence

## Design

- **Deterministic**: keyword-based matching, no randomness
- **Graph-aware**: validates targets exist in scene graph
- **Fallback**: unknown goals produce minimal single-step plan
- **Composable**: default templates extendable
- **No browser/vendor imports in planner**