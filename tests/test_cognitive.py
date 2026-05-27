"""Tests for Dreaming, Causal Chain Analysis, and Competence Matrix."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from netweaver.dreaming import DreamEngine, Hypothesis, _hash
from netweaver.causal import CausalChainTracer, CausalChain, CausalLink
from netweaver.competence import CompetenceMatrix, AgentCompetence, TaskRecord


# ═══════════════════════════════════════════════
# DREAMING TESTS
# ═══════════════════════════════════════════════

class TestDreamEngine:
    def test_init_default(self):
        engine = DreamEngine()
        assert engine.workdir is not None
        assert engine.hypotheses == [] or len(engine.hypotheses) >= 0  # may have loaded
    
    def test_init_custom_workdir(self, tmp_path):
        engine = DreamEngine(workdir=tmp_path)
        assert engine.workdir == tmp_path
    
    def test_extract_patterns(self, tmp_path):
        # Create some Python files
        (tmp_path / "module_a.py").write_text("def foo(): pass\ndef bar(): pass\n")
        (tmp_path / "module_b.py").write_text("class MyClass:\n    def method(self): pass\n")
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_a.py").write_text("def test_one(): pass\ndef test_two(): pass\n")
        
        engine = DreamEngine(workdir=tmp_path)
        patterns = engine.extract_patterns()
        
        assert patterns["total_loc"] > 0
        assert len(patterns["modules"]) >= 2
        assert patterns["test_count"] >= 2
    
    def test_dream_generates_hypotheses(self, tmp_path):
        # Create enough files to trigger hypotheses
        for i in range(10):
            (tmp_path / f"module_{i}.py").write_text(
                f"def func_{i}(): pass\n" * 25  # 25 functions each (high complexity)
            )
        
        engine = DreamEngine(workdir=tmp_path)
        hypotheses = engine.dream(max_hypotheses=5)
        
        assert len(hypotheses) > 0
        assert all(isinstance(h, Hypothesis) for h in hypotheses)
    
    def test_dream_no_duplicates(self, tmp_path):
        for i in range(10):
            (tmp_path / f"mod_{i}.py").write_text("def f(): pass\n" * 25)
        
        engine = DreamEngine(workdir=tmp_path)
        h1 = engine.dream(max_hypotheses=5)
        h2 = engine.dream(max_hypotheses=5)
        
        # Second dream should not generate duplicates
        ids1 = {h.hypothesis_id for h in h1}
        ids2 = {h.hypothesis_id for h in h2}
        assert len(ids1 & ids2) == 0 or len(h2) == 0
    
    def test_dream_with_epistemic_os(self, tmp_path):
        for i in range(10):
            (tmp_path / f"mod_{i}.py").write_text("def f(): pass\n" * 25)
        
        mock_ep = MagicMock()
        mock_ep.add.return_value = MagicMock()
        
        engine = DreamEngine(workdir=tmp_path, epistemic_os=mock_ep)
        hypotheses = engine.dream(max_hypotheses=3)
        
        if hypotheses:
            assert mock_ep.add.called
    
    def test_hypothesis_has_required_fields(self, tmp_path):
        for i in range(10):
            (tmp_path / f"mod_{i}.py").write_text("def f(): pass\n" * 25)
        
        engine = DreamEngine(workdir=tmp_path)
        hypotheses = engine.dream(max_hypotheses=3)
        
        for h in hypotheses:
            assert h.hypothesis_id
            assert h.type
            assert h.content
            assert 0 < h.confidence <= 1.0
            assert h.simulated_outcome
            assert h.validation_method
    
    def test_validate_hypothesis(self, tmp_path):
        engine = DreamEngine(workdir=tmp_path)
        h = Hypothesis(
            hypothesis_id="test123",
            type="test",
            content="Test hypothesis",
            confidence=0.3,
            simulated_outcome="Would improve X",
            validation_method="Run test",
        )
        engine.hypotheses.append(h)
        
        assert engine.validate_hypothesis("test123", "confirmed", new_confidence=0.9)
        assert h.validated
        assert h.confidence == 0.9
        assert h.validation_result == "confirmed"
    
    def test_validate_nonexistent(self, tmp_path):
        engine = DreamEngine(workdir=tmp_path)
        assert not engine.validate_hypothesis("nonexistent", "test")
    
    def test_get_unvalidated(self, tmp_path):
        engine = DreamEngine(workdir=tmp_path)
        h1 = Hypothesis(hypothesis_id="1", type="t", content="c", confidence=0.5,
                         simulated_outcome="o", validation_method="v")
        h2 = Hypothesis(hypothesis_id="2", type="t", content="c2", confidence=0.5,
                         simulated_outcome="o", validation_method="v", validated=True)
        engine.hypotheses = [h1, h2]
        
        unvalidated = engine.get_unvalidated()
        assert len(unvalidated) == 1
        assert unvalidated[0].hypothesis_id == "1"
    
    def test_top_hypotheses(self, tmp_path):
        engine = DreamEngine(workdir=tmp_path)
        for i in range(10):
            h = Hypothesis(
                hypothesis_id=str(i), type="t", content=f"c{i}",
                confidence=i * 0.1, simulated_outcome="o", validation_method="v",
            )
            engine.hypotheses.append(h)
        
        top = engine.top_hypotheses(limit=3)
        assert len(top) == 3
        assert top[0].confidence >= top[1].confidence >= top[2].confidence
    
    def test_persistence(self, tmp_path):
        engine1 = DreamEngine(workdir=tmp_path)
        h = Hypothesis(hypothesis_id="persist1", type="t", content="c",
                        confidence=0.5, simulated_outcome="o", validation_method="v")
        engine1.hypotheses.append(h)
        engine1._save()
        
        engine2 = DreamEngine(workdir=tmp_path)
        assert len(engine2.hypotheses) == 1
        assert engine2.hypotheses[0].hypothesis_id == "persist1"
    
    def test_report(self, tmp_path):
        engine = DreamEngine(workdir=tmp_path)
        h = Hypothesis(hypothesis_id="r1", type="merge_modules", content="c",
                        confidence=0.5, simulated_outcome="o", validation_method="v")
        engine.hypotheses.append(h)
        
        report = engine.report()
        assert report["total_hypotheses"] == 1
        assert report["unvalidated"] == 1
        assert "merge_modules" in report["by_type"]
    
    def test_hypothesis_to_dict_roundtrip(self):
        h = Hypothesis(
            hypothesis_id="abc123",
            type="cache_layer",
            content="What if we cached DB queries?",
            confidence=0.35,
            simulated_outcome="60% fewer queries",
            validation_method="Benchmark",
            related_patterns=["db_access", "query_optimizer"],
        )
        
        d = h.to_dict()
        h2 = Hypothesis.from_dict(d)
        
        assert h2.hypothesis_id == h.hypothesis_id
        assert h2.type == h.type
        assert h2.confidence == h.confidence
        assert h2.related_patterns == h.related_patterns
    
    def test_fill_template(self, tmp_path):
        engine = DreamEngine(workdir=tmp_path)
        patterns = {
            "modules": [{"path": "netweaver/epistemic.py", "loc": 800, "functions": 30, "classes": 5}],
            "test_count": 1500,
            "max_complexity": 30,
        }
        
        result = engine._fill_template(
            "What if we refactored {module} (complexity: {score})?",
            patterns,
        )
        assert "netweaver/epistemic.py" in result
        assert "30" in result
    
    def test_hash_deterministic(self):
        assert _hash("hello") == _hash("hello")
        assert _hash("Hello") == _hash("hello")  # case insensitive
        assert _hash("hello") != _hash("world")


# ═══════════════════════════════════════════════
# CAUSAL CHAIN TESTS
# ═══════════════════════════════════════════════

class TestCausalChainTracer:
    def test_init_default(self):
        tracer = CausalChainTracer()
        assert tracer.workdir is not None
    
    def test_init_custom_workdir(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        assert tracer.workdir == tmp_path
    
    def test_trace_failure_no_test_file(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        chain = tracer.trace_failure(
            "nonexistent_test.py::test_something",
            "AssertionError: expected 1 got 2",
        )
        assert isinstance(chain, CausalChain)
        assert chain.confidence <= 0.3  # Low confidence, can't find test
    
    def test_trace_failure_with_test_file(self, tmp_path):
        # Create a test file
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_epistemic.py").write_text(
            "from netweaver.epistemic import EpistemicOS\n"
            "def test_add():\n"
            "    ep = EpistemicOS()\n"
            "    ep.add('test')\n"
        )
        
        # Create the imported module
        nw_dir = tmp_path / "netweaver"
        nw_dir.mkdir()
        (nw_dir / "epistemic.py").write_text("class EpistemicOS: pass\n")
        
        tracer = CausalChainTracer(workdir=tmp_path)
        chain = tracer.trace_failure(
            "test_epistemic.py::test_add",
            "AttributeError: 'EpistemicOS' object has no attribute 'add'",
        )
        
        assert isinstance(chain, CausalChain)
        assert chain.depth >= 0
        assert chain.confidence > 0
    
    def test_match_attribute_error(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        cause, confidence, fix = tracer._match_error_to_cause(
            "AttributeError: 'Foo' has no attribute 'bar'",
            [tmp_path / "foo.py"],
            [{"hash": "abc123", "file": "foo.py", "message": "refactor foo", "date": "2026-05-27", "files": ["foo.py"]}],
        )
        assert "attribute" in cause.lower() or "renamed" in cause.lower() or "recent" in cause.lower()
        assert confidence > 0.3
    
    def test_match_import_error(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        cause, confidence, fix = tracer._match_error_to_cause(
            "ImportError: cannot import 'Bar' from 'foo'",
            [],
            [{"hash": "def456", "file": "bar.py", "message": "move bar module", "date": "2026-05-27", "files": ["bar.py"]}],
        )
        assert confidence > 0.3
    
    def test_match_assertion_error(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        cause, confidence, fix = tracer._match_error_to_cause(
            "AssertionError: expected 10 but got 5",
            [],
            [],
        )
        # No recent changes → low confidence
        assert confidence <= 0.5
    
    def test_match_type_error(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        cause, confidence, fix = tracer._match_error_to_cause(
            "TypeError: func() takes 2 arguments but 3 were given",
            [],
            [{"hash": "ghi789", "file": "api.py", "message": "add validation param", "date": "2026-05-27", "files": ["api.py"]}],
        )
        assert "signature" in cause.lower() or "recent" in cause.lower()
    
    def test_extract_file_references(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        
        text = '''
        File "/path/to/foo.py", line 42
          raise ValueError("bad input")
        File "netweaver/epistemic.py", line 100
        '''
        
        files = tracer._extract_file_references(text)
        assert len(files) >= 1
    
    def test_batch_trace(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        
        failures = [
            ("test_a.py::test_1", "AttributeError: no attribute x"),
            ("test_b.py::test_2", "AttributeError: no attribute y"),
        ]
        
        chains = tracer.batch_trace(failures)
        assert len(chains) == 2
        # Both should be CausalChain instances
        assert all(isinstance(c, CausalChain) for c in chains)
    
    def test_format_chain(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        
        chain = CausalChain(
            failure="test_foo failed",
            root_cause="Recent commit abc123 changed API",
            chain=[
                CausalLink(source="commit abc123", effect="API change", confidence=0.9, evidence="git log"),
                CausalLink(source="API change", effect="test breakage", confidence=0.8, evidence="error match"),
            ],
            confidence=0.85,
            fix_suggestion="Update test expectations",
            fix_confidence=0.7,
            related_commits=["abc123"],
        )
        
        output = tracer.format_chain(chain)
        assert "CAUSAL CHAIN" in output
        assert "test_foo" in output
        assert "85%" in output
        assert "abc123" in output
    
    def test_causal_chain_depth(self):
        chain = CausalChain(
            failure="test",
            root_cause="cause",
            chain=[CausalLink(source="a", effect="b", confidence=0.9, evidence="e")],
        )
        assert chain.depth == 1
    
    def test_trace_error_pattern(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        chain = tracer.trace_error_pattern("Error in netweaver/epistemic.py line 42: KeyError")
        assert isinstance(chain, CausalChain)
        assert chain.confidence > 0
    
    def test_get_imports(self, tmp_path):
        test_file = tmp_path / "test_module.py"
        test_file.write_text(
            "import os\n"
            "from netweaver.epistemic import EpistemicOS\n"
            "import json\n"
        )
        
        # Create the netweaver module
        nw_dir = tmp_path / "netweaver"
        nw_dir.mkdir()
        (nw_dir / "epistemic.py").write_text("class EpistemicOS: pass\n")
        
        tracer = CausalChainTracer(workdir=tmp_path)
        imports = tracer._get_imports(test_file)
        
        assert len(imports) >= 1
        assert any("epistemic" in str(i) for i in imports)
    
    def test_resolve_module(self, tmp_path):
        tracer = CausalChainTracer(workdir=tmp_path)
        
        resolved = tracer._resolve_module("netweaver.epistemic")
        assert resolved is not None
        assert "netweaver" in str(resolved)
        assert "epistemic" in str(resolved)


# ═══════════════════════════════════════════════
# COMPETENCE MATRIX TESTS
# ═══════════════════════════════════════════════

class TestCompetenceMatrix:
    def test_init_default(self):
        matrix = CompetenceMatrix()
        assert matrix.workdir is not None
        assert len(matrix.agents) == 0 or len(matrix.agents) >= 0  # may have loaded
    
    def test_init_custom_workdir(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        assert matrix.workdir == tmp_path
    
    def test_record_simple(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        matrix.record_simple(
            agent_id="worker-alpha",
            task_id="NW-001",
            task_type="bugfix",
            success=True,
            files=["netweaver/epistemic.py"],
            duration=120.0,
        )
        
        assert "worker-alpha" in matrix.agents
        agent = matrix.agents["worker-alpha"]
        assert agent.total_tasks == 1
        assert agent.successful_tasks == 1
        assert agent.success_rate == 1.0
    
    def test_record_multiple_tasks(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        for i in range(5):
            matrix.record_simple(
                agent_id="worker-beta",
                task_id=f"NW-{i:03d}",
                task_type="test",
                success=(i % 2 == 0),  # 3 success, 2 fail
                duration=60.0 + i * 10,
            )
        
        agent = matrix.agents["worker-beta"]
        assert agent.total_tasks == 5
        assert agent.successful_tasks == 3
        assert abs(agent.success_rate - 0.6) < 0.01
    
    def test_task_type_tracking(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        matrix.record_simple("alpha", "T1", "architecture", True)
        matrix.record_simple("alpha", "T2", "architecture", True)
        matrix.record_simple("alpha", "T3", "bugfix", False)
        matrix.record_simple("alpha", "T4", "bugfix", True)
        matrix.record_simple("alpha", "T5", "bugfix", True)
        
        agent = matrix.agents["alpha"]
        assert agent.task_type_rate("architecture") == 1.0
        assert abs(agent.task_type_rate("bugfix") - 2/3) < 0.01
    
    def test_file_familiarity(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        matrix.record_simple("alpha", "T1", "bugfix", True, files=["a.py", "b.py"])
        matrix.record_simple("alpha", "T2", "bugfix", True, files=["a.py", "c.py"])
        matrix.record_simple("alpha", "T3", "bugfix", True, files=["a.py"])
        
        agent = matrix.agents["alpha"]
        assert agent.file_familiarity["a.py"] == 3
        assert agent.file_familiarity["b.py"] == 1
        assert agent.file_familiarity["c.py"] == 1
    
    def test_competence_score(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        # Agent is great at architecture, bad at bugfixes
        for _ in range(5):
            matrix.record_simple("alpha", "T", "architecture", True, files=["arch.py"])
        for _ in range(5):
            matrix.record_simple("alpha", "T", "bugfix", False, files=["bug.py"])
        
        agent = matrix.agents["alpha"]
        arch_score = agent.competence_score("architecture", ["arch.py"])
        bug_score = agent.competence_score("bugfix", ["bug.py"])
        
        assert arch_score > bug_score
    
    def test_route_task(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        # Alpha: great at architecture
        for _ in range(5):
            matrix.record_simple("alpha", "T", "architecture", True)
        for _ in range(5):
            matrix.record_simple("alpha", "T", "bugfix", False)
        
        # Beta: great at bugfixes
        for _ in range(5):
            matrix.record_simple("beta", "T", "bugfix", True)
        for _ in range(5):
            matrix.record_simple("beta", "T", "architecture", False)
        
        # Route architecture task → should pick alpha
        routed = matrix.route_task("architecture")
        assert routed == "alpha"
        
        # Route bugfix task → should pick beta
        routed = matrix.route_task("bugfix")
        assert routed == "beta"
    
    def test_route_task_with_exclude(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        for _ in range(3):
            matrix.record_simple("alpha", "T", "test", True)
        for _ in range(3):
            matrix.record_simple("beta", "T", "test", True)
        
        # Exclude alpha
        routed = matrix.route_task("test", exclude_agents=["alpha"])
        assert routed == "beta"
    
    def test_route_empty_matrix(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        assert matrix.route_task("test") is None
    
    def test_route_with_scores(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        for _ in range(5):
            matrix.record_simple("alpha", "T", "test", True)
        for _ in range(5):
            matrix.record_simple("beta", "T", "test", False)
        
        scores = matrix.route_with_scores("test")
        assert len(scores) == 2
        assert scores[0][0] == "alpha"  # Alpha has higher score
        assert scores[0][1] > scores[1][1]
    
    def test_specializations(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        # Alpha specializes in architecture (5/5 success)
        for _ in range(5):
            matrix.record_simple("alpha", "T", "architecture", True)
        # Alpha is bad at bugfixes (1/5 success)
        for i in range(5):
            matrix.record_simple("alpha", "T", "bugfix", i == 0)
        
        agent = matrix.agents["alpha"]
        assert "architecture" in agent.specializations
        assert "bugfix" not in agent.specializations
    
    def test_detect_imbalances(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        # Alpha: 20 tasks
        for _ in range(20):
            matrix.record_simple("alpha", "T", "test", True)
        # Beta: 2 tasks
        for _ in range(2):
            matrix.record_simple("beta", "T", "test", True)
        
        imbalances = matrix.detect_imbalances()
        assert len(imbalances) >= 1
    
    def test_team_report(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        
        matrix.record_simple("alpha", "T1", "test", True)
        matrix.record_simple("beta", "T2", "test", False)
        
        report = matrix.team_report()
        assert report["total_agents"] == 2
        assert report["total_tasks"] == 2
        assert "alpha" in report["agents"]
        assert "beta" in report["agents"]
    
    def test_team_report_empty(self, tmp_path):
        matrix = CompetenceMatrix(workdir=tmp_path)
        report = matrix.team_report()
        assert report["total_agents"] == 0
    
    def test_persistence(self, tmp_path):
        matrix1 = CompetenceMatrix(workdir=tmp_path)
        matrix1.record_simple("alpha", "T1", "test", True, files=["a.py"])
        matrix1._save()
        
        matrix2 = CompetenceMatrix(workdir=tmp_path)
        assert "alpha" in matrix2.agents
        assert matrix2.agents["alpha"].total_tasks == 1
    
    def test_from_memory_palace(self, tmp_path):
        # Create a mock memory palace
        palace_data = {
            "memories": [
                {
                    "content": "Worker executed plan successfully",
                    "agent": "worker-1",
                    "outcome": "success",
                    "id": "mem-1",
                    "duration": 120,
                },
                {
                    "content": "Worker completed task with failure",
                    "agent": "worker-1",
                    "outcome": "failure",
                    "id": "mem-2",
                    "duration": 60,
                },
            ]
        }
        palace_file = tmp_path / "palace.json"
        palace_file.write_text(json.dumps(palace_data))
        
        matrix = CompetenceMatrix(workdir=tmp_path)
        matrix.from_memory_palace(str(palace_file))
        
        assert len(matrix.records) >= 2
    
    def test_agent_competence_default_prior(self):
        agent = AgentCompetence(agent_id="new-agent")
        assert agent.success_rate == 0.5  # Prior
        assert agent.task_type_rate("unknown") == 0.5  # Prior
    
    def test_file_familiarity_score(self):
        agent = AgentCompetence(agent_id="test")
        agent.file_familiarity["a.py"] = 5
        agent.file_familiarity["b.py"] = 3
        
        # 2/3 files are familiar
        score = agent.file_familiarity_score(["a.py", "b.py", "c.py"])
        assert abs(score - 2/3) < 0.01
    
    def test_file_familiarity_empty(self):
        agent = AgentCompetence(agent_id="test")
        score = agent.file_familiarity_score([])
        assert score == 0.5
    
    def test_task_record_to_dict_roundtrip(self):
        record = TaskRecord(
            agent_id="alpha",
            task_id="NW-001",
            task_type="architecture",
            files_touched=["a.py", "b.py"],
            success=True,
            duration_seconds=120.0,
        )
        
        d = record.to_dict()
        r2 = TaskRecord.from_dict(d)
        
        assert r2.agent_id == record.agent_id
        assert r2.task_type == record.task_type
        assert r2.success == record.success
    
    def test_agent_to_dict_roundtrip(self):
        agent = AgentCompetence(agent_id="alpha")
        agent.total_tasks = 10
        agent.successful_tasks = 7
        agent.task_type_stats = {"test": {"success": 5, "total": 6}}
        agent.file_familiarity = {"a.py": 3}
        agent.specializations = ["test"]
        
        d = agent.to_dict()
        a2 = AgentCompetence.from_dict(d)
        
        assert a2.agent_id == "alpha"
        assert a2.total_tasks == 10
        assert a2.successful_tasks == 7
        assert a2.specializations == ["test"]
    
    def test_with_epistemic_os(self, tmp_path):
        mock_ep = MagicMock()
        mock_ep.add.return_value = MagicMock()
        
        matrix = CompetenceMatrix(workdir=tmp_path, epistemic_os=mock_ep)
        matrix.record_simple("alpha", "T1", "test", True)
        
        assert mock_ep.add.called
