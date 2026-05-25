"""QA coverage expansion for competence.py — edge cases, tie-breaking, TaskRequirement."""
import tempfile
from pathlib import Path

import pytest

from netweaver.competence import Competence, WorkerProfile, TaskRequirement, CompetenceRegistry


# ── Competence edge cases ──────────────────────────────────────────

def test_competence_default_weight():
    c = Competence("basic")
    assert c.weight == 1.0
    assert c.to_dict() == {"name": "basic", "weight": 1.0}


def test_competence_from_dict_missing_weight():
    c = Competence.from_dict({"name": "x"})
    assert c.weight == 1.0


def test_competence_from_dict_extra_keys_ignored():
    c = Competence.from_dict({"name": "x", "weight": 0.3, "extra": True})
    assert c.name == "x"
    assert c.weight == 0.3


# ── WorkerProfile edge cases ───────────────────────────────────────

def test_worker_profile_auto_created_at():
    w = WorkerProfile(
        worker_id="w1", name="W1", model="m1",
        competences=[Competence("a")],
    )
    assert w.created_at  # not empty
    assert "T" in w.created_at  # ISO format


def test_worker_profile_from_dict_missing_optional_fields():
    d = {"worker_id": "w1", "competences": []}
    w = WorkerProfile.from_dict(d)
    assert w.name == "w1"  # falls back to worker_id
    assert w.model == ""
    assert w.task_count == 0


def test_worker_profile_from_dict_with_all_fields():
    d = {
        "worker_id": "w1",
        "name": "Worker One",
        "model": "m1",
        "competences": [{"name": "a", "weight": 0.7}],
        "schedule": "0 * * * *",
        "workdir": "/tmp",
        "created_at": "2026-01-01T00:00:00",
        "last_active": "2026-01-02T00:00:00",
        "task_count": 42,
    }
    w = WorkerProfile.from_dict(d)
    assert w.name == "Worker One"
    assert w.task_count == 42
    assert w.competences[0].weight == 0.7


def test_match_score_all_match_weighted():
    """Different weights on competences affect partial match."""
    w = WorkerProfile(
        worker_id="w", name="W", model="m",
        competences=[Competence("a", 0.5), Competence("b", 1.0)],
    )
    score = w.match_score(["a"])
    assert score == pytest.approx(0.5)


def test_match_score_mixed_match():
    """One of two required competences matched with weight 1.0."""
    w = WorkerProfile(
        worker_id="w", name="W", model="m",
        competences=[Competence("a", 1.0), Competence("b", 1.0)],
    )
    score = w.match_score(["a", "c"])
    # a matched (1.0), c unmatched → 1.0 / 2.0
    assert score == pytest.approx(0.5)


def test_worker_round_trip_preserves_competences():
    w = WorkerProfile(
        worker_id="w", name="W", model="m",
        competences=[Competence("x", 0.3), Competence("y", 0.9)],
        schedule="5 * * * *",
        workdir="/home",
        task_count=7,
    )
    restored = WorkerProfile.from_dict(w.to_dict())
    assert len(restored.competences) == 2
    assert restored.competences[0].name == "x"
    assert restored.competences[0].weight == pytest.approx(0.3)
    assert restored.competences[1].name == "y"
    assert restored.task_count == 7


# ── TaskRequirement ────────────────────────────────────────────────

def test_task_requirement_fields():
    tr = TaskRequirement(
        task_id="NW-099",
        required_competences=["browser", "executor"],
        preferred_owner="runtime-engineer",
        risk="high",
    )
    assert tr.task_id == "NW-099"
    assert tr.required_competences == ["browser", "executor"]
    assert tr.preferred_owner == "runtime-engineer"
    assert tr.risk == "high"


def test_task_requirement_defaults():
    tr = TaskRequirement(task_id="NW-100", required_competences=["tests"])
    assert tr.preferred_owner == ""
    assert tr.risk == "low"


# ── CompetenceRegistry edge cases ──────────────────────────────────

@pytest.fixture
def tmp_registry():
    with tempfile.TemporaryDirectory() as tmp:
        yield CompetenceRegistry(tmp)


def _make_worker(wid, name, *comp_names_weights):
    comps = [Competence(n, w) for n, w in comp_names_weights]
    return WorkerProfile(worker_id=wid, name=name, model="m", competences=comps)


def test_best_worker_tiebreak_by_task_count(tmp_registry):
    """When scores equal, lower task_count wins (less loaded)."""
    w1 = _make_worker("a", "A", ("x", 1.0))
    w1.task_count = 10
    w2 = _make_worker("b", "B", ("x", 1.0))
    w2.task_count = 2
    tmp_registry.register(w1)
    tmp_registry.register(w2)
    best = tmp_registry.best_worker(["x"])
    assert best.worker_id == "b"  # lower task_count


def test_suggest_new_task_workers_ranked(tmp_registry):
    w1 = _make_worker("a", "A", ("x", 1.0), ("y", 0.5))
    w2 = _make_worker("b", "B", ("x", 0.8))
    w3 = _make_worker("c", "C", ("x", 1.0))
    tmp_registry.register(w1)
    tmp_registry.register(w2)
    tmp_registry.register(w3)
    ranked = tmp_registry.suggest_new_task_workers(["x", "y"])
    # w1 matches both x(1.0)+y(0.5) = 0.75, w2 matches x(0.8) only = 0.4, w3 matches x(1.0) only = 0.5
    assert ranked[0].worker_id == "a"


def test_parse_workers_single_object_json(tmp_registry):
    """Registry with single JSON object (not array) should still parse."""
    path = tmp_registry.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Reg\n```json\n{\"worker_id\": \"z\", \"name\": \"Z\", \"model\": \"m\", \"competences\": []}\n```\n")
    reg2 = CompetenceRegistry(str(path.parents[3]))
    workers = reg2.all_workers()
    assert len(workers) == 1
    assert workers[0].worker_id == "z"


def test_parse_workers_invalid_json_skipped(tmp_registry):
    path = tmp_registry.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Reg\n```json\n{broken json\n```\n```json\n{\"worker_id\": \"ok\", \"name\": \"OK\", \"model\": \"m\", \"competences\": []}\n```\n")
    reg2 = CompetenceRegistry(str(path.parents[3]))
    assert len(reg2.all_workers()) == 1


def test_parse_workers_empty_registry(tmp_registry):
    """No file → empty workers list."""
    assert tmp_registry.all_workers() == []


def test_register_updates_existing(tmp_registry):
    tmp_registry.register(_make_worker("w1", "W1", ("a", 1.0)))
    assert len(tmp_registry.all_workers()) == 1
    tmp_registry.register(_make_worker("w1", "W1 Updated", ("b", 1.0)))
    assert len(tmp_registry.all_workers()) == 1
    assert tmp_registry.get_worker("w1").name == "W1 Updated"


def test_get_worker_not_found(tmp_registry):
    assert tmp_registry.get_worker("nonexistent") is None


def test_workers_with_competence_empty(tmp_registry):
    assert tmp_registry.workers_with_competence("x") == []


def test_best_worker_empty_registry(tmp_registry):
    assert tmp_registry.best_worker(["anything"]) is None


def test_save_generates_markdown(tmp_registry):
    tmp_registry.register(_make_worker("w1", "W1", ("browser", 0.9)))
    text = tmp_registry.path.read_text()
    assert "# Competence Registry" in text
    assert "W1" in text
    assert "```json" in text


def test_save_competence_bar(tmp_registry):
    tmp_registry.register(_make_worker("w1", "W1", ("test", 0.7)))
    text = tmp_registry.path.read_text()
    # 0.7 * 10 = 7 filled bars
    assert "███████" in text  # 7 filled
    assert "───" in text     # 3 empty


def test_unregister_triggers_save(tmp_registry):
    tmp_registry.register(_make_worker("w1", "W1", ("a", 1.0)))
    tmp_registry.register(_make_worker("w2", "W2", ("b", 1.0)))
    tmp_registry.unregister("w1")
    reg2 = CompetenceRegistry(str(tmp_registry.path.parents[3]))
    assert len(reg2.all_workers()) == 1
    assert reg2.get_worker("w1") is None
