"""Causal Chain Analysis — Trace failures back to root causes.

When a test fails, don't just show the error — trace the entire causal chain
from code change → runtime behavior → test failure.

Uses git history, import graphs, and code dependency analysis to build
causal chains with confidence scores.
"""

import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field


def _now() -> datetime:
    return datetime.now()


def _hash(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:16]


@dataclass
class CausalLink:
    """A single link in a causal chain."""
    source: str          # What caused this
    effect: str          # What it produced
    confidence: float    # How sure we are (0-1)
    evidence: str        # Supporting evidence
    timestamp: datetime = field(default_factory=_now)
    
    def to_dict(self) -> Dict:
        return {
            "source": self.source,
            "effect": self.effect,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CausalChain:
    """A chain of causal links from root cause to observed failure."""
    failure: str                     # The observed failure
    root_cause: str                  # The identified root cause
    chain: List[CausalLink] = field(default_factory=list)
    confidence: float = 0.0         # Overall chain confidence
    fix_suggestion: str = ""         # Suggested fix
    fix_confidence: float = 0.0     # Confidence in fix
    related_commits: List[str] = field(default_factory=list)
    
    @property
    def depth(self) -> int:
        return len(self.chain)
    
    def to_dict(self) -> Dict:
        return {
            "failure": self.failure,
            "root_cause": self.root_cause,
            "chain": [l.to_dict() for l in self.chain],
            "confidence": self.confidence,
            "fix_suggestion": self.fix_suggestion,
            "fix_confidence": self.fix_confidence,
            "related_commits": self.related_commits,
        }


class CausalChainTracer:
    """Traces causal chains from test failures to root causes."""
    
    def __init__(self, workdir: Optional[Path] = None):
        self.workdir = workdir or Path.home() / "Documents" / "myhermes"
        self._import_cache: Dict[str, List] = {}
        self._file_cache: Dict[str, str] = {}
    
    # ── Main API ──
    
    def trace_failure(self, test_name: str, error_message: str) -> CausalChain:
        """Trace a test failure back to its root cause."""
        chain = CausalChain(
            failure=f"{test_name}: {error_message[:100]}",
            root_cause="Unknown",
        )
        
        # Step 1: Parse the test to find what it tests
        test_module = self._find_test_module(test_name)
        if not test_module:
            chain.root_cause = "Test module not found"
            chain.confidence = 0.1
            return chain
        
        # Step 2: Build import dependency chain
        imports = self._get_imports(test_module)
        
        # Step 3: Find recent changes to imported modules
        recent_changes = self._get_recent_changes(imports, days=7)
        
        # Step 4: Match error to likely cause
        root_cause, confidence, fix = self._match_error_to_cause(
            error_message, imports, recent_changes
        )
        
        chain.root_cause = root_cause
        chain.confidence = confidence
        chain.fix_suggestion = fix
        chain.fix_confidence = confidence * 0.8  # Fix confidence slightly lower
        chain.related_commits = [c.get("hash", "") for c in recent_changes[:3]]
        
        # Build causal links
        if recent_changes:
            most_recent = recent_changes[0]
            chain.chain.append(CausalLink(
                source=f"Commit {most_recent.get('hash', 'unknown')[:8]}",
                effect=f"Changed {most_recent.get('files', ['unknown'])[0] if most_recent.get('files') else 'unknown'}",
                confidence=0.9,
                evidence=most_recent.get("message", ""),
            ))
        
        for imp in imports[:3]:
            chain.chain.append(CausalLink(
                source=str(imp.name) if hasattr(imp, 'name') else str(imp),
                effect=f"Imported by {test_module.name}",
                confidence=0.85,
                evidence=f"import dependency chain",
            ))
        
        chain.chain.append(CausalLink(
            source="Runtime behavior change",
            effect=error_message[:100],
            confidence=confidence,
            evidence=f"Error pattern matches: {root_cause}",
        ))
        
        return chain
    
    def trace_error_pattern(self, error_text: str) -> CausalChain:
        """Trace a general error (not test-specific) to root cause."""
        chain = CausalChain(
            failure=error_text[:200],
            root_cause="Unknown",
        )
        
        # Extract file references from error
        files = self._extract_file_references(error_text)
        
        # Find recent changes to those files
        recent = self._get_recent_changes_for_files(files, days=7)
        
        if recent:
            most_recent = recent[0]
            chain.root_cause = f"Recent change in {most_recent.get('file', 'unknown')}"
            chain.confidence = 0.7
            chain.related_commits = [most_recent.get("hash", "")]
            chain.fix_suggestion = f"Review commit {most_recent.get('hash', 'unknown')[:8]}: {most_recent.get('message', '')}"
            chain.fix_confidence = 0.6
        else:
            chain.root_cause = "No recent changes found — may be environmental"
            chain.confidence = 0.3
            chain.fix_suggestion = "Check environment, dependencies, and configuration"
            chain.fix_confidence = 0.3
        
        return chain
    
    def batch_trace(self, failures: List[Tuple[str, str]]) -> List[CausalChain]:
        """Trace multiple failures and find common root causes."""
        chains = []
        for test_name, error in failures:
            chain = self.trace_failure(test_name, error)
            chains.append(chain)
        
        # Find common root causes
        root_causes = {}
        for chain in chains:
            rc = chain.root_cause
            root_causes.setdefault(rc, []).append(chain)
        
        # If multiple failures share a root cause, boost confidence
        for rc, affected_chains in root_causes.items():
            if len(affected_chains) > 1:
                boost = min(0.2, 0.05 * (len(affected_chains) - 1))
                for chain in affected_chains:
                    chain.confidence = min(1.0, chain.confidence + boost)
        
        return chains
    
    # ── Internal Analysis ──
    
    def _find_test_module(self, test_name: str) -> Optional[Path]:
        """Find the test file containing a test function."""
        # Convert test name to likely file path
        # e.g., "test_epistemic.py::TestUpdateNode::test_update_confidence"
        parts = test_name.split("::")
        file_part = parts[0] if parts else test_name
        
        # Search in tests/ directory
        tests_dir = self.workdir / "tests"
        if tests_dir.exists():
            for f in tests_dir.glob("*.py"):
                if file_part in f.name:
                    return f
                # Also check if test name is in the file
                try:
                    content = f.read_text(errors="ignore")
                    if file_part in content:
                        return f
                except Exception:
                    continue
        
        return None
    
    def _get_imports(self, module: Path) -> List:
        """Get all imported modules from a Python file."""
        if str(module) in self._import_cache:
            return self._import_cache[str(module)]
        
        imports = []
        try:
            content = module.read_text(errors="ignore")
            
            # Find import statements
            import_patterns = [
                r"^from\s+(netweaver\.\w+)\s+import",
                r"^import\s+(netweaver\.\w+)",
                r"^from\s+(\.?\w+)\s+import",
            ]
            
            for pattern in import_patterns:
                for match in re.finditer(pattern, content, re.MULTILINE):
                    mod_name = match.group(1)
                    mod_path = self._resolve_module(mod_name)
                    if mod_path and mod_path.exists():
                        imports.append(mod_path)
        except Exception:
            pass
        
        self._import_cache[str(module)] = imports
        return imports
    
    def _resolve_module(self, module_name: str) -> Optional[Path]:
        """Resolve a module name to a file path."""
        # netweaver.epistemic → netweaver/epistemic.py
        if module_name.startswith("netweaver."):
            relative = module_name.replace(".", "/") + ".py"
            return self.workdir / relative
        elif module_name.startswith("."):
            relative = module_name.lstrip(".") + ".py"
            return self.workdir / "netweaver" / relative
        else:
            relative = module_name.replace(".", "/") + ".py"
            return self.workdir / relative
    
    def _get_recent_changes(self, modules: List[Path], days: int = 7) -> List[Dict]:
        """Get recent git changes to specified modules."""
        changes = []
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        for module in modules[:10]:  # Limit to 10 modules
            try:
                relative = str(module.relative_to(self.workdir))
                result = subprocess.run(
                    ["git", "log", "--oneline", f"--since={since}",
                     "--format=%H|%s|%ad", "--date=short", "--", relative],
                    cwd=str(self.workdir),
                    capture_output=True, text=True, timeout=10,
                )
                
                for line in result.stdout.strip().split("\n"):
                    if line and "|" in line:
                        parts = line.split("|", 2)
                        changes.append({
                            "hash": parts[0][:8],
                            "message": parts[1] if len(parts) > 1 else "",
                            "date": parts[2] if len(parts) > 2 else "",
                            "file": relative,
                            "files": [relative],
                        })
            except Exception:
                continue
        
        # Sort by date (most recent first)
        changes.sort(key=lambda c: c.get("date", ""), reverse=True)
        return changes
    
    def _get_recent_changes_for_files(self, files: List[str], days: int = 7) -> List[Dict]:
        """Get recent changes for specific files."""
        changes = []
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        for file_path in files[:10]:
            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", f"--since={since}",
                     "--format=%H|%s|%ad", "--date=short", "-1", "--", file_path],
                    cwd=str(self.workdir),
                    capture_output=True, text=True, timeout=10,
                )
                
                for line in result.stdout.strip().split("\n"):
                    if line and "|" in line:
                        parts = line.split("|", 2)
                        changes.append({
                            "hash": parts[0][:8],
                            "message": parts[1] if len(parts) > 1 else "",
                            "date": parts[2] if len(parts) > 2 else "",
                            "file": file_path,
                        })
            except Exception:
                continue
        
        return changes
    
    def _match_error_to_cause(
        self,
        error: str,
        imports: List[Path],
        recent_changes: List[Dict],
    ) -> Tuple[str, float, str]:
        """Match an error message to a likely root cause."""
        error_lower = error.lower()
        
        # Pattern matching for common error types
        patterns = [
            (
                ["attributeerror", "has no attribute"],
                lambda: self._check_attribute_change(imports, recent_changes),
            ),
            (
                ["importerror", "cannot import", "no module named"],
                lambda: self._check_import_change(imports, recent_changes),
            ),
            (
                ["assertionerror", "assert", "expected"],
                lambda: self._check_logic_change(imports, recent_changes),
            ),
            (
                ["typeerror", "argument", "takes"],
                lambda: self._check_signature_change(imports, recent_changes),
            ),
            (
                ["keyerror", "indexerror", "out of range"],
                lambda: self._check_data_structure_change(imports, recent_changes),
            ),
        ]
        
        for keywords, checker in patterns:
            if any(kw in error_lower for kw in keywords):
                cause, confidence, fix = checker()
                if confidence > 0.3:
                    return cause, confidence, fix
        
        # Default: check if any recent changes touch imported modules
        if recent_changes:
            most_recent = recent_changes[0]
            return (
                f"Recent change to {most_recent.get('file', 'unknown')} ({most_recent.get('hash', 'unknown')[:8]})",
                0.5,
                f"Review and potentially revert commit {most_recent.get('hash', 'unknown')[:8]}",
            )
        
        return ("No recent changes found — may be test flakiness", 0.2, "Rerun test to check flakiness")
    
    def _check_attribute_change(self, imports: List[Path], changes: List[Dict]) -> Tuple[str, float, str]:
        """Check if an attribute was renamed/removed."""
        if changes:
            c = changes[0]
            return (
                f"Attribute renamed/removed in {c.get('file', 'unknown')} (commit {c.get('hash', '?')[:8]})",
                0.7,
                f"Check {c.get('file', 'unknown')} for renamed attributes",
            )
        return ("Attribute change in imported module", 0.4, "Check imported modules for API changes")
    
    def _check_import_change(self, imports: List[Path], changes: List[Dict]) -> Tuple[str, float, str]:
        """Check if an import path changed."""
        if changes:
            c = changes[0]
            return (
                f"Module moved/renamed: {c.get('file', 'unknown')} (commit {c.get('hash', '?')[:8]})",
                0.75,
                f"Update import paths for {c.get('file', 'unknown')}",
            )
        return ("Module restructured", 0.5, "Check module structure and import paths")
    
    def _check_logic_change(self, imports: List[Path], changes: List[Dict]) -> Tuple[str, float, str]:
        """Check if logic changed in a way that breaks assertions."""
        if changes:
            c = changes[0]
            return (
                f"Logic change in {c.get('file', 'unknown')} broke assertion (commit {c.get('hash', '?')[:8]})",
                0.65,
                f"Update test expectations to match new behavior in {c.get('file', 'unknown')}",
            )
        return ("Behavior change in tested code", 0.4, "Review test expectations against current implementation")
    
    def _check_signature_change(self, imports: List[Path], changes: List[Dict]) -> Tuple[str, float, str]:
        """Check if a function signature changed."""
        if changes:
            c = changes[0]
            return (
                f"Function signature changed in {c.get('file', 'unknown')} (commit {c.get('hash', '?')[:8]})",
                0.7,
                f"Update call sites to match new signature in {c.get('file', 'unknown')}",
            )
        return ("Function signature changed", 0.5, "Check function signatures in imported modules")
    
    def _check_data_structure_change(self, imports: List[Path], changes: List[Dict]) -> Tuple[str, float, str]:
        """Check if a data structure changed shape."""
        if changes:
            c = changes[0]
            return (
                f"Data structure changed in {c.get('file', 'unknown')} (commit {c.get('hash', '?')[:8]})",
                0.6,
                f"Update code to handle new data structure in {c.get('file', 'unknown')}",
            )
        return ("Data structure shape changed", 0.35, "Check dict/list structures in imported modules")
    
    def _extract_file_references(self, text: str) -> List[str]:
        """Extract file paths from error text."""
        # Match common file path patterns
        patterns = [
            r'File "([^"]+\.py)"',
            r'in (\S+\.py)',
            r'(\w+/\w+\.py)',
            r'(\w+\.py):\d+',
        ]
        
        files = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            files.extend(matches)
        
        return list(set(files))
    
    # ── Reporting ──
    
    def format_chain(self, chain: CausalChain) -> str:
        """Format a causal chain for human-readable output."""
        lines = []
        lines.append(f"═══ CAUSAL CHAIN ═══")
        lines.append(f"Failure: {chain.failure[:100]}")
        lines.append(f"Root Cause: {chain.root_cause}")
        lines.append(f"Confidence: {chain.confidence:.0%}")
        lines.append(f"Chain Depth: {chain.depth}")
        lines.append("")
        
        if chain.chain:
            lines.append("Links:")
            for i, link in enumerate(chain.chain):
                lines.append(f"  {i+1}. {link.source} → {link.effect}")
                lines.append(f"     Confidence: {link.confidence:.0%} | Evidence: {link.evidence[:60]}")
            lines.append("")
        
        if chain.fix_suggestion:
            lines.append(f"Fix: {chain.fix_suggestion}")
            lines.append(f"Fix Confidence: {chain.fix_confidence:.0%}")
        
        if chain.related_commits:
            lines.append(f"Related Commits: {', '.join(chain.related_commits[:3])}")
        
        return "\n".join(lines)
