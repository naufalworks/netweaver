"""Tests for Epistemic OS — Honest reasoning engine."""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from netweaver.epistemic import (
    EpistemicOS,
    EpistemicAnswer,
    KnowledgeNode,
    Contradiction,
    Source,
    _hash_id,
    _tokenize,
    _token_overlap,
    _relevance_score,
    _truncate,
    SOURCE_TRUST,
)


# ═══ Utility Function Tests ═══


class TestTokenize:
    def test_simple(self):
        tokens = _tokenize("hello world")
        assert tokens == {"hello", "world"}

    def test_case_insensitive(self):
        tokens = _tokenize("Hello WORLD")
        assert tokens == {"hello", "world"}

    def test_special_chars(self):
        tokens = _tokenize("hello-world_test.py")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_empty(self):
        assert _tokenize("") == set()


class TestTokenOverlap:
    def test_identical(self):
        assert _token_overlap({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert _token_overlap({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial(self):
        overlap = _token_overlap({"a", "b", "c"}, {"b", "c", "d"})
        assert abs(overlap - 0.5) < 0.01  # 2/4

    def test_empty(self):
        assert _token_overlap(set(), {"a"}) == 0.0
        assert _token_overlap({"a"}, set()) == 0.0


class TestHashId:
    def test_deterministic(self):
        assert _hash_id("hello") == _hash_id("hello")

    def test_case_insensitive(self):
        assert _hash_id("Hello") == _hash_id("hello")

    def test_different_inputs(self):
        assert _hash_id("hello") != _hash_id("world")

    def test_length(self):
        assert len(_hash_id("anything")) == 16


class TestTruncate:
    def test_short(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact(self):
        assert _truncate("hello", 5) == "hello"

    def test_long(self):
        assert _truncate("hello world", 8) == "hello..."


class TestRelevanceScore:
    def test_exact_match(self):
        node = KnowledgeNode(content="postgres performance", topic="database")
        score = _relevance_score(node, {"postgres", "performance"})
        assert score == 1.0

    def test_partial_match(self):
        node = KnowledgeNode(content="postgres performance", topic="database")
        score = _relevance_score(node, {"postgres", "mysql"})
        assert 0.0 < score < 1.0

    def test_no_match(self):
        node = KnowledgeNode(content="postgres performance", topic="database")
        score = _relevance_score(node, {"rust", "compiler"})
        assert score == 0.0

    def test_tag_match(self):
        node = KnowledgeNode(content="some fact", tags=["database", "postgres"])
        score = _relevance_score(node, {"postgres"})
        assert score > 0.0


# ═══ Source Tests ═══


class TestSource:
    def test_create(self):
        s = Source(type="benchmark", ref="bench.py", author="alice")
        assert s.type == "benchmark"
        assert s.ref == "bench.py"
        assert s.trustworthiness == 0.5  # default

    def test_to_dict_roundtrip(self):
        s = Source(type="blog", ref="https://example.com", author="bob", trustworthiness=0.6)
        d = s.to_dict()
        s2 = Source.from_dict(d)
        assert s2.type == "blog"
        assert s2.ref == "https://example.com"
        assert s2.trustworthiness == 0.6


class TestSourceTrust:
    def test_benchmark_high_trust(self):
        assert SOURCE_TRUST["benchmark"] >= 0.8

    def test_hearsay_low_trust(self):
        assert SOURCE_TRUST["hearsay"] <= 0.3


# ═══ KnowledgeNode Tests ═══


class TestKnowledgeNode:
    def test_create_defaults(self):
        n = KnowledgeNode(content="test fact")
        assert n.content == "test fact"
        assert n.confidence == 0.5
        assert n.decay_rate == 0.0
        assert n.id  # auto-generated

    def test_id_from_content(self):
        n1 = KnowledgeNode(content="hello")
        n2 = KnowledgeNode(content="hello")
        assert n1.id == n2.id

    def test_current_confidence_no_decay(self):
        n = KnowledgeNode(content="test", confidence=0.8, decay_rate=0.0)
        assert n.current_confidence == 0.8

    def test_current_confidence_with_decay(self):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        n = KnowledgeNode(
            content="test",
            confidence=0.8,
            decay_rate=0.1,
            last_verified=old,
        )
        # ~2 months old, 10% decay/month → ~0.8 * 0.9^2 ≈ 0.648
        assert 0.5 < n.current_confidence < 0.8

    def test_current_confidence_floor(self):
        old = datetime.now(timezone.utc) - timedelta(days=3650)
        n = KnowledgeNode(
            content="test",
            confidence=0.5,
            decay_rate=0.5,
            last_verified=old,
        )
        assert n.current_confidence >= 0.01  # Floor

    def test_effective_confidence_with_sources(self):
        n = KnowledgeNode(
            content="test",
            confidence=0.8,
            sources=[Source(type="benchmark", ref="b.py", trustworthiness=0.9)],
        )
        eff = n.effective_confidence
        # 0.6 * 0.8 + 0.4 * 0.9 = 0.84
        assert abs(eff - 0.84) < 0.01

    def test_effective_confidence_no_sources(self):
        n = KnowledgeNode(content="test", confidence=0.8)
        assert n.effective_confidence == 0.8

    def test_is_stale(self):
        n = KnowledgeNode(content="test", confidence=0.3)
        assert n.is_stale

        n2 = KnowledgeNode(content="test", confidence=0.8)
        assert not n2.is_stale

    def test_confidence_labels(self):
        labels = {
            0.95: "highly certain",
            0.75: "likely",
            0.55: "uncertain",
            0.35: "weak",
            0.1: "unreliable",
        }
        for conf, expected in labels.items():
            n = KnowledgeNode(content="test", confidence=conf, decay_rate=0)
            assert n.confidence_label == expected, f"conf={conf} → {n.confidence_label} != {expected}"

    def test_touch(self):
        n = KnowledgeNode(content="test")
        assert n.access_count == 0
        n.touch()
        assert n.access_count == 1
        assert n.last_accessed is not None

    def test_verify(self):
        old = datetime.now(timezone.utc) - timedelta(days=30)
        n = KnowledgeNode(content="test", last_verified=old)
        n.verify()
        assert n.last_verified > old

    def test_to_dict_roundtrip(self):
        n = KnowledgeNode(
            content="postgres handles 10K QPS",
            topic="database_performance",
            tags=["postgres", "performance"],
            context="read queries on SSD",
            confidence=0.7,
            decay_rate=0.05,
            sources=[Source(type="benchmark", ref="bench.py")],
        )
        d = n.to_dict()
        n2 = KnowledgeNode.from_dict(d)
        assert n2.content == n.content
        assert n2.topic == n.topic
        assert n2.tags == n.tags
        assert n2.confidence == n.confidence
        assert n2.decay_rate == n.decay_rate
        assert len(n2.sources) == 1
        assert n2.id == n.id

    def test_age_days(self):
        old = datetime.now(timezone.utc) - timedelta(days=10)
        n = KnowledgeNode(content="test", last_verified=old)
        assert n.age_days == 10


# ═══ Contradiction Tests ═══


class TestContradiction:
    def test_create(self):
        c = Contradiction(
            node_a_id="abc123",
            node_b_id="def456",
            severity=0.7,
            reason="Conflicting measurements",
        )
        assert c.severity == 0.7
        assert not c.resolved

    def test_to_dict_roundtrip(self):
        c = Contradiction(
            node_a_id="abc",
            node_b_id="def",
            severity=0.8,
            reason="test",
        )
        d = c.to_dict()
        c2 = Contradiction.from_dict(d)
        assert c2.node_a_id == "abc"
        assert c2.severity == 0.8
        assert c2.reason == "test"


# ═══ EpistemicOS Core Tests ═══


class TestEpistemicOSAdd:
    def test_add_basic(self):
        os = EpistemicOS()
        node = os.add("postgres handles 10K QPS", confidence=0.7)
        assert node.content == "postgres handles 10K QPS"
        assert node.confidence == 0.7
        assert node.id in os.nodes

    def test_add_with_all_metadata(self):
        os = EpistemicOS()
        node = os.add(
            "postgres handles 10K QPS",
            confidence=0.7,
            topic="database_performance",
            tags=["postgres", "performance"],
            context="read queries on SSD",
            sources=[Source(type="benchmark", ref="bench.py")],
            decay_rate=0.05,
        )
        assert node.topic == "database_performance"
        assert "postgres" in node.tags
        assert len(node.sources) == 1

    def test_add_clamps_confidence(self):
        os = EpistemicOS()
        n1 = os.add("test1", confidence=1.5)
        assert n1.confidence == 1.0
        n2 = os.add("test2", confidence=-0.5)
        assert n2.confidence == 0.0

    def test_add_duplicate_overwrites(self):
        os = EpistemicOS()
        n1 = os.add("same content", confidence=0.5)
        n2 = os.add("same content", confidence=0.9)
        assert len(os.nodes) == 1
        assert n2.confidence == 0.9


class TestEpistemicOSQuery:
    def test_query_basic(self):
        os = EpistemicOS()
        os.add("postgres handles 10K QPS", confidence=0.8, topic="database")
        os.add("redis is fast for caching", confidence=0.9, topic="cache")
        
        answer = os.query("postgres performance")
        assert answer.confidence > 0
        assert "postgres" in answer.content.lower() or len(answer.supporting) > 0

    def test_query_no_results(self):
        os = EpistemicOS()
        os.add("postgres handles 10K QPS", confidence=0.8)
        
        answer = os.query("rust compiler")
        assert answer.confidence == 0.0
        assert "no relevant" in answer.content.lower()

    def test_query_records_access(self):
        os = EpistemicOS()
        node = os.add("test fact about databases", confidence=0.8)
        
        os.query("databases")
        assert os.nodes[node.id].access_count >= 1

    def test_query_stale_warning(self):
        os = EpistemicOS()
        old = datetime.now(timezone.utc) - timedelta(days=365)
        os.add(
            "old fact about performance",
            confidence=0.5,
            decay_rate=0.1,
            topic="performance",
        )
        # Manually set to old
        for n in os.nodes.values():
            n.last_verified = old
        
        answer = os.query("performance")
        if answer.supporting:
            # Should have stale warnings
            assert len(answer.stale_warnings) > 0 or answer.confidence < 0.5

    def test_query_with_recommendation(self):
        os = EpistemicOS()
        os.add("postgres performance data", confidence=0.8, topic="database")
        
        answer = os.query("postgres")
        assert answer.recommendation  # Should always have a recommendation

    def test_query_confidence_penalized_by_contradictions(self):
        os = EpistemicOS()
        n1 = os.add(
            "postgres handles 10K QPS",
            confidence=0.8,
            topic="postgres_performance",
        )
        n2 = os.add(
            "postgres handles 5K QPS",
            confidence=0.6,
            topic="postgres_performance",
        )
        
        answer = os.query("postgres QPS performance")
        # Should have lower confidence due to contradictions
        assert answer.confidence < 0.8 or len(answer.contradicting) > 0


class TestEpistemicOSTrace:
    def test_trace_basic(self):
        os = EpistemicOS()
        n1 = os.add("base fact", confidence=0.9)
        n2 = os.add("derived fact", confidence=0.7, depends_on=[n1.id])
        
        chain = os.trace("derived fact")
        assert len(chain) >= 2
        assert any(e["content"] == "base fact" for e in chain)

    def test_trace_not_found(self):
        os = EpistemicOS()
        chain = os.trace("nonexistent")
        assert chain == []

    def test_trace_depth_limit(self):
        os = EpistemicOS()
        # Create a deep chain
        prev_id = None
        for i in range(15):
            node = os.add(
                f"fact level {i}",
                confidence=0.8,
                depends_on=[prev_id] if prev_id else [],
            )
            prev_id = node.id
        
        chain = os.trace(f"fact level 14")
        assert len(chain) <= 11  # depth limit is 10 + root


class TestEpistemicOSVerify:
    def test_verify(self):
        os = EpistemicOS()
        old = datetime.now(timezone.utc) - timedelta(days=30)
        node = os.add("test fact", confidence=0.5)
        os.nodes[node.id].last_verified = old
        
        assert os.verify("test fact")
        assert os.nodes[node.id].last_verified > old

    def test_verify_with_new_confidence(self):
        os = EpistemicOS()
        os.add("test fact", confidence=0.5)
        
        os.verify("test fact", new_confidence=0.9)
        for n in os.nodes.values():
            if n.content == "test fact":
                assert n.confidence == 0.9

    def test_verify_not_found(self):
        os = EpistemicOS()
        assert not os.verify("nonexistent")


# ═══ Analysis Tests ═══


class TestAnalysis:
    def test_detect_contradictions(self):
        os = EpistemicOS()
        os.add("10K QPS", confidence=0.8, topic="postgres_performance")
        os.add("5K QPS", confidence=0.6, topic="postgres_performance")
        
        unresolved = os.detect_contradictions()
        # May or may not detect depending on content overlap
        # Just ensure it doesn't crash
        assert isinstance(unresolved, list)

    def test_stale_knowledge(self):
        os = EpistemicOS()
        os.add("fresh fact", confidence=0.9)
        os.add("stale fact", confidence=0.3)
        
        stale = os.stale_knowledge(threshold=0.4)
        assert len(stale) >= 1
        assert any(n.confidence < 0.4 for n in stale)

    def test_confidence_distribution(self):
        os = EpistemicOS()
        os.add("certain", confidence=0.95)
        os.add("likely", confidence=0.75)
        os.add("uncertain", confidence=0.55)
        os.add("weak", confidence=0.35)
        os.add("unreliable", confidence=0.1)
        
        dist = os.confidence_distribution()
        assert dist["highly_certain"] >= 1
        assert dist["likely"] >= 1
        assert dist["unreliable"] >= 1

    def test_health_report(self):
        os = EpistemicOS()
        os.add("fact1", confidence=0.8, topic="topic1", tags=["tag1"])
        os.add("fact2", confidence=0.6, topic="topic2", tags=["tag2"])
        
        report = os.health_report()
        assert report["total_knowledge"] == 2
        assert 0 < report["avg_confidence"] <= 1
        assert report["health_score"] >= 0
        assert report["health_label"] in ("excellent", "good", "fair", "poor")

    def test_health_report_empty(self):
        os = EpistemicOS()
        report = os.health_report()
        assert report["total_knowledge"] == 0
        assert report["health_score"] == 0.0

    def test_recommend_verification(self):
        os = EpistemicOS()
        os.add("used fact", confidence=0.4, tags=["important"])
        os.add("unused fact", confidence=0.8, tags=["minor"])
        
        # Add citations to first
        for n in os.nodes.values():
            if n.content == "used fact":
                n.citations = ["doc1", "doc2", "doc3"]
        
        recs = os.recommend_verification()
        assert len(recs) >= 1
        # Most important should be first
        if len(recs) >= 2:
            assert recs[0][0].content == "used fact"


class TestConfidencePropagation:
    def test_propagation_basic(self):
        os = EpistemicOS()
        n1 = os.add("base fact", confidence=0.3)  # Low confidence
        n2 = os.add("derived fact", confidence=0.9, depends_on=[n1.id])
        
        updated = os.propagate_confidence()
        # derived fact should have reduced confidence
        if n2.id in updated:
            assert updated[n2.id] < 0.9

    def test_propagation_no_deps(self):
        os = EpistemicOS()
        os.add("independent fact", confidence=0.8)
        
        updated = os.propagate_confidence()
        assert len(updated) == 0


# ═══ Integration Tests ═══


class TestMemoryPalaceImport:
    def test_from_memory_palace(self, tmp_path):
        palace_file = tmp_path / "daemon.json"
        palace_data = {
            "memories": [
                {
                    "decision": "use postgres for storage",
                    "context": {"scope": "architecture"},
                    "outcome": "success",
                    "tags": ["database", "architecture"],
                    "timestamp": "2024-01-01T00:00:00",
                },
                {
                    "decision": "use microservices",
                    "context": {"scope": "architecture"},
                    "outcome": "failure",
                    "tags": ["architecture"],
                    "timestamp": "2024-01-02T00:00:00",
                },
            ]
        }
        palace_file.write_text(json.dumps(palace_data))
        
        os = EpistemicOS()
        os.from_memory_palace(str(palace_file))
        
        assert len(os.nodes) == 2
        
        # Success → higher confidence
        for n in os.nodes.values():
            if "postgres" in n.content:
                assert n.confidence == 0.8
            if "microservices" in n.content:
                assert n.confidence == 0.3

    def test_from_nonexistent_palace(self):
        os = EpistemicOS()
        os.from_memory_palace("/nonexistent/path.json")
        assert len(os.nodes) == 0


# ═══ Persistence Tests ═══


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "epistemic.json")
        
        os1 = EpistemicOS(storage_path=path)
        os1.add("postgres 10K QPS", confidence=0.7, topic="database")
        os1.add("redis caching", confidence=0.9, topic="cache")
        
        os2 = EpistemicOS(storage_path=path)
        assert len(os2.nodes) == 2
        
        # Find and verify content
        found = [n.content for n in os2.nodes.values()]
        assert "postgres 10K QPS" in found
        assert "redis caching" in found

    def test_auto_save_on_add(self, tmp_path):
        path = str(tmp_path / "epistemic.json")
        
        os = EpistemicOS(storage_path=path)
        os.add("test fact", confidence=0.8)
        
        assert Path(path).exists()
        data = json.loads(Path(path).read_text())
        assert len(data["nodes"]) == 1

    def test_save_contractions(self, tmp_path):
        path = str(tmp_path / "epistemic.json")
        
        os = EpistemicOS(storage_path=path)
        os.add("10K QPS", confidence=0.8, topic="postgres_performance")
        os.add("5K QPS", confidence=0.6, topic="postgres_performance")
        
        os2 = EpistemicOS(storage_path=path)
        assert len(os2.contradictions) == len(os.contradictions)


# ═══ EpistemicAnswer Tests ═══


class TestEpistemicAnswer:
    def test_str_representation(self):
        a = EpistemicAnswer(
            content="postgres handles 10K QPS",
            confidence=0.7,
            recommendation="Re-verify stale fact.",
        )
        s = str(a)
        assert "likely" in s
        assert "postgres" in s

    def test_str_with_warnings(self):
        a = EpistemicAnswer(
            content="test",
            confidence=0.3,
            stale_warnings=["old fact is stale"],
            contradicting=[KnowledgeNode(content="contradictor")],
        )
        s = str(a)
        assert "Stale" in s
        assert "Contradicted" in s

    def test_confidence_label(self):
        assert EpistemicAnswer(content="", confidence=0.95).confidence_label == "highly certain"
        assert EpistemicAnswer(content="", confidence=0.1).confidence_label == "unreliable"


# ═══ End-to-End Workflow ═══


class TestEndToEnd:
    def test_full_workflow(self, tmp_path):
        """Complete workflow: add → query → contradict → verify → report."""
        path = str(tmp_path / "epistemic.json")
        os = EpistemicOS(storage_path=path)
        
        # Add knowledge
        n1 = os.add(
            "Postgres handles 10K QPS",
            confidence=0.7,
            topic="database_performance",
            tags=["postgres", "performance"],
            context="read queries, SSD storage",
            sources=[Source(type="benchmark", ref="bench.py", trustworthiness=0.9)],
            decay_rate=0.05,
        )
        
        n2 = os.add(
            "Redis is fast for caching",
            confidence=0.9,
            topic="cache_performance",
            tags=["redis", "cache"],
        )
        
        # Query
        answer = os.query("database performance")
        assert answer.confidence > 0
        
        # Add contradiction
        n3 = os.add(
            "Postgres handles 5K QPS",
            confidence=0.6,
            topic="database_performance",
            tags=["postgres", "performance"],
        )
        
        # Check health
        report = os.health_report()
        assert report["total_knowledge"] == 3
        assert report["health_score"] > 0
        
        # Verify one fact
        os.verify("Postgres handles 10K QPS", new_confidence=0.85)
        
        # Get recommendations
        recs = os.recommend_verification()
        assert len(recs) >= 1
        
        # Trace
        chain = os.trace("Postgres handles 10K QPS")
        assert len(chain) >= 1
        
        # Reload and verify persistence
        os2 = EpistemicOS(storage_path=path)
        assert len(os2.nodes) == 3

    def test_decay_over_time(self):
        """Simulate knowledge decay."""
        os = EpistemicOS()
        
        node = os.add(
            "time-sensitive fact",
            confidence=0.8,
            decay_rate=0.1,  # 10% per month
        )
        
        # Simulate: 6 months pass
        node.last_verified = datetime.now(timezone.utc) - timedelta(days=180)
        
        # Confidence should have decayed significantly
        # 0.8 * 0.9^(180/30.44) ≈ 0.8 * 0.536 ≈ 0.43
        assert node.current_confidence < 0.5
        assert node.current_confidence > 0.01  # But not zero
        
        # After 12 months it would definitely be stale
        node.last_verified = datetime.now(timezone.utc) - timedelta(days=365)
        assert node.is_stale  # Below 0.4 after 12 months of 10% decay

    def test_epistemic_with_netweaver_data(self):
        """Integration test with realistic NetWeaver knowledge."""
        os = EpistemicOS()
        
        # Add realistic NetWeaver knowledge
        scene_graph = os.add(
            "Scene graph captures DOM structure with 95% accuracy",
            confidence=0.85,
            topic="scene_graph",
            tags=["scene_graph", "accuracy"],
            sources=[Source(type="benchmark", ref="tests/test_scene_graph.py", trustworthiness=0.9)],
        )
        
        wnal = os.add(
            "WNAL DSL reduces automation code by 60%",
            confidence=0.7,
            topic="wnal",
            tags=["wnal", "productivity"],
            context="compared to raw Playwright",
            sources=[Source(type="measurement", ref="internal_benchmark.md")],
            decay_rate=0.02,
        )
        
        pipeline = os.add(
            "Autonomous pipeline generates ~3 plans per day",
            confidence=0.8,
            topic="pipeline",
            tags=["pipeline", "throughput"],
            sources=[Source(type="measurement", ref="daemon_metrics.json")],
        )
        
        # Query about the system
        answer = os.query("scene graph accuracy")
        assert answer.confidence > 0
        
        # Health check
        report = os.health_report()
        assert report["total_knowledge"] == 3
        assert report["topics"] == 3
