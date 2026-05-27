"""NetWeaver Task Scheduler — Automated web monitoring and extraction.

Reads tasks from tasks.yaml, runs them on schedule, extracts structured data,
detects changes, and sends notifications.

Design:
  - YAML task definitions (URL + schedule + extractors)
  - CloakBrowser-based extraction (headless)
  - Change detection (hash comparison)
  - Telegram notifications
  - Persistent state (.tini/task_scheduler/state.json)
  - Integrated into daemon loop
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from netweaver.cloak_bridge import CloakBrowserBridge

logger = logging.getLogger("task_scheduler")


# Schedule parsing
SCHEDULE_UNITS = {
    "minute": 60,
    "minutes": 60,
    "hour": 3600,
    "hours": 3600,
    "day": 86400,
    "days": 86400,
    "week": 604800,
    "weeks": 604800,
}


def parse_schedule(schedule: str) -> int:
    """Parse human-readable schedule to seconds.
    
    Examples:
        "30 minutes" -> 1800
        "2 weeks" -> 1209600
        "1 day" -> 86400
    """
    match = re.match(r"(\d+)\s+(\w+)", schedule.strip().lower())
    if not match:
        logger.warning(f"Invalid schedule: {schedule}, defaulting to 1 hour")
        return 3600
    
    value = int(match.group(1))
    unit = match.group(2)
    
    if unit not in SCHEDULE_UNITS:
        logger.warning(f"Unknown unit: {unit}, defaulting to 1 hour")
        return 3600
    
    return value * SCHEDULE_UNITS[unit]


@dataclass
class ExtractionResult:
    """Result of extracting data from a page."""
    task_id: str
    success: bool
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
    
    def to_hash(self) -> str:
        """Hash the extracted data for change detection."""
        content = json.dumps(self.data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class TaskState:
    """Persistent state for a task."""
    task_id: str
    last_run: str = ""
    last_result_hash: str = ""
    run_count: int = 0
    success_count: int = 0
    last_error: str = ""
    
    @property
    def should_run(self, schedule_seconds: int) -> bool:
        """Check if enough time has passed since last run."""
        if not self.last_run:
            return True
        try:
            last = datetime.fromisoformat(self.last_run)
            return datetime.now() - last > timedelta(seconds=schedule_seconds)
        except (ValueError, TypeError):
            return True


class TaskScheduler:
    """Automated web monitoring and extraction engine.
    
    Usage:
        scheduler = TaskScheduler(tasks_file=Path("netweaver/tasks.yaml"))
        scheduler.run_due_tasks()
    """
    
    def __init__(
        self,
        tasks_file: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        headless: bool = True,
    ):
        self.tasks_file = tasks_file or Path("netweaver/tasks.yaml")
        self.state_dir = state_dir or Path(".tini/task_scheduler")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        
        # Load tasks
        self.tasks = self._load_tasks()
        
        # Load state
        self.state = self._load_state()
        
        # Persistent bridge
        self._bridge = CloakBrowserBridge()
    
    def _load_tasks(self) -> List[Dict]:
        """Load task definitions from YAML."""
        if not self.tasks_file.exists():
            logger.warning(f"Tasks file not found: {self.tasks_file}")
            return []
        try:
            with open(self.tasks_file) as f:
                data = yaml.safe_load(f)
                return data.get("tasks", [])
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
            return []
    
    def _load_state(self) -> Dict[str, TaskState]:
        """Load task state from disk."""
        state_file = self.state_dir / "state.json"
        if not state_file.exists():
            return {}
        try:
            data = json.loads(state_file.read_text())
            return {tid: TaskState(**state) for tid, state in data.items()}
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return {}
    
    def _save_state(self):
        """Save task state to disk."""
        state_file = self.state_dir / "state.json"
        data = {tid: {
            "task_id": state.task_id,
            "last_run": state.last_run,
            "last_result_hash": state.last_result_hash,
            "run_count": state.run_count,
            "success_count": state.success_count,
            "last_error": state.last_error,
        } for tid, state in self.state.items()}
        state_file.write_text(json.dumps(data, indent=2))
    
    def run_due_tasks(self) -> List[ExtractionResult]:
        """Run all tasks that are due."""
        results = []
        
        for task in self.tasks:
            task_id = task["id"]
            schedule = parse_schedule(task["schedule"])
            
            # Get or create state
            if task_id not in self.state:
                self.state[task_id] = TaskState(task_id=task_id)
            
            state = self.state[task_id]
            
            # Check if due
            if state.last_run:
                last = datetime.fromisoformat(state.last_run)
                if datetime.now() - last < timedelta(seconds=schedule):
                    continue
            
            # Run task
            try:
                logger.info(f"Running task: {task['name']}")
                result = self._run_task(task)
                results.append(result)
                
                # Update state
                state.last_run = datetime.now().isoformat()
                state.run_count += 1
                if result.success:
                    state.success_count += 1
                    state.last_result_hash = result.to_hash()
                else:
                    state.last_error = result.error[:200]
                
                logger.info(
                    f"[{task_id}] {'✓' if result.success else '✗'} "
                    f"extracted {len(result.data)} items"
                )
                
            except Exception as e:
                logger.error(f"[{task_id}] Error: {e}")
                results.append(ExtractionResult(
                    task_id=task_id,
                    success=False,
                    error=str(e)[:200],
                ))
        
        # Save state
        self._save_state()
        
        return results
    
    def _run_task(self, task: Dict) -> ExtractionResult:
        """Run a single task: navigate + extract."""
        task_id = task["id"]
        url = task["url"]
        extractors = task.get("extractors", [])
        
        # Navigate to URL
        try:
            obs = self._bridge.observe(url, headless=self.headless, timeout=15.0)
        except Exception as e:
            return ExtractionResult(
                task_id=task_id,
                success=False,
                error=f"Navigation failed: {str(e)[:100]}",
            )
        
        # Extract data
        all_data = []
        for extractor in extractors:
            try:
                data = self._extract_data(extractor)
                all_data.extend(data)
            except Exception as e:
                logger.debug(f"[{task_id}] Extractor error: {e}")
        
        success = len(all_data) > 0
        
        return ExtractionResult(
            task_id=task_id,
            success=success,
            data=all_data,
            error="" if success else "No data extracted",
        )
    
    def _extract_data(self, extractor: Dict) -> List[Dict]:
        """Extract data using an extractor definition."""
        ext_type = extractor.get("type", "list")
        selector = extractor.get("selector", "")
        fields = extractor.get("fields", {})
        
        if not selector or not self._bridge._page:
            return []
        
        results = []
        
        if ext_type == "list":
            # Extract list of items
            elements = self._bridge._page.locator(selector).all()
            
            for el in elements[:50]:  # Limit to 50 items
                item = {}
                for field_name, field_selector in fields.items():
                    try:
                        # Try to get text content
                        child = el.locator(field_selector).first
                        if child.count() > 0:
                            text = child.text_content(timeout=1000)
                            item[field_name] = text.strip() if text else ""
                        else:
                            item[field_name] = ""
                    except Exception:
                        item[field_name] = ""
                
                # Only add if we got at least one field
                if any(item.values()):
                    results.append(item)
        
        return results
    
    def detect_changes(self, results: List[ExtractionResult]) -> List[Dict]:
        """Detect changes in results compared to last run."""
        changes = []
        
        for result in results:
            if not result.success:
                continue
            
            task_id = result.task_id
            state = self.state.get(task_id)
            if not state:
                continue
            
            # Compare hashes
            current_hash = result.to_hash()
            if state.last_result_hash and state.last_result_hash != current_hash:
                changes.append({
                    "task_id": task_id,
                    "type": "data_changed",
                    "old_hash": state.last_result_hash,
                    "new_hash": current_hash,
                    "items_count": len(result.data),
                })
        
        return changes
    
    def format_results(self, results: List[ExtractionResult]) -> str:
        """Format results as readable summary."""
        if not results:
            return "No tasks run this cycle."
        
        lines = ["═══ Task Scheduler Report ═══", ""]
        
        for result in results:
            status = "✓" if result.success else "✗"
            lines.append(f"{status} {result.task_id}: {len(result.data)} items")
            
            if result.success and result.data:
                # Show first 3 items
                for item in result.data[:3]:
                    item_str = ", ".join(f"{k}={v[:30]}" for k, v in item.items() if v)
                    lines.append(f"  - {item_str}")
                if len(result.data) > 3:
                    lines.append(f"  ... and {len(result.data) - 3} more")
            
            if result.error:
                lines.append(f"  Error: {result.error[:80]}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def close(self):
        """Clean up browser resources."""
        self._bridge.close()
