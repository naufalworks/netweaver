#!/usr/bin/env python3
"""Knowledge Graph CLI — Query and visualize your project ecosystem."""

import argparse
import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from netweaver.knowledge_graph import KnowledgeGraph


def cmd_scan(args):
    """Scan projects and build knowledge graph."""
    print("═══ SCANNING PROJECTS ═══\n")
    
    kg = KnowledgeGraph()
    
    # Default workspace
    workspace = Path(args.workspace) if args.workspace else Path.home() / "Documents"
    
    # Find all git projects
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
    
    # Analyze patterns
    print("\nAnalyzing patterns...")
    patterns = kg.analyze_patterns()
    print(f"Found {len(patterns)} cross-project patterns")
    
    # Save graph
    if args.output:
        output_path = Path(args.output)
        kg.save(str(output_path))
        print(f"\nSaved to: {output_path}")
    
    return kg


def cmd_visualize(args):
    """Generate Mermaid visualization."""
    print("═══ GENERATING VISUALIZATION ═══\n")
    
    # Load or scan
    if args.input:
        kg = KnowledgeGraph()
        kg.load(args.input)
        print(f"Loaded from: {args.input}")
    else:
        kg = cmd_scan(args)
    
    # Generate visualization
    viz = kg.visualize(output_path=args.output)
    
    if args.output:
        print(f"\nVisualization saved to: {args.output}")
    else:
        print("\n" + viz)


def cmd_query(args):
    """Query the knowledge graph."""
    if not args.input:
        print("Error: --input required for query command", file=sys.stderr)
        sys.exit(1)
    
    kg = KnowledgeGraph()
    kg.load(args.input)
    
    results = kg.query(args.query)
    
    if not results:
        print(f"No results for: {args.query}")
        return
    
    print(f"═══ RESULTS ({len(results)}) ═══\n")
    
    for r in results:
        if r['type'] == 'project':
            print(f"Project: {r['name']}")
            print(f"  Path: {r['path']}")
            print(f"  Modules: {r['modules']}, LOC: {r['loc']:,}")
        elif r['type'] == 'module':
            print(f"Module: {r['name']} ({r['project']})")
            print(f"  Path: {r['path']}")
            print(f"  Classes: {r['classes']}, Functions: {r['functions']}")
        print()


def cmd_patterns(args):
    """Show cross-project patterns."""
    if not args.input:
        print("Error: --input required for patterns command", file=sys.stderr)
        sys.exit(1)
    
    kg = KnowledgeGraph()
    kg.load(args.input)
    
    if not kg.cross_project_patterns:
        kg.analyze_patterns()
    
    print("═══ CROSS-PROJECT PATTERNS ═══\n")
    
    # Shared libraries
    shared = [p for p in kg.cross_project_patterns if p['type'] == 'shared_library']
    if shared:
        print("Shared Libraries:")
        for p in sorted(shared, key=lambda x: x['count'], reverse=True)[:10]:
            projects = ", ".join(p['projects'][:3])
            if len(p['projects']) > 3:
                projects += f" (+{len(p['projects'])-3} more)"
            print(f"  • {p['library']}: {p['count']} projects ({projects})")
        print()
    
    # Design patterns
    patterns = [p for p in kg.cross_project_patterns if p['type'] == 'design_pattern']
    if patterns:
        print("Design Patterns:")
        for p in sorted(patterns, key=lambda x: x['count'], reverse=True):
            projects = ", ".join(list(p['projects'].keys())[:3])
            print(f"  • {p['pattern']}: {p['count']} occurrences ({projects})")
        print()
    
    # Similar structures
    similar = [p for p in kg.cross_project_patterns if p['type'] == 'similar_structure']
    if similar:
        print("Similar Module Structures:")
        for p in similar[:5]:
            sig = p['signature']
            print(f"  • {sig[0]} classes, {sig[1]} functions, {sig[2]} imports: {p['count']} modules")
        print()


def cmd_suggest(args):
    """Show cross-pollination suggestions."""
    if not args.input:
        print("Error: --input required for suggest command", file=sys.stderr)
        sys.exit(1)
    
    kg = KnowledgeGraph()
    kg.load(args.input)
    
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
            print(f"  💡 {s['suggestion']}")
        elif s['type'] == 'standardize_library':
            print(f"Standardize library: {s['library']}")
            print(f"  Used by {len(s['projects'])} projects: {', '.join(s['projects'])}")
            print(f"  💡 {s['suggestion']}")
        print()


def cmd_stats(args):
    """Show knowledge graph statistics."""
    if not args.input:
        print("Error: --input required for stats command", file=sys.stderr)
        sys.exit(1)
    
    kg = KnowledgeGraph()
    kg.load(args.input)
    
    print("═══ KNOWLEDGE GRAPH STATISTICS ═══\n")
    
    print(f"Projects: {len(kg.projects)}")
    total_modules = sum(p.module_count for p in kg.projects.values())
    total_loc = sum(p.total_loc for p in kg.projects.values())
    print(f"Total modules: {total_modules:,}")
    print(f"Total LOC: {total_loc:,}")
    print()
    
    print("Projects:")
    for name, proj in sorted(kg.projects.items(), key=lambda x: x[1].total_loc, reverse=True):
        print(f"  • {name}: {proj.module_count} modules, {proj.total_loc:,} LOC")
    print()
    
    print(f"Shared libraries: {len(kg.shared_libraries)}")
    print(f"Cross-project patterns: {len(kg.cross_project_patterns)}")


def main():
    parser = argparse.ArgumentParser(
        description="Knowledge Graph CLI — Map your project ecosystem",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan all projects in ~/Documents and save graph
  python knowledge_graph_cli.py scan --output graph.json
  
  # Generate visualization
  python knowledge_graph_cli.py visualize --input graph.json --output graph.md
  
  # Query for modules
  python knowledge_graph_cli.py query --input graph.json daemon
  
  # Show patterns
  python knowledge_graph_cli.py patterns --input graph.json
  
  # Show suggestions
  python knowledge_graph_cli.py suggest --input graph.json
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Scan command
    scan_parser = subparsers.add_parser('scan', help='Scan projects and build knowledge graph')
    scan_parser.add_argument('--workspace', help='Workspace directory (default: ~/Documents)')
    scan_parser.add_argument('--output', '-o', help='Output JSON file')
    scan_parser.set_defaults(func=cmd_scan)
    
    # Visualize command
    viz_parser = subparsers.add_parser('visualize', help='Generate Mermaid visualization')
    viz_parser.add_argument('--input', '-i', help='Input JSON file')
    viz_parser.add_argument('--output', '-o', help='Output markdown file')
    viz_parser.add_argument('--workspace', help='Workspace directory (if no input)')
    viz_parser.set_defaults(func=cmd_visualize)
    
    # Query command
    query_parser = subparsers.add_parser('query', help='Query the knowledge graph')
    query_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
    query_parser.add_argument('query', help='Search query')
    query_parser.set_defaults(func=cmd_query)
    
    # Patterns command
    patterns_parser = subparsers.add_parser('patterns', help='Show cross-project patterns')
    patterns_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
    patterns_parser.set_defaults(func=cmd_patterns)
    
    # Suggest command
    suggest_parser = subparsers.add_parser('suggest', help='Show cross-pollination suggestions')
    suggest_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
    suggest_parser.set_defaults(func=cmd_suggest)
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show knowledge graph statistics')
    stats_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
    stats_parser.set_defaults(func=cmd_stats)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == '__main__':
    main()
