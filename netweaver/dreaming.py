"""Dreaming — Background hypothesis generation for autonomous development.

While idle, the daemon 'dreams' — scanning the codebase for patterns,
asking 'what if' questions, simulating outcomes, and storing hypotheses
as low-confidence knowledge in Epistemic OS.

This is the cognitive layer that proposes architectural improvements,
refactoring opportunities, and novel approaches the system never considered.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field


def _now() -> datetime:
    return datetime.now()


def _hash(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:16]


# ── Hypothesis Types ──

HYPOTHESIS_TEMPLATES = [
    # Architecture hypotheses
    {
        "type": "merge_modules",
        "template": "What if we merged {a} and {b}?",
        "condition": lambda patterns: len(patterns.get("shared_modules", [])) > 2,
        "confidence": 0.3,
        "decay": 0.05,
    },
    {
        "type": "extract_module",
        "template": "What if we extracted {pattern} into a shared library?",
        "condition": lambda patterns: patterns.get("duplicate_count", 0) > 3,
        "confidence": 0.35,
        "decay": 0.03,
    },
    {
        "type": "remove_dependency",
        "template": "What if {module} didn't depend on {dep}?",
        "condition": lambda patterns: len(patterns.get("dependencies", [])) > 5,
        "confidence": 0.25,
        "decay": 0.05,
    },
    # Testing hypotheses
    {
        "type": "test_order",
        "template": "What if tests ran in dependency order instead of alphabetical?",
        "condition": lambda patterns: patterns.get("test_count", 0) > 100,
        "confidence": 0.4,
        "decay": 0.02,
    },
    {
        "type": "test_parallelism",
        "template": "What if we parallelized {module} tests ({count} tests)?",
        "condition": lambda patterns: patterns.get("test_count", 0) > 50,
        "confidence": 0.45,
        "decay": 0.02,
    },
    # Code quality hypotheses
    {
        "type": "reduce_complexity",
        "template": "What if we refactored {module} (complexity: {score})?",
        "condition": lambda patterns: patterns.get("max_complexity", 0) > 20,
        "confidence": 0.5,
        "decay": 0.03,
    },
    {
        "type": "dead_code",
        "template": "What if {module} has dead code ({lines} unused LOC)?",
        "condition": lambda patterns: patterns.get("unused_loc", 0) > 100,
        "confidence": 0.3,
        "decay": 0.04,
    },
    # Performance hypotheses
    {
        "type": "cache_layer",
        "template": "What if we cached {operation} results?",
        "condition": lambda patterns: patterns.get("repeated_ops", 0) > 3,
        "confidence": 0.35,
        "decay": 0.03,
    },
    {
        "type": "batch_processing",
        "template": "What if we batched {operation} calls?",
        "condition": lambda patterns: patterns.get("api_calls", 0) > 10,
        "confidence": 0.4,
        "decay": 0.03,
    },
    # Process hypotheses
    {
        "type": "plan_batching",
        "template": "What if we batched plan generation (currently {rate}/cycle)?",
        "condition": lambda patterns: patterns.get("plans_per_cycle", 0) > 5,
        "confidence": 0.35,
        "decay": 0.04,
    },
    {
        "type": "review_queue_optimization",
        "template": "What if review queue was prioritized by epistemic confidence?",
        "condition": lambda patterns: patterns.get("queue_size", 0) > 10,
        "confidence": 0.45,
        "decay": 0.02,
    },
]


@dataclass
class Hypothesis:
    """A proposed improvement with simulated outcome."""
    hypothesis_id: str
    type: str
    content: str
    confidence: float  # Initial confidence (low — it's a guess)
    simulated_outcome: str  # What would happen if we tried this
    validation_method: str  # How to test this hypothesis
    generated: datetime = field(default_factory=_now)
    validated: bool = False
    validation_result: str = ""
    related_patterns: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "type": self.type,
            "content": self.content,
            "confidence": self.confidence,
            "simulated_outcome": self.simulated_outcome,
            "validation_method": self.validation_method,
            "generated": self.generated.isoformat(),
            "validated": self.validated,
            "validation_result": self.validation_result,
            "related_patterns": self.related_patterns,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Hypothesis":
        return cls(
            hypothesis_id=data["hypothesis_id"],
            type=data["type"],
            content=data["content"],
            confidence=data["confidence"],
            simulated_outcome=data.get("simulated_outcome", ""),
            validation_method=data.get("validation_method", ""),
            generated=datetime.fromisoformat(data["generated"]) if "generated" in data else _now(),
            validated=data.get("validated", False),
            validation_result=data.get("validation_result", ""),
            related_patterns=data.get("related_patterns", []),
        )


class DreamEngine:
    """Generates hypotheses by analyzing codebase patterns."""
    
    def __init__(
        self,
        workdir: Optional[Path] = None,
        epistemic_os=None,
        knowledge_graph=None,
    ):
        self.workdir = workdir or Path.home() / "Documents" / "myhermes"
        self.epistemic_os = epistemic_os
        self.knowledge_graph = knowledge_graph
        self.hypotheses: List[Hypothesis] = []
        self._load()
    
    # ── Pattern Extraction ──
    
    def extract_patterns(self) -> Dict[str, Any]:
        """Extract patterns from codebase for hypothesis generation."""
        patterns: Dict[str, Any] = {
            "modules": [],
            "test_count": 0,
            "total_loc": 0,
            "max_complexity": 0,
            "duplicate_count": 0,
            "shared_modules": [],
            "dependencies": [],
            "unused_loc": 0,
            "repeated_ops": 0,
            "api_calls": 0,
            "plans_per_cycle": 0,
            "queue_size": 0,
        }
        
        # Scan Python files
        for py_file in self.workdir.glob("**/*.py"):
            if ".venv" in str(py_file) or "__pycache__" in str(py_file):
                continue
            if ".tini" in str(py_file):
                continue
            
            try:
                content = py_file.read_text(errors="ignore")
                lines = content.split("\n")
                loc = len([l for l in lines if l.strip() and not l.strip().startswith("#")])
                
                patterns["total_loc"] += loc
                patterns["modules"].append({
                    "path": str(py_file.relative_to(self.workdir)),
                    "loc": loc,
                    "functions": len(re.findall(r"^\s*def ", content, re.MULTILINE)),
                    "classes": len(re.findall(r"^\s*class ", content, re.MULTILINE)),
                })
                
                # Estimate complexity (function count as proxy)
                func_count = len(re.findall(r"^\s*def ", content, re.MULTILINE))
                if func_count > patterns["max_complexity"]:
                    patterns["max_complexity"] = func_count
                
                # Count test functions
                if "test_" in py_file.name:
                    patterns["test_count"] += len(
                        re.findall(r"def test_", content)
                    )
                
                # Count imports (dependency proxy)
                imports = re.findall(r"^(?:from|import)\s+(\S+)", content, re.MULTILINE)
                for imp in imports:
                    if imp.startswith("netweaver.") or imp.startswith("."):
                        patterns["dependencies"].append(imp)
                
            except Exception:
                continue
        
        # Check review queue size
        queue_file = self.workdir / ".tini" / "netweaver" / "company" / "REVIEW_QUEUE.md"
        if queue_file.exists():
            try:
                queue_content = queue_file.read_text()
                patterns["queue_size"] = queue_content.count("### Plan:")
            except Exception:
                pass
        
        # Count shared module names
        module_names = {}
        for m in patterns["modules"]:
            name = Path(m["path"]).stem
            module_names.setdefault(name, []).append(m["path"])
        for name, paths in module_names.items():
            if len(paths) > 1:
                patterns["shared_modules"].extend(paths)
        
        return patterns
    
    # ── Dreaming ──
    
    def dream(self, max_hypotheses: int = 5) -> List[Hypothesis]:
        """Generate hypotheses based on current codebase patterns."""
        patterns = self.extract_patterns()
        new_hypotheses = []
        
        for template in HYPOTHESIS_TEMPLATES:
            if len(new_hypotheses) >= max_hypotheses:
                break
            
            try:
                if not template["condition"](patterns):
                    continue
                
                # Generate hypothesis content
                content = self._fill_template(template["template"], patterns)
                
                # Check for duplicates
                hyp_id = _hash(content)
                if any(h.hypothesis_id == hyp_id for h in self.hypotheses):
                    continue
                
                # Simulate outcome
                outcome = self._simulate_outcome(template["type"], patterns)
                
                # Determine validation method
                validation = self._suggest_validation(template["type"], patterns)
                
                hypothesis = Hypothesis(
                    hypothesis_id=hyp_id,
                    type=template["type"],
                    content=content,
                    confidence=template["confidence"],
                    simulated_outcome=outcome,
                    validation_method=validation,
                    related_patterns=self._find_related_patterns(patterns, template["type"]),
                )
                
                new_hypotheses.append(hypothesis)
                self.hypotheses.append(hypothesis)
                
            except Exception:
                continue
        
        # Store in Epistemic OS if available
        if self.epistemic_os:
            self._store_in_epistemic(new_hypotheses)
        
        self._save()
        return new_hypotheses
    
    def _fill_template(self, template: str, patterns: Dict) -> str:
        """Fill template placeholders with real data."""
        result = template
        
        # Module names
        modules = [m["path"] for m in patterns.get("modules", [])]
        if "{a}" in result and len(modules) > 0:
            result = result.replace("{a}", modules[0] if modules else "module_a")
        if "{b}" in result and len(modules) > 1:
            result = result.replace("{b}", modules[1] if len(modules) > 1 else "module_b")
        
        # Counts
        result = result.replace("{count}", str(patterns.get("test_count", 0)))
        result = result.replace("{score}", str(patterns.get("max_complexity", 0)))
        result = result.replace("{lines}", str(patterns.get("unused_loc", 0)))
        result = result.replace("{rate}", str(patterns.get("plans_per_cycle", 0)))
        
        # Module name
        if "{module}" in result and modules:
            # Pick the largest module
            largest = max(patterns.get("modules", []), key=lambda m: m.get("loc", 0), default=None)
            result = result.replace("{module}", largest["path"] if largest else "unknown")
        
        # Dependencies
        deps = patterns.get("dependencies", [])
        if "{dep}" in result and deps:
            result = result.replace("{dep}", deps[0] if deps else "unknown")
        
        # Operations
        if "{operation}" in result:
            result = result.replace("{operation}", "database query" if "cache" in result.lower() else "API call")
        
        # Pattern name
        if "{pattern}" in result:
            shared = patterns.get("shared_modules", [])
            if shared:
                result = result.replace("{pattern}", Path(shared[0]).stem)
            else:
                result = result.replace("{pattern}", "common utility")
        
        return result
    
    def _simulate_outcome(self, hyp_type: str, patterns: Dict) -> str:
        """Simulate what would happen if hypothesis were true."""
        simulations = {
            "merge_modules": f"Could save ~{len(patterns.get('shared_modules', [])) * 50} LOC, reduce import complexity by ~{len(patterns.get('shared_modules', []))} imports",
            "extract_module": "Shared library would reduce duplication, but adds indirection layer",
            "remove_dependency": "Cleaner architecture, but may require interface extraction",
            "test_order": f"Could reduce test runtime by ~15% for {patterns.get('test_count', 0)} tests",
            "test_parallelism": f"Could reduce test runtime by ~40% (from ~{patterns.get('test_count', 0) // 100}s to ~{patterns.get('test_count', 0) // 250}s)",
            "reduce_complexity": "Easier to maintain, lower bug risk, but refactoring cost",
            "dead_code": f"Could remove ~{patterns.get('unused_loc', 100)} LOC of unused code",
            "cache_layer": "Could reduce repeated operations by ~60%",
            "batch_processing": "Could reduce API calls by ~70%",
            "plan_batching": "Daemon would generate fewer, higher-quality plans",
            "review_queue_optimization": "High-confidence plans would be reviewed first",
        }
        return simulations.get(hyp_type, "Outcome uncertain — needs investigation")
    
    def _suggest_validation(self, hyp_type: str, patterns: Dict) -> str:
        """Suggest how to validate the hypothesis."""
        validations = {
            "merge_modules": "Create PR with merged modules, run tests, measure LOC reduction",
            "extract_module": "Extract to shared lib, measure import count before/after",
            "remove_dependency": "Remove dep, add interface, run tests",
            "test_order": "Reorder tests by dependency graph, measure runtime",
            "test_parallelism": "Run with pytest-xdist, measure speedup",
            "reduce_complexity": "Refactor largest functions, verify tests still pass",
            "dead_code": "Run vulture/deadcode, remove unused, verify tests",
            "cache_layer": "Add caching, benchmark before/after",
            "batch_processing": "Implement batching, measure API call reduction",
            "plan_batching": "Modify daemon to batch, measure plan quality",
            "review_queue_optimization": "Sort queue by confidence, measure time-to-execute",
        }
        return validations.get(hyp_type, "Manual investigation required")
    
    def _find_related_patterns(self, patterns: Dict, hyp_type: str) -> List[str]:
        """Find related patterns from knowledge graph."""
        related = []
        if self.knowledge_graph:
            try:
                # Query knowledge graph for related patterns
                all_patterns = self.knowledge_graph.get_patterns() if hasattr(self.knowledge_graph, 'get_patterns') else []
                for p in all_patterns[:5]:
                    if hasattr(p, 'name'):
                        related.append(p.name)
            except Exception:
                pass
        return related
    
    def _store_in_epistemic(self, hypotheses: List[Hypothesis]):
        """Store hypotheses in Epistemic OS as low-confidence knowledge."""
        for h in hypotheses:
            try:
                self.epistemic_os.add(
                    content=h.content,
                    confidence=h.confidence,
                    topic="hypothesis",
                    tags=["dream", h.type, "unvalidated"],
                    context=json.dumps({
                        "simulated_outcome": h.simulated_outcome,
                        "validation_method": h.validation_method,
                        "hypothesis_id": h.hypothesis_id,
                    }),
                    decay_rate=h.confidence * 0.1,  # Higher initial conf → slower decay
                )
            except Exception:
                continue
    
    # ── Validation ──
    
    def validate_hypothesis(
        self,
        hypothesis_id: str,
        result: str,
        new_confidence: Optional[float] = None,
    ) -> bool:
        """Mark a hypothesis as validated (confirmed or rejected)."""
        for h in self.hypotheses:
            if h.hypothesis_id == hypothesis_id:
                h.validated = True
                h.validation_result = result
                if new_confidence is not None:
                    h.confidence = new_confidence
                self._save()
                return True
        return False
    
    def get_unvalidated(self) -> List[Hypothesis]:
        """Get all unvalidated hypotheses."""
        return [h for h in self.hypotheses if not h.validated]
    
    def get_by_type(self, hyp_type: str) -> List[Hypothesis]:
        """Get hypotheses by type."""
        return [h for h in self.hypotheses if h.type == hyp_type]
    
    def top_hypotheses(self, limit: int = 5) -> List[Hypothesis]:
        """Get top hypotheses by confidence (unvalidated only)."""
        unvalidated = self.get_unvalidated()
        return sorted(unvalidated, key=lambda h: h.confidence, reverse=True)[:limit]
    
    # ── Persistence ──
    
    def _save(self):
        """Save hypotheses to disk."""
        save_path = self.workdir / ".tini" / "dreams.json"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "last_dream": _now().isoformat(),
        }
        save_path.write_text(json.dumps(data, indent=2))
    
    def _load(self):
        """Load hypotheses from disk."""
        save_path = self.workdir / ".tini" / "dreams.json"
        if save_path.exists():
            try:
                data = json.loads(save_path.read_text())
                self.hypotheses = [Hypothesis.from_dict(h) for h in data.get("hypotheses", [])]
            except Exception:
                self.hypotheses = []
    
    # ── Reporting ──
    
    def report(self) -> Dict[str, Any]:
        """Generate a dream report."""
        return {
            "total_hypotheses": len(self.hypotheses),
            "unvalidated": len(self.get_unvalidated()),
            "validated": len(self.hypotheses) - len(self.get_unvalidated()),
            "by_type": {
                t: len(self.get_by_type(t))
                for t in set(h.type for h in self.hypotheses)
            },
            "top_hypotheses": [
                {
                    "content": h.content,
                    "confidence": h.confidence,
                    "type": h.type,
                    "outcome": h.simulated_outcome,
                }
                for h in self.top_hypotheses()
            ],
        }
