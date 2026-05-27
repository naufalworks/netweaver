# Knowledge Graph CLI — Query and visualize your project ecosystem

A cross-project knowledge graph that maps your entire development workspace, finding patterns, shared dependencies, and opportunities for code reuse.

## Features

- **Multi-project scanning** — Automatically discovers and analyzes all Git repositories
- **Pattern detection** — Finds shared libraries, design patterns, and similar structures
- **Cross-pollination suggestions** — Identifies code that could be extracted to shared libraries
- **Mermaid visualization** — Generates beautiful dependency graphs
- **JSON persistence** — Save and load knowledge graphs for fast queries
- **Rich CLI** — Multiple commands for different use cases

## Installation

The knowledge graph is part of the NetWeaver package. Ensure you have the required dependencies:

```bash
pip install rich
```

## Usage

### Scan Projects

Scan all Git repositories in your workspace and build the knowledge graph:

```bash
# Scan ~/Documents (default)
python netweaver/knowledge_graph_cli.py scan --output .tini/knowledge_graph.json

# Scan specific workspace
python netweaver/knowledge_graph_cli.py scan --workspace ~/projects --output kg.json
```

### Generate Visualization

Create a Mermaid diagram showing projects and shared libraries:

```bash
# Generate and display
python netweaver/knowledge_graph_cli.py visualize --input .tini/knowledge_graph.json

# Save to file
python netweaver/knowledge_graph_cli.py visualize --input kg.json --output graph.md
```

### Query

Search for projects, modules, or files:

```bash
python netweaver/knowledge_graph_cli.py query --input kg.json daemon
python netweaver/knowledge_graph_cli.py query --input kg.json utils
```

### Analyze Patterns

Find cross-project patterns and similarities:

```bash
python netweaver/knowledge_graph_cli.py patterns --input kg.json
```

Output includes:
- **Shared libraries** — Libraries used by multiple projects
- **Design patterns** — Common patterns (Async, Dataclass, Singleton, etc.)
- **Similar structures** — Modules with similar class/function/import counts

### Get Suggestions

Discover opportunities for code reuse:

```bash
python netweaver/knowledge_graph_cli.py suggest --input kg.json
```

Output includes:
- Similar modules across projects (candidates for shared libraries)
- Libraries that could be standardized across projects

### View Statistics

See an overview of your project ecosystem:

```bash
python netweaver/knowledge_graph_cli.py stats --input kg.json
```

## Programmatic API

```python
from netweaver.knowledge_graph import KnowledgeGraph

# Build knowledge graph
kg = KnowledgeGraph()
kg.scan_project("/path/to/project1")
kg.scan_project("/path/to/project2")

# Analyze patterns
patterns = kg.analyze_patterns()

# Query
results = kg.query("daemon")

# Get suggestions
suggestions = kg.suggest_cross_pollination()

# Save/load
kg.save("knowledge_graph.json")
kg.load("knowledge_graph.json")

# Generate visualization
viz = kg.visualize(output_path="graph.md")
```

## Example Output

### Patterns

```
═══ CROSS-PROJECT PATTERNS ═══

Shared Libraries:
  • sys: 6 projects (morpheus-evolution-lab, Kiro-Multi-Agent-System, flowhunter)
  • asyncio: 5 projects (morpheus-evolution-lab, Kiro-Multi-Agent-System, memtxt)
  • json: 6 projects (morpheus-evolution-lab, Kiro-Multi-Agent-System, flowhunter)

Design Patterns:
  • Async: 38 occurrences (Kiro-Multi-Agent-System, flowhunter, hermes)
  • Dataclass: 20 occurrences (Kiro-Multi-Agent-System, myhermes)
  • Singleton: 4 occurrences (memtxt, myhermes)
```

### Suggestions

```
═══ CROSS-POLLINATION SUGGESTIONS ═══

Similar module: utils
  - proj1: utils.py
  - proj2: utils.py
  💡 Consider extracting utils to a shared library

Standardize library: pytest
  Used by 3 projects: Kiro-Multi-Agent-System, memtxt, myhermes
  💡 Standardize pytest usage across 3 projects
```

## Architecture

- **CodeEntity** — Base class for code elements (modules, classes, functions)
- **Module** — Python module with imports, classes, functions
- **Project** — Collection of modules with metadata
- **KnowledgeGraph** — Main class that scans, analyzes, and queries

## Testing

Run the test suite:

```bash
pytest tests/test_knowledge_graph.py -v
```

All 20 tests cover:
- Project scanning and module parsing
- Pattern detection (shared libraries, design patterns)
- Cross-pollination suggestions
- Visualization generation
- Query functionality
- JSON serialization/deserialization
- Edge cases (empty projects, syntax errors)

## Future Enhancements

Potential additions:
- **Incremental updates** — Only rescan changed files
- **Dependency depth** — Track transitive dependencies
- **Code similarity** — Use embeddings to find semantically similar code
- **Web dashboard** — Interactive visualization with filters
- **Git integration** — Track how the graph evolves over time
- **Import cycles** — Detect circular dependencies across projects

## License

Part of the NetWeaver project.
