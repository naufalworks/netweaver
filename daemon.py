#!/usr/bin/env python3
"""
NetWeaver Daemon — Self-evolving development daemon.
No cron. No schedules. Pure event-driven: watches files, detects gaps, executes work.
Zero token cost when idle.
"""
from __future__ import annotations

import json, os, sys, time, hashlib, subprocess, urllib.request, traceback
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── Config ───────────────────────────────────────────────────────────────────
WORKDIR = Path(os.environ.get("NETWEAVER_WORKDIR", str(Path.home() / "Documents/myhermes")))
TINI = WORKDIR / ".tini"
MODEL = os.environ.get("NETWEAVER_MODEL", "claude-combo")
API_URL = os.environ.get("NETWEAVER_API_URL", "http://localhost:20128/v1/chat/completions")
API_KEY = os.environ.get("NETWEAVER_API_KEY", "")
POLL_INTERVAL = float(os.environ.get("NETWEAVER_POLL", "2"))
SELF_DIAGNOSE_INTERVAL = int(os.environ.get("NETWEAVER_DIAGNOSE", "10"))
IDLE_TIMEOUT = int(os.environ.get("NETWEAVER_IDLE_TIMEOUT", "21600"))  # 6h
CIRCUIT_BREAKER_PATH = TINI / "circuit_breaker.json"
DAEMON_FAILURE_THRESHOLD = int(os.environ.get("DAEMON_CB_THRESHOLD", "5"))
DAEMON_PAUSE_DURATION = int(os.environ.get("DAEMON_CB_PAUSE", "3600"))  # 1h

# ── State files ──────────────────────────────────────────────────────────────
WATCHED_FILES = [
    TINI / "netweaver/company/KANBAN.md",
    TINI / "netweaver/HANDOFF.md",
    TINI / "netweaver/STATUS.md",
    TINI / "netweaver/BLOCKERS.md",
    TINI / "netweaver/BACKLOG.md",
    TINI / "circuit_breaker.json",
    TINI / "agent_health.json",
    TINI / "events.jsonl",
    TINI / "work_queue.json",
    TINI / "daemon_state.json",
    WORKDIR / "ROADMAP.md",
    WORKDIR / "PROJECT_GOAL.md",
]
CHECKPOINT_FILE = TINI / "daemon_checkpoint.json"
STOP_FLAG = TINI / "daemon_stop"
HEARTBEAT_FILE = TINI / "daemon_heartbeat.txt"
PID_LOCK_FILE = TINI / "daemon.pid"

# ── LLM Caller ───────────────────────────────────────────────────────────────

def llm_call(system: str, prompt: str, max_retries: int = 2) -> Optional[dict]:
    """Call the local model API. Returns parsed JSON response or None."""
    data = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        API_URL, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
    )
    for attempt in range(max_retries + 1):
        # Write heartbeat before each attempt — watchdog uses 120s threshold
        try:
            HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT_FILE.write_text(str(time.time()))
        except:
            pass
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=180).read())
            content = resp["choices"][0]["message"]["content"]
            return _parse_json_response(content)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if "rate_limit" in body.lower() or "429" in body:
                log(f"⚠ Rate limited, waiting 30s (attempt {attempt+1}/{max_retries+1})")
                time.sleep(30)
                continue
            log(f"⚠ HTTP {e.code}: {body[:200]}")
            return None
        except (json.JSONDecodeError, KeyError, urllib.error.URLError, TimeoutError, OSError) as e:
            log(f"⚠ LLM error: {e}")
            return None
    return None

def _parse_json_response(text: str) -> Optional[dict]:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return None

# ── File watching ────────────────────────────────────────────────────────────

def file_hash(path: Path) -> str:
    """SHA256 hash of file mtime + size (fast, no content read)."""
    if not path.exists():
        return ""
    s = path.stat()
    return hashlib.md5(f"{s.st_mtime_ns}:{s.st_size}".encode()).hexdigest()[:12]

def read_file(path: Path) -> str:
    """Read file, return empty string if missing."""
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""

def log(msg: str):
    """Write timestamped log entry."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── State scanner ────────────────────────────────────────────────────────────

def scan_state() -> dict:
    """Read ALL state files → structured dict for LLM."""
    return {
        "circuit_breaker": _safe_json(TINI / "circuit_breaker.json"),
        "agent_health": _safe_json(TINI / "agent_health.json"),
        "daemon_state": _safe_json(TINI / "daemon_state.json"),
        "work_queue": _safe_json(TINI / "work_queue.json"),
        "roadmap": read_file(WORKDIR / "ROADMAP.md"),
        "product_spec": read_file(TINI / "netweaver/company/PRODUCT_SPEC.md"),
        "kanban": {
            "ready": _extract_section(TINI / "netweaver/company/KANBAN.md", "ready"),
            "in_progress": _extract_section(TINI / "netweaver/company/KANBAN.md", "in_progress"),
            "done": _extract_section(TINI / "netweaver/company/KANBAN.md", "done"),
        },
        "health_summary": _compute_health(),
    }

def _safe_json(path: Path) -> dict:
    try: return json.loads(read_file(path)) if path.exists() else {}
    except: return {}

def _extract_section(path: Path, section: str) -> str:
    """Extract a ## section from markdown."""
    text = read_file(path)
    lines = text.split("\n")
    in_section = False
    result = []
    for line in lines:
        if line.strip().startswith("## ") and section in line:
            in_section = True
            continue
        if line.strip().startswith("## ") and in_section:
            break
        if in_section:
            result.append(line)
    return "\n".join(result[:30])  # cap at 30 lines

def _compute_health() -> str:
    """Summary of pipeline health."""
    cb = _safe_json(TINI / "circuit_breaker.json")
    health = _safe_json(TINI / "agent_health.json")
    total = len(cb)
    failed = sum(1 for v in cb.values() if v.get("consecutive_failures", 0) > 0)
    stale = sum(1 for v in health.values() if v.get("last_ok", 0) < time.time() - 86400)
    return f"{total} agents tracked, {failed} with failures, {stale} stale (>24h)"

# ── Circuit breaker helpers ──────────────────────────────────────────────────

def _update_daemon_cb(success: bool):
    """Update daemon circuit breaker: reset on success, increment on failure."""
    try:
        cb = _safe_json(CIRCUIT_BREAKER_PATH)
        d = cb.setdefault("daemon", {"consecutive_failures": 0, "paused_until": None, "last_ok": None})
        if success:
            d["consecutive_failures"] = 0
            d["paused_until"] = None
            d["last_ok"] = datetime.now().isoformat()
        else:
            d["consecutive_failures"] = d.get("consecutive_failures", 0) + 1
            if d["consecutive_failures"] >= DAEMON_FAILURE_THRESHOLD:
                d["paused_until"] = time.time() + DAEMON_PAUSE_DURATION
        CIRCUIT_BREAKER_PATH.write_text(json.dumps(cb, indent=2) + "\n")
    except Exception as e:
        log(f"⚠ CB update error: {e}")

def _daemon_circuit_open() -> bool:
    """Returns True if daemon is circuit-broken (paused due to failures)."""
    try:
        cb = _safe_json(CIRCUIT_BREAKER_PATH)
        d = cb.get("daemon", {})
        until = d.get("paused_until")
        if until and time.time() < until:
            log(f"⏸ Daemon circuit open — paused {int(until - time.time())}s remaining")
            return True
        return False
    except:
        return False

# ── Task generation (LLM-guided) ─────────────────────────────────────────────

TASK_SYSTEM = """You are the NetWeaver Daemon — an autonomous development engine managing TWO projects:

## Project 1: PIPELINE (self-health)
The infrastructure that builds NetWeaver. Needs: circuit breaker fixes, token optimization, error recovery, agent health.

## Project 2: NETWEAVER (product)
Browser-native web cognition engine. Phase 1 (mock mode) complete. Phase 2 (real CloakBrowser) not started.

## Your task generation rules:
1. Read the state below. Find REAL gaps between roadmap and current state.
2. NEVER generate "extract inline skill doc from cron prompt" tasks — the cron prompt templates are clean (~2K chars each, no inline 25K blob). This was investigated and the issue does not exist.
3. Generate exactly ONE task. Only if a real gap exists.
4. Output ONLY valid JSON. No markdown, no explanation.

## Priority order:
1. Pipeline health (circuit breakers tripped, agents failing, stale agents) — only if CB shows consecutive_failures > 0
2. NetWeaver Phase 2 gaps (roadmap says implement X, codebase doesn't have X)
3. Self-evolution (token optimization, prompt improvements)

## Output format when task is found:
{"action_taken":true, "task":{"id":"NW-XXX","project":"pipeline|netweaver","goal":"...","why":"which gap led to this","scope":["file1","file2"],"acceptance":"how to verify","priority":1-5}}

## Output format when no task:
{"action_taken":false, "reason":"no gaps found"}

The state below includes: circuit breaker health, agent health, roadmap status, KANBAN content, project files."""

def generate_task(state: dict) -> Optional[dict]:
    """Ask LLM to analyze state and generate a task."""
    prompt = json.dumps(state, indent=2, default=str)
    result = llm_call(TASK_SYSTEM, prompt[:4000])  # cap prompt size
    if result and result.get("action_taken"):
        return result.get("task")
    return None

# ── Task executor (sub-tasking + actual file writes) ────────────────────────

PLAN_SYSTEM = """You are NetWeaver Daemon planner. Break this task into 2-5 small steps.
Each step = 1 file to create/modify + its tests (for a total of <= 2 files).
Output ONLY valid JSON:
{"steps":[{"id":1,"goal":"...","read_files":["file_to_inspect.py"],"write_files":["file_to_create.py"]}]}

Rules:
- read_files = files to read for context (existing code to understand)
- write_files = files to create or overwrite (1-2 max)
- Each step must be achievable by: read files → generate content → write → test
- First step should be the most foundational""" 

STEP_SYSTEM = """You are NetWeaver Daemon executor. You receive existing file content.
Your JOB: output the NEW content for files that need changing.
Output ONLY valid JSON. NEVER say "done:true" without providing actual file content.

FORMAT:
{"files":[{"path":"relative/file.py","content":"# entire new file content here\\n..."}],"summary":"what changed"}

OR if no changes needed:
{"files":[],"summary":"nothing to change"}

RULES:
- Each entry in "files" is the COMPLETE new content for that file
- Include imports, existing functions, everything — complete overwrite
- Content must pass: echo content > file.py && python -c "import file" without error
- Write real Python code, not placeholders"""

MAX_FILE_READ_CHARS = 4000  # cap per file to avoid prompt bloat

def _read_files(file_list: list[str]) -> dict[str, str]:
    """Read existing files for context. Returns {path: content}."""
    contents = {}
    for f in file_list:
        path = WORKDIR / f
        if path.exists():
            contents[f] = path.read_text()[:MAX_FILE_READ_CHARS]
        else:
            contents[f] = "(file does not exist yet — will be created)"
    return contents

def _test_summary() -> str:
    """Return last line of test output (e.g., '1334 passed')."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line"],
        capture_output=True, text=True, cwd=str(WORKDIR), timeout=60
    )
    return r.stdout.strip().split("\n")[-1] if r.stdout else "no output"

def _run_tests() -> bool:
    """Run full test suite. Returns True if all pass."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line"],
            capture_output=True, text=True, cwd=str(WORKDIR), timeout=60
        )
        return "passed" in r.stdout and "failed" not in r.stdout
    except:
        return False

def generate_plan(task: dict) -> Optional[dict]:
    """Ask LLM to break task into small sub-steps. Returns {'steps': [...]}."""
    prompt = json.dumps({
        "task_id": task.get("id"),
        "goal": task.get("goal"),
        "project_files": [str(p.relative_to(WORKDIR)) for p in WORKDIR.rglob("*.py")
                         if "node_modules" not in str(p)],
        "current_tests": _test_summary(),
    }, indent=2, default=str)
    
    for attempt in range(3):
        result = llm_call(PLAN_SYSTEM, prompt[:4000], max_retries=1)
        if result and "steps" in result and isinstance(result["steps"], list):
            return result
        log(f"  \u26a0 Plan retry {attempt+1}: no valid steps")
        time.sleep(5)
    return None

def execute_step(step: dict, task_context: str) -> dict:
    """Execute one step: read files → LLM generates content → write files → test.
    
    Returns {'done': bool, 'files_written': [...], 'summary': str}
    On failure, all written files are reverted (atomic)."""
    
    # Phase 1: Read context files
    read_files = step.get("read_files", [])
    write_files = step.get("write_files", [])
    context = _read_files(read_files)
    
    prompt = json.dumps({
        "step": step,
        "task_context": task_context[:800],
        "existing_files": context,
        "files_to_write": write_files,
        "working_directory": str(WORKDIR),
        "test_command": "python -m pytest tests/ -q --tb=line",
    }, indent=2, default=str)
    
    # Phase 2: Ask LLM for actual file content
    result = None
    for attempt in range(3):
        result = llm_call(STEP_SYSTEM, prompt[:5000], max_retries=2)
        if result and isinstance(result.get("files"), list):
            break
        delay = 2 ** attempt * 5
        log(f"  \u26a0 Step retry {attempt+1}/3 in {delay}s")
        time.sleep(delay)
    
    if not result or not isinstance(result.get("files"), list):
        return {"done": False, "error": "LLM didn't return valid file content", 
                "files_written": [], "summary": "failed"}
    
    # Phase 3: Backup existing files, then write new content
    files_written = []
    backups = {}  # path -> original content (None = file didn't exist)
    try:
        for fc in result["files"]:
            path_str = fc.get("path", "")
            content = fc.get("content", "")
            if not path_str or not content:
                continue
            abs_path = WORKDIR / path_str
            # Backup existing
            if abs_path.exists():
                backups[path_str] = abs_path.read_text()
            else:
                backups[path_str] = None
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content)
            files_written.append(path_str)
            log(f"  \u270d Wrote {path_str} ({len(content)} chars)")
        
        # Phase 4: Run test suite
        tests_ok = _run_tests()
        
        if not tests_ok and files_written:
            # Revert all changes
            for fp in files_written:
                abs_path = WORKDIR / fp
                if backups.get(fp) is not None:
                    abs_path.write_text(backups[fp])
                    log(f"  \u21a9 Reverted {fp} (tests broke)")
                else:
                    if abs_path.exists():
                        abs_path.unlink()
                        log(f"  \u21a9 Deleted {fp} (tests broke, was new)")
            return {
                "done": False,
                "files_written": files_written,
                "summary": f"wrote then reverted {len(files_written)} file(s), tests FAIL",
                "reverted": True,
            }
        
        return {
            "done": tests_ok and len(files_written) > 0,
            "files_written": files_written,
            "summary": f"wrote {len(files_written)} file(s), tests {'OK' if tests_ok else 'FAIL'}",
        }
    except Exception as e:
        # Emergency revert on unexpected error
        for fp in files_written:
            abs_path = WORKDIR / fp
            if backups.get(fp) is not None:
                abs_path.write_text(backups[fp])
            else:
                if abs_path.exists():
                    abs_path.unlink()
        return {"done": False, "files_written": [], "summary": f"error + reverted: {e}"}

def execute_task(task: dict) -> dict:
    """Execute a work item: generate plan → execute steps → verify."""
    log(f"\u25b6 Task: {task.get('id','?')} — {task.get('goal','?')[:80]}")
    
    plan = generate_plan(task)
    if not plan:
        return {"done": False, "error": "Could not generate plan"}
    
    steps = plan["steps"]
    log(f"   Plan: {len(steps)} step(s)")
    
    completed = 0
    for step in steps:
        log(f"  Step {step['id']}: {step['goal'][:70]}")
        result = execute_step(step, task.get("goal", ""))
        
        if result.get("done"):
            completed += 1
            log(f"  \u2705 Step {step['id']} done: {result.get('summary','')[:80]}")
            
            # If step broke tests, try to fix
            test_result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line"],
                capture_output=True, text=True, cwd=str(WORKDIR), timeout=60
            )
            if "failed" in test_result.stdout or "FAILED" in test_result.stdout:
                log(f"  \u26a0 Tests broken after step {step['id']}, fixing...")
                fix_step = {
                    "id": f"{step['id']}-fix",
                    "goal": f"Fix test failures: {test_result.stdout.strip().split(chr(10))[-3:]}",
                    "read_files": step.get("write_files", []),
                    "write_files": step.get("write_files", []),
                }
                fix_result = execute_step(fix_step, task.get("goal", ""))
                if fix_result.get("done"):
                    completed += 0  # same step, don't double-count
        else:
            log(f"  \u274c Step {step['id']} failed: {result.get('summary','?')[:100]}")
    
    final_tests = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line"],
        capture_output=True, text=True, cwd=str(WORKDIR), timeout=60
    )
    all_pass = "passed" in final_tests.stdout and "failed" not in final_tests.stdout
    
    return {
        "done": completed > 0 and all_pass,
        "steps_completed": completed,
        "steps_total": len(steps),
        "tests_ok": all_pass,
        "summary": f"{completed}/{len(steps)} steps, files written: {sum(1 for s in steps if s.get('write_files',[]))}, tests {'OK' if all_pass else 'FAIL'}",
    }

# ── Self-diagnose ────────────────────────────────────────────────────────────

DIAG_SYSTEM = """You are the self-diagnosis engine. Review the daemon's recent activity.
Check: are tasks being created? Executed? Any error patterns? 
Output JSON:
{"healthy":true|false, "observation":"...", "recommendation":"..."}"""

def self_diagnose():
    """Periodic health check of the daemon itself."""
    recent = list((TINI / "events.jsonl").read_text().split("\n")[-10:]) \
        if (TINI / "events.jsonl").exists() else []
    
    prompt = json.dumps({
        "daemon_state": _safe_json(CHECKPOINT_FILE),
        "recent_events": recent,
        "circuit_breaker": _safe_json(TINI / "circuit_breaker.json"),
        "agent_health": _safe_json(TINI / "agent_health.json"),
    }, indent=2, default=str)
    
    result = llm_call(DIAG_SYSTEM, prompt[:3000])
    if result:
        log(f"🔍 Self-diagnosis: {result.get('observation','?')}")
        if not result.get("healthy", True):
            log(f"⚠ Recommendation: {result.get('recommendation','?')}")

# ── Checkpoint system ────────────────────────────────────────────────────────

def write_checkpoint(data: dict):
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["_ts"] = datetime.now().isoformat()
    CHECKPOINT_FILE.write_text(json.dumps(data, indent=2, default=str) + "\n")

def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try: return json.loads(CHECKPOINT_FILE.read_text())
        except: pass
    return {"cycle": 0, "tasks_completed": [], "last_event": None}

def write_heartbeat():
    """Write heartbeat timestamp for watchdog to check."""
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_FILE.write_text(str(time.time()))

def _run_execute_and_checkpoint(task: dict, cycle: int, checkpoint: dict):
    """Execute task, log result, write checkpoint + event. Shared by event and idle paths."""
    DONE = "\u2705"
    FAIL = "\u274c"
    result = execute_task(task)
    icon = DONE if result.get("done") else FAIL
    log(f"  \u2192 Result: {icon} {result.get('summary','')[:100]}")
    _update_daemon_cb(result.get("done", False))
    
    checkpoint["cycle"] = cycle
    tasks = checkpoint.get("tasks_completed", [])
    tasks.append({
        "id": task.get("id"),
        "goal": task.get("goal"),
        "done": result.get("done"),
        "time": datetime.now().isoformat(),
    })
    checkpoint["tasks_completed"] = tasks[-20:]
    write_checkpoint(checkpoint)
    
    event = {
        "ts": datetime.now().isoformat(),
        "type": "task_completed" if result.get("done") else "task_failed",
        "task_id": task.get("id"),
        "goal": task.get("goal"),
        "result": result.get("summary", str(result)[:200]),
    }
    events_file = TINI / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    with open(events_file, "a") as f:
        f.write(json.dumps(event) + "\n")

# ── Main loop ────────────────────────────────────────────────────────────────

def main():
    # ── PID lock: prevent duplicate instances ──
    pid = str(os.getpid())
    if PID_LOCK_FILE.exists():
        try:
            old_pid = int(PID_LOCK_FILE.read_text().strip())
            old_alive = os.kill(old_pid, 0) is None  # no error = alive
        except (ValueError, OSError):
            old_alive = False
        if old_alive:
            log(f"⚠ PID lock: {old_pid} still alive. Exiting.")
            sys.exit(0)
    PID_LOCK_FILE.write_text(pid)
    
    log(f"╔══════════════════════════════════════╗")
    log(f"║ NetWeaver Daemon v2                  ║")
    log(f"║ Model: {MODEL}")
    log(f"║ Workdir: {WORKDIR}")
    log(f"║ Poll: {POLL_INTERVAL}s, Diag: every {SELF_DIAGNOSE_INTERVAL} cycles")
    log(f"╚══════════════════════════════════════╝")
    
    # Clear stop flag if present
    if STOP_FLAG.exists():
        STOP_FLAG.unlink()
    
    checkpoint = load_checkpoint()
    poll_hashes: dict[str, str] = {}
    cycle = checkpoint.get("cycle", 0)
    last_event_time = time.time()
    
    while True:
        # ── Check stop flag ──
        if STOP_FLAG.exists():
            log("🛑 Stop flag detected. Exiting.")
            write_checkpoint({"action": "stopped", "cycle": cycle})
            break
        
        # ── Write heartbeat ──
        if cycle % 30 == 0:
            write_heartbeat()
        
        # ── Circuit breaker check — auto-pause if too many failures ──
        if _daemon_circuit_open():
            time.sleep(POLL_INTERVAL)
            cycle += 1
            continue
        
        # ── 1. Poll files (skip events.jsonl if only changed by us) ──
        changed = []
        for path in WATCHED_FILES:
            # Skip events.jsonl and circuit_breaker.json — we write to them, would cause self-trigger
            if path.name in ("events.jsonl", "circuit_breaker.json") and path.suffix in (".jsonl", ".json"):
                continue
            h = file_hash(path)
            if poll_hashes.get(str(path)) != h:
                changed.append(str(path))
                poll_hashes[str(path)] = h
        
        # ── 2. If nothing changed, check idle timeout ──
        if not changed:
            if time.time() - last_event_time > IDLE_TIMEOUT:
                log(f"⏰ Idle {IDLE_TIMEOUT}s — self-check")
                state = scan_state()
                task = generate_task(state)
                if task:
                    log(f"  Idle generated: {task.get('id','?')}")
                    _run_execute_and_checkpoint(task, cycle, checkpoint)
                last_event_time = time.time()
            time.sleep(POLL_INTERVAL)
            cycle += 1
            continue
        
        last_event_time = time.time()
        
        log(f"📂 Change detected: {len(changed)} file(s)")
        for c in changed:
            log(f"   {Path(c).name}")
        
        # ── 3. Read state → generate task ──
        state = scan_state()
        write_checkpoint({"action": "event_detected", "changed": changed, "cycle": cycle})
        
        task = generate_task(state)
        if not task:
            log("  No task needed (no gaps found)")
            cycle += 1
            time.sleep(POLL_INTERVAL)
            continue
        
        log(f"  \u2192 Generated: {task.get('id','?')} ({task.get('project','?')})")
        log(f"     Goal: {task.get('goal','?')[:100]}")

        # \u2500\u2500 4. Execute + record \u2500\u2500
        _run_execute_and_checkpoint(task, cycle, checkpoint)

        # \u2500\u2500 5. Self-diagnose \u2500\u2500
        if cycle % SELF_DIAGNOSE_INTERVAL == 0:
            self_diagnose()
        
        # ── Short pause before next poll ──
        time.sleep(1)
        cycle += 1

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("🛑 Interrupted by user")
    except Exception as e:
        log(f"💥 Fatal error: {e}")
        traceback.print_exc()
        write_checkpoint({"action": "crashed", "error": str(e), "time": datetime.now().isoformat()})
        sys.exit(1)
