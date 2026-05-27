"""Tests for Agent Memory Palace."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from netweaver.memory_palace import (
    Memory,
    MemoryPalace,
    _context_fingerprint,
    _jaccard_similarity,
    _tokenize,
    DECAY_HALFLIFE_DAYS,
    MAX_MEMORIES_PER_AGENT,
)


# ═══════════════════════════════════════════════════════════════
# Helper function tests
# ═══════════════════════════════════════════════════════════════

class TestHelpers:
    """Test helper functions."""

    def test_tokenize_basic(self):
        tokens = _tokenize("Hello World Test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_tokenize_short_words_filtered(self):
        tokens = _tokenize("a an the is to")
        assert len(tokens) == 1  # "the" is 3 chars

    def test_tokenize_special_chars(self):
        tokens = _tokenize("hello-world_test.py")
        assert "hello" in tokens
        # Underscore is part of token: "world_test" stays together
        assert "world_test" in tokens

    def test_tokenize_numbers_in_tokens(self):
        tokens = _tokenize("test123 hello456")
        assert "test123" in tokens
        assert "hello456" in tokens

    def test_context_fingerprint_simple(self):
        ctx = {"scope": "test-healer", "module": "daemon"}
        fp = _context_fingerprint(ctx)
        assert "k:scope" in fp
        assert "k:module" in fp
        assert "test" in fp  # tokenized from "test-healer"
        assert "healer" in fp

    def test_context_fingerprint_nested(self):
        ctx = {"outer": {"inner": "value"}}
        fp = _context_fingerprint(ctx)
        assert "k:outer" in fp
        assert "value" in fp

    def test_context_fingerprint_list(self):
        ctx = {"files": ["daemon.py", "executor.py"]}
        fp = _context_fingerprint(ctx)
        assert "k:files" in fp
        assert "daemon" in fp
        assert "executor" in fp

    def test_context_fingerprint_numeric(self):
        ctx = {"count": 42}
        fp = _context_fingerprint(ctx)
        assert "k:count" in fp
        assert "v:42" in fp

    def test_jaccard_identical(self):
        assert _jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_jaccard_disjoint(self):
        assert _jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_jaccard_partial(self):
        sim = _jaccard_similarity({"a", "b", "c"}, {"a", "b", "d"})
        assert abs(sim - 0.5) < 0.01  # 2/4

    def test_jaccard_empty(self):
        assert _jaccard_similarity(set(), set()) == 1.0

    def test_jaccard_one_empty(self):
        assert _jaccard_similarity({"a"}, set()) == 0.0


# ═══════════════════════════════════════════════════════════════
# Memory dataclass tests
# ═══════════════════════════════════════════════════════════════

class TestMemory:
    """Test Memory dataclass."""

    def test_create_memory(self):
        mem = Memory(
            id="",
            agent_type="reviewer",
            decision="approved NW-027",
            context={"scope": "test-healer"},
            outcome="success",
        )
        assert mem.agent_type == "reviewer"
        assert mem.decision == "approved NW-027"
        assert mem.outcome == "success"
        assert mem.timestamp > 0
        assert len(mem.id) == 12

    def test_generate_id_deterministic(self):
        mem1 = Memory(id="", agent_type="a", decision="d", context={}, outcome="success", timestamp=100.0)
        mem2 = Memory(id="", agent_type="a", decision="d", context={}, outcome="success", timestamp=100.0)
        assert mem1.id == mem2.id

    def test_generate_id_unique_for_different_content(self):
        mem1 = Memory(id="", agent_type="a", decision="d1", context={}, outcome="success", timestamp=100.0)
        mem2 = Memory(id="", agent_type="a", decision="d2", context={}, outcome="success", timestamp=100.0)
        assert mem1.id != mem2.id

    def test_age_days(self):
        mem = Memory(id="", agent_type="a", decision="d", context={}, outcome="s", timestamp=time.time() - 86400)
        assert abs(mem.age_days() - 1.0) < 0.1

    def test_decay_weight_fresh(self):
        mem = Memory(id="", agent_type="a", decision="d", context={}, outcome="s", timestamp=time.time())
        assert abs(mem.decay_weight() - 1.0) < 0.01

    def test_decay_weight_one_halflife(self):
        ts = time.time() - DECAY_HALFLIFE_DAYS * 86400
        mem = Memory(id="", agent_type="a", decision="d", context={}, outcome="s", timestamp=ts)
        assert abs(mem.decay_weight() - 0.5) < 0.05

    def test_decay_weight_two_halflives(self):
        ts = time.time() - 2 * DECAY_HALFLIFE_DAYS * 86400
        mem = Memory(id="", agent_type="a", decision="d", context={}, outcome="s", timestamp=ts)
        assert abs(mem.decay_weight() - 0.25) < 0.05

    def test_relevance_score_success(self):
        mem = Memory(id="", agent_type="a", decision="d", context={}, outcome="success", timestamp=time.time())
        assert mem.relevance_score() > 0.9

    def test_relevance_score_failure(self):
        mem = Memory(id="", agent_type="a", decision="d", context={}, outcome="failure", timestamp=time.time())
        score = mem.relevance_score()
        assert 0.7 < score < 0.9

    def test_relevance_score_access_bonus(self):
        mem = Memory(id="", agent_type="a", decision="d", context={}, outcome="success", timestamp=time.time())
        base_score = mem.relevance_score()
        mem.access_count = 100
        boosted_score = mem.relevance_score()
        assert boosted_score > base_score

    def test_to_dict_from_dict_roundtrip(self):
        mem = Memory(
            id="",
            agent_type="worker",
            decision="implemented NW-031",
            context={"scope": "tests", "files": ["test_observer.py"]},
            outcome="success",
            outcome_details="All tests passed",
            tags=["testing", "observer"],
        )
        d = mem.to_dict()
        restored = Memory.from_dict(d)
        assert restored.agent_type == "worker"
        assert restored.decision == "implemented NW-031"
        assert restored.outcome == "success"
        assert restored.tags == ["testing", "observer"]
        assert restored.id == mem.id


# ═══════════════════════════════════════════════════════════════
# MemoryPalace tests
# ═══════════════════════════════════════════════════════════════

class TestMemoryPalace:
    """Test MemoryPalace class."""

    def test_create_palace(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        assert palace.agent_type == "reviewer"
        assert palace.count == 0

    def test_remember_basic(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        mem = palace.remember(
            decision="approved NW-027",
            context={"scope": "test-healer", "module": "daemon"},
            outcome="success",
        )
        assert palace.count == 1
        assert mem.decision == "approved NW-027"
        assert mem.outcome == "success"

    def test_remember_persists_to_disk(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(
            decision="approved NW-027",
            context={"scope": "test-healer"},
            outcome="success",
        )

        # Create new palace from same dir — should load
        palace2 = MemoryPalace("reviewer", memory_dir=tmp_path)
        assert palace2.count == 1

    def test_remember_with_tags(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(
            decision="approved",
            context={"scope": "test"},
            outcome="success",
            tags=["testing", "critical"],
        )
        mem = list(palace._memories.values())[0]
        assert "testing" in mem.tags
        assert "critical" in mem.tags

    def test_recall_by_query(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(
            decision="approved NW-027",
            context={"scope": "test-healer", "module": "daemon"},
            outcome="success",
        )
        palace.remember(
            decision="approved NW-028",
            context={"scope": "backlog-generator", "module": "daemon"},
            outcome="success",
        )
        palace.remember(
            decision="rejected NW-099",
            context={"scope": "ui-dashboard", "module": "frontend"},
            outcome="failure",
        )

        # Query for test-related memories
        results = palace.recall(query={"scope": "test-healer"})
        assert len(results) >= 1
        # First result should be the test-healer memory
        assert "NW-027" in results[0][0].decision

    def test_recall_by_tags(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(decision="d1", context={}, outcome="success", tags=["testing"])
        palace.remember(decision="d2", context={}, outcome="success", tags=["ui"])
        palace.remember(decision="d3", context={}, outcome="success", tags=["testing", "critical"])

        results = palace.recall(tags=["testing"])
        assert len(results) == 2

    def test_recall_by_outcome(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(decision="d1", context={}, outcome="success")
        palace.remember(decision="d2", context={}, outcome="failure")
        palace.remember(decision="d3", context={}, outcome="success")

        results = palace.recall(outcome="success")
        assert len(results) == 2

        results = palace.recall(outcome="failure")
        assert len(results) == 1

    def test_recall_limit(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        for i in range(20):
            palace.remember(decision=f"d{i}", context={"index": str(i)}, outcome="success")

        results = palace.recall(limit=5)
        assert len(results) == 5

    def test_recall_increments_access(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(decision="d1", context={"scope": "test"}, outcome="success")

        mem_id = list(palace._memories.keys())[0]
        assert palace._memories[mem_id].access_count == 0

        palace.recall(query={"scope": "test"})
        assert palace._memories[mem_id].access_count == 1

    def test_update_outcome(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        mem = palace.remember(decision="d1", context={}, outcome="pending")

        result = palace.update_outcome(mem.id, "success", "All tests passed")
        assert result is True
        assert palace._memories[mem.id].outcome == "success"
        assert palace._memories[mem.id].outcome_details == "All tests passed"

    def test_update_outcome_nonexistent(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        result = palace.update_outcome("nonexistent", "success")
        assert result is False

    def test_forget(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        mem = palace.remember(decision="d1", context={}, outcome="success")
        assert palace.count == 1

        result = palace.forget(mem.id)
        assert result is True
        assert palace.count == 0

    def test_forget_nonexistent(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        result = palace.forget("nonexistent")
        assert result is False

    def test_clear(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        for i in range(5):
            palace.remember(decision=f"d{i}", context={}, outcome="success")
        assert palace.count == 5

        removed = palace.clear()
        assert removed == 5
        assert palace.count == 0

    def test_export(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(decision="d1", context={"scope": "test"}, outcome="success")
        palace.remember(decision="d2", context={"scope": "ui"}, outcome="failure")

        exported = palace.export()
        assert len(exported) == 2
        assert all(isinstance(e, dict) for e in exported)

    def test_len(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        assert len(palace) == 0
        palace.remember(decision="d1", context={}, outcome="success")
        assert len(palace) == 1

    def test_repr(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        assert "reviewer" in repr(palace)
        assert "0" in repr(palace)


# ═══════════════════════════════════════════════════════════════
# Introspection tests
# ═══════════════════════════════════════════════════════════════

class TestIntrospection:
    """Test memory introspection and insights."""

    def test_introspect_empty(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        result = palace.introspect()
        assert result["total_memories"] == 0
        assert result["success_rate"] == 0.0
        assert len(result["insights"]) > 0

    def test_introspect_success_rate(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        for i in range(8):
            palace.remember(decision=f"d{i}", context={}, outcome="success")
        for i in range(2):
            palace.remember(decision=f"f{i}", context={}, outcome="failure")

        result = palace.introspect()
        assert result["total_memories"] == 10
        assert abs(result["success_rate"] - 0.8) < 0.01

    def test_introspect_high_success_insight(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        for i in range(10):
            palace.remember(decision=f"d{i}", context={}, outcome="success")

        result = palace.introspect()
        assert any("High success rate" in i for i in result["insights"])

    def test_introspect_low_success_insight(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        for i in range(3):
            palace.remember(decision=f"d{i}", context={}, outcome="success")
        for i in range(7):
            palace.remember(decision=f"f{i}", context={}, outcome="failure")

        result = palace.introspect()
        assert any("Low success rate" in i for i in result["insights"])

    def test_introspect_tag_frequency(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        for i in range(5):
            palace.remember(decision=f"d{i}", context={}, outcome="success", tags=["testing"])
        for i in range(2):
            palace.remember(decision=f"f{i}", context={}, outcome="success", tags=["ui"])

        result = palace.introspect()
        assert result["top_tags"][0] == ("testing", 5)

    def test_introspect_outcome_distribution(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(decision="d1", context={}, outcome="success")
        palace.remember(decision="d2", context={}, outcome="success")
        palace.remember(decision="d3", context={}, outcome="failure")
        palace.remember(decision="d4", context={}, outcome="partial")

        result = palace.introspect()
        assert result["outcome_distribution"]["success"] == 2
        assert result["outcome_distribution"]["failure"] == 1
        assert result["outcome_distribution"]["partial"] == 1

    def test_introspect_memory_span(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(decision="d1", context={}, outcome="success")
        palace.remember(decision="d2", context={}, outcome="success")

        result = palace.introspect()
        assert any("Memory span" in i for i in result["insights"])

    def test_introspect_context_keys(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        palace.remember(decision="d1", context={"scope": "test", "module": "daemon"}, outcome="success")
        palace.remember(decision="d2", context={"scope": "test", "module": "executor"}, outcome="success")
        palace.remember(decision="d3", context={"scope": "ui", "module": "frontend"}, outcome="failure")

        result = palace.introspect()
        success_keys = dict(result["success_context_keys"])
        assert "scope" in success_keys


# ═══════════════════════════════════════════════════════════════
# Pruning tests
# ═══════════════════════════════════════════════════════════════

class TestPruning:
    """Test memory pruning."""

    def test_prune_when_under_limit(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        for i in range(10):
            palace.remember(decision=f"d{i}", context={}, outcome="success")

        palace._prune()
        assert palace.count == 10  # No pruning needed

    def test_prune_removes_lowest_score(self, tmp_path):
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)

        # Manually set max to small number for testing
        with patch("netweaver.memory_palace.MAX_MEMORIES_PER_AGENT", 5):
            for i in range(10):
                mem = palace.remember(decision=f"d{i}", context={"index": str(i)}, outcome="success")
                # Make some memories old (low score)
                if i < 5:
                    palace._memories[mem.id].timestamp = time.time() - 365 * 86400

            palace._prune()
            assert palace.count <= 5

    def test_auto_prune_on_remember(self, tmp_path):
        """Auto-prune triggers when over MAX_MEMORIES_PER_AGENT."""
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)

        # Override max for testing
        original_max = MAX_MEMORIES_PER_AGENT
        try:
            import netweaver.memory_palace as mp
            mp.MAX_MEMORIES_PER_AGENT = 5

            for i in range(10):
                palace.remember(decision=f"d{i}", context={}, outcome="success")

            # Should have pruned to ~80% of max (4)
            assert palace.count <= 5
        finally:
            mp.MAX_MEMORIES_PER_AGENT = original_max


# ═══════════════════════════════════════════════════════════════
# Persistence tests
# ═══════════════════════════════════════════════════════════════

class TestPersistence:
    """Test memory persistence."""

    def test_save_and_load(self, tmp_path):
        palace1 = MemoryPalace("worker", memory_dir=tmp_path)
        palace1.remember(decision="implemented feature X", context={"files": ["x.py"]}, outcome="success")
        palace1.remember(decision="fixed bug Y", context={"files": ["y.py"]}, outcome="failure", tags=["bugfix"])

        palace2 = MemoryPalace("worker", memory_dir=tmp_path)
        assert palace2.count == 2

        results = palace2.recall(tags=["bugfix"])
        assert len(results) == 1
        assert "bug Y" in results[0][0].decision

    def test_file_format(self, tmp_path):
        palace = MemoryPalace("daemon", memory_dir=tmp_path)
        palace.remember(decision="test", context={"key": "value"}, outcome="success")

        data = json.loads((tmp_path / "daemon.json").read_text())
        assert data["agent_type"] == "daemon"
        assert data["count"] == 1
        assert len(data["memories"]) == 1
        assert "updated" in data

    def test_corrupt_file_handling(self, tmp_path):
        # Write corrupt JSON
        (tmp_path / "reviewer.json").write_text("{invalid json")

        palace = MemoryPalace("reviewer", memory_dir=tmp_path)
        assert palace.count == 0  # Should start fresh

    def test_multiple_agents_independent(self, tmp_path):
        reviewer = MemoryPalace("reviewer", memory_dir=tmp_path)
        worker = MemoryPalace("worker", memory_dir=tmp_path)

        reviewer.remember(decision="approved", context={}, outcome="success")
        worker.remember(decision="implemented", context={}, outcome="success")

        assert reviewer.count == 1
        assert worker.count == 1

        # Reload and verify independence
        reviewer2 = MemoryPalace("reviewer", memory_dir=tmp_path)
        worker2 = MemoryPalace("worker", memory_dir=tmp_path)
        assert reviewer2.count == 1
        assert worker2.count == 1


# ═══════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════

class TestMemoryPalaceIntegration:
    """Integration tests for realistic usage patterns."""

    def test_reviewer_workflow(self, tmp_path):
        """Simulate a reviewer agent's memory lifecycle."""
        palace = MemoryPalace("reviewer", memory_dir=tmp_path)

        # Phase 1: Review and approve plans
        m1 = palace.remember(
            decision="approved NW-027 (test healer)",
            context={"scope": "test-healer", "complexity": "medium", "files_touched": 3},
            outcome="pending",
            tags=["test", "infrastructure"],
        )
        m2 = palace.remember(
            decision="approved NW-028 (backlog gen)",
            context={"scope": "backlog-generator", "complexity": "high", "files_touched": 5},
            outcome="pending",
            tags=["daemon", "planning"],
        )
        m3 = palace.remember(
            decision="rejected NW-099 (vague scope)",
            context={"scope": "improve-stuff", "complexity": "low", "files_touched": 0},
            outcome="success",
            tags=["rejected", "vague"],
        )

        # Phase 2: Plans get implemented, update outcomes
        palace.update_outcome(m1.id, "success", "All 15 tests passed, committed")
        palace.update_outcome(m2.id, "failure", "Worker hit timeout, plan too complex")

        # Phase 3: Recall — next time a similar plan comes in
        # Query for test-healer type plans
        similar = palace.recall(query={"scope": "test-healer", "complexity": "medium"})
        assert len(similar) >= 1
        assert "NW-027" in similar[0][0].decision

        # Phase 4: Introspect
        insights = palace.introspect()
        assert insights["total_memories"] == 3
        assert insights["outcome_distribution"]["success"] == 2
        assert insights["outcome_distribution"]["failure"] == 1

    def test_worker_learning_pattern(self, tmp_path):
        """Simulate worker learning from successes and failures."""
        palace = MemoryPalace("worker", memory_dir=tmp_path)

        # Worker remembers implementation patterns
        patterns = [
            ("implemented observer tests", {"pattern": "unit-test", "module": "observer", "loc": 200}, "success"),
            ("implemented bridge tests", {"pattern": "integration-test", "module": "playwright_bridge", "loc": 400}, "failure"),
            ("implemented planner fix", {"pattern": "bugfix", "module": "planner", "loc": 15}, "success"),
            ("implemented scene graph test", {"pattern": "unit-test", "module": "scene_graph", "loc": 150}, "success"),
            ("implemented E2E demo", {"pattern": "integration-test", "module": "all", "loc": 300}, "failure"),
        ]

        for decision, ctx, outcome in patterns:
            palace.remember(decision=decision, context=ctx, outcome=outcome, tags=[ctx["pattern"]])

        # Worker asks: what patterns succeed?
        successes = palace.recall(outcome="success")
        assert len(successes) == 3

        # Worker asks: what patterns fail?
        failures = palace.recall(outcome="failure")
        assert len(failures) == 2

        # Introspect reveals integration-test pattern is risky
        insights = palace.introspect()
        assert insights["success_rate"] < 1.0

        # Recall similar to a new integration-test task
        similar = palace.recall(query={"pattern": "integration-test", "module": "all"})
        assert len(similar) >= 1
        # Should recall the failed E2E demo
        assert any("E2E" in m.decision for m, _ in similar)

    def test_daemon_gap_detection_learning(self, tmp_path):
        """Simulate daemon learning from gap detection cycles."""
        palace = MemoryPalace("daemon", memory_dir=tmp_path)

        # Daemon records gap detection outcomes
        for i in range(10):
            scope = "test-infrastructure" if i < 7 else "ui-feature"
            outcome = "success" if i < 8 else "failure"
            palace.remember(
                decision=f"generated plan for gap-{i}",
                context={"scope": scope, "cycle": i, "backlog_size": 10 + i},
                outcome=outcome,
                tags=[scope],
            )

        # Daemon introspects
        insights = palace.introspect()
        assert insights["total_memories"] == 10
        assert insights["success_rate"] == 0.8

        # Daemon recalls: what scopes lead to good plans?
        test_results = palace.recall(query={"scope": "test-infrastructure"}, outcome="success")
        assert len(test_results) == 7
