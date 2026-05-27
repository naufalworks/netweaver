# NetWeaver Company Roles

## CEO/Product
model: claude-combo
owns: product direction, SaaS value, MVP priorities
writes: PRODUCT_SPEC.md, KANBAN.md priorities

## CTO/Architect
model: claude-combo
owns: architecture, interfaces, ADRs, task decomposition
writes: ARCHITECTURE_DECISIONS.md, HANDOFF.md

## Runtime Engineer
model: claude-combo
owns: CloakBrowser integration, observer, executor, network capture
writes: netweaver/observer.py, runtime tests

## WNAL Engineer
model: claude-combo
owns: DSL/IR, typed actions, verifier contracts
writes: netweaver/wnal.py, schema tests

## QA Benchmark
model: claude-combo
owns: benchmarks, fixtures, regression tests, quality metrics
writes: benchmarks/*, tests/*

## Safety Reviewer
model: claude-combo
owns: permissions, prompt injection, irreversible action gates
writes: SAFETY.md, review notes
