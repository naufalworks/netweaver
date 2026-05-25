# Failure Ledger

Tracked failure patterns and resolutions for self-healing orchestrator.

| Pattern ID | Pattern | Root Cause | Resolution | First Seen | Last Seen | Count |
|---|---|---|---|---|---|---|
| F-001 | "No active credentials for provider: openai" on local-proxy jobs | Local proxy (localhost:20128) upstream temporarily lost openai credentials. Jobs configured with `provider: local` + `model: xmtp/mimo-v2.5-pro` but proxy routed to openai upstream which had no creds. | Transient — proxy self-healed within ~2min. No config change needed. Jobs auto-retry on next schedule. | 2026-05-24 22:10 | 2026-05-24 22:12 | 3 |
