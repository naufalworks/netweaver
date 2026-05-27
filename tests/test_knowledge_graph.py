"""Tests for Cross-Project Knowledge Graph."""

import json
import tempfile
from pathlib import Path
import pytest

from netweaver.knowledge_graph import KnowledgeGraph, Module, Project, CodeEntity


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project structure for testing."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    
    # Create .git directory to mark as project
    (project_dir / ".git").mkdir()
    
    # Create some Python files
    (project_dir / "main.py").write_text("""
import os
import sys
from pathlib import Path

class MainApp:
    def __init__(self):
        self.name = "test"
    
    def run(self):
        print("running")

def helper():
    pass
""")
    
    (project_dir / "utils.py").write_text("""
import json
from dataclasses import dataclass

@dataclass
class Config:
    name: str
    value: int

def load_config():
    pass
""")
    
    # Create a subdirectory with more files
    sub_dir = project_dir / "lib"
    sub_dir.mkdir()
    
    (sub_dir / "core.py").write_text("""
import asyncio
from abc import ABC, abstractmethod

class BaseService(ABC):
    @abstractmethod
    def start(self):
        pass

async def async_helper():
    await asyncio.sleep(1)
""")
    
    return project_dir


def test_scan_project(temp_project):
    """Test scanning a project."""
    kg = KnowledgeGraph()
    project = kg.scan_project(str(temp_project))
    
    assert project.name == "test_project"
    assert project.module_count == 3
    assert project.total_loc > 0
    assert "python" in project.languages


def test_scan_project_modules(temp_project):
    """Test that modules are parsed correctly."""
    kg = KnowledgeGraph()
    project = kg.scan_project(str(temp_project))
    
    # Check main.py
    main_mod = project.modules.get("main.py")
    assert main_mod is not None
    assert "MainApp" in main_mod.classes
    assert "helper" in main_mod.functions
    assert "os" in main_mod.imports
    assert "sys" in main_mod.imports
    
    # Check utils.py
    utils_mod = project.modules.get("utils.py")
    assert utils_mod is not None
    assert "Config" in utils_mod.classes
    assert "load_config" in utils_mod.functions


def test_scan_project_dependencies(temp_project):
    """Test that dependencies are tracked."""
    kg = KnowledgeGraph()
    project = kg.scan_project(str(temp_project))
    
    # Should track external dependencies
    assert "json" in project.dependencies or "asyncio" in project.dependencies


def test_skip_directories(temp_project):
    """Test that certain directories are skipped."""
    kg = KnowledgeGraph()
    
    # Create files in directories that should be skipped
    (temp_project / "__pycache__").mkdir()
    (temp_project / "__pycache__" / "cached.py").write_text("x = 1")
    
    (temp_project / "venv").mkdir()
    (temp_project / "venv" / "lib.py").write_text("y = 2")
    
    project = kg.scan_project(str(temp_project))
    
    # Should only have 3 modules (main, utils, lib/core)
    assert project.module_count == 3


def test_analyze_patterns_shared_libraries(tmp_path):
    """Test finding shared libraries across projects."""
    kg = KnowledgeGraph()
    
    # Create two projects that both use 'requests'
    proj1 = tmp_path / "proj1"
    proj1.mkdir()
    (proj1 / ".git").mkdir()
    (proj1 / "main.py").write_text("import requests")
    
    proj2 = tmp_path / "proj2"
    proj2.mkdir()
    (proj2 / ".git").mkdir()
    (proj2 / "main.py").write_text("import requests")
    
    kg.scan_project(str(proj1))
    kg.scan_project(str(proj2))
    
    patterns = kg.analyze_patterns()
    
    # Should find 'requests' as shared library
    shared_libs = [p for p in patterns if p['type'] == 'shared_library']
    assert any(p['library'] == 'requests' for p in shared_libs)


def test_analyze_patterns_design_patterns(temp_project):
    """Test finding design patterns."""
    kg = KnowledgeGraph()
    kg.scan_project(str(temp_project))
    patterns = kg.analyze_patterns()
    
    # Should find Dataclass pattern (utils.py uses @dataclass)
    design_patterns = [p for p in patterns if p['type'] == 'design_pattern']
    assert any(p['pattern'] == 'Dataclass' for p in design_patterns)
    
    # Should find Async pattern (lib/core.py uses async def)
    assert any(p['pattern'] == 'Async' for p in design_patterns)
    
    # Should find Abstract pattern (lib/core.py uses ABC)
    assert any(p['pattern'] == 'Abstract' for p in design_patterns)


def test_suggest_cross_pollination(tmp_path):
    """Test cross-pollination suggestions."""
    kg = KnowledgeGraph()
    
    # Create two projects with similarly-named modules
    proj1 = tmp_path / "proj1"
    proj1.mkdir()
    (proj1 / ".git").mkdir()
    (proj1 / "utils.py").write_text("def helper(): pass")
    
    proj2 = tmp_path / "proj2"
    proj2.mkdir()
    (proj2 / ".git").mkdir()
    (proj2 / "utils.py").write_text("def helper(): pass")
    
    kg.scan_project(str(proj1))
    kg.scan_project(str(proj2))
    
    suggestions = kg.suggest_cross_pollination()
    
    # Should suggest extracting utils to shared library
    assert any(s['type'] == 'similar_module' and s['name'] == 'utils' for s in suggestions)


def test_visualize(temp_project):
    """Test Mermaid visualization generation."""
    kg = KnowledgeGraph()
    kg.scan_project(str(temp_project))
    kg.analyze_patterns()
    
    viz = kg.visualize()
    
    assert "```mermaid" in viz
    assert "graph TD" in viz
    assert "test_project" in viz
    assert "Statistics" in viz


def test_visualize_to_file(temp_project, tmp_path):
    """Test saving visualization to file."""
    kg = KnowledgeGraph()
    kg.scan_project(str(temp_project))
    
    output_file = tmp_path / "graph.md"
    kg.visualize(output_path=str(output_file))
    
    assert output_file.exists()
    content = output_file.read_text()
    assert "mermaid" in content


def test_query_projects(temp_project):
    """Test querying for projects."""
    kg = KnowledgeGraph()
    kg.scan_project(str(temp_project))
    
    results = kg.query("test_project")
    
    assert len(results) > 0
    assert any(r['type'] == 'project' and r['name'] == 'test_project' for r in results)


def test_query_modules(temp_project):
    """Test querying for modules."""
    kg = KnowledgeGraph()
    kg.scan_project(str(temp_project))
    
    results = kg.query("utils")
    
    assert len(results) > 0
    assert any(r['type'] == 'module' and r['name'] == 'utils' for r in results)


def test_query_no_results(temp_project):
    """Test query with no matches."""
    kg = KnowledgeGraph()
    kg.scan_project(str(temp_project))
    
    results = kg.query("nonexistent_xyz_123")
    
    assert len(results) == 0


def test_to_json(temp_project):
    """Test JSON serialization."""
    kg = KnowledgeGraph()
    kg.scan_project(str(temp_project))
    kg.analyze_patterns()
    
    json_str = kg.to_json()
    data = json.loads(json_str)
    
    assert 'projects' in data
    assert 'test_project' in data['projects']
    assert 'shared_libraries' in data
    assert 'patterns' in data


def test_save_and_load(temp_project, tmp_path):
    """Test saving and loading knowledge graph."""
    kg = KnowledgeGraph()
    kg.scan_project(str(temp_project))
    kg.analyze_patterns()
    
    # Save
    save_path = tmp_path / "kg.json"
    kg.save(str(save_path))
    assert save_path.exists()
    
    # Load into new instance
    kg2 = KnowledgeGraph()
    kg2.load(str(save_path))
    
    assert 'test_project' in kg2.projects
    assert kg2.projects['test_project'].total_loc == kg.projects['test_project'].total_loc


def test_empty_project(tmp_path):
    """Test scanning a project with no Python files."""
    empty_proj = tmp_path / "empty"
    empty_proj.mkdir()
    (empty_proj / ".git").mkdir()
    (empty_proj / "README.md").write_text("# Empty")
    
    kg = KnowledgeGraph()
    project = kg.scan_project(str(empty_proj))
    
    assert project.module_count == 0
    assert project.total_loc == 0


def test_syntax_error_handling(temp_project):
    """Test handling of files with syntax errors."""
    # Create a file with invalid Python
    (temp_project / "bad.py").write_text("""
def broken(
    # Missing closing paren and colon
""")
    
    kg = KnowledgeGraph()
    project = kg.scan_project(str(temp_project))
    
    # Should still parse other files successfully
    assert project.module_count == 3  # bad.py should be skipped


def test_multiple_projects(tmp_path):
    """Test scanning multiple projects."""
    kg = KnowledgeGraph()
    
    for i in range(3):
        proj = tmp_path / f"proj{i}"
        proj.mkdir()
        (proj / ".git").mkdir()
        (proj / "main.py").write_text(f"# Project {i}\nx = {i}")
        kg.scan_project(str(proj))
    
    assert len(kg.projects) == 3


def test_code_entity_id():
    """Test CodeEntity ID generation."""
    entity = CodeEntity(
        name="test",
        path=Path("/some/path.py"),
        project="myproject"
    )
    
    assert entity.id == "myproject:/some/path.py:test"


def test_module_properties():
    """Test Module dataclass properties."""
    mod = Module(
        name="mymodule",
        path=Path("/path/to/mymodule.py"),
        project="myproject",
        loc=100,
        classes=["ClassA", "ClassB"],
        functions=["func1", "func2"],
        imports={"os", "sys"}
    )
    
    assert mod.name == "mymodule"
    assert len(mod.classes) == 2
    assert len(mod.functions) == 2
    assert len(mod.imports) == 2


def test_project_properties():
    """Test Project dataclass properties."""
    proj = Project(
        name="test",
        path=Path("/path/to/test")
    )
    
    assert proj.module_count == 0
    
    proj.modules["mod1"] = Module(name="mod1", path=Path("mod1.py"), project="test")
    assert proj.module_count == 1
