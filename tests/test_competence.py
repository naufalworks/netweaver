"""Tests for CompetenceRegistry."""
import tempfile
from pathlib import Path

import pytest

from netweaver.competence import Competence, WorkerProfile, CompetenceRegistry


# ── Competence ──────────────────────────────────────────────────────

def test_competence_to_dict():
    c = Competence("browser", 0.8)
    assert c.to_dict() == {"name": "browser", "weight": 0.8}


def test_competence_from_dict():
    c = Competence.from_dict({"name": "browser", "weight": 0.8})
    assert c.name == "browser"
    assert c.weight == 0.8


# ── WorkerProfile ───────────────────────────────────────────────────

@pytest.fixture
def worker():
    return WorkerProfile(
        worker_id="netweaver-runtime-engineer",
        name="Runtime Engineer",
        model="glm/glm-5.1",
        competences=[
            Competence("browser", 1.0),
            Competence("executor", 1.0),
            Competence("observer", 0.8),
            Competence("tests", 0.5),
        ],
        schedule="5,20,35,50",
        workdir="/projects/myhermes",
    )


def test_worker_has_competence(worker: WorkerProfile):
    assert worker.has_competence("browser")
    assert worker.has_competence("executor")
    assert not worker.has_competence("frontend")


def test_match_score_exact(worker: WorkerProfile):
    score = worker.match_score(["browser", "executor"])
    assert score == pytest.approx(1.0)


def test_match_score_partial(worker: WorkerProfile):
    score = worker.match_score(["browser"])
    assert score == pytest.approx(1.0)


def test_match_score_zero(worker: WorkerProfile):
    score = worker.match_score(["frontend", "design"])
    assert score == pytest.approx(0.0)


def test_match_score_weighted(worker: WorkerProfile):
    score = worker.match_score(["browser", "frontend"])
    assert score == pytest.approx(0.5)  # 1.0 / 2


def test_match_score_empty(worker: WorkerProfile):
    score = worker.match_score([])
    assert score == pytest.approx(0.5)


def test_worker_round_trip(worker: WorkerProfile):
    d = worker.to_dict()
    w2 = WorkerProfile.from_dict(d)
    assert w2.worker_id == worker.worker_id
    assert w2.name == worker.name
    assert len(w2.competences) == len(worker.competences)
    assert w2.has_competence("browser")


# ── CompetenceRegistry ──────────────────────────────────────────────

@pytest.fixture
def registry():
    with tempfile.TemporaryDirectory() as tmp:
        reg = CompetenceRegistry(tmp)
        reg.register(WorkerProfile(
            worker_id="worker-a", name="Worker A", model="m1",
            competences=[Competence("browser", 1.0), Competence("tests", 0.5)],
        ))
        reg.register(WorkerProfile(
            worker_id="worker-b", name="Worker B", model="m2",
            competences=[Competence("frontend", 1.0), Competence("design", 0.8)],
        ))
        yield reg


def test_register_and_get(registry: CompetenceRegistry):
    w = registry.get_worker("worker-a")
    assert w is not None
    assert w.name == "Worker A"


def test_register_duplicate(registry: CompetenceRegistry):
    registry.register(WorkerProfile(
        worker_id="worker-a", name="Worker A v2", model="m1",
        competences=[Competence("new", 1.0)],
    ))
    w = registry.get_worker("worker-a")
    assert w.name == "Worker A v2"


def test_all_workers(registry: CompetenceRegistry):
    assert len(registry.all_workers()) == 2


def test_workers_with_competence(registry: CompetenceRegistry):
    browsers = registry.workers_with_competence("browser")
    assert len(browsers) == 1
    assert browsers[0].worker_id == "worker-a"


def test_unregister(registry: CompetenceRegistry):
    assert registry.unregister("worker-a") is True
    assert registry.get_worker("worker-a") is None
    assert registry.unregister("nonexistent") is False


def test_best_worker(registry: CompetenceRegistry):
    w = registry.best_worker(["browser", "tests"])
    assert w is not None
    assert w.worker_id == "worker-a"


def test_best_worker_exclude(registry: CompetenceRegistry):
    w = registry.best_worker(["browser", "tests"], exclude=["worker-a"])
    assert w is None  # only worker-a can do browser


def test_best_worker_no_match(registry: CompetenceRegistry):
    w = registry.best_worker(["database"])
    assert w is None


def test_suggest_ranked(registry: CompetenceRegistry):
    workers = registry.suggest_new_task_workers(["browser"])
    assert len(workers) == 1
    assert workers[0].worker_id == "worker-a"


def test_persistence_across_reload(registry: CompetenceRegistry):
    path = registry.path
    assert path.exists()
    reg2 = CompetenceRegistry(path.parents[3])  # climb back to tmp root
    assert len(reg2.all_workers()) == 2


def test_empty_registry():
    with tempfile.TemporaryDirectory() as tmp:
        reg = CompetenceRegistry(tmp)
        assert reg.all_workers() == []
        assert reg.best_worker(["browser"]) is None
