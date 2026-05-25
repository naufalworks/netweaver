"""QA coverage expansion for prompt_manager.py — token estimate, record_run, failure trim, edge cases."""
import json
import tempfile

import pytest

from netweaver.prompt_manager import PromptManager, PromptVersion


@pytest.fixture
def pm():
    with tempfile.TemporaryDirectory() as tmp:
        yield PromptManager(tmp)


# ── PromptVersion unit tests ───────────────────────────────────────

def test_token_estimate_short():
    pv = PromptVersion(version=1, agent="a", content="hello world")
    # 11 chars / 4 = 2
    assert pv.token_estimate == 2


def test_token_estimate_long():
    content = "a" * 4000  # 4000 chars / 4 = 1000 tokens
    pv = PromptVersion(version=1, agent="a", content=content)
    assert pv.token_estimate == 1000


def test_token_estimate_empty():
    pv = PromptVersion(version=1, agent="a", content="")
    assert pv.token_estimate == 0


def test_prompt_version_to_dict_round_trip():
    pv = PromptVersion(
        version=3,
        agent="worker-x",
        content="Do things",
        success_rate=0.85,
        avg_tokens=1200,
        failures=["err1", "err2"],
        parent=2,
        author="system",
        reason="auto-fix",
        created_at="2026-05-24T12:00:00",
    )
    d = pv.to_dict()
    assert d["version"] == 3
    assert d["token_estimate"] == pv.token_estimate
    restored = PromptVersion.from_dict(d)
    assert restored.version == 3
    assert restored.agent == "worker-x"
    assert restored.content == "Do things"
    assert restored.success_rate == 0.85
    assert restored.avg_tokens == 1200
    assert restored.failures == ["err1", "err2"]
    assert restored.parent == 2
    assert restored.author == "system"
    assert restored.reason == "auto-fix"
    assert restored.created_at == "2026-05-24T12:00:00"


def test_prompt_version_from_dict_defaults():
    d = {"version": 1, "agent": "a", "content": "c"}
    pv = PromptVersion.from_dict(d)
    assert pv.success_rate == 1.0
    assert pv.avg_tokens == 0
    assert pv.failures == []
    assert pv.parent is None
    assert pv.author == "system"
    assert pv.reason == ""


def test_prompt_version_auto_created_at():
    pv = PromptVersion(version=1, agent="a", content="c")
    assert pv.created_at
    assert "T" in pv.created_at


# ── Record run: success rate decay ─────────────────────────────────

def test_record_run_success_rate_decay(pm):
    pm.save_prompt("a", "content")
    # Start at 1.0
    # After success: 1.0 * 0.9 + 1.0 * 0.1 = 1.0
    pm.record_run("a", success=True)
    assert pm.current_version("a").success_rate == 1.0
    # After fail: 1.0 * 0.9 + 0.0 * 0.1 = 0.9
    pm.record_run("a", success=False)
    assert pm.current_version("a").success_rate == 0.9
    # After fail: 0.9 * 0.9 + 0.0 * 0.1 = 0.81
    pm.record_run("a", success=False)
    assert pm.current_version("a").success_rate == pytest.approx(0.81)


def test_record_run_avg_tokens(pm):
    pm.save_prompt("a", "content")
    pm.record_run("a", success=True, tokens_used=500)
    assert pm.current_version("a").avg_tokens == 500
    # max is tracked, not running average
    pm.record_run("a", success=True, tokens_used=300)
    assert pm.current_version("a").avg_tokens == 500
    pm.record_run("a", success=True, tokens_used=800)
    assert pm.current_version("a").avg_tokens == 800


def test_record_run_failure_dedup(pm):
    pm.save_prompt("a", "content")
    pm.record_run("a", success=False, error="ctx_overflow")
    pm.record_run("a", success=False, error="ctx_overflow")
    pm.record_run("a", success=False, error="ctx_overflow")
    failures = pm.current_version("a").failures
    assert failures.count("ctx_overflow") == 1


def test_record_run_failure_trim_to_10(pm):
    pm.save_prompt("a", "content")
    for i in range(15):
        pm.record_run("a", success=False, error=f"err-{i}")
    assert len(pm.current_version("a").failures) == 10
    # Should keep last 10
    assert "err-14" in pm.current_version("a").failures


def test_record_run_no_current_prompt(pm):
    """Should be a no-op, not an error."""
    pm.record_run("nonexistent", success=True)


# ── Rollback edge cases ────────────────────────────────────────────

def test_rollback_nonexistent_version(pm):
    pm.save_prompt("a", "v1")
    v = pm.rollback("a", target_version=999)
    assert v is None


def test_rollback_to_first_version(pm):
    pm.save_prompt("a", "v1")
    pm.save_prompt("a", "v2")
    pm.save_prompt("a", "v3")
    v = pm.rollback("a", target_version=1)
    assert v == 1
    assert pm.current_prompt_text("a") == "v1"


def test_rollback_empty_agent(pm):
    v = pm.rollback("nonexistent")
    assert v is None


def test_rollback_no_current_file(pm):
    """If current file is deleted, rollback returns None (no known current version)."""
    pm.save_prompt("a", "v1")
    pm.save_prompt("a", "v2")
    (pm.root / ".tini" / "prompts" / "a" / "current").unlink()
    v = pm.rollback("a")
    assert v is None  # can't roll back without knowing current version


# ── Optimization ───────────────────────────────────────────────────

def test_needs_optimization_repeated_failures(pm):
    pm.save_prompt("a", "content")
    for i in range(3):
        pm.record_run("a", success=False, error=f"fail-{i}")
    need = pm.needs_optimization("a")
    assert need is not None
    assert "repeated_failures" in need


def test_needs_optimization_no_prompt(pm):
    need = pm.needs_optimization("nonexistent")
    assert need == "no_prompt"


def test_needs_optimization_multiple_reasons(pm):
    big = "x " * 3000  # ~6000 chars → ~1500 tokens (>2000 triggers check)
    # Actually 6000/4 = 1500, not >2000. Let's use bigger.
    big = "x " * 10000  # ~20000 chars / 4 = 5000 tokens
    pm.save_prompt("a", big)
    for _ in range(10):
        pm.record_run("a", success=False)
    need = pm.needs_optimization("a")
    assert need is not None
    assert "low_success_rate" in need
    assert "large_prompt" in need


def test_optimize_no_current(pm):
    v = pm.optimize("nonexistent", "content")
    # No prompt exists → needs_optimization returns "no_prompt"
    # save_prompt is called → returns v1
    assert v == 1


def test_optimize_different_content(pm):
    pm.save_prompt("a", "old")
    v = pm.optimize("a", "new better prompt")
    assert v == 2
    assert pm.current_prompt_text("a") == "new better prompt"


# ── Persistence ────────────────────────────────────────────────────

def test_prompt_file_created(pm):
    pm.save_prompt("a", "hello world")
    p = pm.root / ".tini" / "prompts" / "a" / "v1.prompt"
    assert p.exists()
    assert p.read_text() == "hello world"


def test_registry_json_structure(pm):
    pm.save_prompt("a", "content")
    reg_path = pm.root / ".tini" / "prompts" / "a" / "registry.json"
    data = json.loads(reg_path.read_text())
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["version"] == 1
    assert data[0]["agent"] == "a"


def test_load_registry_corrupt_json(pm):
    agent_dir = pm.root / ".tini" / "prompts" / "broken"
    agent_dir.mkdir(parents=True)
    (agent_dir / "registry.json").write_text("not valid json{{{")
    versions = pm.load_registry("broken")
    assert versions == []


def test_current_version_fallback_to_last(pm):
    """If current file content doesn't match any registry entry, fallback to last."""
    pm.save_prompt("a", "v1 content")
    pm.save_prompt("a", "v2 content")
    # Corrupt current file with unknown content
    (pm.root / ".tini" / "prompts" / "a" / "current").write_text("unknown content")
    current = pm.current_version("a")
    assert current is not None
    assert current.version == 2  # falls back to last registered


def test_current_version_empty_registry(pm):
    assert pm.current_version("nonexistent") is None


# ── Multi-agent isolation ──────────────────────────────────────────

def test_agents_isolated(pm):
    pm.save_prompt("a", "prompt for a")
    pm.save_prompt("b", "prompt for b")
    assert pm.current_prompt_text("a") == "prompt for a"
    assert pm.current_prompt_text("b") == "prompt for b"
    assert pm.list_versions("a") == [1]
    assert pm.list_versions("b") == [1]


def test_all_agents_sorted(pm):
    pm.save_prompt("charlie", "c")
    pm.save_prompt("alpha", "a")
    pm.save_prompt("bravo", "b")
    assert pm.all_agents() == ["alpha", "bravo", "charlie"]


def test_all_agents_empty(pm):
    assert pm.all_agents() == []


def test_multiple_saves_multiple_files(pm):
    pm.save_prompt("a", "v1")
    pm.save_prompt("a", "v2")
    pm.save_prompt("a", "v3")
    d = pm.root / ".tini" / "prompts" / "a"
    prompt_files = sorted(f.name for f in d.iterdir() if f.suffix == ".prompt")
    assert prompt_files == ["v1.prompt", "v2.prompt", "v3.prompt"]
