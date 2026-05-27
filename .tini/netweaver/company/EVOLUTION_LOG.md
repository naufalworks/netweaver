# Evolution Log — agent lifecycle tracking

Records creation, deletion, and modification of pipeline agents.

## 2026-05-24 — meta-review upgraded to self-healing orchestrator
action: rename + upgrade
from: autonomy-pipeline-meta-review
to: autonomy-pipeline-self-healer
change: added cronjob toolset, self-healing rules, failure ledger access
reason: enable auto-diagnose, auto-fix, dynamic agent creation/deletion

