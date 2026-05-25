import pytest
import os

def test_project_goal():
    """
    Test PROJECT_GOAL.md contains NetWeaver mission and objectives.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_goal_path = os.path.join(current_dir, '..', 'PROJECT_GOAL.md')
    
    assert os.path.exists(project_goal_path), f"File not found: {project_goal_path}"
    
    with open(project_goal_path, 'r') as f:
        content = f.read()
    
    # Verify mission
    assert "NetWeaver" in content
    assert "browser-native AI OS" in content
    assert "evidence-first web cognition engine" in content
    
    # Verify principles
    assert "Evidence-first" in content or "evidence" in content.lower()
    assert "WebSceneGraph" in content
    assert "WNAL" in content
    
    # Check sections
    assert "## Mission" in content
    assert "## Principles" in content
    assert "## Architecture" in content
    assert "## Current Status" in content
