"""Cross-Project Knowledge Graph — Map your entire dev ecosystem.

Builds a graph of:
- Projects → Files → Modules → Classes/Functions
- Dependencies (imports)
- Patterns (similar code patterns across projects)
- Connections (shared libraries, similar structures)

Usage:
    kg = KnowledgeGraph()
    kg.scan_project("/path/to/project")
    kg.analyze_patterns()
    kg.visualize(output="graph.md")
"""

import ast
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
import json


@dataclass
class CodeEntity:
    """Base class for code entities (modules, classes, functions)."""
    name: str
    path: Path
    project: str
    loc: int = 0  # lines of code
    dependencies: Set[str] = field(default_factory=set)
    metadata: Dict = field(default_factory=dict)
    
    @property
    def id(self) -> str:
        """Unique ID for this entity."""
        return f"{self.project}:{self.path}:{self.name}"


@dataclass
class Module(CodeEntity):
    """Python module."""
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    imports: Set[str] = field(default_factory=set)


@dataclass
class Project:
    """A project in the knowledge graph."""
    name: str
    path: Path
    modules: Dict[str, Module] = field(default_factory=dict)
    total_loc: int = 0
    languages: Set[str] = field(default_factory=set)
    dependencies: Set[str] = field(default_factory=set)
    _module_count: int = 0  # Cached count for when modules dict is not loaded
    
    @property
    def module_count(self) -> int:
        return len(self.modules) if self.modules else self._module_count


class KnowledgeGraph:
    """Cross-project knowledge graph."""
    
    def __init__(self):
        self.projects: Dict[str, Project] = {}
        self.cross_project_patterns: List[Dict] = []
        self.shared_libraries: Dict[str, Set[str]] = defaultdict(set)  # lib -> projects using it
    
    def scan_project(self, project_path: str) -> Project:
        """Scan a project and add it to the graph."""
        path = Path(project_path)
        if not path.exists():
            raise ValueError(f"Project path does not exist: {project_path}")
        
        project_name = path.name
        project = Project(name=project_name, path=path)
        
        # Scan Python files
        for py_file in path.rglob("*.py"):
            if self._should_skip(py_file):
                continue
            
            module = self._parse_module(py_file, project_name)
            if module:
                project.modules[str(py_file.relative_to(path))] = module
                project.total_loc += module.loc
                project.languages.add("python")
                
                # Track external dependencies
                for imp in module.imports:
                    if not imp.startswith('.') and not imp.startswith(project_name):
                        project.dependencies.add(imp.split('.')[0])
                        self.shared_libraries[imp.split('.')[0]].add(project_name)
        
        # Cache module count
        project._module_count = len(project.modules)
        
        self.projects[project_name] = project
        return project
    
    def _should_skip(self, path: Path) -> bool:
        """Check if file should be skipped."""
        skip_dirs = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'build', 'dist'}
        for part in path.parts:
            if part in skip_dirs:
                return True
        return False
    
    def _parse_module(self, path: Path, project_name: str) -> Optional[Module]:
        """Parse a Python module and extract structure."""
        try:
            code = path.read_text(encoding='utf-8', errors='ignore')
            tree = ast.parse(code)
            
            module = Module(
                name=path.stem,
                path=path,
                project=project_name,
                loc=len(code.splitlines())
            )
            
            # Extract imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module.imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module.imports.add(node.module)
                
                # Extract classes and functions
                elif isinstance(node, ast.ClassDef):
                    module.classes.append(node.name)
                elif isinstance(node, ast.FunctionDef):
                    module.functions.append(node.name)
            
            return module
            
        except (SyntaxError, UnicodeDecodeError, OSError):
            return None
    
    def analyze_patterns(self) -> List[Dict]:
        """Find cross-project patterns and similarities."""
        patterns = []
        
        # 1. Shared libraries
        for lib, projects in self.shared_libraries.items():
            if len(projects) >= 2:
                patterns.append({
                    'type': 'shared_library',
                    'library': lib,
                    'projects': list(projects),
                    'count': len(projects)
                })
        
        # 2. Similar module structures
        module_signatures = defaultdict(list)
        for project in self.projects.values():
            for mod in project.modules.values():
                # Create signature: (num_classes, num_functions, num_imports)
                sig = (len(mod.classes), len(mod.functions), len(mod.imports))
                module_signatures[sig].append((project.name, mod.name))
        
        for sig, modules in module_signatures.items():
            if len(modules) >= 3 and sig[0] + sig[1] > 0:  # At least 3 similar modules with content
                patterns.append({
                    'type': 'similar_structure',
                    'signature': sig,
                    'modules': modules[:10],  # Limit to 10 examples
                    'count': len(modules)
                })
        
        # 3. Common design patterns
        pattern_counts = defaultdict(lambda: defaultdict(int))
        for project in self.projects.values():
            for mod in project.modules.values():
                # Heuristics for design patterns
                code = mod.path.read_text(encoding='utf-8', errors='ignore') if mod.path.exists() else ""
                
                if re.search(r'class\s+\w*Factory', code) or 'Factory' in mod.name:
                    pattern_counts['Factory'][project.name] += 1
                if re.search(r'class\s+\w*Singleton', code) or 'singleton' in code.lower():
                    pattern_counts['Singleton'][project.name] += 1
                if '@dataclass' in code or 'from dataclasses' in code:
                    pattern_counts['Dataclass'][project.name] += 1
                if 'async def' in code:
                    pattern_counts['Async'][project.name] += 1
                if 'abstractmethod' in code or 'ABC' in code:
                    pattern_counts['Abstract'][project.name] += 1
        
        for pattern, project_counts in pattern_counts.items():
            # Report patterns that appear in at least 1 project (with at least 1 occurrence)
            if sum(project_counts.values()) >= 1:
                patterns.append({
                    'type': 'design_pattern',
                    'pattern': pattern,
                    'projects': dict(project_counts),
                    'count': sum(project_counts.values())
                })
        
        self.cross_project_patterns = patterns
        return patterns
    
    def suggest_cross_pollination(self) -> List[Dict]:
        """Suggest code that could be shared across projects."""
        suggestions = []
        
        # Find modules with similar names across projects
        name_to_modules = defaultdict(list)
        for project in self.projects.values():
            for mod_path, mod in project.modules.items():
                name_to_modules[mod.name].append((project.name, mod_path))
        
        for name, modules in name_to_modules.items():
            if len(modules) >= 2:
                suggestions.append({
                    'type': 'similar_module',
                    'name': name,
                    'locations': modules,
                    'suggestion': f"Consider extracting {name} to a shared library"
                })
        
        # Find heavily-used libraries that could be standardized
        for lib, projects in self.shared_libraries.items():
            if len(projects) >= 3:
                suggestions.append({
                    'type': 'standardize_library',
                    'library': lib,
                    'projects': list(projects),
                    'suggestion': f"Standardize {lib} usage across {len(projects)} projects"
                })
        
        return suggestions
    
    def visualize(self, output_path: Optional[str] = None) -> str:
        """Generate Mermaid visualization of the knowledge graph."""
        lines = [
            "```mermaid",
            "graph TD",
        ]
        
        # Add projects
        for project in self.projects.values():
            lines.append(f"    {project.name}[{project.name}<br/>{project.module_count} modules<br/>{project.total_loc} LOC]")
            lines.append(f"    style {project.name} fill:#e1f5ff")
        
        # Add shared libraries
        for lib, projects in sorted(self.shared_libraries.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
            if len(projects) >= 2:
                lib_id = f"lib_{lib.replace('-', '_').replace('.', '_')}"
                lines.append(f"    {lib_id}({lib})")
                lines.append(f"    style {lib_id} fill:#fff4e1")
                
                for proj in list(projects)[:5]:  # Limit connections
                    lines.append(f"    {proj} --> {lib_id}")
        
        lines.append("```")
        
        # Add statistics
        lines.extend([
            "",
            "## Statistics",
            f"- **Projects:** {len(self.projects)}",
            f"- **Total modules:** {sum(p.module_count for p in self.projects.values())}",
            f"- **Total LOC:** {sum(p.total_loc for p in self.projects.values()):,}",
            f"- **Cross-project patterns:** {len(self.cross_project_patterns)}",
            "",
        ])
        
        # Add patterns
        if self.cross_project_patterns:
            lines.append("## Patterns Found")
            for pattern in self.cross_project_patterns[:10]:
                if pattern['type'] == 'shared_library':
                    lines.append(f"- **Shared library:** {pattern['library']} (used by {pattern['count']} projects)")
                elif pattern['type'] == 'design_pattern':
                    lines.append(f"- **Design pattern:** {pattern['pattern']} ({pattern['count']} occurrences)")
        
        content = '\n'.join(lines)
        
        if output_path:
            Path(output_path).write_text(content)
        
        return content
    
    def query(self, query: str) -> List[Dict]:
        """Query the knowledge graph."""
        results = []
        query_lower = query.lower()
        
        # Search projects
        for project in self.projects.values():
            if query_lower in project.name.lower():
                results.append({
                    'type': 'project',
                    'name': project.name,
                    'path': str(project.path),
                    'modules': project.module_count,
                    'loc': project.total_loc
                })
            
            # Search modules
            for mod_path, mod in project.modules.items():
                if query_lower in mod.name.lower() or query_lower in mod_path.lower():
                    results.append({
                        'type': 'module',
                        'project': project.name,
                        'path': mod_path,
                        'name': mod.name,
                        'classes': len(mod.classes),
                        'functions': len(mod.functions)
                    })
        
        return results[:20]  # Limit results
    
    def to_json(self) -> str:
        """Serialize knowledge graph to JSON."""
        data = {
            'projects': {
                name: {
                    'path': str(proj.path),
                    'modules': {
                        mod_name: {
                            'name': mod.name,
                            'path': str(mod.path),
                            'loc': mod.loc,
                            'classes': mod.classes,
                            'functions': mod.functions,
                            'imports': list(mod.imports)
                        }
                        for mod_name, mod in proj.modules.items()
                    },
                    'total_loc': proj.total_loc,
                    'languages': list(proj.languages),
                    'dependencies': list(proj.dependencies)
                }
                for name, proj in self.projects.items()
            },
            'shared_libraries': {
                lib: list(projects)
                for lib, projects in self.shared_libraries.items()
            },
            'patterns': self.cross_project_patterns
        }
        return json.dumps(data, indent=2)
    
    def save(self, path: str):
        """Save knowledge graph to file."""
        Path(path).write_text(self.to_json())
    
    def load(self, path: str):
        """Load knowledge graph from file."""
        data = json.loads(Path(path).read_text())
        
        for name, proj_data in data.get('projects', {}).items():
            project = Project(
                name=name,
                path=Path(proj_data['path']),
                total_loc=proj_data.get('total_loc', proj_data.get('loc', 0)),
                languages=set(proj_data['languages']),
                dependencies=set(proj_data['dependencies'])
            )
            
            # Reconstruct modules if they exist
            if 'modules' in proj_data and isinstance(proj_data['modules'], dict):
                for mod_name, mod_data in proj_data['modules'].items():
                    module = Module(
                        name=mod_data['name'],
                        path=Path(mod_data['path']),
                        project=name,
                        loc=mod_data['loc'],
                        classes=mod_data.get('classes', []),
                        functions=mod_data.get('functions', []),
                        imports=set(mod_data.get('imports', []))
                    )
                    project.modules[mod_name] = module
            
            # Set module count for backward compatibility
            project._module_count = proj_data.get('_module_count', len(project.modules))
            self.projects[name] = project
        
        for lib, projects in data.get('shared_libraries', {}).items():
            self.shared_libraries[lib] = set(projects)
        
        self.cross_project_patterns = data.get('patterns', [])
