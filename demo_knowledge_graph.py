#!/usr/bin/env python3
"""
Knowledge Graph Demo Script
Showcases the cross-project knowledge graph functionality.
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from netweaver.knowledge_graph import KnowledgeGraph


def print_header(text):
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def main():
    print_header("Knowledge Graph Demo")
    print("This demo shows how to use the cross-project knowledge graph")
    print("to analyze your development ecosystem.\n")
    
    # Initialize knowledge graph
    kg = KnowledgeGraph()
    workspace = Path.home() / "Documents"
    
    # Step 1: Scan projects
    print_header("Step 1: Scanning Projects")
    print(f"Scanning all Git repositories in {workspace}...\n")
    
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
    
    # Step 2: Analyze patterns
    print_header("Step 2: Analyzing Cross-Project Patterns")
    print("Finding shared libraries, design patterns, and similarities...\n")
    
    patterns = kg.analyze_patterns()
    print(f"Found {len(patterns)} cross-project patterns\n")
    
    # Show shared libraries
    shared_libs = [p for p in patterns if p['type'] == 'shared_library']
    if shared_libs:
        print("Shared Libraries (used by 3+ projects):")
        for p in sorted(shared_libs, key=lambda x: x['count'], reverse=True)[:10]:
            projects = ", ".join(p['projects'][:3])
            if len(p['projects']) > 3:
                projects += f" (+{len(p['projects'])-3} more)"
            print(f"  • {p['library']}: {p['count']} projects ({projects})")
        print()
    
    # Show design patterns
    design_patterns = [p for p in patterns if p['type'] == 'design_pattern']
    if design_patterns:
        print("Design Patterns:")
        for p in sorted(design_patterns, key=lambda x: x['count'], reverse=True):
            projects = ", ".join(list(p['projects'].keys())[:3])
            print(f"  • {p['pattern']}: {p['count']} occurrences ({projects})")
        print()
    
    # Step 3: Get suggestions
    print_header("Step 3: Cross-Pollination Suggestions")
    print("Finding opportunities for code reuse...\n")
    
    suggestions = kg.suggest_cross_pollination()
    if suggestions:
        for i, s in enumerate(suggestions[:5], 1):
            print(f"{i}. {s['suggestion']}")
            if s['type'] == 'similar_module':
                print(f"   Module: {s['name']}")
                print(f"   Found in: {', '.join(p for p, _ in s['locations'][:3])}")
            elif s['type'] == 'standardize_library':
                print(f"   Library: {s['library']}")
                print(f"   Used by: {', '.join(s['projects'][:3])}")
            print()
    else:
        print("No suggestions found.\n")
    
    # Step 4: Generate visualization
    print_header("Step 4: Generate Visualization")
    output_path = Path(".tini/knowledge_graph_demo.md")
    print(f"Generating Mermaid diagram to {output_path}...\n")
    
    viz = kg.visualize(output_path=str(output_path))
    print(f"✓ Visualization saved to {output_path}")
    print("\nFirst 30 lines of visualization:")
    print("-" * 70)
    for line in viz.split('\n')[:30]:
        print(line)
    print("-" * 70)
    
    # Step 5: Query examples
    print_header("Step 5: Query Examples")
    
    # Query for projects
    print("\nQuery: 'myhermes'")
    results = kg.query("myhermes")
    for r in results[:3]:
        if r['type'] == 'project':
            print(f"  Project: {r['name']}")
            print(f"    Modules: {r['modules']}, LOC: {r['loc']:,}")
    
    # Query for common module names
    print("\nQuery: 'test'")
    results = kg.query("test")
    if results:
        print(f"  Found {len(results)} results:")
        for r in results[:5]:
            if r['type'] == 'module':
                print(f"    - {r['name']} in {r['project']}")
    else:
        print("  No results")
    
    # Step 6: Statistics
    print_header("Step 6: Project Statistics")
    
    total_modules = sum(p.module_count for p in kg.projects.values())
    total_loc = sum(p.total_loc for p in kg.projects.values())
    
    print(f"Total Projects: {len(kg.projects)}")
    print(f"Total Modules: {total_modules:,}")
    print(f"Total Lines of Code: {total_loc:,}\n")
    
    print("Projects by size:")
    for name, proj in sorted(kg.projects.items(), key=lambda x: x[1].total_loc, reverse=True):
        if proj.total_loc > 0:
            print(f"  • {name}: {proj.module_count} modules, {proj.total_loc:,} LOC")
    
    # Step 7: Save knowledge graph
    print_header("Step 7: Save Knowledge Graph")
    kg_path = Path(".tini/knowledge_graph_demo.json")
    kg.save(str(kg_path))
    print(f"✓ Knowledge graph saved to {kg_path}")
    print(f"  You can reload it later with: kg.load('{kg_path}')")
    
    print_header("Demo Complete!")
    print("Next steps:")
    print("  1. Open .tini/knowledge_graph_demo.md to see the visualization")
    print("  2. Use 'netweaver kg patterns' to explore patterns")
    print("  3. Use 'netweaver kg suggest' to find reuse opportunities")
    print("  4. Use 'netweaver kg query <term>' to search")
    print()


if __name__ == "__main__":
    main()
