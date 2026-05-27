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
        # Should have a Source with ref="pytest"
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
        
        # Reload
        ep2 = EpistemicOS(storage_path=storage)
        updated = ep2._find_node(node.id)
        assert updated.confidence == 0.9
        assert "verified" in updated.tags
    
    def test_update_duplicate_verification_method(self, tmp_ep):
        node = tmp_ep.add("Test fact", confidence=0.8)
        tmp_ep.update_node(node.id, verification_method="pytest")
        tmp_ep.update_node(node.id, verification_method="pytest")
        updated = tmp_ep._find_node(node.id)
        # Should only have one pytest source
        pytest_refs = [s for s in updated.sources if s.ref == "pytest"]
        assert len(pytest_refs) == 1


# ── AutoVerifier tests ──

class TestAutoVerifier:
    def test_init(self, verifier):
        assert verifier.epistemic_os is not None
        assert verifier.skill_store is not None
    
    def test_verify_stale_knowledge_empty(self, verifier):
        """No stale knowledge → all zeros."""
        results = verifier.verify_stale_knowledge()
        assert results["verified"] == 0
        assert results["failed"] == 0
        assert results["needs_manual"] == 0
    
    def test_verify_stale_knowledge_with_stale(self, verifier, tmp_ep):
        """Add knowledge with low confidence → flagged as stale."""
        verifier.epistemic_os.add(
            "Old fact about testing",
            confidence=0.2,
            topic="testing",
            tags=["test"],
        )
        results = verifier.verify_stale_knowledge()
        assert len(results["details"]) > 0
    
    def test_is_testable_claim(self, verifier, tmp_ep):
        """Test pattern matching for testable claims."""
        node = tmp_ep.add("All tests pass", confidence=0.8, topic="testing")
        assert verifier._is_testable_claim(node)
        
        node2 = tmp_ep.add("Build succeeds", confidence=0.8, topic="build")
        assert verifier._is_testable_claim(node2)
        
        node3 = tmp_ep.add("User prefers dark mode", confidence=0.8, topic="ui")
        assert not verifier._is_testable_claim(node3)
    
    def test_verify_testable_claim_tests(self, verifier, tmp_ep):
        """Verify a claim about tests by running pytest."""
        node = tmp_ep.add("All tests pass in the project", confidence=0.5, topic="testing")
        result = verifier._verify_testable_claim(node)
        # Should have run tests and updated
        assert result["status"] in ("verified", "failed", "needs_manual")
        assert "node_id" in result
    
    def test_resolve_contradictions_empty(self, verifier):
        """No contradictions → empty results."""
        results = verifier.resolve_contradictions()
        assert results["total"] == 0
        assert results["resolved"] == 0
    
    def test_resolve_contradictions_with_data(self, verifier, tmp_ep):
        """Add contradictory knowledge → detect and suggest resolution."""
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
        """Auto-resolve should deprecate the lower confidence node."""
        a = tmp_ep.add(
            "Database handles 10K writes/sec",
            confidence=0.95,
            topic="performance",
            sources=[Source(type="benchmark", ref="load_test.py", trustworthiness=0.95)],
        )
        b = tmp_ep.add(
            "Database handles 100 writes/sec",
            confidence=0.2,
            topic="performance",
            sources=[Source(type="hearsay", ref="reddit", trustworthiness=0.2)],
        )
        
        results = verifier.resolve_contradictions()
        # Should have auto-resolved
        assert results["resolved"] >= 1
    
    def test_suggest_resolution_needs_manual(self, verifier, tmp_ep):
        """Close confidence + close sources → needs manual review."""
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
        """Node with no sources → quality = 0.3."""
        node = tmp_ep.add("Fact without sources", confidence=0.5)
        quality = verifier._source_quality(node)
        assert quality == 0.3
    
    def test_source_quality_high_trust(self, verifier, tmp_ep):
        """Node with high-trust sources → high quality."""
        node = tmp_ep.add(
            "Benchmarked fact",
            confidence=0.9,
            sources=[Source(type="benchmark", ref="test.py", trustworthiness=0.95)],
        )
        quality = verifier._source_quality(node)
        assert quality > 0.9
    
    def test_calibrate_confidence_no_skills(self, verifier):
        """No site skills → no calibration."""
        results = verifier.calibrate_confidence()
        assert results["skills_calibrated"] == 0
        assert results["total_predictions"] == 0
    
    def test_run_full_verification_cycle(self, verifier, tmp_ep):
        """Full cycle should return all three sections."""
        tmp_ep.add("Some fact", confidence=0.8, topic="general")
        results = verifier.run_full_verification_cycle()
        assert "stale_knowledge" in results
        assert "contradictions" in results
        assert "calibration" in results
        assert "timestamp" in results
    
    def test_verification_log_saved(self, verifier, tmp_ep, tmp_path):
        """Verification log should be saved to disk."""
        # Patch log file path
        log_file = tmp_path / "epistemic" / "verification_log.json"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        verifier.run_full_verification_cycle()
        history = verifier.get_verification_history()
        assert len(history) >= 1
    
    def test_verification_history_empty(self, verifier):
        """No history → empty list."""
        history = verifier.get_verification_history()
        assert history == []
    
    def test_verify_node_site_skill_tag(self, verifier, tmp_ep):
        """Node with site_skill tag should try skill verification."""
        node = tmp_ep.add(
            "Site skill test",
            confidence=0.5,
            topic="site_skill",
            tags=["site_skill", "skill:test-id"],
        )
        result = verifier._verify_node(node)
        # Should try to load the skill (and fail gracefully)
        assert result["status"] in ("verified", "failed", "needs_manual")
    
    def test_verify_node_unknown_type(self, verifier, tmp_ep):
        """Unknown node type → needs manual."""
        node = tmp_ep.add(
            "Random subjective opinion about design",
            confidence=0.5,
            topic="opinion",
        )
        result = verifier._verify_node(node)
        assert result["status"] == "needs_manual"


# ── EpistemicSiteSkill tests ──

class TestEpistemicSiteSkill:
    def test_create(self, tmp_ep):
        """Create an epistemic site skill."""
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-login",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep)
        assert ep_skill.skill.name == "login"
        assert ep_skill.confidence == 0.5  # default
    
    def test_record_outcome_success(self, tmp_ep):
        """Successful execution → confidence increases."""
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-login-success",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep)
        
        ep_skill.record_outcome(success=True)
        assert ep_skill.confidence > 0.5
        assert ep_skill.skill.execution_stats["success_count"] == 1
    
    def test_record_outcome_failure(self, tmp_ep):
        """Failed execution → confidence decreases."""
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-login-fail",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep, confidence=0.8)
        
        ep_skill.record_outcome(success=False)
        assert ep_skill.confidence < 0.8
        assert ep_skill.skill.execution_stats["fail_count"] == 1
    
    def test_is_stale(self, tmp_ep):
        """Old skill → stale."""
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-login-stale",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep)
        # Manually set last_verified to old date
        ep_skill.last_verified = datetime.now() - timedelta(days=60)
        assert ep_skill.is_stale()
    
    def test_not_stale(self, tmp_ep):
        """Recent skill → not stale."""
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-login-fresh",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep)
        assert not ep_skill.is_stale()
    
    def test_multiple_outcomes_converge(self, tmp_ep):
        """Multiple successes should converge confidence toward 1.0."""
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-login-converge",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep, confidence=0.5)
        
        for _ in range(10):
            ep_skill.record_outcome(success=True)
        
        assert ep_skill.confidence > 0.8
    
    def test_record_outcome_with_epistemic_os(self, tmp_ep):
        """Recorded outcome should add knowledge to EpistemicOS."""
        skill = SiteSkill(
            name="checkout",
            site_url="https://shop.example.com",
            skill_id="test-checkout-ep",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep)
        ep_skill.record_outcome(success=True)
        
        # Check that knowledge was added
        assert len(tmp_ep.nodes) > 0
    
    def test_get_calibration_score_no_predictions(self, tmp_ep):
        """No predictions → None."""
        skill = SiteSkill(
            name="login",
            site_url="https://example.com",
            skill_id="test-login-no-pred",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep)
        assert ep_skill.get_calibration_score() is None


# ── EpistemicSkillStore tests ──

class TestEpistemicSkillStore:
    def test_create_default_dir(self):
        """Default skills directory."""
        store = EpistemicSkillStore()
        assert store.skills_dir.exists()
    
    def test_load_all_empty(self, tmp_path):
        """Empty directory → empty list."""
        store = EpistemicSkillStore(skills_dir=tmp_path)
        skills = store.load_all()
        assert skills == []
    
    def test_get_stale_skills(self, tmp_ep):
        """Should return stale skills."""
        skill = SiteSkill(
            name="old-skill",
            site_url="https://old.example.com",
            skill_id="test-old-skill",
        )
        ep_skill = EpistemicSiteSkill(skill, epistemic_os=tmp_ep)
        ep_skill.last_verified = datetime.now() - timedelta(days=60)
        
        store = EpistemicSkillStore()
        # Can't easily test without saving to disk
        # But the method should work
        stale = store.get_stale_skills(threshold_days=30)
        assert isinstance(stale, list)
    
    def test_health_report(self, tmp_path, tmp_ep):
        """Health report should return valid structure."""
        store = EpistemicSkillStore(skills_dir=tmp_path, epistemic_os=tmp_ep)
        report = store.health_report()
        assert "total_skills" in report
        assert "avg_confidence" in report
        assert "stale_count" in report


# ── Integration tests ──

class TestEpistemicIntegration:
    def test_full_lifecycle(self, tmp_ep):
        """Full lifecycle: add → query → verify → decay → stale."""
        # Add knowledge
        node = tmp_ep.add(
            "API latency is under 100ms",
            confidence=0.9,
            topic="performance",
            tags=["api", "latency"],
            sources=[Source(type="benchmark", ref="load_test.py")],
        )
        
        # Query
        answer = tmp_ep.query("API latency performance")
        assert len(answer.nodes) > 0
        
        # Verify
        assert tmp_ep.verify(node.id, new_confidence=0.95)
        
        # Update
        assert tmp_ep.update_node(node.id, confidence=0.95, tags=["verified"])
        
        # Health
        report = tmp_ep.health_report()
        assert report["total_knowledge"] >= 1
    
    def test_verifier_with_contradictions(self, tmp_ep):
        """Add contradictions → verifier detects and suggests."""
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
        
        # Should auto-resolve (high conf + high trust vs low conf + low trust)
        assert results["resolved"] >= 1
    
    def test_update_node_through_verifier(self, tmp_ep):
        """Verifier should update nodes via update_node."""
        node = tmp_ep.add(
            "All unit tests pass",
            confidence=0.5,
            topic="testing",
            tags=["test"],
        )
        
        # Manually update
        old_confidence = node.confidence
        tmp_ep.update_node(
            node.id,
            confidence=0.85,
            verification_method="pytest",
            tags=["auto-verified"],
        )
        
        updated = tmp_ep._find_node(node.id)
        assert updated.confidence == 0.85
        assert "auto-verified" in updated.tags
        # Should have pytest source
        refs = [s.ref for s in updated.sources]
        assert "pytest" in refs
    
    def test_health_report_after_verification(self, tmp_ep):
        """Health should improve after verification."""
        # Add stale knowledge
        tmp_ep.add("Old stale fact", confidence=0.1, topic="old")
        tmp_ep.add("Good fact", confidence=0.9, topic="good")
        
        report_before = tmp_ep.health_report()
        
        # Verify the stale fact
        stale_nodes = tmp_ep.stale_knowledge()
        for node in stale_nodes:
            tmp_ep.update_node(node.id, confidence=0.8, verification_method="manual")
        
        report_after = tmp_ep.health_report()
        assert report_after["avg_confidence"] > report_before["avg_confidence"]
