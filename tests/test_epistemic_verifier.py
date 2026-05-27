"""Tests for Epistemic Verifier and Site Skill integration."""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from netweaver.epistemic import EpistemicOS, Source
from netweaver.epistemic_verifier import AutoVerifier
from netweaver.epistemic_site_skill import EpistemicSiteSkill, EpistemicSkillStore
from netweaver.site_skill import SiteSkill


# ── Fixtures ──

@pytest.fixture
def tmp_ep(tmp_path):
    """Create a temp EpistemicOS."""
    storage = str(tmp_path / "epistemic.json")
    return EpistemicOS(storage_path=storage)


@pytest.fixture
def verifier(tmp_ep):
    """Create an AutoVerifier."""
    return AutoVerifier(tmp_ep)


@pytest.fixture
def tmp_skills(tmp_path):
    """Create a temp skills directory."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return skills_dir


# ── EpistemicOS.update_node tests ──

class TestUpdateNode:
    def test_update_confidence(self, tmp_ep):
        node = tmp_ep.add("Test fact", confidence=0.5)
        assert tmp_ep.update_node(node.id, confidence=0.9)
        updated = tmp_ep._find_node(node.id)
        assert updated.confidence == 0.9

    def test_update_tags(self, tmp_ep):
        node = tmp_ep.add("Test fact", confidence=0.8, tags=["a"])
        assert tmp_ep.update_node(node.id, tags=["b", "c"])
        updated = tmp_ep._find_node(node.id)
        assert "a" in updated.tags
        assert "b" in updated.tags
        assert "c" in updated.tags

    def test_update_last_verified(self, tmp_ep):
        node = tmp_ep.add("Test fact", confidence=0.8)
        custom_time = datetime.now() - timedelta(hours=1)
        assert tmp_ep.update_node(node.id, last_verified=custom_time)
        updated = tmp_ep._find_node(node.id)
        assert updated.last_verified == custom_time

    def test_update_verification_method(self, tmp_ep):
        node = tmp_ep.add("Test fact", confidence=0.8)
        assert tmp_ep.update_node(node.id, verification_method="pytest")
        updated = tmp_ep._find_node(node.id)
        refs = [s.ref for s in updated.sources]
        assert "pytest" in refs

    def test_update_nonexistent_returns_false(self, tmp_ep):
        assert not tmp_ep.update_node("nonexistent_id", confidence=0.5)

    def test_update_clamps_confidence(self, tmp_ep):
        node = tmp_ep.add("Test fact", confidence=0.5)
        tmp_ep.update_node(node.id, confidence=1.5)
        assert tmp_ep._find_node(node.id).confidence == 1.0
        tmp_ep.update_node(node.id, confidence=-0.5)
        assert tmp_ep._find_node(node.id).confidence == 0.0

    def test_update_persists(self, tmp_ep):
        storage = tmp_ep._storage_path
        node = tmp_ep.add("Test fact", confidence=0.5)
        tmp_ep.update_node(node.id, confidence=0.9, tags=["verified"])

        ep2 = EpistemicOS(storage_path=storage)
        updated = ep2._find_node(node.id)
        assert updated.confidence == 0.9
        assert "verified" in updated.tags

    def test_update_duplicate_verification_method(self, tmp_ep):
        node = tmp_ep.add("Test fact", confidence=0.8)
        tmp_ep.update_node(node.id, verification_method="pytest")
        tmp_ep.update_node(node.id, verification_method="pytest")
        updated = tmp_ep._find_node(node.id)
        pytest_refs = [s for s in updated.sources if s.ref == "pytest"]
        assert len(pytest_refs) == 1


# ── AutoVerifier tests ──

class TestAutoVerifier:
    def test_init(self, verifier):
        assert verifier.epistemic_os is not None
        assert verifier.skill_store is not None

    def test_verify_stale_knowledge_empty(self, verifier):
        results = verifier.verify_stale_knowledge()
        assert results["verified"] == 0
        assert results["failed"] == 0
        assert results["needs_manual"] == 0

    def test_verify_stale_knowledge_with_stale(self, verifier, tmp_ep):
        verifier.epistemic_os.add(
            "Old fact about testing",
            confidence=0.2,
            topic="testing",
            tags=["test"],
        )
        results = verifier.verify_stale_knowledge()
        assert len(results["details"]) > 0

    def test_is_testable_claim(self, verifier, tmp_ep):
        node = tmp_ep.add("All tests pass", confidence=0.8, topic="testing")
        assert verifier._is_testable_claim(node)

        node2 = tmp_ep.add("Build succeeds", confidence=0.8, topic="build")
        assert verifier._is_testable_claim(node2)

        node3 = tmp_ep.add("User prefers dark mode", confidence=0.8, topic="ui")
        assert not verifier._is_testable_claim(node3)

    def test_verify_testable_claim_tests(self, verifier, tmp_ep):
        node = tmp_ep.add("All tests pass in the project", confidence=0.5, topic="testing")
        result = verifier._verify_testable_claim(node)
        assert result["status"] in ("verified", "failed", "needs_manual")
        assert "node_id" in result

    def test_resolve_contradictions_empty(self, verifier):
        results = verifier.resolve_contradictions()
        assert results["total"] == 0
        assert results["resolved"] == 0

    def test_resolve_contradictions_with_data(self, verifier, tmp_ep):
        tmp_ep.add(
            "API handles 1000 QPS",
            confidence=0.9,
            topic="performance",
            sources=[Source(type="benchmark", ref="load_test.py")],
        )
        tmp_ep.add(
            "API handles 100 QPS",
            confidence=0.3,
            topic="performance",
            sources=[Source(type="hearsay", ref="forum_post")],
        )

        results = verifier.resolve_contradictions()
        assert results["total"] >= 1
        assert len(results["suggestions"]) >= 1

    def test_auto_resolve_keeps_higher_confidence(self, verifier, tmp_ep):
        tmp_ep.add(
            "Database handles 10K writes/sec",
            confidence=0.95,
            topic="performance",
            sources=[Source(type="benchmark", ref="load_test.py", trustworthiness=0.95)],
        )
        tmp_ep.add(
            "Database handles 100 writes/sec",
            confidence=0.2,
            topic="performance",
            sources=[Source(type="hearsay", ref="reddit", trustworthiness=0.2)],
        )

        results = verifier.resolve_contradictions()
        assert results["resolved"] >= 1

    def test_suggest_resolution_needs_manual(self, verifier, tmp_ep):
        tmp_ep.add(
            "Feature X works well",
            confidence=0.6,
            topic="feature",
            sources=[Source(type="manual", ref="dev1")],
        )
        tmp_ep.add(
            "Feature X has problems",
            confidence=0.55,
            topic="feature",
            sources=[Source(type="manual", ref="dev2")],
        )

        results = verifier.resolve_contradictions()
        for s in results.get("suggestions", []):
            if not s["auto_resolvable"]:
                assert "manual" in " ".join(s["reasoning"]).lower()

    def test_source_quality_empty(self, verifier, tmp_ep):
        node = tmp_ep.add("Fact without sources", confidence=0.5)
        quality = verifier._source_quality(node)
        assert quality == 0.3

    def test_source_quality_high_trust(self, verifier, tmp_ep):
        node = tmp_ep.add(
            "Benchmarked fact",
            confidence=0.9,
            sources=[Source(type="benchmark", ref="test.py", trustworthiness=0.95)],
        )
        quality = verifier._source_quality(node)
        assert quality > 0.9

    def test_calibrate_confidence_no_skills(self, verifier):
        results = verifier.calibrate_confidence()
        assert results["skills_calibrated"] == 0
        assert results["total_predictions"] == 0

    def test_run_full_verification_cycle(self, verifier, tmp_ep):
        tmp_ep.add("Some fact", confidence=0.8, topic="general")
        results = verifier.run_full_verification_cycle()
        assert "stale_knowledge" in results
        assert "contradictions" in results
        assert "calibration" in results
        assert "timestamp" in results

    def test_verification_history(self, verifier):
        verifier.run_full_verification_cycle()
        history = verifier.get_verification_history()
        assert len(history) >= 1

    def test_verify_node_site_skill_tag(self, verifier, tmp_ep):
        node = tmp_ep.add(
            "Site skill test",
            confidence=0.5,
            topic="site_skill",
            tags=["site_skill", "skill:test-id"],
        )
        result = verifier._verify_node(node)
        assert result["status"] in ("verified", "failed", "needs_manual")

    def test_verify_node_unknown_type(self, verifier, tmp_ep):
        node = tmp_ep.add(
            "Random subjective opinion about design",
            confidence=0.5,
            topic="opinion",
        )
        result = verifier._verify_node(node)
        assert result["status"] == "needs_manual"


# ── EpistemicSiteSkill tests ──

class TestEpistemicSiteSkill:
    def test_create(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-create",
        )
        ep_skill = EpistemicSiteSkill(skill)
        assert ep_skill.skill.name == "login"
        assert ep_skill.confidence == 0.5  # default

    def test_record_execution_success(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-success",
        )
        ep_skill = EpistemicSiteSkill(skill)

        ep_skill.record_execution(success=True)
        assert ep_skill.confidence > 0.5
        assert ep_skill.skill.execution_stats["success_count"] == 1

    def test_record_execution_failure(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-fail",
        )
        ep_skill = EpistemicSiteSkill(skill)
        ep_skill.confidence = 0.8

        ep_skill.record_execution(success=False)
        assert ep_skill.confidence < 0.8
        assert ep_skill.skill.execution_stats["fail_count"] == 1

    def test_is_stale(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-stale",
        )
        ep_skill = EpistemicSiteSkill(skill)
        ep_skill.last_verified = datetime.now() - timedelta(days=60)
        assert ep_skill.is_stale()

    def test_not_stale(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-fresh",
        )
        ep_skill = EpistemicSiteSkill(skill)
        assert not ep_skill.is_stale()

    def test_multiple_executions_converge(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-converge",
        )
        ep_skill = EpistemicSiteSkill(skill)
        ep_skill.confidence = 0.5

        for _ in range(10):
            ep_skill.record_execution(success=True)

        assert ep_skill.confidence > 0.8

    def test_current_confidence_decay(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-decay",
        )
        ep_skill = EpistemicSiteSkill(skill)
        ep_skill.confidence = 0.9
        ep_skill.decay_rate = 0.1
        ep_skill.last_verified = datetime.now() - timedelta(days=60)

        # Should be decayed after 2 months
        assert ep_skill.current_confidence < 0.9
        assert ep_skill.current_confidence > 0.01

    def test_get_calibration_score_no_predictions(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-no-pred",
        )
        ep_skill = EpistemicSiteSkill(skill)
        assert ep_skill.get_calibration_score() is None

    def test_get_calibration_score_with_predictions(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-calib",
        )
        ep_skill = EpistemicSiteSkill(skill)

        for _ in range(5):
            ep_skill.record_execution(success=True)

        score = ep_skill.get_calibration_score()
        assert score is not None
        assert 0 <= score <= 1

    def test_needs_verification_low_confidence(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-need-ver",
        )
        ep_skill = EpistemicSiteSkill(skill)
        ep_skill.confidence = 0.3
        assert ep_skill.needs_verification()

    def test_to_dict(self):
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-ep-dict",
        )
        ep_skill = EpistemicSiteSkill(skill)
        data = ep_skill.to_dict()
        assert "epistemic" in data
        assert "confidence" in data["epistemic"]
        assert "decay_rate" in data["epistemic"]


# ── EpistemicSkillStore tests ──

class TestEpistemicSkillStore:
    def test_create_default_dir(self):
        store = EpistemicSkillStore()
        assert store.skills_dir.exists()

    def test_load_all_empty(self, tmp_path):
        store = EpistemicSkillStore(skills_dir=tmp_path)
        skills = store.load_all()
        assert skills == []

    def test_get_stale_skills_empty(self, tmp_path):
        store = EpistemicSkillStore(skills_dir=tmp_path)
        stale = store.get_stale_skills(threshold_days=30)
        assert isinstance(stale, list)
        assert len(stale) == 0

    def test_get_low_confidence_skills_empty(self, tmp_path):
        store = EpistemicSkillStore(skills_dir=tmp_path)
        low = store.get_low_confidence_skills(min_confidence=0.6)
        assert isinstance(low, list)
        assert len(low) == 0

    def test_get_verification_priorities_empty(self, tmp_path):
        store = EpistemicSkillStore(skills_dir=tmp_path)
        priorities = store.get_verification_priorities()
        assert isinstance(priorities, list)


# ── Integration tests ──

class TestEpistemicIntegration:
    def test_full_lifecycle(self, tmp_ep):
        node = tmp_ep.add(
            "API latency is under 100ms",
            confidence=0.9,
            topic="performance",
            tags=["api", "latency"],
            sources=[Source(type="benchmark", ref="load_test.py")],
        )

        answer = tmp_ep.query("API latency performance")
        assert len(answer.supporting) > 0

        assert tmp_ep.verify(node.id, new_confidence=0.95)
        assert tmp_ep.update_node(node.id, confidence=0.95, tags=["verified"])

        report = tmp_ep.health_report()
        assert report["total_knowledge"] >= 1

    def test_verifier_with_contradictions(self, tmp_ep):
        tmp_ep.add(
            "Redis is fast for caching",
            confidence=0.9,
            topic="caching",
            sources=[Source(type="benchmark", ref="redis_bench.py", trustworthiness=0.95)],
        )
        tmp_ep.add(
            "Redis is slow for caching",
            confidence=0.2,
            topic="caching",
            sources=[Source(type="hearsay", ref="blog", trustworthiness=0.3)],
        )

        verifier = AutoVerifier(tmp_ep)
        results = verifier.resolve_contradictions()
        assert results["total"] >= 1
        assert results["resolved"] >= 1

    def test_update_node_through_verifier(self, tmp_ep):
        node = tmp_ep.add(
            "All unit tests pass",
            confidence=0.5,
            topic="testing",
            tags=["test"],
        )

        tmp_ep.update_node(
            node.id,
            confidence=0.85,
            verification_method="pytest",
            tags=["auto-verified"],
        )

        updated = tmp_ep._find_node(node.id)
        assert updated.confidence == 0.85
        assert "auto-verified" in updated.tags
        refs = [s.ref for s in updated.sources]
        assert "pytest" in refs

    def test_health_report_after_verification(self, tmp_ep):
        tmp_ep.add("Old stale fact", confidence=0.1, topic="old")
        tmp_ep.add("Good fact", confidence=0.9, topic="good")

        report_before = tmp_ep.health_report()

        stale_nodes = tmp_ep.stale_knowledge()
        for node in stale_nodes:
            tmp_ep.update_node(node.id, confidence=0.8, verification_method="manual")

        report_after = tmp_ep.health_report()
        assert report_after["avg_confidence"] > report_before["avg_confidence"]

    def test_site_skill_epistemic_roundtrip(self):
        """Site skill → record executions → check calibration."""
        skill = SiteSkill(
            name="checkout",
            site_url="https://shop.example.com",
            skill_id="test-ep-roundtrip",
        )
        ep_skill = EpistemicSiteSkill(skill)

        # Simulate 5 successes and 1 failure
        for _ in range(5):
            ep_skill.record_execution(success=True)
        ep_skill.record_execution(success=False)

        # Should have predictions (>= 6 since skill may have persisted data)
        assert len(ep_skill.predicted_outcomes) >= 6
        # Calibration score should exist
        score = ep_skill.get_calibration_score()
        assert score is not None
        # Confidence should be high (5/6 success) — Bayesian update with lr=0.1
        assert ep_skill.confidence > 0.6
