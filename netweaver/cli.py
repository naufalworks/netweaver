#!/usr/bin/env python3
"""NetWeaver CLI — Query pipeline state without reading files."""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
import re

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

TINI = Path.home() / "Documents/myhermes/.tini"
NETWEAVER = TINI / "netweaver"
COMPANY = NETWEAVER / "company"


def cmd_status():
    """Show pipeline health and current state."""
    print("═══ NETWEAVER STATUS ═══\n")
    
    # Test count
    print("Tests: ", end="")
    try:
        import subprocess
        result = subprocess.run(
            ["pytest", "--co", "-q"],
            cwd=Path.home() / "Documents/myhermes",
            capture_output=True,
            text=True,
            timeout=5
        )
        count = result.stdout.count("test_")
        print(f"{count} collected ✅")
    except:
        print("unknown")
    
    # Daemon heartbeat
    hb_file = TINI / "daemon_heartbeat.txt"
    if hb_file.exists():
        try:
            ts = float(hb_file.read_text().strip())
            if ts > 0:
                age = datetime.now(timezone.utc).timestamp() - ts
                status = "✅" if age < 300 else "⚠️ STALE"
                print(f"Daemon: {status} (heartbeat {age:.0f}s ago)")
            else:
                print("Daemon: ⚠️ STOPPED (heartbeat=0)")
        except:
            print("Daemon: ❌ heartbeat unreadable")
    else:
        print("Daemon: ❌ no heartbeat file")
    
    # Circuit breaker
    cb_file = TINI / "circuit_breaker.json"
    if cb_file.exists():
        try:
            cb = json.loads(cb_file.read_text())
            tripped = [k for k, v in cb.items() if v.get("paused_until")]
            if tripped:
                print(f"Circuit Breaker: ⚠️ TRIPPED ({len(tripped)} agents)")
            else:
                print("Circuit Breaker: ✅ all clear")
        except:
            print("Circuit Breaker: ❌ unreadable")
    else:
        print("Circuit Breaker: ✅ no file (fresh)")
    
    # Recent failures
    events_file = TINI / "events.jsonl"
    if events_file.exists():
        try:
            events = [json.loads(l) for l in events_file.read_text().strip().split("\n")[-50:]]
            failures = [e for e in events if "fail" in e.get("type", "").lower()]
            if failures:
                print(f"Recent Failures: ⚠️ {len(failures)} in last 50 events")
            else:
                print("Recent Failures: ✅ none")
        except:
            pass


def cmd_kanban():
    """Show Kanban board summary."""
    print("═══ KANBAN BOARD ═══\n")
    
    kanban_file = COMPANY / "KANBAN.md"
    if not kanban_file.exists():
        print("❌ KANBAN.md not found")
        return
    
    content = kanban_file.read_text()
    
    # Parse sections
    sections = {
        "ready": [],
        "in_progress": [],
        "blocked": [],
        "done": []
    }
    
    current_section = None
    for line in content.split("\n"):
        if line.startswith("## "):
            section = line[3:].strip().lower().replace(" ", "_")
            if section in sections:
                current_section = section
        elif line.startswith("### ") and current_section:
            task_id = line[4:].split()[0]
            sections[current_section].append(task_id)
    
    # Display
    print(f"Ready:       {len(sections['ready'])} tasks")
    for task in sections['ready'][:5]:
        print(f"  • {task}")
    if len(sections['ready']) > 5:
        print(f"  ... and {len(sections['ready']) - 5} more")
    
    print(f"\nIn Progress: {len(sections['in_progress'])} tasks")
    for task in sections['in_progress'][:5]:
        print(f"  • {task}")
    
    print(f"\nBlocked:     {len(sections['blocked'])} tasks")
    for task in sections['blocked'][:5]:
        print(f"  • {task}")
    
    print(f"\nDone:        {len(sections['done'])} tasks")


def cmd_queue():
    """Show review queue status."""
    print("═══ REVIEW QUEUE ═══\n")
    
    queue_file = COMPANY / "REVIEW_QUEUE.md"
    if not queue_file.exists():
        print("❌ REVIEW_QUEUE.md not found")
        return
    
    content = queue_file.read_text()
    
    pending = content.count("PENDING")
    approved = content.count("APPROVED")
    blocked = content.count("BLOCKED")
    
    # Don't count the header mention
    if "Set **Status** to **APPROVED**" in content:
        approved -= 1
    if "Set **Status** to **BLOCKED**" in content:
        blocked -= 1
    
    print(f"Pending:  {pending}")
    print(f"Approved: {approved}")
    print(f"Blocked:  {blocked}")
    print(f"Total:    {pending + approved + blocked}")


def cmd_logs():
    """Show recent daemon logs."""
    print("═══ RECENT LOGS (last 30 lines) ═══\n")
    
    log_file = TINI / "daemon_stdout.log"
    if not log_file.exists():
        print("❌ daemon_stdout.log not found")
        return
    
    lines = log_file.read_text().strip().split("\n")
    for line in lines[-30:]:
        print(line)


def cmd_metrics():
    """Show performance metrics."""
    print("═══ PERFORMANCE METRICS ═══\n")
    
    metrics_file = TINI / "metrics.json"
    if not metrics_file.exists():
        print("No metrics yet (just started tracking)")
        return
    
    try:
        metrics = json.loads(metrics_file.read_text())
        series = metrics.get("series", {})
        
        for name, data in series.items():
            if not data:
                continue
            values = [d["v"] for d in data]
            avg = sum(values) / len(values)
            mn, mx = min(values), max(values)
            print(f"{name}:")
            print(f"  Samples: {len(values)}")
            print(f"  Avg: {avg:.3f}, Min: {mn:.3f}, Max: {mx:.3f}")
            print()
    except:
        print("❌ metrics.json unreadable")


def cmd_backlog():
    """Show backlog tasks."""
    print("═══ BACKLOG ═══\n")
    
    backlog_file = NETWEAVER / "BACKLOG.md"
    if not backlog_file.exists():
        print("❌ BACKLOG.md not found")
        return
    
    content = backlog_file.read_text()
    tasks = re.findall(r"^## (NW-\d+|P-\d+) (.+)$", content, re.MULTILINE)
    
    print(f"{len(tasks)} tasks in backlog:\n")
    for task_id, title in tasks:
        print(f"  • {task_id}: {title}")


def cmd_dashboard():
    """Launch live TUI dashboard."""
    try:
        from netweaver.dashboard import main as dashboard_main
        dashboard_main()
    except ImportError:
        print("❌ Rich library not installed. Install with: pip install rich")
    except KeyboardInterrupt:
        print("\n👋 Dashboard stopped.")


def cmd_memory():
    """Show agent memory palace stats."""
    from netweaver.memory_palace import MemoryPalace

    print("═══ AGENT MEMORY PALACE ═══\n")

    agents = ["daemon", "reviewer", "worker", "planner"]
    for agent_type in agents:
        palace = MemoryPalace(agent_type)
        if palace.count == 0:
            print(f"  {agent_type}: (empty)")
            continue

        insights = palace.introspect()
        print(f"  {agent_type}:")
        print(f"    Memories: {insights['total_memories']}")
        print(f"    Success rate: {insights['success_rate']:.0%}")
        dist = insights["outcome_distribution"]
        dist_str = ", ".join(f"{k}: {v}" for k, v in dist.items())
        print(f"    Outcomes: {dist_str}")
        if insights["top_tags"]:
            tags = ", ".join(f"{t}({c})" for t, c in insights["top_tags"][:5])
            print(f"    Top tags: {tags}")
        for insight in insights["insights"][:2]:
            print(f"    💡 {insight}")
        print()


def cmd_kg(args):
    """Knowledge graph operations."""
    from netweaver.knowledge_graph import KnowledgeGraph
    
    kg_file = TINI / "knowledge_graph.json"
    
    if args.kg_action == "scan":
        print("═══ SCANNING PROJECTS ═══\n")
        kg = KnowledgeGraph()
        
        workspace = Path(args.workspace) if args.workspace else Path.home() / "Documents"
        scanned = 0
        
        for project_dir in sorted(workspace.iterdir()):
            if project_dir.is_dir() and (project_dir / ".git").exists():
                print(f"  Scanning: {project_dir.name}...")
                try:
                    project = kg.scan_project(str(project_dir))
                    print(f"    ✓ {project.module_count} modules, {project.total_loc:,} LOC")
                    scanned += 1
                except Exception as e:
                    print(f"    ✗ Error: {e}")
        
        print(f"\nScanned {scanned} projects")
        print("\nAnalyzing patterns...")
        patterns = kg.analyze_patterns()
        print(f"Found {len(patterns)} cross-project patterns")
        
        kg.save(str(kg_file))
        print(f"\nSaved to: {kg_file}")
    
    elif args.kg_action == "visualize":
        if not kg_file.exists():
            print("❌ Knowledge graph not found. Run 'netweaver kg scan' first.")
            return
        
        kg = KnowledgeGraph()
        kg.load(str(kg_file))
        
        output_path = args.output if args.output else TINI / "knowledge_graph.md"
        viz = kg.visualize(output_path=str(output_path))
        
        if args.output:
            print(f"Visualization saved to: {output_path}")
        else:
            print(viz)
    
    elif args.kg_action == "query":
        if not kg_file.exists():
            print("❌ Knowledge graph not found. Run 'netweaver kg scan' first.")
            return
        
        kg = KnowledgeGraph()
        kg.load(str(kg_file))
        results = kg.query(args.query)
        
        if not results:
            print(f"No results for: {args.query}")
            return
        
        print(f"═══ RESULTS ({len(results)}) ═══\n")
        for r in results:
            if r['type'] == 'project':
                print(f"Project: {r['name']}")
                print(f"  Modules: {r['modules']}, LOC: {r['loc']:,}\n")
            elif r['type'] == 'module':
                print(f"Module: {r['name']} ({r['project']})")
                print(f"  Path: {r['path']}")
                print(f"  Classes: {r['classes']}, Functions: {r['functions']}\n")
    
    elif args.kg_action == "patterns":
        if not kg_file.exists():
            print("❌ Knowledge graph not found. Run 'netweaver kg scan' first.")
            return
        
        kg = KnowledgeGraph()
        kg.load(str(kg_file))
        
        print("═══ CROSS-PROJECT PATTERNS ═══\n")
        
        shared = [p for p in kg.cross_project_patterns if p['type'] == 'shared_library']
        if shared:
            print("Shared Libraries:")
            for p in sorted(shared, key=lambda x: x['count'], reverse=True)[:10]:
                projects = ", ".join(p['projects'][:3])
                if len(p['projects']) > 3:
                    projects += f" (+{len(p['projects'])-3} more)"
                print(f"  • {p['library']}: {p['count']} projects ({projects})")
            print()
        
        patterns = [p for p in kg.cross_project_patterns if p['type'] == 'design_pattern']
        if patterns:
            print("Design Patterns:")
            for p in sorted(patterns, key=lambda x: x['count'], reverse=True):
                projects = ", ".join(list(p['projects'].keys())[:3])
                print(f"  • {p['pattern']}: {p['count']} occurrences ({projects})")
    
    elif args.kg_action == "suggest":
        if not kg_file.exists():
            print("❌ Knowledge graph not found. Run 'netweaver kg scan' first.")
            return
        
        kg = KnowledgeGraph()
        kg.load(str(kg_file))
        suggestions = kg.suggest_cross_pollination()
        
        if not suggestions:
            print("No cross-pollination suggestions found")
            return
        
        print("═══ CROSS-POLLINATION SUGGESTIONS ═══\n")
        for s in suggestions[:20]:
            if s['type'] == 'similar_module':
                print(f"Similar module: {s['name']}")
                for proj, path in s['locations']:
                    print(f"  - {proj}: {path}")
                print(f"  💡 {s['suggestion']}\n")
            elif s['type'] == 'standardize_library':
                print(f"Standardize library: {s['library']}")
                print(f"  Used by {len(s['projects'])} projects: {', '.join(s['projects'])}")
                print(f"  💡 {s['suggestion']}\n")
    
    elif args.kg_action == "stats":
        if not kg_file.exists():
            print("❌ Knowledge graph not found. Run 'netweaver kg scan' first.")
            return
        
        kg = KnowledgeGraph()
        kg.load(str(kg_file))
        
        print("═══ KNOWLEDGE GRAPH STATISTICS ═══\n")
        print(f"Projects: {len(kg.projects)}")
        total_modules = sum(p.module_count for p in kg.projects.values())
        total_loc = sum(p.total_loc for p in kg.projects.values())
        print(f"Total modules: {total_modules:,}")
        print(f"Total LOC: {total_loc:,}\n")
        
        print("Projects:")
        for name, proj in sorted(kg.projects.items(), key=lambda x: x[1].total_loc, reverse=True):
            print(f"  • {name}: {proj.module_count} modules, {proj.total_loc:,} LOC")


def main():
    parser = argparse.ArgumentParser(
        description="NetWeaver CLI — Query pipeline state",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    subparsers.add_parser("status", help="Show pipeline health and current state")
    subparsers.add_parser("kanban", help="Show Kanban board summary")
    subparsers.add_parser("queue", help="Show review queue status")
    subparsers.add_parser("logs", help="Show recent daemon logs")
    subparsers.add_parser("metrics", help="Show performance metrics")
    subparsers.add_parser("backlog", help="Show backlog tasks")
    subparsers.add_parser("dashboard", help="Launch live TUI dashboard (Rich)")
    subparsers.add_parser("memory", help="Show agent memory palace stats")
    
    # Knowledge graph subcommand
    kg_parser = subparsers.add_parser("kg", help="Knowledge graph operations")
    kg_subparsers = kg_parser.add_subparsers(dest="kg_action", help="Knowledge graph action")
    
    kg_scan = kg_subparsers.add_parser("scan", help="Scan all projects and build knowledge graph")
    kg_scan.add_argument("--workspace", "-w", help="Workspace directory (default: ~/Documents)")
    
    kg_viz = kg_subparsers.add_parser("visualize", help="Generate Mermaid visualization")
    kg_viz.add_argument("--output", "-o", help="Output file (default: .tini/knowledge_graph.md)")
    
    kg_query = kg_subparsers.add_parser("query", help="Query the knowledge graph")
    kg_query.add_argument("query", help="Search query")
    
    kg_subparsers.add_parser("patterns", help="Show cross-project patterns")
    kg_subparsers.add_parser("suggest", help="Show cross-pollination suggestions")
    kg_subparsers.add_parser("stats", help="Show knowledge graph statistics")
    
    args = parser.parse_args()
    
    if args.command == "status":
        cmd_status()
    elif args.command == "kanban":
        cmd_kanban()
    elif args.command == "queue":
        cmd_queue()
    elif args.command == "logs":
        cmd_logs()
    elif args.command == "metrics":
        cmd_metrics()
    elif args.command == "backlog":
        cmd_backlog()
    elif args.command == "dashboard":
        cmd_dashboard()
    elif args.command == "memory":
        cmd_memory()
    elif args.command == "kg":
        if hasattr(args, 'kg_action') and args.kg_action:
            cmd_kg(args)
        else:
            kg_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
