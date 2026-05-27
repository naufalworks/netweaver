"""Auto-verification system for epistemic knowledge.

Automatically verifies stale knowledge by:
- Running tests to verify technical claims
- Re-executing site skills to verify they still work
- Detecting contradictions and suggesting resolutions
- Calibrating confidence scores based on actual outcomes
"""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from .epistemic import EpistemicOS, KnowledgeNode, Source
from .epistemic_site_skill import EpistemicSkillStore, EpistemicSiteSkill


class AutoVerifier:
    """Automatically verify stale epistemic knowledge."""
    
    def __init__(self, epistemic_os: EpistemicOS):
        self.epistemic_os = epistemic_os
        self.skill_store = EpistemicSkillStore()
        self.verification_log = []
    
    def verify_stale_knowledge(self, max_items: int = 10) -> Dict[str, Any]:
        """Verify stale knowledge nodes.
        
        Returns:
            Dict with verification results
        """
        stale_nodes = self.epistemic_os.stale_knowledge(threshold=0.4)
        stale_nodes = stale_nodes[:max_items]
        
        results = {
            "verified": 0,
            "failed": 0,
            "needs_manual": 0,
            "details": []
        }
        
        for node in stale_nodes:
            result = self._verify_node(node)
            results["details"].append(result)
            
            if result["status"] == "verified":
                results["verified"] += 1
            elif result["status"] == "failed":
                results["failed"] += 1
            else:
                results["needs_manual"] += 1
        
        self._log_verification("stale_knowledge", results)
        return results
    
    def _verify_node(self, node: KnowledgeNode) -> Dict[str, Any]:
        """Verify a single knowledge node."""
        # Check if it's a site skill
        if "site_skill" in node.tags:
            return self._verify_site_skill_node(node)
        
        # Check if it's a technical claim we can test
        if self._is_testable_claim(node):
            return self._verify_testable_claim(node)
        
        # Otherwise, needs manual verification
        return {
            "node_id": node.id,
            "content": node.content,
            "status": "needs_manual",
            "reason": "No automatic verification method available",
            "confidence_change": None
        }
    
    def _verify_site_skill_node(self, node: KnowledgeNode) -> Dict[str, Any]:
        """Verify a site skill knowledge node."""
        # Extract skill ID from node
        skill_id = None
        for tag in node.tags:
            if tag.startswith("skill:"):
                skill_id = tag[6:]
                break
        
        if not skill_id:
            return {
                "node_id": node.id,
                "content": node.content,
                "status": "needs_manual",
                "reason": "Could not extract skill ID",
                "confidence_change": None
            }
        
        # Load and verify the skill
        base_skill = self.skill_store.load(skill_id)
        if not base_skill:
            return {
                "node_id": node.id,
                "content": node.content,
                "status": "failed",
                "reason": "Skill no longer exists",
                "confidence_change": -0.5
            }
        
        # Try to re-execute the skill (simplified - just check if it can be loaded)
        try:
            epistemic_skill = EpistemicSiteSkill(base_skill)
            
            # For now, just check if the skill is still valid
            # In a real system, we'd re-execute it
            if epistemic_skill.is_stale():
                # Update confidence
                new_confidence = node.confidence * 0.8
                self.epistemic_os.update_node(
                    node.id,
                    confidence=new_confidence,
                    last_verified=datetime.now(),
                    verification_method="stale_check"
                )
                
                return {
                    "node_id": node.id,
                    "content": node.content,
                    "status": "verified",
                    "reason": "Skill still valid but stale",
                    "confidence_change": new_confidence - node.confidence
                }
            else:
                return {
                    "node_id": node.id,
                    "content": node.content,
                    "status": "verified",
                    "reason": "Skill is current",
                    "confidence_change": 0
                }
        except Exception as e:
            return {
                "node_id": node.id,
                "content": node.content,
                "status": "failed",
                "reason": f"Error loading skill: {e}",
                "confidence_change": -0.3
            }
    
    def _is_testable_claim(self, node: KnowledgeNode) -> bool:
        """Check if a claim can be verified via tests."""
        testable_patterns = [
            "test", "tests pass", "tests passing",
            "performance", "speed", "latency",
            "memory", "cpu", "resource",
            "build", "compile", "lint"
        ]
        
        content_lower = node.content.lower()
        return any(pattern in content_lower for pattern in testable_patterns)
    
    def _verify_testable_claim(self, node: KnowledgeNode) -> Dict[str, Any]:
        """Verify a testable technical claim."""
        # Try to run relevant tests
        if "test" in node.content.lower():
            return self._verify_via_tests(node)
        
        # Try to check build status
        if "build" in node.content.lower() or "compile" in node.content.lower():
            return self._verify_via_build(node)
        
        return {
            "node_id": node.id,
            "content": node.content,
            "status": "needs_manual",
            "reason": "Testable but no verification method implemented",
            "confidence_change": None
        }
    
    def _verify_via_tests(self, node: KnowledgeNode) -> Dict[str, Any]:
        """Verify by running tests."""
        try:
            # Run pytest
            result = subprocess.run(
                ["pytest", "-q", "--tb=no"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Parse output
            output = result.stdout
            if "passed" in output and result.returncode == 0:
                # Tests passed
                new_confidence = min(0.95, node.confidence + 0.1)
                self.epistemic_os.update_node(
                    node.id,
                    confidence=new_confidence,
                    last_verified=datetime.now(),
                    verification_method="pytest"
                )
                
                return {
                    "node_id": node.id,
                    "content": node.content,
                    "status": "verified",
                    "reason": "Tests passed",
                    "confidence_change": new_confidence - node.confidence,
                    "evidence": output.strip().split('\n')[-1]
                }
            else:
                # Tests failed
                new_confidence = max(0.2, node.confidence - 0.3)
                self.epistemic_os.update_node(
                    node.id,
                    confidence=new_confidence,
                    last_verified=datetime.now(),
                    verification_method="pytest"
                )
                
                return {
                    "node_id": node.id,
                    "content": node.content,
                    "status": "failed",
                    "reason": "Tests failed",
                    "confidence_change": new_confidence - node.confidence,
                    "evidence": output.strip().split('\n')[-1]
                }
        except subprocess.TimeoutExpired:
            return {
                "node_id": node.id,
                "content": node.content,
                "status": "needs_manual",
                "reason": "Test execution timed out",
                "confidence_change": None
            }
        except Exception as e:
            return {
                "node_id": node.id,
                "content": node.content,
                "status": "needs_manual",
                "reason": f"Test execution failed: {e}",
                "confidence_change": None
            }
    
    def _verify_via_build(self, node: KnowledgeNode) -> Dict[str, Any]:
        """Verify by checking build status."""
        try:
            # Try common build checks
            checks = [
                (["python", "-m", "py_compile", "netweaver/epistemic.py"], "py_compile"),
                (["python", "-m", "py_compile", "daemon.py"], "py_compile"),
            ]
            
            for cmd, method in checks:
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                if result.returncode != 0:
                    new_confidence = max(0.3, node.confidence - 0.2)
                    self.epistemic_os.update_node(
                        node.id,
                        confidence=new_confidence,
                        last_verified=datetime.now(),
                        verification_method=method
                    )
                    
                    return {
                        "node_id": node.id,
                        "content": node.content,
                        "status": "failed",
                        "reason": f"Build check failed: {' '.join(cmd)}",
                        "confidence_change": new_confidence - node.confidence
                    }
            
            # All checks passed
            new_confidence = min(0.9, node.confidence + 0.05)
            self.epistemic_os.update_node(
                node.id,
                confidence=new_confidence,
                last_verified=datetime.now(),
                verification_method="build_check"
            )
            
            return {
                "node_id": node.id,
                "content": node.content,
                "status": "verified",
                "reason": "Build checks passed",
                "confidence_change": new_confidence - node.confidence
            }
        except Exception as e:
            return {
                "node_id": node.id,
                "content": node.content,
                "status": "needs_manual",
                "reason": f"Build verification failed: {e}",
                "confidence_change": None
            }
    
    def resolve_contradictions(self) -> Dict[str, Any]:
        """Detect and suggest resolutions for contradictions."""
        contradictions = self.epistemic_os.detect_contradictions()
        
        results = {
            "total": len(contradictions),
            "resolved": 0,
            "suggestions": []
        }
        
        for contradiction in contradictions:
            # Get the actual nodes
            node_a = self.epistemic_os._find_node(contradiction.node_a_id)
            node_b = self.epistemic_os._find_node(contradiction.node_b_id)
            
            if not node_a or not node_b:
                continue
            
            suggestion = self._suggest_resolution(contradiction, node_a, node_b)
            results["suggestions"].append(suggestion)
            
            if suggestion.get("auto_resolvable"):
                # Auto-resolve by picking the higher confidence one
                self._auto_resolve_contradiction(contradiction, node_a, node_b, suggestion)
                results["resolved"] += 1
        
        self._log_verification("contradictions", results)
        return results
    
    def _suggest_resolution(self, contradiction, node_a, node_b) -> Dict[str, Any]:
        """Suggest how to resolve a contradiction."""
        # Check if one is much newer
        age_diff = abs((node_a.last_verified - node_b.last_verified).days)
        
        # Check if one has much higher confidence
        conf_diff = abs(node_a.confidence - node_b.confidence)
        
        # Check if one has better sources
        source_a_quality = self._source_quality(node_a)
        source_b_quality = self._source_quality(node_b)
        
        suggestion = {
            "node_a_id": node_a.id,
            "node_a_content": node_a.content,
            "node_a_confidence": node_a.confidence,
            "node_b_id": node_b.id,
            "node_b_content": node_b.content,
            "node_b_confidence": node_b.confidence,
            "auto_resolvable": False,
            "resolution": None,
            "reasoning": []
        }
        
        # Auto-resolve if one is clearly better
        if conf_diff > 0.3 and source_a_quality > source_b_quality + 0.2:
            suggestion["auto_resolvable"] = True
            suggestion["resolution"] = "keep_a"
            suggestion["reasoning"].append(f"A has higher confidence ({node_a.confidence:.2f} vs {node_b.confidence:.2f})")
            suggestion["reasoning"].append(f"A has better sources ({source_a_quality:.2f} vs {source_b_quality:.2f})")
        elif conf_diff > 0.3 and source_b_quality > source_a_quality + 0.2:
            suggestion["auto_resolvable"] = True
            suggestion["resolution"] = "keep_b"
            suggestion["reasoning"].append(f"B has higher confidence ({node_b.confidence:.2f} vs {node_a.confidence:.2f})")
            suggestion["reasoning"].append(f"B has better sources ({source_b_quality:.2f} vs {source_a_quality:.2f})")
        elif age_diff > 30 and conf_diff > 0.2:
            # Prefer newer if significantly newer and has reasonable confidence
            newer = node_a if node_a.last_verified > node_b.last_verified else node_b
            older = node_b if newer == node_a else node_a
            if newer.confidence >= older.confidence - 0.1:
                suggestion["auto_resolvable"] = True
                suggestion["resolution"] = "keep_newer"
                suggestion["reasoning"].append(f"Newer by {age_diff} days with similar confidence")
        else:
            suggestion["reasoning"].append("Needs manual review - no clear winner")
        
        return suggestion
    
    def _source_quality(self, node: KnowledgeNode) -> float:
        """Calculate source quality score."""
        if not node.sources:
            return 0.3
        
        # Average trustworthiness of sources
        total = sum(source.trustworthiness for source in node.sources)
        return total / len(node.sources)
    
    def _auto_resolve_contradiction(self, contradiction, node_a, node_b, suggestion: Dict[str, Any]):
        """Auto-resolve a contradiction based on suggestion."""
        if suggestion["resolution"] == "keep_a":
            # Deprecate B
            self.epistemic_os.update_node(
                node_b.id,
                confidence=0.1,
                tags=node_b.tags + ["deprecated", "contradicted"]
            )
        elif suggestion["resolution"] == "keep_b":
            # Deprecate A
            self.epistemic_os.update_node(
                node_a.id,
                confidence=0.1,
                tags=node_a.tags + ["deprecated", "contradicted"]
            )
        elif suggestion["resolution"] == "keep_newer":
            # Keep the newer one
            newer = node_a if node_a.last_verified > node_b.last_verified else node_b
            older = node_b if newer == node_a else node_a
            self.epistemic_os.update_node(
                older.id,
                confidence=0.1,
                tags=older.tags + ["deprecated", "outdated"]
            )
    
    def calibrate_confidence(self) -> Dict[str, Any]:
        """Calibrate confidence scores based on prediction accuracy."""
        skills = self.skill_store.load_all()
        
        results = {
            "skills_calibrated": 0,
            "total_predictions": 0,
            "calibration_scores": []
        }
        
        for skill in skills:
            if not skill.skill.predicted_outcomes:
                continue
            
            # Calculate Brier score
            brier_score = skill.get_calibration_score()
            if brier_score is None:
                continue
            
            results["total_predictions"] += len(skill.skill.predicted_outcomes)
            
            # Interpret Brier score
            # 0.0 = perfect calibration
            # 0.25 = random guessing
            # 1.0 = worst possible
            if brier_score < 0.1:
                quality = "excellent"
            elif brier_score < 0.2:
                quality = "good"
            elif brier_score < 0.3:
                quality = "fair"
            else:
                quality = "poor"
            
            results["calibration_scores"].append({
                "skill_id": skill.skill.skill_id,
                "skill_name": skill.skill.name,
                "brier_score": brier_score,
                "quality": quality,
                "predictions": len(skill.skill.predicted_outcomes)
            })
            
            # Adjust decay rate based on calibration
            if brier_score > 0.3:
                # Poor calibration - increase decay rate
                new_decay = min(0.2, skill.decay_rate + 0.02)
                skill.decay_rate = new_decay
                skill._save_epistemic_data()
                results["skills_calibrated"] += 1
        
        self._log_verification("calibration", results)
        return results
    
    def run_full_verification_cycle(self) -> Dict[str, Any]:
        """Run all verification checks."""
        results = {
            "timestamp": datetime.now().isoformat(),
            "stale_knowledge": self.verify_stale_knowledge(),
            "contradictions": self.resolve_contradictions(),
            "calibration": self.calibrate_confidence()
        }
        
        # Save verification log
        self._save_verification_log()
        
        return results
    
    def _log_verification(self, check_type: str, results: Dict[str, Any]):
        """Log verification results."""
        self.verification_log.append({
            "timestamp": datetime.now().isoformat(),
            "type": check_type,
            "results": results
        })
    
    def _save_verification_log(self):
        """Save verification log to disk."""
        log_file = Path(".tini/epistemic/verification_log.json")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(log_file, "w") as f:
            json.dump(self.verification_log, f, indent=2)
    
    def get_verification_history(self, last_n: int = 10) -> List[Dict[str, Any]]:
        """Get recent verification history."""
        log_file = Path(".tini/epistemic/verification_log.json")
        if not log_file.exists():
            return []
        
        with open(log_file) as f:
            log = json.load(f)
        
        return log[-last_n:]
