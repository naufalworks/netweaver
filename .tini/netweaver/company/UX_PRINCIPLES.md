# NetWeaver UX Principles

## Product Promise
Web automation with receipts.

## Newbie Experience
Users should never need to know Playwright, selectors, DOM, WNAL, JS, or network internals.

They should see:
- goal
- simple plan
- approval request if risky
- progress updates
- verified result
- evidence summary

## Modes

### Watch-only
Observe/explain website without clicking.

### Guided automation
Suggest actions and ask before risky steps.

### Autonomous task
Run scheduled safe workflows and report anomalies/results.

### Teach mode
User performs a task once; NetWeaver records a reusable verified site skill.

## Communication Style
- concise
- non-technical by default
- show technical evidence only behind expandable details
- always explain risk before irreversible actions

## Safety UX
Require explicit approval for:
- purchases/payments
- sending messages/posts/emails
- deleting/modifying remote data
- account/security changes
- credential submission unless explicitly authorized

## Evidence UX
Every result should have a human-readable receipt:

```text
Result: Payment succeeded ✅
Evidence:
- URL: /billing
- API: GET /api/payments → 200
- DOM: latest status = Paid
```

## CLI UX
Target commands:

```bash
netweaver observe https://example.com
netweaver run "check latest invoice"
netweaver teach "export monthly report"
netweaver skill list
```

## Design Rule
If a newbie cannot understand the result, the UX failed.
