# STATE — NetWeaver (project view)

Last updated: 2026-05-31 21:56 UTC

## Project Health

- 2336 tests ✅ passing
- daemon.py: heartbeat ✅, file rollback ✅, cleanup_loop ✅, metrics ✅
- executor.py: fully reconstructed ✅
- circuit_breaker.json: active ✅
- self-healing pipeline: 8 crons active ✅
- KANBAN.md: fixed ✅ (done items moved to correct section)
- CLI tool: `netweaver status/kanban/queue/logs/metrics/backlog` ✅

## Active Pipeline

| Component | Schedule | Status |
|-----------|----------|--------|
| Daemon (gap detection + plan gen) | every 2min | ✅ running |
| Auto-reviewer (approve/reject plans) | :03/:18/:33/:48 | ✅ cron |
| Worker (execute approved plans) | :15/:45 | ✅ cron |
| Watchdog (restart dead daemon) | every 5min | ✅ cron |
| Self-test (8-point health check) | every 30min | ✅ cron |
| Ideas archival (stale >72h) | 3AM daily | ✅ cron |
| Coverage report (weekly scan) | Mon 4AM | ✅ cron |
| Git auto-push (push to origin) | every 6h | ✅ cron |

## Self-Healing Features

| Feature | Location | Status |
|---------|----------|--------|
| Log rotation (hourly, keep 1000) | cleanup_loop | ✅ |
| Backup prune (keep 20) | cleanup_loop | ✅ |
| Events rotation (keep 2000) | cleanup_loop | ✅ |
| Skills purge (>7d) | cleanup_loop | ✅ |
| Agent reaper (>48h) | cleanup_loop | ✅ |
| Metrics tracking | record_metric() | ✅ |
| Auto-archive rejected plans (>3x) | archive_stale_rejections() | ✅ |
| Circuit breaker (5 failures → pause 10min) | circuit_breaker | ✅ |
| Heartbeat monitoring | heartbeat_loop | ✅ |
| File rollback on test failure | backup_file/restore | ✅ |

## Backlog

- 13 tasks queued (NW-031 to NW-038, P-01 to P-05)
- Priority: Observer/Playwright tests (700 LOC untested) → E2E demo → skill auto-learning

## Module Health

| Module | LOC | Tests | Status |
|--------|-----|-------|--------|
| action_orchestrator | 1011 | ✅ | stable |
| executor | 760 | ✅ | stable |
| planner | 631 | ✅ | stable |
| scene_graph_builder | 629 | ✅ | stable |
| graph_query | 616 | ✅ | stable |
| perspective | 570 | ✅ | stable |
| scene_graph | 452 | ✅ | stable |
| cloak_bridge | 443 | ❌ untested | needs NW-031 |
| wnal | 427 | ✅ | stable |
| evidence | 410 | ✅ | stable |
| playwright_bridge | 399 | ❌ untested | needs NW-031 |
| observer | 301 | ❌ untested | needs NW-031 |
