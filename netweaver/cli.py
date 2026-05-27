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


def cmd_epistemic(args):
    """Epistemic OS — honest reasoning engine."""
    from netweaver.epistemic import EpistemicOS
    
    storage = str(TINI / "epistemic.json")
    os = EpistemicOS(storage_path=storage)
    
    if args.ep_action == "add":
        sources = []
        if args.source:
            from netweaver.epistemic import Source
            src_type, src_ref = args.source.split(":", 1) if ":" in args.source else ("manual", args.source)
            sources.append(Source(type=src_type, ref=src_ref))
        
        tags = args.tags.split(",") if args.tags else []
        
        node = os.add(
            content=args.content,
            confidence=args.confidence,
            topic=args.topic or "",
            tags=tags,
            context=args.context or "",
            sources=sources,
            decay_rate=args.decay,
        )
        print(f"✅ Added: {node.content}")
        print(f"   ID: {node.id}")
        print(f"   Confidence: {node.confidence:.0%} ({node.confidence_label})")
    
    elif args.ep_action == "query":
        answer = os.query(args.query)
        print(str(answer))
    
    elif args.ep_action == "health":
        report = os.health_report()
        print("═══ EPISTEMIC OS HEALTH ═══\n")
        print(f"Total knowledge: {report['total_knowledge']}")
        print(f"Avg confidence: {report['avg_confidence']:.0%}")
        print(f"Stale facts: {report['stale_count']}")
        print(f"Contradictions: {report['contradictions']}")
        print(f"Topics: {report['topics']}")
        print(f"Health score: {report['health_score']:.0f}/100 ({report['health_label']})")
        
        if report.get("top_tags"):
            print(f"\nTop tags:")
            for tag, count in report["top_tags"][:5]:
                print(f"  • {tag}: {count}")
        
        if report.get("confidence_distribution"):
            print(f"\nConfidence distribution:")
            for label, count in report["confidence_distribution"].items():
                if count > 0:
                    print(f"  • {label}: {count}")
    
    elif args.ep_action == "stale":
        stale = os.stale_knowledge()
        if not stale:
            print("✅ No stale knowledge (all facts have confidence >= 40%)")
            return
        
        print(f"═══ STALE KNOWLEDGE ({len(stale)} facts) ═══\n")
        for node in sorted(stale, key=lambda n: n.current_confidence):
            print(f"⚠️  {node.content}")
            print(f"   Confidence: {node.current_confidence:.0%} ({node.confidence_label})")
            print(f"   Age: {node.age_days}d, Decay: {node.decay_rate:.0%}/mo")
            print()
    
    elif args.ep_action == "verify":
        success = os.verify(args.content, new_confidence=args.confidence)
        if success:
            conf_str = f" → {args.confidence:.0%}" if args.confidence else ""
            print(f"✅ Verified: {args.content}{conf_str}")
        else:
            print(f"❌ Not found: {args.content}")
    
    elif args.ep_action == "contradictions":
        unresolved = os.detect_contradictions()
        if not unresolved:
            print("✅ No unresolved contradictions")
            return
        
        print(f"═══ CONTRADICTIONS ({len(unresolved)}) ═══\n")
        for c in unresolved:
            a = os.nodes.get(c.node_a_id)
            b = os.nodes.get(c.node_b_id)
            if a and b:
                print(f"⚠️  Severity: {c.severity:.0%}")
                print(f"   A: {a.content} ({a.confidence:.0%})")
                print(f"   B: {b.content} ({b.confidence:.0%})")
                print(f"   Reason: {c.reason}")
                print()
    
    elif args.ep_action == "recommend":
        recs = os.recommend_verification()
        if not recs:
            print("✅ Nothing to verify")
            return
        
        print("═══ RECOMMENDED VERIFICATIONS ═══\n")
        for node, reason in recs[:10]:
            print(f"• {node.content}")
            print(f"  Confidence: {node.current_confidence:.0%} | Reason: {reason}")
            print()
    
    elif args.ep_action == "trace":
        chain = os.trace(args.content)
        if not chain:
            print(f"❌ Not found: {args.content}")
            return
        
        print(f"═══ PROVENANCE CHAIN ═══\n")
        for entry in chain:
            indent = "  " * entry["depth"]
            print(f"{indent}• {entry['content']}")
            print(f"{indent}  Confidence: {entry['confidence']:.0%} ({entry['label']})")
            if entry["sources"]:
                for s in entry["sources"]:
                    print(f"{indent}  Source: {s}")
    
    elif args.ep_action == "import-memory":
        os.from_memory_palace(args.palace_file)
        print(f"✅ Imported from {args.palace_file}")
        print(f"   Total knowledge: {len(os.nodes)}")
    
    elif args.ep_action == "auto-verify":
        from netweaver.epistemic_verifier import AutoVerifier
        
        verifier = AutoVerifier(os)
        results = verifier.run_full_verification_cycle()
        
        print("═══ AUTO-VERIFICATION RESULTS ═══\n")
        
        # Stale knowledge
        stale = results["stale_knowledge"]
        print(f"Stale Knowledge:")
        print(f"  Verified: {stale['verified']}")
        print(f"  Failed: {stale['failed']}")
        print(f"  Needs manual: {stale['needs_manual']}")
        
        if stale.get("details"):
            print(f"\n  Details:")
            for d in stale["details"][:5]:  # Show first 5
                status_icon = "✅" if d["status"] == "verified" else "❌" if d["status"] == "failed" else "⚠️"
                print(f"    {status_icon} {d['content'][:60]}")
                if d.get("reason"):
                    print(f"       {d['reason']}")
        
        print()
        
        # Contradictions
        contra = results["contradictions"]
        print(f"Contradictions:")
        print(f"  Total: {contra['total']}")
        print(f"  Resolved: {contra['resolved']}")
        
        if contra.get("suggestions"):
            print(f"\n  Suggestions:")
            for s in contra["suggestions"][:3]:  # Show first 3
                print(f"    A: {s['node_a_content'][:50]} ({s['node_a_confidence']:.0%})")
                print(f"    B: {s['node_b_content'][:50]} ({s['node_b_confidence']:.0%})")
                print(f"    Auto-resolve: {s['auto_resolvable']}")
                if s.get("reasoning"):
                    print(f"    Reason: {', '.join(s['reasoning'][:2])}")
                print()
        
        # Calibration
        calib = results["calibration"]
        print(f"Calibration:")
        print(f"  Skills calibrated: {calib['skills_calibrated']}")
        print(f"  Total predictions: {calib['total_predictions']}")
        
        if calib.get("calibration_scores"):
            print(f"\n  Scores:")
            for c in calib["calibration_scores"][:5]:  # Show first 5
                print(f"    {c['skill_name']}: Brier={c['brier_score']:.2f} ({c['quality']})")
        
        print("\n✅ Verification complete")


def cmd_dream(args):
    """Dreaming — background hypothesis generation."""
    from netweaver.dreaming import DreamEngine
    
    engine = DreamEngine()
    
    if args.dream_action == "generate":
        hypotheses = engine.dream(max_hypotheses=5)
        if not hypotheses:
            print("✅ No new hypotheses generated")
            return
        
        print(f"═══ GENERATED {len(hypotheses)} HYPOTHESES ═══\n")
        for i, h in enumerate(hypotheses, 1):
            print(f"{i}. [{h.confidence:.0%}] {h.content}")
            print(f"   Type: {h.type}")
            print(f"   Outcome: {h.simulated_outcome}")
            print(f"   Validate: {h.validation_method}")
            print(f"   ID: {h.hypothesis_id[:12]}")
            print()
    
    elif args.dream_action == "list":
        unvalidated = engine.get_unvalidated()
        if not unvalidated:
            print("✅ No unvalidated hypotheses")
            return
        
        print(f"═══ UNVALIDATED HYPOTHESES ({len(unvalidated)}) ═══\n")
        for h in sorted(unvalidated, key=lambda x: x.confidence, reverse=True):
            print(f"[{h.confidence:.0%}] {h.content}")
            print(f"   Type: {h.type} | ID: {h.hypothesis_id[:12]}")
            print()
    
    elif args.dream_action == "top":
        top = engine.top_hypotheses(limit=5)
        if not top:
            print("✅ No hypotheses available")
            return
        
        print(f"═══ TOP {len(top)} HYPOTHESES ═══\n")
        for i, h in enumerate(top, 1):
            print(f"{i}. [{h.confidence:.0%}] {h.content}")
            print(f"   Outcome: {h.simulated_outcome}")
            print()
    
    elif args.dream_action == "validate":
        success = engine.validate_hypothesis(
            hypothesis_id=args.hypothesis_id,
            result=args.result,
            new_confidence=args.confidence,
        )
        if success:
            print(f"✅ Validated hypothesis {args.hypothesis_id[:12]}")
            print(f"   Result: {args.result}")
            if args.confidence:
                print(f"   New confidence: {args.confidence:.0%}")
        else:
            print(f"❌ Hypothesis not found: {args.hypothesis_id[:12]}")
    
    elif args.dream_action == "report":
        report = engine.report()
        print("═══ DREAMING REPORT ═══\n")
        print(f"Total hypotheses: {report['total_hypotheses']}")
        print(f"Unvalidated: {report['unvalidated']}")
        print(f"Validated: {report['validated']}")
        print(f"\nBy type:")
        for type_name, count in report["by_type"].items():
            print(f"  • {type_name}: {count}")
        print(f"\nTop hypotheses:")
        for i, h in enumerate(report["top_hypotheses"][:3], 1):
            print(f"  {i}. [{h['confidence']:.0%}] {h['content'][:60]}")


def cmd_causal(args):
    """Causal chain analysis — trace failures to root causes."""
    from netweaver.causal import CausalChainTracer
    
    tracer = CausalChainTracer()
    
    if args.causal_action == "trace":
        chain = tracer.trace_failure(args.test_name, args.error)
        print(tracer.format_chain(chain))
    
    elif args.causal_action == "error":
        chain = tracer.trace_error_pattern(args.error_text)
        print(tracer.format_chain(chain))
    
    elif args.causal_action == "batch":
        # Get recent test failures from daemon logs
        log_file = TINI / "logs" / "daemon.log"
        if not log_file.exists():
            print("❌ No daemon logs found")
            return
        
        try:
            # Parse recent test failures from logs
            failures = []
            with open(log_file, "r") as f:
                for line in f.readlines()[-100:]:  # Last 100 lines
                    if "test_fail" in line or "FAILED" in line:
                        # Extract test name and error
                        match = re.search(r"(test_\S+\.py::\S+)", line)
                        if match:
                            failures.append((match.group(1), line[:200]))
            
            if not failures:
                print("✅ No recent test failures found")
                return
            
            print(f"═══ BATCH TRACING {len(failures)} FAILURES ═══\n")
            chains = tracer.batch_trace(failures[:5])  # Limit to 5
            
            for i, chain in enumerate(chains, 1):
                print(f"{i}. {chain.failure[:60]}")
                print(f"   Root cause: {chain.root_cause}")
                print(f"   Confidence: {chain.confidence:.0%}")
                if chain.fix_suggestion:
                    print(f"   Fix: {chain.fix_suggestion}")
                print()
        except Exception as e:
            print(f"❌ Batch trace failed: {e}")


def cmd_competence(args):
    """Competence matrix — agent specialization tracking."""
    from netweaver.competence_matrix import CompetenceMatrix
    
    matrix = CompetenceMatrix()
    
    if args.comp_action == "team":
        report = matrix.team_report()
        print("═══ TEAM COMPETENCE REPORT ═══\n")
        print(f"Total agents: {report['total_agents']}")
        print(f"Total tasks: {report['total_tasks']}")
        if report['total_tasks'] > 0:
            print(f"Overall success: {report['overall_success_rate']:.0%}")
        
        if report["agents"]:
            print(f"\nAgents:")
            for agent_id, stats in report["agents"].items():
                specs = ", ".join(stats["specializations"]) if stats["specializations"] else "none"
                print(f"  • {agent_id}: {stats['success_rate']:.0%} success, {stats['total_tasks']} tasks")
                print(f"    Specializations: {specs}")
        
        if report["best_by_type"]:
            print(f"\nBest by task type:")
            for task_type, best in report["best_by_type"].items():
                print(f"  • {task_type}: {best['agent']} ({best['score']:.0%})")
    
    elif args.comp_action == "agent":
        agent = matrix.get_agent(args.agent_id)
        if not agent:
            print(f"❌ Agent not found: {args.agent_id}")
            return
        
        print(f"═══ AGENT: {agent.agent_id} ═══\n")
        print(f"Success rate: {agent.success_rate:.0%}")
        print(f"Total tasks: {agent.total_tasks}")
        print(f"Successful: {agent.successful_tasks}")
        print(f"Avg duration: {agent.avg_duration:.1f}s")
        print(f"Specializations: {', '.join(agent.specializations) if agent.specializations else 'none'}")
        
        if agent.task_type_stats:
            print(f"\nTask type performance:")
            for task_type, stats in sorted(agent.task_type_stats.items()):
                rate = stats["success"] / stats["total"] if stats["total"] > 0 else 0
                print(f"  • {task_type}: {rate:.0%} ({stats['success']}/{stats['total']})")
        
        if agent.file_familiarity:
            top_files = sorted(agent.file_familiarity.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"\nMost familiar files:")
            for file_path, count in top_files:
                print(f"  • {file_path}: {count} tasks")
    
    elif args.comp_action == "route":
        files = args.files.split(",") if args.files else []
        agent_id = matrix.route_task(args.task_type, files=files)
        
        if not agent_id:
            print(f"❌ No agents available for task type: {args.task_type}")
            return
        
        print(f"✅ Routed {args.task_type} task to: {agent_id}")
        
        # Show scores for all agents
        scores = matrix.route_with_scores(args.task_type, files=files)
        if scores:
            print(f"\nAll agents ranked:")
            for i, (aid, score) in enumerate(scores, 1):
                print(f"  {i}. {aid}: {score:.0%}")
    
    elif args.comp_action == "imbalances":
        imbalances = matrix.detect_imbalances()
        if not imbalances:
            print("✅ No workload imbalances detected")
            return
        
        print(f"═══ WORKLOAD IMBALANCES ({len(imbalances)}) ═══\n")
        for imb in imbalances:
            print(f"⚠️  {imb['agent_id']}: {imb['issue']}")
            print(f"   Tasks: {imb['tasks']} (avg: {imb['avg']:.1f}, ratio: {imb['ratio']:.2f}x)")
            print()
    
    elif args.comp_action == "record":
        matrix.record_simple(
            agent_id=args.agent_id,
            task_id=args.task_id,
            task_type=args.task_type,
            success=args.success,
            duration=args.duration,
        )
        status = "success" if args.success else "failure"
        print(f"✅ Recorded {status} for {args.agent_id} on {args.task_type} task {args.task_id}")
        
        # Show updated agent stats
        agent = matrix.get_agent(args.agent_id)
        if agent:
            print(f"   Agent success rate: {agent.success_rate:.0%} ({agent.successful_tasks}/{agent.total_tasks})")


def cmd_web_learn():
    """Run an autonomous web exploration cycle manually."""
    from netweaver.web_learner import AutonomousWebExplorer

    print("🌐 Running autonomous web exploration (headless)...\n")
    explorer = AutonomousWebExplorer(headless=True)

    try:
        results = explorer.explore_cycle()
        print(explorer.summary(results))
    finally:
        explorer.close()


def cmd_tasks(action: str):
    """Task scheduler commands."""
    from netweaver.task_scheduler import TaskScheduler
    from pathlib import Path

    scheduler = TaskScheduler(
        tasks_file=Path("netweaver/tasks.yaml"),
        state_dir=Path(".tini/task_scheduler"),
        headless=True,
    )

    try:
        if action == "run":
            print("🎯 Running due tasks...\n")
            results = scheduler.run_due_tasks()
            print(scheduler.format_results(results))
            
            changes = scheduler.detect_changes(results)
            if changes:
                print(f"\n⚡ Changes detected in {len(changes)} tasks:")
                for c in changes:
                    print(f"  - {c['task_id']}: {c['items_count']} items")
        
        elif action == "list":
            print("📋 Task definitions:\n")
            for task in scheduler.tasks:
                state = scheduler.state.get(task["id"])
                status = "never run" if not state else f"last={state.last_run[:19]}"
                print(f"  • {task['name']}")
                print(f"    ID: {task['id']}")
                print(f"    URL: {task['url']}")
                print(f"    Schedule: {task['schedule']}")
                print(f"    Status: {status}")
                print()
        
        elif action == "results":
            print("📊 Latest state:\n")
            for tid, state in scheduler.state.items():
                print(f"  {tid}:")
                print(f"    Last run: {state.last_run}")
                print(f"    Runs: {state.run_count}, Success: {state.success_count}")
                if state.last_error:
                    print(f"    Last error: {state.last_error[:80]}")
                print()
        
        else:
            print("Usage: netweaver tasks {run|list|results}")
    
    finally:
        scheduler.close()


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
    subparsers.add_parser("learn", help="Run web learning cycle (headless CloakBrowser)")

    # Task scheduler commands
    tasks_parser = subparsers.add_parser("tasks", help="Task scheduler — automated web monitoring")
    tasks_subparsers = tasks_parser.add_subparsers(dest="tasks_action")
    tasks_subparsers.add_parser("run", help="Run all due tasks now")
    tasks_subparsers.add_parser("list", help="Show task definitions and state")
    tasks_subparsers.add_parser("results", help="Show latest extraction results")
    
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
    
    # Epistemic OS subcommand
    ep_parser = subparsers.add_parser("ep", help="Epistemic OS — honest reasoning")
    ep_subparsers = ep_parser.add_subparsers(dest="ep_action", help="Epistemic action")
    
    ep_add = ep_subparsers.add_parser("add", help="Add knowledge with confidence")
    ep_add.add_argument("content", help="The knowledge content")
    ep_add.add_argument("--confidence", "-c", type=float, default=0.5, help="Confidence 0.0-1.0")
    ep_add.add_argument("--topic", "-t", help="Topic/category")
    ep_add.add_argument("--tags", help="Comma-separated tags")
    ep_add.add_argument("--context", help="Context/conditions")
    ep_add.add_argument("--source", "-s", help="Source (type:ref, e.g. benchmark:bench.py)")
    ep_add.add_argument("--decay", "-d", type=float, default=0.0, help="Decay rate per month")
    
    ep_query = ep_subparsers.add_parser("query", help="Query with honest uncertainty")
    ep_query.add_argument("query", help="Question to answer")
    
    ep_subparsers.add_parser("health", help="Show knowledge base health")
    ep_subparsers.add_parser("stale", help="Show stale/unreliable knowledge")
    ep_subparsers.add_parser("contradictions", help="Show unresolved contradictions")
    ep_subparsers.add_parser("recommend", help="Recommend what to verify next")
    
    ep_verify = ep_subparsers.add_parser("verify", help="Re-verify a piece of knowledge")
    ep_verify.add_argument("content", help="Knowledge content or ID")
    ep_verify.add_argument("--confidence", "-c", type=float, help="New confidence")
    
    ep_trace = ep_subparsers.add_parser("trace", help="Trace provenance chain")
    ep_trace.add_argument("content", help="Knowledge content or ID")
    
    ep_import = ep_subparsers.add_parser("import-memory", help="Import from Memory Palace")
    ep_import.add_argument("palace_file", help="Path to Memory Palace JSON file")
    
    ep_auto_verify = ep_subparsers.add_parser("auto-verify", help="Run full auto-verification cycle")
    
    # Dreaming subcommand
    dream_parser = subparsers.add_parser("dream", help="Dreaming — background hypothesis generation")
    dream_subparsers = dream_parser.add_subparsers(dest="dream_action", help="Dreaming action")
    
    dream_subparsers.add_parser("generate", help="Generate new hypotheses")
    dream_subparsers.add_parser("list", help="List all hypotheses")
    dream_subparsers.add_parser("top", help="Show top hypotheses by confidence")
    
    dream_validate = dream_subparsers.add_parser("validate", help="Validate a hypothesis")
    dream_validate.add_argument("hypothesis_id", help="Hypothesis ID to validate")
    dream_validate.add_argument("result", help="Validation result (confirmed/rejected)")
    dream_validate.add_argument("--confidence", "-c", type=float, help="New confidence score")
    
    dream_subparsers.add_parser("report", help="Generate dreaming report")
    
    # Causal Chain Analysis subcommand
    causal_parser = subparsers.add_parser("causal", help="Causal chain analysis — trace failures to root causes")
    causal_subparsers = causal_parser.add_subparsers(dest="causal_action", help="Causal action")
    
    causal_trace = causal_subparsers.add_parser("trace", help="Trace a test failure")
    causal_trace.add_argument("test_name", help="Test name (e.g., test_foo.py::test_bar)")
    causal_trace.add_argument("error", help="Error message")
    
    causal_error = causal_subparsers.add_parser("error", help="Trace a general error")
    causal_error.add_argument("error_text", help="Error text")
    
    causal_subparsers.add_parser("batch", help="Batch trace recent test failures")
    
    # Competence Matrix subcommand
    comp_parser = subparsers.add_parser("comp", help="Competence matrix — agent specialization tracking")
    comp_subparsers = comp_parser.add_subparsers(dest="comp_action", help="Competence action")
    
    comp_subparsers.add_parser("team", help="Show team competence report")
    
    comp_agent = comp_subparsers.add_parser("agent", help="Show agent competence")
    comp_agent.add_argument("agent_id", help="Agent ID")
    
    comp_route = comp_subparsers.add_parser("route", help="Route a task to best agent")
    comp_route.add_argument("task_type", help="Task type (architecture/bugfix/refactor/test/feature)")
    comp_route.add_argument("--files", help="Comma-separated file list")
    
    comp_subparsers.add_parser("imbalances", help="Detect workload imbalances")
    
    comp_record = comp_subparsers.add_parser("record", help="Record task outcome")
    comp_record.add_argument("agent_id", help="Agent ID")
    comp_record.add_argument("task_id", help="Task ID")
    comp_record.add_argument("task_type", help="Task type")
    comp_record.add_argument("--success", "-s", action="store_true", help="Mark as success")
    comp_record.add_argument("--duration", "-d", type=float, default=0, help="Duration in seconds")
    
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
    elif args.command == "learn":
        cmd_web_learn()
    elif args.command == "tasks":
        action = getattr(args, 'tasks_action', None) or "list"
        cmd_tasks(action)
    elif args.command == "kg":
        if hasattr(args, 'kg_action') and args.kg_action:
            cmd_kg(args)
        else:
            kg_parser.print_help()
    elif args.command == "ep":
        if hasattr(args, 'ep_action') and args.ep_action:
            cmd_epistemic(args)
        else:
            ep_parser.print_help()
    elif args.command == "dream":
        if hasattr(args, 'dream_action') and args.dream_action:
            cmd_dream(args)
        else:
            dream_parser.print_help()
    elif args.command == "causal":
        if hasattr(args, 'causal_action') and args.causal_action:
            cmd_causal(args)
        else:
            causal_parser.print_help()
    elif args.command == "comp":
        if hasattr(args, 'comp_action') and args.comp_action:
            cmd_competence(args)
        else:
            comp_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
