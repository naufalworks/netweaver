"""Site skill integration with epistemic tracking.

Extends SiteSkill with confidence scores that decay over time,
and integrates with EpistemicOS for knowledge management.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from .site_skill import SiteSkill, SkillStore
from .epistemic import EpistemicOS, Source


class EpistemicSiteSkill:
    """Site skill with epistemic confidence tracking."""
    
    def __init__(self, skill: SiteSkill):
        self.skill = skill
        self.epistemic_os = EpistemicOS()
        self._load_epistemic_data()
    
    def _load_epistemic_data(self):
        """Load epistemic data for this skill."""
        skill_id = self.skill.skill_id
        data_file = Path(f".tini/epistemic/site_skills/{skill_id}.json")
        
        if data_file.exists():
            import json
            with open(data_file) as f:
                data = json.load(f)
                self.confidence = data.get("confidence", 0.5)
                self.last_verified = datetime.fromisoformat(data.get("last_verified", datetime.now().isoformat()))
                self.decay_rate = data.get("decay_rate", 0.1)  # 10% per month
                self.verification_count = data.get("verification_count", 0)
                self.predicted_outcomes = data.get("predicted_outcomes", [])
        else:
            # Initial confidence based on success rate
            stats = self.skill.execution_stats
            total = stats.get("total_count", 0)
            successes = stats.get("success_count", 0)
            self.confidence = successes / total if total > 0 else 0.5
            self.last_verified = datetime.now()
            self.decay_rate = 0.1
            self.verification_count = 0
            self.predicted_outcomes = []
    
    def _save_epistemic_data(self):
        """Save epistemic data for this skill."""
        data_dir = Path(".tini/epistemic/site_skills")
        data_dir.mkdir(parents=True, exist_ok=True)
        
        data_file = data_dir / f"{self.skill.skill_id}.json"
        import json
        with open(data_file, "w") as f:
            json.dump({
                "confidence": self.confidence,
                "last_verified": self.last_verified.isoformat(),
                "decay_rate": self.decay_rate,
                "verification_count": self.verification_count,
                "predicted_outcomes": self.predicted_outcomes,
            }, f, indent=2)
    
    @property
    def current_confidence(self) -> float:
        """Get current confidence after decay."""
        days_old = (datetime.now() - self.last_verified).days
        months_old = days_old / 30.0
        decayed = self.confidence * ((1 - self.decay_rate) ** months_old)
        return max(0.01, decayed)  # Floor at 1%
    
    def record_execution(self, success: bool, evidence: Optional[Dict] = None):
        """Record execution outcome and update confidence."""
        # Update skill stats
        if success:
            self.skill.record_success()
        else:
            self.skill.record_failure()
        
        # Update epistemic confidence
        # Bayesian update: move confidence toward outcome
        learning_rate = 0.1
        outcome = 1.0 if success else 0.0
        self.confidence = (1 - learning_rate) * self.confidence + learning_rate * outcome
        
        # Track prediction for calibration
        predicted = self.current_confidence
        self.predicted_outcomes.append({
            "predicted": predicted,
            "actual": outcome,
            "timestamp": datetime.now().isoformat(),
            "evidence": evidence,
        })
        
        # Keep only last 100 predictions
        if len(self.predicted_outcomes) > 100:
            self.predicted_outcomes = self.predicted_outcomes[-100:]
        
        # Add to epistemic OS
        evidence_context = json.dumps({
            "success": success,
            "predicted_confidence": predicted,
            "skill_stats": self.skill.execution_stats,
        })
        source = Source(
            type="execution_outcome",
            ref=f"skill:{self.skill.skill_id}",
            author="system",
            trustworthiness=0.9 if success else 0.7,
        )
        self.epistemic_os.add(
            content=f"Site skill '{self.skill.name}' on {self.skill.site_url}",
            confidence=self.confidence,
            tags=["site_skill", self.skill.skill_id, self.skill.site_url],
            context=evidence_context,
            sources=[source],
            decay_rate=0.05 if not success else 0.01,  # Faster decay on failure
        )
        
        self.last_verified = datetime.now()
        self.verification_count += 1
        self._save_epistemic_data()
    
    def is_stale(self, threshold_days: int = 30) -> bool:
        """Check if skill knowledge is stale."""
        days_old = (datetime.now() - self.last_verified).days
        return days_old > threshold_days
    
    def needs_verification(self, min_confidence: float = 0.6) -> bool:
        """Check if skill needs verification."""
        return self.current_confidence < min_confidence or self.is_stale()
    
    def get_calibration_score(self) -> Optional[float]:
        """Calculate calibration score (how well predictions match outcomes).
        
        Returns Brier score: lower is better (0 = perfect, 1 = worst).
        """
        if not self.predicted_outcomes:
            return None
        
        brier_sum = 0.0
        for outcome in self.predicted_outcomes:
            predicted = outcome["predicted"]
            actual = outcome["actual"]
            brier_sum += (predicted - actual) ** 2
        
        return brier_sum / len(self.predicted_outcomes)
    
    def to_dict(self) -> Dict[str, Any]:
        """Export skill with epistemic data."""
        data = self.skill.to_dict()
        data["epistemic"] = {
            "confidence": self.confidence,
            "current_confidence": self.current_confidence,
            "last_verified": self.last_verified.isoformat(),
            "decay_rate": self.decay_rate,
            "verification_count": self.verification_count,
            "calibration_score": self.get_calibration_score(),
            "needs_verification": self.needs_verification(),
            "is_stale": self.is_stale(),
        }
        return data


class EpistemicSkillStore:
    """Store for epistemic site skills."""
    
    def __init__(self, skills_dir: Path = Path(".tini/skills")):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)
    
    def load_all(self) -> List[EpistemicSiteSkill]:
        """Load all skills with epistemic data."""
        store = SkillStore(self.skills_dir)
        skills = []
        for skill_file in self.skills_dir.glob("*.json"):
            try:
                skill_id = skill_file.stem
                base_skill = store.load(skill_id)
                if base_skill:
                    epistemic_skill = EpistemicSiteSkill(base_skill)
                    skills.append(epistemic_skill)
            except Exception as e:
                print(f"Warning: Failed to load {skill_file}: {e}")
        return skills
    
    def load(self, skill_id: str) -> Optional[EpistemicSiteSkill]:
        """Load a single skill by ID with epistemic data."""
        store = SkillStore(self.skills_dir)
        base_skill = store.load(skill_id)
        if base_skill:
            return EpistemicSiteSkill(base_skill)
        return None
    
    def get_stale_skills(self, threshold_days: int = 30) -> List[EpistemicSiteSkill]:
        """Get skills with stale knowledge."""
        return [s for s in self.load_all() if s.is_stale(threshold_days)]
    
    def get_low_confidence_skills(self, min_confidence: float = 0.6) -> List[EpistemicSiteSkill]:
        """Get skills with low confidence."""
        return [s for s in self.load_all() if s.current_confidence < min_confidence]
    
    def get_verification_priorities(self) -> List[Dict[str, Any]]:
        """Get prioritized list of skills needing verification.
        
        Priority = (1 - confidence) * usage_frequency * staleness
        """
        skills = self.load_all()
        priorities = []
        
        for skill in skills:
            if not skill.needs_verification():
                continue
            
            # Calculate priority score
            usage = skill.skill.execution_stats.get("total_count", 0)
            usage_factor = min(usage / 10, 1.0)  # Cap at 10 uses
            staleness = (datetime.now() - skill.last_verified).days / 30
            confidence_gap = 1.0 - skill.current_confidence
            
            priority_score = confidence_gap * (1 + usage_factor) * (1 + staleness * 0.1)
            
            priorities.append({
                "skill": skill,
                "score": priority_score,
                "reason": self._get_verification_reason(skill),
            })
        
        # Sort by priority (highest first)
        priorities.sort(key=lambda x: x["score"], reverse=True)
        return priorities
    
    def _get_verification_reason(self, skill: EpistemicSiteSkill) -> str:
        """Get human-readable reason for verification."""
        reasons = []
        
        if skill.current_confidence < 0.6:
            reasons.append(f"low confidence ({skill.current_confidence:.0%})")
        
        if skill.is_stale():
            days = (datetime.now() - skill.last_verified).days
            reasons.append(f"stale ({days}d old)")
        
        calibration = skill.get_calibration_score()
        if calibration is not None and calibration > 0.25:
            reasons.append(f"poor calibration (Brier={calibration:.2f})")
        
        return ", ".join(reasons) if reasons else "routine check"
