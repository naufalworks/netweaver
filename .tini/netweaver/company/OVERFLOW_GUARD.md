# Context Overflow Guard

## Trigger

A cron job fails with `429` or empty response due to prompt exceeding model's context budget.

## Causes

- Inlining large skill docs/app source in prompt instead of loading via `skills` parameter
- Prompt is >10KB raw text (model context ~8K-32K tokens)

## Prevention (mandatory)

1. Never inline skill content in cron prompt. Use `skills: ["hermes-agent"]` — the system loads them efficiently.
2. Keep prompts under 1,000 chars. If you need more, split into separate jobs.
3. Use compact form:

```
Role: <role>
Workdir: <path>
Read <file> → pick task → execute → report
Rules: <short list>
```

NO long mission statements, NO inlined code/docs, NO communication protocol walls of text.

## Detection

Watchdog checks for:
- `last_status: error` with frequency >2 per 6h
- Prompt sizes >2,000 chars (flag in meta-review)

## Recovery

1. Shorten prompt to <1,000 chars
2. Verify skills parameter loads the right skills
3. Run one tick manually
4. If still failing: check model endpoint
