import subprocess
import os
import pytest

def test_init_repo(tmp_path):
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Create sample .gitignore
    (repo_dir / ".gitignore").write_text("# Sample gitignore\n*.pyc\n__pycache__/\n")

    # Path to script (tests/ → scripts/)
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "init_repo.sh"))

    # Set git user config via environment variables
    env = os.environ.copy()
    env['GIT_AUTHOR_NAME'] = 'Test'
    env['GIT_AUTHOR_EMAIL'] = 'test@example.com'
    env['GIT_COMMITTER_NAME'] = 'Test'
    env['GIT_COMMITTER_EMAIL'] = 'test@example.com'

    # Run the script
    result = subprocess.run(['bash', script_path], capture_output=True, text=True, cwd=repo_dir, env=env)
    assert result.returncode == 0, f"Script failed: {result.stderr}"

    # Verify .git directory exists
    assert (repo_dir / ".git").is_dir()

    # Verify initial commit message
    log = subprocess.run(['git', 'log', '--oneline'], capture_output=True, text=True, cwd=repo_dir)
    assert "Initial commit" in log.stdout

    # Verify .gitignore is tracked
    files = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, cwd=repo_dir)
    assert '.gitignore' in files.stdout

    # Test idempotent
    result2 = subprocess.run(['bash', script_path], capture_output=True, text=True, cwd=repo_dir, env=env)
    assert "already initialized" in result2.stdout
