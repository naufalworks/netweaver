#!/usr/bin/env python3
"""
NetWeaver Daemon — Self-evolving, self-healing development daemon.

Capabilities:
- Heartbeat writing (watchdog liveness signal)
- File watching with change detection (hash-based)
- Gap detection: scan BACKLOG → generate plans → write to REVIEW_QUEUE
- PLAN_ONLY mode: never executes plans directly, only proposes
- File rollback: backup before any write, auto-revert on test failure
- Self-healing: git checkpoint, test-on-write, auto-revert
- Circuit breaker: pause after N failures, alert on threshold
- Event logging: JSONL event ledger for audit trail
- Graceful shutdown with signal handling and drain
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from netweaver.memory_palace import MemoryPalace
from netweaver.epistemic_daemon import EpistemicDaemon
from netweaver.dreaming import DreamEngine
from netweaver.causal import CausalChainTracer
from netweaver.competence_matrix import CompetenceMatrix
from netweaver.web_learner import AutonomousWebExplorer
from netweaver.task_scheduler import TaskScheduler

# --- Configuration ---
WORKDIR = Path(os.environ.get("NETWEAVER_WORKDIR", str(Path.home() / "Documents/myhermes")))
TINI_DIR = WORKDIR / ".tini"
NETWEAVER_DIR = TINI_DIR / "netweaver"
COMPANY_DIR = NETWEAVER_DIR / "company"

HEARTBEAT_FILE = TINI_DIR / "daemon_heartbeat.txt"
PID_FILE = TINI_DIR / "daemon.pid"
EVENTS_FILE = TINI_DIR / "events.jsonl"
CHECKPOINT_FILE = TINI_DIR / "daemon_checkpoint.json"
CIRCUIT_BREAKER_FILE = TINI_DIR / "circuit_breaker.json"
FAILED_CACHE_FILE = TINI_DIR / "failed_task_cache.json"
AGENT_HEALTH_FILE = TINI_DIR / "agent_health.json"

REVIEW_QUEUE = COMPANY_DIR / "REVIEW_QUEUE.md"
KANBAN = COMPANY_DIR / "KANBAN.md"
BACKLOG = NETWEAVER_DIR / "BACKLOG.md"
STATUS_FILE = NETWEAVER_DIR / "STATUS.md"
HANDOFF_FILE = NETWEAVER_DIR / "HANDOFF.md"

BACKUPS_DIR = TINI_DIR / "backups"
GIT_CHECKPOINTS_DIR = TINI_DIR / "git_checkpoints"

# Tuning
HEARTBEAT_INTERVAL = 60       # seconds between heartbeat writes
SCAN_INTERVAL = 120            # seconds between file scans
TEST_TIMEOUT = 180             # seconds for pytest
MAX_FAILURES_BEFORE_PAUSE = 5  # circuit breaker threshold
PAUSE_DURATION = 600           # seconds to pause after breaker trip
MAX_EVENTS_LOG = 5000          # trim events beyond this
QUARANTINE_THRESHOLD = 10      # failures before task is permanently quarantined

# --- Logging ---
LOG_FILE = TINI_DIR / "daemon_stdout.log"
TINI_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
GIT_CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), mode="a"),
    ],
)
logger = logging.getLogger("daemon")

# --- Global state ---
shutdown_event = asyncio.Event()
inflight_tasks: Set[asyncio.Task] = set()
daemon_palace = MemoryPalace("daemon")
epistemic_daemon = EpistemicDaemon()
dream_engine = DreamEngine(workdir=WORKDIR, epistemic_os=epistemic_daemon.ep)
causal_tracer = CausalChainTracer(workdir=WORKDIR)
competence_matrix = CompetenceMatrix(workdir=WORKDIR, epistemic_os=epistemic_daemon.ep)
web_explorer = AutonomousWebExplorer(
    registry_path=NETWEAVER_DIR / ".tini" / "web_explorer",
    epistemic_daemon=epistemic_daemon,
    competence_matrix=competence_matrix,
    headless=True,
)
task_scheduler = TaskScheduler(
    tasks_file=NETWEAVER_DIR / "tasks.yaml",
    state_dir=NETWEAVER_DIR / ".tini" / "task_scheduler",
    headless=True,
)
file_hashes: Dict[str, str] = {}
cycle_count = 0


# ============================================================
# Utility functions
# ============================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> Optional[str]:
    """Compute MD5 hash of file contents. None if missing."""
    if not path.exists():
        return None
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except (OSError, IOError):
        return None


def safe_read_json(path: Path, default: Any = None) -> Any:
    """Read JSON file safely."""
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def safe_write_json(path: Path, data: Any) -> bool:
    """Write JSON atomically (write to temp, then rename)."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(path)
        return True
    except OSError as e:
        logger.error(f"Failed to write {path}: {e}")
        return False


def log_event(event_type: str, data: Dict[str, Any]) -> None:
    """Append event to JSONL ledger."""
    event = {
        "ts": now_iso(),
        "type": event_type,
        "cycle": cycle_count,
        **data,
    }
    try:
        with open(EVENTS_FILE, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
        # Trim if too large
        _trim_events()
    except OSError as e:
        logger.error(f"Event log write failed: {e}")


def _trim_events() -> None:
    """Keep events file under MAX_EVENTS_LOG lines."""
    try:
        if not EVENTS_FILE.exists():
            return
        lines = EVENTS_FILE.read_text().strip().split("\n")
        if len(lines) > MAX_EVENTS_LOG:
            keep = lines[-MAX_EVENTS_LOG:]
            EVENTS_FILE.write_text("\n".join(keep) + "\n")
    except OSError:
        pass


# ============================================================
# Heartbeat
# ============================================================

def write_heartbeat() -> None:
    """Write current timestamp to heartbeat file."""
    try:
        HEARTBEAT_FILE.write_text(str(time.time()))
    except OSError as e:
        logger.error(f"Heartbeat write failed: {e}")


# ============================================================
# File backup & rollback
# ============================================================

def backup_file(path: Path) -> Optional[Path]:
    """Create timestamped backup of a file before modification."""
    if not path.exists():
        return None
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{path.stem}_{ts}{path.suffix}"
        backup_path = BACKUPS_DIR / backup_name
        backup_path.write_bytes(path.read_bytes())
        logger.debug(f"Backed up {path.name} → {backup_path.name}")
        return backup_path
    except OSError as e:
        logger.error(f"Backup failed for {path}: {e}")
        return None


def restore_from_backup(path: Path) -> bool:
    """Restore file from most recent backup."""
    try:
        pattern = f"{path.stem}_*{path.suffix}"
        backups = sorted(BACKUPS_DIR.glob(pattern), reverse=True)
        if not backups:
            logger.warning(f"No backup found for {path.name}")
            return False
        latest = backups[0]
        path.write_bytes(latest.read_bytes())
        logger.info(f"Restored {path.name} from {latest.name}")
        return True
    except OSError as e:
        logger.error(f"Restore failed for {path}: {e}")
        return False


# ============================================================
# Git checkpoint & self-healing
# ============================================================

def git_checkpoint(tag: str) -> bool:
    """Create a git checkpoint (commit) for rollback."""
    try:
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=str(WORKDIR),
            capture_output=True, text=True, timeout=30,
        )
        result = subprocess.run(
            ["git", "commit", "-m", f"daemon-checkpoint: {tag}", "--allow-empty"],
            cwd=str(WORKDIR),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"Git checkpoint: {tag}")
            log_event("git_checkpoint", {"tag": tag})
            return True
        return False
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error(f"Git checkpoint failed: {e}")
        return False


def run_tests(scope: Optional[str] = None) -> tuple[bool, str]:
    """Run pytest and return (passed, output_summary)."""
    cmd = [
        sys.executable, "-m", "pytest",
        "--ignore=vendor",
        "--tb=line", "-q",
        "--timeout=120",
    ]
    if scope:
        cmd.append(scope)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(WORKDIR),
            capture_output=True, text=True,
            timeout=TEST_TIMEOUT,
        )
        output = result.stdout + result.stderr
        # Extract summary line
        lines = output.strip().split("\n")
        summary = lines[-1] if lines else "no output"
        passed = result.returncode == 0
        return passed, summary
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except OSError as e:
        return False, f"ERROR: {e}"


def self_heal(changed_files: List[Path]) -> bool:
    """Run tests after changes. If failed, revert changed files."""
    logger.info(f"Self-heal: running tests after {len(changed_files)} file changes")
    passed, summary = run_tests()

    if passed:
        log_event("self_heal_ok", {"summary": summary, "files": [str(f) for f in changed_files]})
        logger.info(f"Self-heal: PASS — {summary}")
        return True

    # Tests failed → revert
    logger.warning(f"Self-heal: FAIL — {summary}. Reverting {len(changed_files)} files.")
    log_event("self_heal_fail", {"summary": summary, "files": [str(f) for f in changed_files]})

    for f in changed_files:
        if not restore_from_backup(f):
            # No backup → try git checkout
            try:
                subprocess.run(
                    ["git", "checkout", "--", str(f.relative_to(WORKDIR))],
                    cwd=str(WORKDIR),
                    capture_output=True, timeout=10,
                )
                logger.info(f"Reverted {f.name} via git checkout")
            except (subprocess.TimeoutExpired, OSError, ValueError):
                logger.error(f"Could not revert {f.name}")

    # Verify tests pass after revert
    passed2, summary2 = run_tests()
    if passed2:
        logger.info(f"Self-heal: Revert successful — {summary2}")
        log_event("self_heal_revert_ok", {"summary": summary2})
    else:
        logger.error(f"Self-heal: Revert FAILED — {summary2}")
        log_event("self_heal_revert_fail", {"summary": summary2})

    return False


# ============================================================
# Circuit breaker
# ============================================================

def load_circuit_breaker() -> Dict[str, Any]:
    return safe_read_json(CIRCUIT_BREAKER_FILE, {
        "daemon": {"consecutive_failures": 0, "paused_until": None}
    })


def save_circuit_breaker(data: Dict[str, Any]) -> None:
    safe_write_json(CIRCUIT_BREAKER_FILE, data)


def record_success(agent: str = "daemon") -> None:
    """Record success, reset failure counter and clear pause."""
    cb = load_circuit_breaker()
    if agent not in cb:
        cb[agent] = {"consecutive_failures": 0, "paused_until": None}
    cb[agent]["consecutive_failures"] = 0
    cb[agent]["paused_until"] = None
    cb[agent]["last_ok"] = now_iso()
    save_circuit_breaker(cb)


def record_failure(agent: str = "daemon", reason: str = "unknown") -> bool:
    """Record failure. Returns True if breaker tripped (should pause)."""
    cb = load_circuit_breaker()
    if agent not in cb:
        cb[agent] = {"consecutive_failures": 0, "paused_until": None}
    cb[agent]["consecutive_failures"] = cb[agent].get("consecutive_failures", 0) + 1
    cb[agent]["last_error"] = now_iso()
    cb[agent]["last_error_reason"] = reason
    tripped = cb[agent]["consecutive_failures"] >= MAX_FAILURES_BEFORE_PAUSE
    if tripped:
        cb[agent]["paused_until"] = (
            datetime.now(timezone.utc).timestamp() + PAUSE_DURATION
        )
        logger.warning(
            f"Circuit breaker TRIPPED for {agent}: "
            f"{cb[agent]['consecutive_failures']} failures. "
            f"Pausing for {PAUSE_DURATION}s."
        )
        log_event("circuit_breaker_trip", {"agent": agent, "failures": cb[agent]["consecutive_failures"]})
    save_circuit_breaker(cb)
    return tripped


def is_paused(agent: str = "daemon") -> bool:
    """Check if agent is paused by circuit breaker."""
    cb = load_circuit_breaker()
    if agent not in cb:
        return False
    paused_until = cb[agent].get("paused_until")
    if paused_until is None:
        return False
    if time.time() < paused_until:
        return True
    # Pause expired → reset
    cb[agent]["paused_until"] = None
    cb[agent]["consecutive_failures"] = 0
    save_circuit_breaker(cb)
    logger.info(f"Circuit breaker RESET for {agent} (pause expired)")
    return False


# ============================================================
# Failed task cache & quarantine
# ============================================================

def load_failed_cache() -> Dict[str, int]:
    return safe_read_json(FAILED_CACHE_FILE, {})


def save_failed_cache(data: Dict[str, int]) -> None:
    safe_write_json(FAILED_CACHE_FILE, data)


def record_task_failure(task_id: str) -> bool:
    """Record task failure. Returns True if quarantined."""
    cache = load_failed_cache()
    cache[task_id] = cache.get(task_id, 0) + 1
    save_failed_cache(cache)
    if cache[task_id] >= QUARANTINE_THRESHOLD:
        logger.warning(f"Task {task_id} QUARANTINED ({cache[task_id]} failures)")
        log_event("task_quarantined", {"task_id": task_id, "failures": cache[task_id]})
        return True
    return False


def is_quarantined(task_id: str) -> bool:
    cache = load_failed_cache()
    return cache.get(task_id, 0) >= QUARANTINE_THRESHOLD


# ============================================================
# File watching & change detection
# ============================================================

WATCHED_FILES = [
    REVIEW_QUEUE,
    KANBAN,
    BACKLOG,
    STATUS_FILE,
    HANDOFF_FILE,
    NETWEAVER_DIR / "BLOCKERS.md",
]


def detect_changes() -> List[Path]:
    """Check watched files for changes since last scan."""
    global file_hashes
    changed = []
    for path in WATCHED_FILES:
        new_hash = file_hash(path)
        old_hash = file_hashes.get(str(path))
        if new_hash != old_hash:
            if old_hash is not None:  # Not first scan
                changed.append(path)
            file_hashes[str(path)] = new_hash or ""
    return changed


def init_hashes() -> None:
    """Initialize file hashes on startup."""
    global file_hashes
    for path in WATCHED_FILES:
        h = file_hash(path)
        file_hashes[str(path)] = h if h is not None else ""


# ============================================================
# Gap detection & plan generation
# ============================================================

def parse_backlog_tasks() -> List[Dict[str, str]]:
    """Parse BACKLOG.md for actionable tasks."""
    if not BACKLOG.exists():
        return []
    content = BACKLOG.read_text()
    lines = content.split("\n")
    tasks = []
    current_id = None
    current_data = {}
    in_acceptance = False
    acceptance_lines = []

    for line in lines:
        stripped = line.strip()
        # Match task headers like "## NW-025 Skill Learner — Close the Learning Loop"
        if stripped.startswith("## NW-") or stripped.startswith("## P2-") or stripped.startswith("## PL-"):
            if current_id:
                if acceptance_lines:
                    current_data["acceptance"] = " ".join(acceptance_lines)
                tasks.append(current_data)
                acceptance_lines = []
                in_acceptance = False
            parts = stripped[3:].split(" ", 1)
            current_id = parts[0] if parts else "UNKNOWN"
            current_data = {
                "id": current_id,
                "title": parts[1] if len(parts) > 1 else current_id,
                "tiny_goal": "",
                "files_to_touch": "",
                "acceptance": "",
            }
        elif not current_id:
            continue
        elif stripped.startswith("tiny_goal:"):
            current_data["tiny_goal"] = stripped[len("tiny_goal:"):].strip()
            in_acceptance = False
        elif stripped.startswith("files_to_touch:"):
            current_data["files_to_touch"] = stripped[len("files_to_touch:"):].strip()
            in_acceptance = False
        elif stripped.startswith("acceptance_checks:"):
            single = stripped[len("acceptance_checks:"):].strip()
            if single:
                acceptance_lines.append(single)
            in_acceptance = True
        elif in_acceptance and stripped.startswith("- "):
            acceptance_lines.append(stripped[2:])
        elif in_acceptance and stripped and not stripped.startswith("##"):
            # Non-list line in acceptance block — might be new field
            if ":" in stripped and not stripped.startswith("-"):
                in_acceptance = False
            else:
                acceptance_lines.append(stripped)
        elif stripped.startswith("##"):
            in_acceptance = False

    if current_id:
        if acceptance_lines:
            current_data["acceptance"] = " ".join(acceptance_lines)
        tasks.append(current_data)

    return tasks


def parse_kanban_ready() -> Set[str]:
    """Get task IDs currently in ready/doing state."""
    if not KANBAN.exists():
        return set()
    content = KANBAN.read_text()
    ids = set()
    in_ready = False
    for line in content.split("\n"):
        if line.strip() == "## ready":
            in_ready = True
            continue
        if line.startswith("## ") and in_ready:
            break
        if in_ready and line.startswith("### "):
            # Extract ID like "NW-A003" from "### NW-A003 CI Setup"
            parts = line[4:].split(" ", 1)
            if parts:
                ids.add(parts[0])
    return ids


def parse_review_queue_pending() -> Set[str]:
    """Get task IDs already in review queue."""
    if not REVIEW_QUEUE.exists():
        return set()
    content = REVIEW_QUEUE.read_text()
    ids = set()
    for line in content.split("\n"):
        if line.startswith("### "):
            parts = line[4:].split(" ", 1)
            if parts:
                ids.add(parts[0])
    return ids


def parse_kanban_done() -> Set[str]:
    """Get task IDs in the done section of KANBAN."""
    if not KANBAN.exists():
        return set()
    content = KANBAN.read_text()
    ids = set()
    in_done = False
    for line in content.split("\n"):
        if line.strip() == "## done":
            in_done = True
            continue
        if line.startswith("## ") and in_done:
            break
        if in_done and line.startswith("### "):
            parts = line[4:].split(" ", 1)
            if parts:
                ids.add(parts[0])
    return ids


def detect_gaps() -> List[Dict[str, str]]:
    """Find backlog tasks not yet in KANBAN (ready or done) or REVIEW_QUEUE."""
    backlog_tasks = parse_backlog_tasks()
    ready_ids = parse_kanban_ready()
    done_ids = parse_kanban_done()
    queue_ids = parse_review_queue_pending()
    active_ids = ready_ids | done_ids | queue_ids

    gaps = []
    for task in backlog_tasks:
        tid = task["id"]
        if tid in active_ids:
            continue
        if is_quarantined(tid):
            continue
        gaps.append(task)

    return gaps


def generate_plan(task: Dict[str, str]) -> str:
    """Generate a plan entry for REVIEW_QUEUE.md with epistemic analysis."""
    tid = task["id"]
    title = task.get("title", tid)
    tiny_goal = task.get("tiny_goal", f"Implement {tid}")
    files = task.get("files_to_touch", "TBD")
    acceptance = task.get("acceptance", "Tests pass; no regressions.")

    base_plan = f"""### {tid} {title}
**Status**: PENDING
**Risk**: MEDIUM
**Scope**: {files}
**Tiny Goal**: {tiny_goal}
**Acceptance**: {acceptance}
**Generated**: {now_iso()}
"""

    # Enrich with epistemic analysis
    try:
        enriched, warnings = epistemic_daemon.enrich_plan_with_epistemic(task, base_plan)
        if warnings:
            log_event("epistemic_warnings", {"task_id": tid, "warnings": warnings})
        return enriched + "\n\n---\n"
    except Exception as e:
        logger.warning(f"Epistemic enrichment failed for {tid}: {e}")
        return base_plan + "\n---\n"


def write_plans_to_review_queue(plans: List[str]) -> int:
    """Append new plans to REVIEW_QUEUE.md. Returns count added."""
    if not plans:
        return 0

    # Backup before write
    backup_file(REVIEW_QUEUE)

    content = REVIEW_QUEUE.read_text() if REVIEW_QUEUE.exists() else "# NetWeaver Review Queue\n\n---\n"

    # Check for duplicates
    existing_ids = parse_review_queue_pending()
    new_plans = []
    for plan in plans:
        # Extract task ID from plan header
        for line in plan.split("\n"):
            if line.startswith("### "):
                tid = line[4:].split(" ", 1)[0]
                if tid not in existing_ids:
                    new_plans.append(plan)
                break

    if not new_plans:
        return 0

    content += "\n".join(new_plans)
    REVIEW_QUEUE.write_text(content)
    logger.info(f"Wrote {len(new_plans)} plans to REVIEW_QUEUE")
    log_event("plans_generated", {"count": len(new_plans), "ids": [p.split("### ")[1].split(" ")[0] for p in new_plans if "### " in p]})
    return len(new_plans)


# ============================================================
# Main daemon loop
# ============================================================

async def cleanup_loop() -> None:
    """Periodic cleanup: rotate logs, prune backups, skills, agent fingerprints."""
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(3600)  # Run every hour
            if shutdown_event.is_set():
                break
            
            # 1. Rotate daemon log (keep last 1000 lines)
            log_file = TINI_DIR / "daemon_stdout.log"
            if log_file.exists() and log_file.stat().st_size > 100_000:
                lines = log_file.read_text().splitlines()
                if len(lines) > 1000:
                    log_file.write_text("\n".join(lines[-1000:]) + "\n")
            
            # 2. Prune old backups (keep last 20)
            backups_dir = TINI_DIR / "backups"
            if backups_dir.exists():
                backups = sorted(backups_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
                for old in backups[20:]:
                    try:
                        old.unlink()
                    except OSError:
                        pass
            
            # 3. Rotate events log (keep last 2000)
            events_file = TINI_DIR / "events.jsonl"
            if events_file.exists():
                lines = events_file.read_text().strip().splitlines()
                if len(lines) > 2000:
                    events_file.write_text("\n".join(lines[-2000:]) + "\n")
            
            # 4. Clean stale PID files
            pid_file = TINI_DIR / "daemon.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                except (ValueError, OSError, ProcessLookupError):
                    pid_file.unlink(missing_ok=True)
            
            # 5. Purge stale skills (>7 days)
            skills_dir = TINI_DIR / "skills"
            if skills_dir.exists():
                now_ts = time.time()
                for f in skills_dir.glob("*.json"):
                    if (now_ts - f.stat().st_mtime) > 7 * 24 * 3600:
                        try:
                            f.unlink()
                        except OSError:
                            pass
            
            # 6. Dead agent reaper (fingerprints >48h)
            agent_dir = TINI_DIR / "agent_states"
            if agent_dir.exists():
                now_ts = time.time()
                reaped = 0
                for f in agent_dir.glob("*.fingerprint"):
                    if (now_ts - f.stat().st_mtime) > 48 * 3600:
                        try:
                            f.unlink()
                            reaped += 1
                        except OSError:
                            pass
                if reaped:
                    log_event("agent_reaped", {"count": reaped})
            
            # 7. Update metrics summary
            _update_metrics_summary()
        
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
    
    logger.info("Cleanup loop exited")


# ============================================================
# Performance metrics
# ============================================================

METRICS_FILE = TINI_DIR / "metrics.json"

def record_metric(name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
    """Record a performance metric (plan_gen_time, test_duration, etc.)."""
    metrics = safe_read_json(METRICS_FILE, {"series": {}, "last_updated": None})
    series = metrics.get("series", {})
    if name not in series:
        series[name] = []
    series[name].append({
        "v": round(value, 3),
        "ts": now_iso(),
        **(tags or {}),
    })
    # Keep last 100 data points per metric
    series[name] = series[name][-100:]
    metrics["series"] = series
    metrics["last_updated"] = now_iso()
    safe_write_json(METRICS_FILE, metrics)


def _update_metrics_summary() -> None:
    """Write human-readable metrics summary."""
    metrics = safe_read_json(METRICS_FILE, {"series": {}})
    series = metrics.get("series", {})
    if not series:
        return
    
    lines = ["# Performance Metrics", ""]
    for name, data_points in series.items():
        if not data_points:
            continue
        values = [d["v"] for d in data_points]
        avg = sum(values) / len(values)
        mn, mx = min(values), max(values)
        lines.append(f"## {name}")
        lines.append(f"- Samples: {len(values)}")
        lines.append(f"- Avg: {avg:.3f}, Min: {mn:.3f}, Max: {mx:.3f}")
        lines.append("")
    
    summary_file = TINI_DIR / "metrics_summary.md"
    try:
        summary_file.write_text("\n".join(lines))
    except OSError:
        pass


# ============================================================
# Auto-retry: archive plans rejected >3 times
# ============================================================

REJECTED_ARCHIVE = COMPANY_DIR / "REJECTED_ARCHIVE.md"
MAX_REJECTIONS = 3

def archive_stale_rejections() -> int:
    """Move plans rejected >3 times to archive. Returns count archived."""
    if not REVIEW_QUEUE.exists():
        return 0
    
    content = REVIEW_QUEUE.read_text()
    import re
    
    # Split into plan blocks
    plans = re.split(r"(?=## PLAN:)", content)
    kept = []
    archived = []
    
    for plan in plans:
        if not plan.strip() or "## PLAN:" not in plan:
            kept.append(plan)
            continue
        
        # Count REJECTED markers
        rejections = plan.count("STATUS: REJECTED")
        if rejections >= MAX_REJECTIONS:
            archived.append(plan)
        else:
            kept.append(plan)
    
    if archived:
        # Write archived plans
        try:
            existing = REJECTED_ARCHIVE.read_text() if REJECTED_ARCHIVE.exists() else "# Rejected Plans Archive\n\n"
            existing += f"\n## Archived {now_iso()}\n"
            for a in archived:
                existing += a + "\n---\n"
            REJECTED_ARCHIVE.write_text(existing)
            
            # Rewrite queue without archived plans
            REVIEW_QUEUE.write_text("".join(kept))
            logger.info(f"Archived {len(archived)} rejected plans")
            log_event("plans_archived", {"count": len(archived)})
        except OSError as e:
            logger.error(f"Archive failed: {e}")
            return 0
    
    return len(archived)


async def heartbeat_loop() -> None:
    """Write heartbeat periodically."""
    while not shutdown_event.is_set():
        write_heartbeat()
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def web_learning_loop() -> None:
    """Periodic web learning: visit sites, observe, execute, learn skills.

    Runs every 30 minutes in headless mode. Never blocks the main scan loop.
    """
    LEARN_INTERVAL = 1800  # 30 minutes

    # Wait for daemon to stabilize
    await asyncio.sleep(60)
    logger.info("Web learning loop started")

    while not shutdown_event.is_set():
        if is_paused("daemon"):
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=LEARN_INTERVAL)
            except asyncio.TimeoutError:
                pass
            continue

        try:
            logger.info("Web learning cycle starting...")
            t0 = time.time()

            # Run exploration in thread pool (it's sync/blocking)
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, web_explorer.explore_cycle)

            duration = time.time() - t0
            successes = sum(1 for r in results if r.success)
            total_elements = sum(r.elements_found for r in results)
            total_actions = sum(r.actions_succeeded for r in results)

            logger.info(
                f"Web learning complete: {successes}/{len(results)} sites, "
                f"{total_elements} elements, {total_actions} actions ({duration:.1f}s)"
            )

            log_event("web_learning", {
                "sites": len(results),
                "successes": successes,
                "elements": total_elements,
                "actions": total_actions,
                "duration_s": round(duration, 1),
                "details": [
                    {
                        "url": r.url,
                        "success": r.success,
                        "elements": r.elements_found,
                        "actions": r.actions_succeeded,
                        "nodes": r.scene_graph_nodes,
                    }
                    for r in results
                ],
            })

            # Record to epistemic
            epistemic_daemon.record_outcome(
                task_id="web_learning_cycle",
                success=successes > 0,
                evidence={
                    "sites": len(results),
                    "successes": successes,
                    "elements": total_elements,
                },
            )

        except Exception as e:
            logger.error(f"Web learning error: {e}")
            log_event("web_learning_error", {"error": str(e)[:200]})

        # Sleep until next cycle
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=LEARN_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def task_scheduler_loop() -> None:
    """Periodic task scheduler: run defined automation tasks on schedule.

    Checks tasks.yaml every 10 minutes, runs tasks that are due,
    detects changes, and sends notifications.
    """
    CHECK_INTERVAL = 600  # 10 minutes

    # Wait for daemon to stabilize
    await asyncio.sleep(90)

    logger.info("Task scheduler loop started")

    while not shutdown_event.is_set():
        try:
            t0 = time.time()

            # Run due tasks in thread pool (it's sync/blocking)
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, task_scheduler.run_due_tasks)

            if results:
                duration = time.time() - t0
                successes = sum(1 for r in results if r.success)
                total_items = sum(len(r.data) for r in results)

                logger.info(
                    f"Task scheduler complete: {successes}/{len(results)} tasks, "
                    f"{total_items} items ({duration:.1f}s)"
                )

                # Detect changes
                changes = task_scheduler.detect_changes(results)
                if changes:
                    logger.info(f"Changes detected: {len(changes)} tasks")
                    # TODO: Send Telegram notification here

                # Log event
                log_event("task_scheduler", {
                    "tasks": len(results),
                    "successes": successes,
                    "items": total_items,
                    "changes": len(changes),
                    "duration_s": round(duration, 1),
                })

        except Exception as e:
            logger.error(f"Task scheduler error: {e}")

        # Sleep until next check
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=CHECK_INTERVAL)
        except asyncio.TimeoutError:
            pass


def update_status_md(test_count: int, passed: bool) -> None:
    """Auto-update STATUS.md with current test count and timestamp."""
    status_file = NETWEAVER_DIR / "STATUS.md"
    if not status_file.exists():
        return
    
    try:
        content = status_file.read_text()
        
        # Update test count
        test_status = "✅ passing" if passed else "❌ failing"
        content = re.sub(
            r"- \d+ tests [✅❌] (passing|failing)",
            f"- {test_count} tests {test_status}",
            content
        )
        
        # Update timestamp
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        content = re.sub(
            r"Last updated: .+",
            f"Last updated: {ts}",
            content
        )
        
        status_file.write_text(content)
    except (OSError, re.error) as e:
        logger.error(f"STATUS.md update failed: {e}")


async def scan_loop() -> None:
    """Main scan loop: detect changes, find gaps, generate plans."""
    global cycle_count

    # Wait for initial file state to settle
    await asyncio.sleep(5)
    init_hashes()
    logger.info("File hashes initialized")

    while not shutdown_event.is_set():
        cycle_count += 1

        # Check circuit breaker
        if is_paused("daemon"):
            logger.debug(f"Cycle {cycle_count}: paused (circuit breaker)")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=SCAN_INTERVAL)
            except asyncio.TimeoutError:
                pass
            continue

        try:
            # 1. Detect file changes
            changed = detect_changes()
            if changed:
                names = [f.name for f in changed]
                logger.info(f"Cycle {cycle_count}: changes detected in {names}")
                log_event("file_changes", {"files": names})

            # 2. Detect gaps (backlog → not in kanban/queue)
            gaps = detect_gaps()
            if gaps:
                logger.info(f"Cycle {cycle_count}: {len(gaps)} gaps found")
                t0 = time.time()
                plans = [generate_plan(g) for g in gaps[:3]]  # Max 3 plans per cycle
                plan_gen_time = time.time() - t0
                record_metric("plan_gen_time_s", plan_gen_time, {"cycle": str(cycle_count), "count": str(len(plans))})
                count = write_plans_to_review_queue(plans)
                if count > 0:
                    record_success()
                    # Remember plan generation for future learning
                    for gap, plan_text in zip(gaps[:3], plans):
                        task_id = gap.get("id", "unknown")
                        daemon_palace.remember(
                            decision=f"generated plan for {task_id}",
                            context={"scope": gap.get("goal", "")[:80], "task_id": task_id},
                            outcome="pending",
                            tags=["plan-gen", task_id],
                        )
                        # Record epistemic outcome for plan generation
                        epistemic_daemon.record_outcome(
                            task_id=task_id,
                            success=True,
                            evidence={"phase": "plan_generated", "cycle": cycle_count},
                        )
                        # Record competence for plan generation
                        competence_matrix.record_simple(
                            agent_id="daemon",
                            task_id=task_id,
                            task_type="plan_gen",
                            success=True,
                            duration=plan_gen_time / max(len(gaps[:3]), 1),
                        )
            else:
                logger.debug(f"Cycle {cycle_count}: no gaps")

            # 2b. Archive plans rejected >3 times
            archive_stale_rejections()

            # 3. Update checkpoint
            checkpoint = {
                "action": "scan" if not changed else "event_detected",
                "changed": [str(f) for f in changed],
                "cycle": cycle_count,
                "_ts": now_iso(),
                "gaps_found": len(gaps) if gaps else 0,
                "paused": is_paused("daemon"),
            }
            safe_write_json(CHECKPOINT_FILE, checkpoint)

            # 4. Periodic test run (every 10 cycles = ~20min)
            if cycle_count % 10 == 0:
                logger.info(f"Cycle {cycle_count}: periodic test run")
                t0 = time.time()
                passed, summary = run_tests()
                test_dur = time.time() - t0
                record_metric("test_duration_s", test_dur, {"cycle": str(cycle_count)})
                # Auto-update STATUS.md with test count
                test_count_match = re.search(r"(\d+) passed", summary)
                test_count = int(test_count_match.group(1)) if test_count_match else 0
                update_status_md(test_count, passed)
                if passed:
                    record_success()
                    log_event("periodic_test_ok", {"summary": summary})
                else:
                    record_failure("daemon", f"periodic test fail: {summary}")
                    log_event("periodic_test_fail", {"summary": summary})
                    
                    # Causal chain analysis on test failures
                    try:
                        # Extract first failing test from summary
                        failing_test = re.search(r"(test_\S+\.py::\S+)", summary)
                        if failing_test:
                            test_name = failing_test.group(1)
                            error_msg = summary[:500]  # Truncate for analysis
                            chain = causal_tracer.trace_failure(test_name, error_msg)
                            if chain.confidence > 0.5:
                                logger.info(f"Causal analysis: {chain.root_cause} ({chain.confidence:.0%} confidence)")
                                log_event("causal_analysis", {
                                    "test": test_name,
                                    "root_cause": chain.root_cause,
                                    "confidence": chain.confidence,
                                    "fix": chain.fix_suggestion,
                                })
                    except Exception as e:
                        logger.debug(f"Causal tracing failed: {e}")

            # 5. Epistemic health check (every 15 cycles = ~30min)
            if cycle_count % 15 == 0 and cycle_count > 0:
                try:
                    health = epistemic_daemon.get_health_report()
                    stale = epistemic_daemon.get_stale_knowledge()
                    if stale:
                        logger.info(f"Cycle {cycle_count}: {len(stale)} stale epistemic facts")
                        log_event("epistemic_stale", {"count": len(stale), "items": stale[:3]})
                    if health["health_score"] < 70:
                        logger.warning(f"Cycle {cycle_count}: epistemic health low ({health['health_score']}/100)")
                        log_event("epistemic_health_low", {"health": health})
                except Exception as e:
                    logger.warning(f"Epistemic health check failed: {e}")

            # 6. Dreaming cycle (every 20 cycles = ~40min)
            if cycle_count % 20 == 0 and cycle_count > 0:
                try:
                    logger.info(f"Cycle {cycle_count}: dreaming...")
                    hypotheses = dream_engine.dream(max_hypotheses=5)
                    if hypotheses:
                        logger.info(f"Generated {len(hypotheses)} hypotheses")
                        log_event("dream", {
                            "count": len(hypotheses),
                            "hypotheses": [{"type": h.type, "content": h.content[:100], "confidence": h.confidence} for h in hypotheses],
                        })
                except Exception as e:
                    logger.warning(f"Dreaming failed: {e}")

        except Exception as e:
            logger.error(f"Cycle {cycle_count} error: {e}\n{traceback.format_exc()}")
            record_failure("daemon", str(e))
            log_event("cycle_error", {"error": str(e)})

        # Wait for next scan
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=SCAN_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def main_loop() -> None:
    """Main async entry point."""
    logger.info(f"NetWeaver Daemon starting (PID {os.getpid()})")
    logger.info(f"Workdir: {WORKDIR}")

    # Write PID
    PID_FILE.write_text(str(os.getpid()))

    # Write initial heartbeat
    write_heartbeat()

    # Git checkpoint on start
    git_checkpoint(f"daemon-start-{int(time.time())}")

    # Launch tasks
    hb_task = asyncio.create_task(heartbeat_loop())
    scan_task = asyncio.create_task(scan_loop())
    cleanup_task = asyncio.create_task(cleanup_loop())
    web_learn_task = asyncio.create_task(web_learning_loop())
    inflight_tasks.add(hb_task)
    inflight_tasks.add(scan_task)
    inflight_tasks.add(cleanup_task)
    inflight_tasks.add(web_learn_task)

    log_event("daemon_start", {"pid": os.getpid()})

    # Wait for shutdown
    await shutdown_event.wait()
    logger.info("Shutdown signal received, draining...")

    # Cancel and drain
    for task in inflight_tasks:
        task.cancel()
    await asyncio.gather(*inflight_tasks, return_exceptions=True)
    inflight_tasks.clear()

    # Final heartbeat (stale marker)
    try:
        HEARTBEAT_FILE.write_text("0")  # Mark as stopped
    except OSError:
        pass

    log_event("daemon_stop", {"cycles": cycle_count})
    logger.info(f"Daemon stopped after {cycle_count} cycles.")


def handle_signal(signum: int, frame: Any) -> None:
    """Signal handler — set shutdown event."""
    logger.info(f"Signal {signum} received")
    shutdown_event.set()


def main() -> None:
    """Entry point."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: shutdown_event.set())
        except NotImplementedError:
            signal.signal(sig, handle_signal)

    try:
        loop.run_until_complete(main_loop())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt")
        if not shutdown_event.is_set():
            shutdown_event.set()
    finally:
        loop.close()
        logger.info("Event loop closed.")


if __name__ == "__main__":
    main()
