#!/usr/bin/env python3
"""NetWeaver TUI Dashboard — Live terminal interface using Rich."""

import json
import time
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn
from rich import box

TINI = Path.home() / "Documents/myhermes/.tini"
NETWEAVER = TINI / "netweaver"
COMPANY = NETWEAVER / "company"

console = Console()


def get_daemon_status():
    """Get daemon heartbeat status."""
    hb_file = TINI / "daemon_heartbeat.txt"
    if not hb_file.exists():
        return "dead", "No heartbeat file"
    
    try:
        ts = float(hb_file.read_text().strip())
        if ts == 0:
            return "stopped", "Daemon stopped (hb=0)"
        age = time.time() - ts
        if age < 300:
            return "alive", f"Heartbeat {age:.0f}s ago"
        else:
            return "stale", f"Stale heartbeat {age:.0f}s ago"
    except (ValueError, OSError):
        return "dead", "Heartbeat unreadable"


def get_circuit_breaker():
    """Get circuit breaker status."""
    cb_file = TINI / "circuit_breaker.json"
    if not cb_file.exists():
        return "clear", 0, []
    
    try:
        cb = json.loads(cb_file.read_text())
        tripped = [k for k, v in cb.items() if v.get("paused_until")]
        if tripped:
            return "tripped", len(tripped), tripped
        return "clear", 0, []
    except (json.JSONDecodeError, OSError):
        return "error", 0, ["Unreadable"]


def get_test_count():
    """Get test count from last test run."""
    events_file = TINI / "events.jsonl"
    if not events_file.exists():
        return 0, "unknown"
    
    try:
        lines = events_file.read_text().strip().split("\n")
        for line in reversed(lines):
            event = json.loads(line)
            if event.get("type") in ("periodic_test_ok", "periodic_test_fail"):
                summary = event.get("summary", "")
                match = re.search(r"(\d+) passed", summary)
                if match:
                    status = "passing" if "ok" in event.get("type", "") else "failing"
                    return int(match.group(1)), status
    except (json.JSONDecodeError, OSError):
        pass
    return 0, "unknown"


def get_epistemic_health():
    """Get epistemic OS health status."""
    ep_file = TINI / "epistemic.json"
    if not ep_file.exists():
        return {"total_knowledge": 0, "health_score": 0, "health_label": "empty", "stale_count": 0, "contradictions": 0}
    
    try:
        from netweaver.epistemic import EpistemicOS
        os = EpistemicOS(storage_path=str(ep_file))
        return os.health_report()
    except Exception:
        return {"total_knowledge": 0, "health_score": 0, "health_label": "error", "stale_count": 0, "contradictions": 0}


def get_kanban_counts():
    """Count tasks in each Kanban column."""
    kanban_file = COMPANY / "KANBAN.md"
    if not kanban_file.exists():
        return {"ready": 0, "in_progress": 0, "blocked": 0, "done": 0}
    
    content = kanban_file.read_text()
    sections = {"ready": 0, "in_progress": 0, "blocked": 0, "done": 0}
    
    current_section = None
    for line in content.split("\n"):
        if line.startswith("## "):
            section = line[3:].strip().lower().replace(" ", "_")
            if section in sections:
                current_section = section
            else:
                current_section = None
        elif line.startswith("### ") and current_section:
            sections[current_section] += 1
    
    return sections


def get_queue_counts():
    """Count plans in review queue."""
    queue_file = COMPANY / "REVIEW_QUEUE.md"
    if not queue_file.exists():
        return {"pending": 0, "approved": 0, "blocked": 0}
    
    content = queue_file.read_text()
    pending = content.count("PENDING")
    approved = content.count("APPROVED") - 1  # Subtract header mention
    blocked = content.count("BLOCKED") - 1
    
    return {"pending": max(0, pending), "approved": max(0, approved), "blocked": max(0, blocked)}


def get_recent_events(count=5):
    """Get recent events from ledger."""
    events_file = TINI / "events.jsonl"
    if not events_file.exists():
        return []
    
    try:
        lines = events_file.read_text().strip().split("\n")
        events = [json.loads(l) for l in lines[-count:]]
        return events
    except (json.JSONDecodeError, OSError):
        return []


def get_metrics():
    """Get performance metrics."""
    metrics_file = TINI / "metrics.json"
    if not metrics_file.exists():
        return {}
    
    try:
        data = json.loads(metrics_file.read_text())
        series = data.get("series", {})
        result = {}
        for name, points in series.items():
            if points:
                values = [p["v"] for p in points]
                result[name] = {
                    "avg": sum(values) / len(values),
                    "count": len(values),
                    "last": values[-1] if values else 0,
                }
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def build_dashboard():
    """Build the dashboard layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=10),
    )
    
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1),
    )
    
    layout["left"].split_column(
        Layout(name="pipeline", size=8),
        Layout(name="kanban"),
        Layout(name="queue", size=8),
    )
    
    layout["right"].split_column(
        Layout(name="epistemic", size=10),
        Layout(name="metrics"),
        Layout(name="events"),
    )
    
    return layout


def update_dashboard(layout):
    """Update dashboard with current data."""
    # Header
    daemon_status, daemon_msg = get_daemon_status()
    cb_status, cb_count, cb_agents = get_circuit_breaker()
    test_count, test_status = get_test_count()
    
    header_text = Text()
    
    # Daemon status
    if daemon_status == "alive":
        header_text.append("● Daemon: ", style="green")
    elif daemon_status == "stale":
        header_text.append("● Daemon: ", style="yellow")
    else:
        header_text.append("● Daemon: ", style="red")
    header_text.append(f"{daemon_status.upper()} — {daemon_msg}  ", style="dim")
    
    # Circuit breaker
    if cb_status == "tripped":
        header_text.append("⚡ CB: TRIPPED ", style="red bold")
        header_text.append(f"({cb_count} agents)  ", style="red")
    else:
        header_text.append("✓ CB: Clear  ", style="green")
    
    # Tests
    if test_status == "passing":
        header_text.append(f"✓ Tests: {test_count} passing", style="green")
    elif test_status == "failing":
        header_text.append(f"✗ Tests: {test_count} failing", style="red")
    else:
        header_text.append("? Tests: unknown", style="yellow")
    
    layout["header"].update(Panel(header_text, title="NetWeaver Pipeline", border_style="blue"))
    
    # Pipeline health
    pipeline_table = Table(show_header=False, box=None, padding=(0, 1))
    pipeline_table.add_column("Component", style="cyan")
    pipeline_table.add_column("Status")
    
    pipeline_table.add_row("Daemon", "✓" if daemon_status == "alive" else "✗")
    pipeline_table.add_row("Circuit Breaker", "✓" if cb_status == "clear" else "⚡")
    pipeline_table.add_row("Tests", f"{test_count}" if test_count > 0 else "?")
    
    metrics = get_metrics()
    if "plan_gen_time_s" in metrics:
        avg = metrics["plan_gen_time_s"]["avg"]
        pipeline_table.add_row("Plan Gen", f"{avg:.3f}s avg")
    if "test_duration_s" in metrics:
        avg = metrics["test_duration_s"]["avg"]
        pipeline_table.add_row("Test Run", f"{avg:.1f}s avg")
    
    layout["pipeline"].update(Panel(pipeline_table, title="Pipeline Health", border_style="green"))
    
    # Kanban
    kanban = get_kanban_counts()
    kanban_table = Table(show_header=True, box=box.SIMPLE)
    kanban_table.add_column("Ready", justify="center")
    kanban_table.add_column("In Progress", justify="center")
    kanban_table.add_column("Blocked", justify="center")
    kanban_table.add_column("Done", justify="center")
    
    kanban_table.add_row(
        str(kanban["ready"]),
        str(kanban["in_progress"]),
        str(kanban["blocked"]),
        str(kanban["done"]),
    )
    
    layout["kanban"].update(Panel(kanban_table, title="Kanban Board", border_style="cyan"))
    
    # Queue
    queue = get_queue_counts()
    queue_table = Table(show_header=True, box=box.SIMPLE)
    queue_table.add_column("Pending", justify="center", style="yellow")
    queue_table.add_column("Approved", justify="center", style="green")
    queue_table.add_column("Blocked", justify="center", style="red")
    
    queue_table.add_row(
        str(queue["pending"]),
        str(queue["approved"]),
        str(queue["blocked"]),
    )
    
    layout["queue"].update(Panel(queue_table, title="Review Queue", border_style="yellow"))
    
    # Epistemic OS
    ep_health = get_epistemic_health()
    ep_table = Table(show_header=False, box=None, padding=(0, 1))
    ep_table.add_column("Metric", style="magenta")
    ep_table.add_column("Value", justify="right")
    
    health_label = ep_health.get("health_label", "empty")
    health_color = {"excellent": "green", "good": "green", "fair": "yellow", "poor": "red", "empty": "dim", "error": "red"}.get(health_label, "dim")
    
    ep_table.add_row("Knowledge", str(ep_health.get("total_knowledge", 0)))
    ep_table.add_row("Confidence", f"{ep_health.get('avg_confidence', 0):.0%}")
    ep_table.add_row("Stale", str(ep_health.get("stale_count", 0)))
    ep_table.add_row("Contradictions", str(ep_health.get("contradictions", 0)))
    ep_table.add_row("Health", f"[{health_color}]{ep_health.get('health_score', 0)}/100 ({health_label})[/{health_color}]")
    
    layout["epistemic"].update(Panel(ep_table, title="Epistemic OS", border_style="magenta"))
    
    # Metrics
    metrics_table = Table(show_header=True, box=box.SIMPLE)
    metrics_table.add_column("Metric", style="cyan")
    metrics_table.add_column("Avg", justify="right")
    metrics_table.add_column("Samples", justify="right")
    metrics_table.add_column("Last", justify="right")
    
    for name, data in metrics.items():
        metrics_table.add_row(
            name.replace("_", " ").title(),
            f"{data['avg']:.3f}",
            str(data['count']),
            f"{data['last']:.3f}",
        )
    
    if not metrics:
        metrics_table.add_row("No metrics yet", "", "", "")
    
    layout["metrics"].update(Panel(metrics_table, title="Performance Metrics", border_style="magenta"))
    
    # Recent events
    events = get_recent_events(8)
    events_text = Text()
    
    for event in reversed(events):
        ts = event.get("ts", "")[:19].replace("T", " ")
        etype = event.get("type", "unknown")
        
        # Color code by event type
        if "fail" in etype or "error" in etype:
            style = "red"
        elif "ok" in etype or "success" in etype:
            style = "green"
        elif "plan" in etype or "gap" in etype:
            style = "cyan"
        else:
            style = "dim"
        
        events_text.append(f"{ts} ", style="dim")
        events_text.append(f"{etype}\n", style=style)
    
    if not events:
        events_text.append("No recent events", style="dim")
    
    layout["events"].update(Panel(events_text, title="Recent Events", border_style="blue"))
    
    # Footer
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer_text = Text(f"Last update: {now} | Ctrl+C to exit", style="dim")
    layout["footer"].update(footer_text)


def main():
    """Run the live dashboard."""
    console.clear()
    console.print("\n[yellow]Starting NetWeaver Dashboard...[/yellow]")
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")
    time.sleep(1)
    
    layout = build_dashboard()
    
    try:
        with Live(layout, console=console, refresh_per_second=2, screen=True) as live:
            while True:
                update_dashboard(layout)
                time.sleep(5)  # Update every 5 seconds
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")


if __name__ == "__main__":
    main()
