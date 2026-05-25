# Autonomous Pipeline v2: Event-Driven + Tiered Autonomy

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the polling-based 10-agent cron pipeline with an event-driven, token-efficient, self-healing architecture that reduces daily token burn by ~70% and adds automatic failure recovery.

**Architecture:** Three-tier system — Watchtower (script, 0 tokens) detects state changes → Dispatcher (cheap routing) decides who runs → Workers (mimo-v2.5-pro) execute scoped tasks with minimal context. Circuit breaker auto-pauses failing agents. State fingerprinting skips no-op runs.

**Current State:** 10 cron jobs polling every 15-60min. ~800-1200 API calls/day. ~60% idle waste. No circuit breaker. No conflict detection.

**Target State:** 6-7 jobs. ~200-400 API calls/day. Event-triggered. Auto-healing. Compact context.

**Tech Stack:** Bash/Python scripts (watchtower), Hermes cron jobs (agents), JSONL event bus, SHA256 fingerprinting, JSON circuit breaker state.

---

## Phase 1: Foundation (Quick Wins)

### Task 1: Create Watchtower Script

**Objective:** Replace the LLM-based self-healer with a zero-token filesystem monitor.

**Files:**
- Create: `~/.hermes/scripts/netweaver_watchdog_v2.py`

**Step 1: Write the watchtower script**

```python
#!/usr/bin/env python3
"""
NetWeaver Watchtower v2 — Zero-token event detector.
Runs every 2 min via cron (no_agent=true).
Outputs alerts to stdout only when something needs attention.
Silent stdout = no delivery (watchdog pattern).
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

WORKDIR = Path(os.environ.get("NETWEAVER_WORKDIR", "/Users/azfar.naufal/Documents/myhermes"))
TINI = WORKDIR / ".tini"
NETWEAVER = TINI / "netweaver"
EVENTS_FILE = TINI / "events.jsonl"
STATE_FILE = TINI / "state_fingerprint.txt"
CIRCUIT_FILE = TINI / "circuit_breaker.json"

# Files to monitor for changes
WATCHED_FILES = [
    NETWEAVER / "company" / "KANBAN.md",
    NETWEAVER / "STATUS.md",
    NETWEAVER / "HANDOFF.md",
    NETWEAVER / "BLOCKERS.md",
    NETWEAVER / "BACKLOG.md",
    TINI / "ideas" / "reviewed.md",
    TINI / "ideas" / "inbox.md",
    TINI / "ideas" / "executing.md",
]

# Agent health tracking
AGENT_HEALTH_FILE = TINI / "agent_health.json"


def file_mtime_hash(paths):
    """Compute fingerprint from file mtimes + sizes."""
    h = hashlib.sha256()
    for p in sorted(paths):
        if p.exists():
            stat = p.stat()
            h.update(f"{p.name}:{stat.st_mtime_ns}:{stat.st_size}".encode())
        else:
            h.update(f"{p.name}:missing".encode())
    return h.hexdigest()[:16]


def load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return default if default is not None else {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def append_event(event_type, payload):
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    event = {"type": event_type, "ts": datetime.now().isoformat(), **payload}
    with open(EVENTS_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")


def check_state_changes():
    """Check if any watched files changed since last run."""
    current = file_mtime_hash(WATCHED_FILES)
    last = STATE_FILE.read_text().strip() if STATE_FILE.exists() else ""
    if current != last:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(current)
        append_event("state_changed", {"fingerprint": current})
        return True
    return False


def check_agent_health():
    """Detect agents that missed too many scheduled runs."""
    health = load_json(AGENT_HEALTH_FILE, {})
    now = time.time()
    alerts = []

    # Expected intervals (seconds) per agent
    EXPECTED = {
        "architect": 900,       # 15min
        "runtime-engineer": 900,
        "wnal-engineer": 900,
        "safety-review": 900,
        "qa-benchmark": 900,
        "task-compiler": 3600,  # 60min
        "task-runner": 1800,    # 30min
    }

    for agent, interval in EXPECTED.items():
        last_ok = health.get(agent, {}).get("last_ok", 0)
        missed = int((now - last_ok) / interval) if last_ok > 0 else 0
        if last_ok > 0 and missed >= 3:
            alerts.append(f"Agent '{agent}' missed ~{missed} runs (last ok: {datetime.fromtimestamp(last_ok).isoformat()})")

    return alerts


def check_circuit_breaker():
    """Check if any agents are paused and should be resumed."""
    cb = load_json(CIRCUIT_FILE, {})
    now = datetime.now()
    resumed = []

    for agent, state in cb.items():
        paused_until = state.get("paused_until")
        if paused_until:
            try:
                resume_time = datetime.fromisoformat(paused_until)
                if now >= resume_time:
                    state["paused_until"] = None
                    state["consecutive_failures"] = 0
                    resumed.append(agent)
            except (ValueError, TypeError):
                pass

    if resumed:
        save_json(CIRCUIT_FILE, cb)
        append_event("circuit_breaker_resumed", {"agents": resumed})

    return resumed


def check_file_conflicts():
    """Detect if multiple agents wrote to the same file recently."""
    # Check for .lock files or recent concurrent writes
    lock_files = list(TINI.glob("**/*.lock"))
    conflicts = []
    for lf in lock_files:
        age = time.time() - lf.stat().st_mtime
        if age > 300:  # stale lock > 5min
            conflicts.append(f"Stale lock: {lf} (age: {int(age)}s)")
            lf.unlink()  # auto-clean stale locks
    return conflicts


def main():
    output = []

    # 1. State change detection
    changed = check_state_changes()
    if changed:
        output.append("STATE_CHANGED: Watched files modified since last check")

    # 2. Agent health
    health_alerts = check_agent_health()
    if health_alerts:
        output.extend([f"HEALTH_ALERT: {a}" for a in health_alerts])

    # 3. Circuit breaker resume check
    resumed = check_circuit_breaker()
    if resumed:
        output.append(f"CIRCUIT_RESUMED: Agents back online: {', '.join(resumed)}")

    # 4. File conflicts
    conflicts = check_file_conflicts()
    if conflicts:
        output.extend([f"CONFLICT: {c}" for c in conflicts])

    # Only output if there's something to report
    if output:
        print("\n".join(output))
    # Empty stdout = silent (no delivery)


if __name__ == "__main__":
    main()
```

**Step 2: Make it executable**

```bash
chmod +x ~/.hermes/scripts/netweaver_watchdog_v2.py
```

**Step 3: Test it runs silently when nothing changed**

```bash
python3 ~/.hermes/scripts/netweaver_watchdog_v2.py
# Expected: empty output (no changes detected yet)

# Touch a watched file to trigger
touch /Users/azfar.naufal/Documents/myhermes/.tini/netweaver/company/KANBAN.md
python3 ~/.hermes/scripts/netweaver_watchdog_v2.py
# Expected: "STATE_CHANGED: Watched files modified since last check"
```

**Step 4: Create cron job (replace old self-healer)**

```
hermes cronjob create \
  --name "netweaver-watchtower" \
  --schedule "every 2m" \
  --no-agent \
  --script "netweaver_watchdog_v2.py"
```

**Step 5: Pause old self-healer**

```
hermes cronjob pause eda27641f001
```

**Verification:** Watchtower runs silently when nothing changes. Outputs alerts only on state change, health issues, or conflicts. Zero tokens consumed.

---

### Task 2: Implement Circuit Breaker

**Objective:** Auto-pause agents after 3 consecutive failures, auto-resume after cooldown.

**Files:**
- Create: `.tini/circuit_breaker.json` (initial empty state)
- Modify: Each worker agent's prompt (add circuit breaker check)

**Step 1: Initialize circuit breaker state**

```bash
echo '{}' > /Users/azfar.naufal/Documents/myhermes/.tini/circuit_breaker.json
```

**Step 2: Add circuit breaker check script**

Create `~/.hermes/scripts/circuit_breaker_check.py`:

```python
#!/usr/bin/env python3
"""
Check circuit breaker before agent runs.
Usage: python3 circuit_breaker_check.py <agent_name>
Exit 0 = allowed to run. Exit 1 = paused (skip).
Prints reason to stdout.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

CIRCUIT_FILE = Path("/Users/azfar.naufal/Documents/myhermes/.tini/circuit_breaker.json")
COOLDOWN_MINUTES = 60
MAX_FAILURES = 3

def main():
    agent = sys.argv[1] if len(sys.argv) > 1 else "unknown"

    if not CIRCUIT_FILE.exists():
        sys.exit(0)  # no circuit breaker file = allow

    try:
        cb = json.loads(CIRCUIT_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    state = cb.get(agent, {})
    failures = state.get("consecutive_failures", 0)
    paused_until = state.get("paused_until")

    if paused_until:
        try:
            if datetime.now() < datetime.fromisoformat(paused_until):
                print(f"PAUSED: {agent} circuit breaker active until {paused_until} ({failures} consecutive failures)")
                sys.exit(1)
        except (ValueError, TypeError):
            pass

    if failures >= MAX_FAILURES:
        resume_at = datetime.now().replace(second=0, microsecond=0)
        from datetime import timedelta
        resume_at = resume_at + timedelta(minutes=COOLDOWN_MINUTES)
        state["paused_until"] = resume_at.isoformat()
        cb[agent] = state
        CIRCUIT_FILE.write_text(json.dumps(cb, indent=2) + "\n")
        print(f"PAUSED: {agent} hit {failures} failures. Paused until {resume_at.isoformat()}")
        sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
```

```bash
chmod +x ~/.hermes/scripts/circuit_breaker_check.py
```

**Step 3: Add circuit breaker update script**

Create `~/.hermes/scripts/circuit_breaker_update.py`:

```python
#!/usr/bin/env python3
"""
Update circuit breaker after agent run.
Usage: python3 circuit_breaker_update.py <agent_name> <ok|error>
"""
import json
import sys
from pathlib import Path
from datetime import datetime

CIRCUIT_FILE = Path("/Users/azfar.naufal/Documents/myhermes/.tini/circuit_breaker.json")
HEALTH_FILE = Path("/Users/azfar.naufal/Documents/myhermes/.tini/agent_health.json")

def load_json(p, default=None):
    if p.exists():
        try:
            return json.loads(p.read_text())
        except: pass
    return default if default is not None else {}

def save_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")

def main():
    agent = sys.argv[1]
    status = sys.argv[2]  # "ok" or "error"

    # Update circuit breaker
    cb = load_json(CIRCUIT_FILE, {})
    state = cb.get(agent, {"consecutive_failures": 0})

    if status == "ok":
        state["consecutive_failures"] = 0
        state["paused_until"] = None
        state["last_ok"] = datetime.now().isoformat()
    else:
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        state["last_error"] = datetime.now().isoformat()

    cb[agent] = state
    save_json(CIRCUIT_FILE, cb)

    # Update health tracking
    health = load_json(HEALTH_FILE, {})
    if status == "ok":
        health.setdefault(agent, {})["last_ok"] = datetime.now().timestamp()
    save_json(HEALTH_FILE, health)

if __name__ == "__main__":
    main()
```

```bash
chmod +x ~/.hermes/scripts/circuit_breaker_update.py
```

**Step 4: Test circuit breaker**

```bash
# Should allow (no failures)
python3 ~/.hermes/scripts/circuit_breaker_check.py "test-agent"
echo $?  # Expected: 0

# Simulate 3 errors
python3 ~/.hermes/scripts/circuit_breaker_update.py "test-agent" error
python3 ~/.hermes/scripts/circuit_breaker_update.py "test-agent" error
python3 ~/.hermes/scripts/circuit_breaker_update.py "test-agent" error

# Should block now
python3 ~/.hermes/scripts/circuit_breaker_check.py "test-agent"
echo $?  # Expected: 1

# Reset
python3 ~/.hermes/scripts/circuit_breaker_update.py "test-agent" ok
```

**Verification:** Circuit breaker blocks agents after 3 failures. Auto-resumes after 60min cooldown.

---

### Task 3: Add Circuit Breaker to Agent Prompts

**Objective:** Make each agent check circuit breaker before doing work, and update it after.

**Files:**
- Modify: Each cron job prompt (10 jobs)

**Step 1: Add pre-flight check to each agent prompt**

Add this block to the START of every agent's cron prompt:

```
PRE-FLIGHT (before any work):
Run: python3 ~/.hermes/scripts/circuit_breaker_check.py "<agent-name>"
If exit code 1 → output "Circuit breaker active, skipping" and stop.

POST-FLIGHT (after work):
Run: python3 ~/.hermes/scripts/circuit_breaker_update.py "<agent-name>" ok
On failure: python3 ~/.hermes/scripts/circuit_breaker_update.py "<agent-name>" error
```

Agent name mapping:
| Job ID | Agent Name |
|--------|-----------|
| 7dabb518dfb6 | architect |
| b5294bd85a71 | runtime-engineer |
| 5418e6d5c065 | wnal-engineer |
| b25048563a4d | safety-review |
| 1e9b68aba836 | qa-benchmark |
| 4f1d20284401 | task-compiler |
| 2300b4c5ec18 | task-reviewer |
| ff7647b176ed | task-runner |
| be2a31e8eb60 | task-runner-extra |
| eda27641f001 | self-healer (being replaced) |

**Verification:** Each agent checks circuit breaker before running. Failed agents get paused automatically.

---

## Phase 2: Efficiency Gains

### Task 4: State Fingerprinting (Skip No-Op Runs)

**Objective:** Skip agent runs when nothing has changed since last run.

**Files:**
- Create: `~/.hermes/scripts/state_check.py`

**Step 1: Write state check script**

```python
#!/usr/bin/env python3
"""
State fingerprint checker for no-op run skipping.
Usage: python3 state_check.py <agent_name>
Computes SHA256 of relevant file mtimes. Compares to last run.
Exit 0 = state changed (run needed). Exit 1 = no change (skip).
"""
import hashlib
import json
import os
import sys
from pathlib import Path

WORKDIR = Path("/Users/azfar.naufal/Documents/myhermes")
TINI = WORKDIR / ".tini"
STATE_DIR = TINI / "agent_states"

# Per-agent relevant files (only watch what matters to each agent)
AGENT_WATCH_FILES = {
    "architect": [
        "netweaver/ROADMAP.md", "netweaver/BACKLOG.md",
        "netweaver/STATUS.md", "netweaver/BLOCKERS.md",
        "netweaver/company/KANBAN.md", "netweaver/company/PRODUCT_SPEC.md",
    ],
    "runtime-engineer": [
        "netweaver/company/KANBAN.md", "netweaver/HANDOFF.md",
        "netweaver/STATUS.md", "netweaver/BLOCKERS.md",
    ],
    "wnal-engineer": [
        "netweaver/company/KANBAN.md", "netweaver/HANDOFF.md",
        "netweaver/STATUS.md",
    ],
    "safety-review": [
        "netweaver/company/KANBAN.md", "netweaver/REVIEW.md",
        "netweaver/HANDOFF.md", "netweaver/company/SAFETY.md",
    ],
    "qa-benchmark": [
        "netweaver/company/KANBAN.md", "netweaver/HANDOFF.md",
        "netweaver/benchmarks/",
    ],
    "task-compiler": [
        "ideas/inbox.md", "ideas/reviewed.md",
    ],
    "task-reviewer": [
        "ideas/inbox.md", "ideas/reviewed.md",
    ],
    "task-runner": [
        "ideas/reviewed.md", "ideas/executing.md", "ideas/executed.md",
    ],
    "task-runner-extra": [
        "ideas/reviewed.md", "ideas/executing.md", "ideas/executed.md",
    ],
}

def compute_fingerprint(agent):
    files = AGENT_WATCH_FILES.get(agent, [])
    h = hashlib.sha256()
    for f in sorted(files):
        p = TINI / f
        if p.is_dir():
            for child in sorted(p.iterdir()):
                stat = child.stat()
                h.update(f"{child.name}:{stat.st_mtime_ns}:{stat.st_size}".encode())
        elif p.exists():
            stat = p.stat()
            h.update(f"{f}:{stat.st_mtime_ns}:{stat.st_size}".encode())
        else:
            h.update(f"{f}:missing".encode())
    return h.hexdigest()[:16]

def main():
    agent = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{agent}.fingerprint"

    current = compute_fingerprint(agent)
    last = state_file.read_text().strip() if state_file.exists() else ""

    if current == last:
        print(f"NO_CHANGE: {agent} — relevant files unchanged since last run. Skipping.")
        sys.exit(1)  # skip

    state_file.write_text(current)
    print(f"CHANGED: {agent} — state updated, proceeding with run.")
    sys.exit(0)  # proceed

if __name__ == "__main__":
    main()
```

```bash
chmod +x ~/.hermes/scripts/state_check.py
```

**Step 2: Add to agent prompts**

Add before the circuit breaker check:

```
STATE CHECK (skip if nothing changed):
Run: python3 ~/.hermes/scripts/state_check.py "<agent-name>"
If exit code 1 → output "No changes detected, skipping" and stop.
```

**Step 3: Test**

```bash
# First run — should proceed (no previous state)
python3 ~/.hermes/scripts/state_check.py "architect"
echo $?  # Expected: 0

# Second run — should skip (nothing changed)
python3 ~/.hermes/scripts/state_check.py "architect"
echo $?  # Expected: 1

# Touch a relevant file
touch /Users/azfar.naufal/Documents/myhermes/.tini/netweaver/company/KANBAN.md
python3 ~/.hermes/scripts/state_check.py "architect"
echo $?  # Expected: 0
```

**Verification:** Agents skip runs when their relevant files haven't changed. Eliminates ~60% of idle runs.

---

### Task 5: Merge TINI Pipeline (4 Jobs → 2)

**Objective:** Consolidate the 4-step TINI idea pipeline into 2 event-triggered agents.

**Current flow:**
```
01-research (60m) → 02-review (60m) → 03-executor (30m) → 04-extra (30m)
Total latency: ~120min. 4 agents, each re-reads everything.
```

**New flow:**
```
task-compiler (event: inbox.md changes) → task-runner (event: reviewed.md changes)
Total latency: ~15min. 2 agents, scoped context.
```

**Step 1: Create task-compiler prompt (merges research + review)**

New cron job replacing jobs 01 + 02:

```
Name: tini-task-compiler
Schedule: every 60m (will become event-driven in Phase 3)
Model: xmtp/mimo-v2.5-pro

Prompt:
---
Role: Task compiler (merges research + review).

PRE-FLIGHT:
Run: python3 ~/.hermes/scripts/state_check.py "task-compiler"
If exit 1 → "No changes, skipping" and stop.
Run: python3 ~/.hermes/scripts/circuit_breaker_check.py "task-compiler"
If exit 1 → "Circuit breaker active" and stop.

TASK:
1. Read .tini/ideas/inbox.md
2. If empty → "Inbox empty, nothing to compile" and stop.
3. For each idea in inbox:
   a. Evaluate feasibility (1-5)
   b. Estimate effort (S/M/L)
   c. Write acceptance criteria (2-3 items)
   d. Assign to appropriate executor role
4. Write approved tasks to .tini/ideas/reviewed.md (APPEND, don't overwrite)
5. Clear processed items from inbox.md

POST-FLIGHT:
Run: python3 ~/.hermes/scripts/circuit_breaker_update.py "task-compiler" ok
On error: python3 ~/.hermes/scripts/circuit_breaker_update.py "task-compiler" error

NEVER produce empty output. If nothing to do, say so.
---
```

**Step 2: Create task-runner prompt (merges executor + extra)**

New cron job replacing jobs 03 + 04:

```
Name: tini-task-runner
Schedule: every 30m
Model: xmtp/mimo-v2.5-pro

Prompt:
---
Role: Task runner.

PRE-FLIGHT:
Run: python3 ~/.hermes/scripts/state_check.py "task-runner"
If exit 1 → "No changes, skipping" and stop.
Run: python3 ~/.hermes/scripts/circuit_breaker_check.py "task-runner"
If exit 1 → "Circuit breaker active" and stop.

TASK:
1. Read .tini/ideas/reviewed.md
2. If empty → "No reviewed tasks, nothing to run" and stop.
3. Pick the HIGHEST PRIORITY task with status=approved.
4. Set status to "executing" in reviewed.md.
5. Execute the task (code, file changes, etc).
6. On success: move to executed.md, write results.
7. On failure: mark as "failed" with error reason, move back to reviewed.md for retry.

POST-FLIGHT:
Run: python3 ~/.hermes/scripts/circuit_breaker_update.py "task-runner" ok
On error: python3 ~/.hermes/scripts/circuit_breaker_update.py "task-runner" error

NEVER produce empty output.
---
```

**Step 3: Create the new jobs and pause old ones**

```bash
# Create new task-compiler (replaces 01 + 02)
hermes cronjob create --name "tini-task-compiler" --schedule "every 60m" \
  --model "xmtp/mimo-v2.5-pro" --provider "local" \
  --skills hermes-agent \
  --toolsets file,terminal,skills,memory,session_search \
  --workdir /Users/azfar.naufal/Documents/myhermes \
  --prompt "<prompt from step 1>"

# Create new task-runner (replaces 03 + 04)
hermes cronjob create --name "tini-task-runner" --schedule "every 30m" \
  --model "xmtp/mimo-v2.5-pro" --provider "local" \
  --skills hermes-agent \
  --toolsets file,terminal,skills,memory,session_search \
  --workdir /Users/azfar.naufal/Documents/myhermes \
  --prompt "<prompt from step 2>"

# Pause old TINI jobs
hermes cronjob pause 4f1d20284401  # 01-research
hermes cronjob pause 2300b4c5ec18  # 02-review
hermes cronjob pause ff7647b176ed  # 03-executor
hermes cronjob pause be2a31e8eb60  # 04-extra
```

**Verification:** 4 TINI jobs consolidated to 2. Pipeline latency drops from ~120min to ~30min.

---

### Task 6: Compact Context Injection

**Objective:** Stop agents from re-reading 10 files. Give them only what they need.

**Files:**
- Modify: Each NetWeaver agent prompt

**Step 1: Add context preamble to each agent**

Instead of "Read KANBAN, STATUS, HANDOFF, BLOCKERS, ROADMAP, BACKLOG...",
use this pattern:

```
CONTEXT (pre-loaded, do NOT re-read these files):
{context_blob}

The above is your working context. Do NOT read the files again.
Focus only on your assigned task below.
```

The `{context_blob}` would be injected by a future dispatcher.
For now, agents can still read files but we add the fingerprinting
skip (Task 4) to avoid reading when nothing changed.

**Step 2: Reduce skill loading**

Remove `hermes-agent` skill from agents that don't need it.
Only the self-healer/dispatcher needs hermes-agent skill.

Workers only need: file, terminal, memory (no skills, no session_search).

```
Current:  skills=hermes-agent, toolsets=file,terminal,skills,memory,session_search,todo
Optimized: skills=[], toolsets=file,terminal,memory
```

Saves ~2-3K tokens per run on skill prompt injection.

**Verification:** Agents use fewer tokens per run. No behavioral change.

---

## Phase 3: Event-Driven Dispatcher

### Task 7: Create Dispatcher Agent

**Objective:** Replace fixed-schedule NetWeaver jobs with an event-driven dispatcher.

**Files:**
- Create: New cron job "netweaver-dispatcher"
- Pause: 5 individual NetWeaver agent jobs

**Step 1: Create dispatcher prompt**

```
Name: netweaver-dispatcher
Schedule: every 5m (lightweight — reads events, dispatches workers)
Model: xmtp/mimo-v2.5-pro

Prompt:
---
Role: NetWeaver dispatcher. You are the brain that decides which
workers run, based on what actually changed.

WORKFLOW:
1. Read .tini/events.jsonl (last 20 events)
2. Read .tini/netweaver/company/KANBAN.md (scan for status markers)
3. Read .tini/circuit_breaker.json (check who's paused)
4. Read .tini/agent_states/*.fingerprint (check what's stale)

DECISION MATRIX:
- New task added to KANBAN (status=todo) → dispatch architect
- Task moved to "in-progress" → dispatch runtime-engineer
- Task involves WNAL/DSL → dispatch wnal-engineer
- Task status="review" → dispatch safety-review
- Task status="testing" → dispatch qa-benchmark
- No changes → "No dispatch needed" and stop

DISPATCH METHOD:
Write dispatch orders to .tini/dispatch_queue.json:
{
  "dispatches": [
    {"agent": "architect", "task_ref": "KANBAN#12", "priority": "high"},
    {"agent": "runtime-engineer", "task_ref": "KANBAN#8", "priority": "normal"}
  ],
  "ts": "2026-05-24T22:30:00"
}

Workers read dispatch_queue.json on their next run.

POST-FLIGHT:
Run: python3 ~/.hermes/scripts/circuit_breaker_update.py "dispatcher" ok
On error: python3 ~/.hermes/scripts/circuit_breaker_update.py "dispatcher" error

NEVER produce empty output. If nothing to dispatch, say "No dispatch needed."
---
```

**Step 2: Modify worker prompts to read dispatch queue**

Workers add to their pre-flight:

```
DISPATCH CHECK:
Read .tini/dispatch_queue.json
If no dispatch for this agent → "No tasks dispatched, skipping" and stop.
If dispatch exists → proceed with the dispatched task only.
Clear this agent's entry from dispatch_queue.json after completing.
```

**Step 3: Create dispatcher, pause old jobs**

```bash
# Create dispatcher
hermes cronjob create --name "netweaver-dispatcher" --schedule "every 5m" \
  --model "xmtp/mimo-v2.5-pro" --provider "local" \
  --skills hermes-agent \
  --toolsets file,terminal,memory \
  --workdir /Users/azfar.naufal/Documents/myhermes \
  --prompt "<prompt from step 1>"

# Pause individual NetWeaver jobs
hermes cronjob pause 7dabb518dfb6  # architect
hermes cronjob pause b5294bd85a71  # runtime-engineer
hermes cronjob pause 5418e6d5c065  # wnal-engineer
hermes cronjob pause b25048563a4d  # safety-review
hermes cronjob pause 1e9b68aba836  # qa-benchmark
```

**Verification:** 5 NetWeaver polling jobs replaced by 1 dispatcher. Workers only run when dispatched.

---

## Final State

After all 3 phases:

```
JOB                          TYPE        SCHEDULE     TOKENS/RUN
───────────────────────────  ──────────  ───────────  ──────────
netweaver-watchtower         script      every 2m     0 (no_agent)
netweaver-dispatcher         agent       every 5m     ~5K (light)
netweaver-architect          agent       dispatched   ~30K (scoped)
netweaver-runtime-engineer   agent       dispatched   ~30K (scoped)
netweaver-wnal-engineer      agent       dispatched   ~30K (scoped)
netweaver-safety-review      agent       dispatched   ~20K (scoped)
netweaver-qa-benchmark       agent       dispatched   ~20K (scoped)
tini-task-compiler           agent       every 60m    ~25K (compact)
tini-task-runner             agent       every 30m    ~25K (compact)
───────────────────────────  ──────────  ───────────  ──────────
TOTAL: 9 jobs (down from 11)
```

**Savings breakdown:**
- Watchtower replaces self-healer: ~480 LLM calls/day → 0
- State fingerprinting: eliminates ~60% no-op runs
- Dispatcher replaces 5 polling jobs: 480 runs/day → 288
- Compact context: ~3K tokens saved per run
- Circuit breaker: prevents cascade failures

**Estimated total:** ~800-1200 API calls/day → ~200-350/day. ~70% reduction.

---

## Rollback Plan

Each phase is reversible:
- Phase 1: Unpause old self-healer, delete watchtower cron
- Phase 2: Unpause old TINI jobs, delete new ones
- Phase 3: Unpause individual NetWeaver jobs, delete dispatcher

Old jobs stay paused (not deleted) until new architecture is proven stable for 48 hours.

---

## Acceptance Criteria

- [ ] Watchtower runs silently when nothing changes
- [ ] Watchtower alerts on state change, health issues, conflicts
- [ ] Circuit breaker pauses agent after 3 consecutive failures
- [ ] Circuit breaker auto-resumes after 60min cooldown
- [ ] State fingerprinting skips runs when files unchanged
- [ ] TINI pipeline latency < 30min (down from 120min)
- [ ] Dispatcher correctly routes tasks to appropriate workers
- [ ] Workers only run when dispatched (not polling)
- [ ] Total daily API calls < 400 (down from 800-1200)
- [ ] All old jobs remain paused (not deleted) for rollback
