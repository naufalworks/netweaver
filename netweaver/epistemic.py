"""Epistemic OS — Honest reasoning for AI systems.

Every piece of knowledge has:
- Confidence: How sure are we? (0.0 - 1.0)
- Decay: How fast does confidence drop over time?
- Provenance: Where did this come from?
- Contradictions: What conflicts with this?
- Context: Under what conditions is this true?

Core insight: Knowledge isn't binary (true/false).
It's probabilistic, contextual, and decaying.

Usage:
    os = EpistemicOS()
    
    # Add knowledge
    os.add("Postgres handles 10K QPS",
           confidence=0.7,
           sources=["benchmark_2023.py"],
           context="read queries, SSD storage",
           decay_rate=0.05)  # -5% per month
    
    # Query with honest uncertainty
    answer = os.query("Can we handle 50K QPS?")
    # → "Uncertain (40% confidence). Best data: 10K QPS (6mo old)..."
    
    # Detect contradictions
    os.add("Postgres handles 5K QPS", confidence=0.6)
    contradictions = os.detect_contradictions()
    # → [Contradiction(a, b, severity=0.3)]
    
    # Check what's stale
    stale = os.stale_knowledge(threshold=0.4)
    # → Nodes with confidence < 40%
    
    # Trace provenance
    chain = os.trace("Postgres handles 10K QPS")
    # → [blog_post → internal_benchmark → design_doc → auth.py]
"""

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Source:
    """Origin of a piece of knowledge."""
    type: str  # "benchmark", "blog", "meeting", "code", "conversation", "observation"
    ref: str   # URL, file path, meeting date, etc.
    author: str = ""
    created: datetime = field(default_factory=_now)
    trustworthiness: float = 0.5  # How reliable is this source type?
    
    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "ref": self.ref,
            "author": self.author,
            "created": self.created.isoformat(),
            "trustworthiness": self.trustworthiness,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Source":
        return cls(
            type=data["type"],
            ref=data["ref"],
            author=data.get("author", ""),
            created=datetime.fromisoformat(data["created"]) if "created" in data else _now(),
            trustworthiness=data.get("trustworthiness", 0.5),
        )


# Default trustworthiness by source type
SOURCE_TRUST = {
    "benchmark": 0.9,
    "test_result": 0.9,
    "measurement": 0.85,
    "code": 0.8,
    "documentation": 0.7,
    "blog": 0.5,
    "conversation": 0.4,
    "hearsay": 0.2,
}


@dataclass
class KnowledgeNode:
    """A piece of knowledge with epistemic metadata."""
    
    # Content
    content: str
    topic: str = ""  # e.g. "postgres_performance", "api_design"
    tags: List[str] = field(default_factory=list)
    context: str = ""  # Under what conditions is this true?
    
    # Confidence
    confidence: float = 0.5  # 0.0 (no idea) to 1.0 (certain)
    
    # Temporal
    created: datetime = field(default_factory=_now)
    last_verified: datetime = field(default_factory=_now)
    decay_rate: float = 0.0  # Confidence loss per month (0.0 = no decay)
    
    # Provenance
    sources: List[Source] = field(default_factory=list)
    
    # Relationships
    contradictions: List[str] = field(default_factory=list)  # IDs of contradicting nodes
    supports: List[str] = field(default_factory=list)  # IDs of supporting nodes
    depends_on: List[str] = field(default_factory=list)  # Other knowledge this relies on
    citations: List[str] = field(default_factory=list)  # Where this knowledge is used
    
    # Access tracking
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    
    # Internal
    _id: str = ""
    
    def __post_init__(self):
        if not self._id:
            self._id = _hash_id(self.content)
    
    @property
    def id(self) -> str:
        return self._id or _hash_id(self.content)
    
    @property
    def current_confidence(self) -> float:
        """Confidence after temporal decay."""
        if self.decay_rate <= 0:
            return self.confidence
        
        months_old = (_now() - self.last_verified).days / 30.44
        decayed = self.confidence * math.pow(1 - self.decay_rate, months_old)
        return max(0.01, decayed)  # Floor at 1%
    
    @property
    def effective_confidence(self) -> float:
        """Confidence factoring in source trustworthiness."""
        if not self.sources:
            return self.current_confidence
        
        avg_trust = sum(s.trustworthiness for s in self.sources) / len(self.sources)
        # Blend: 60% current confidence, 40% source trust
        return 0.6 * self.current_confidence + 0.4 * avg_trust
    
    @property
    def is_stale(self) -> bool:
        return self.current_confidence < 0.4
    
    @property
    def age_days(self) -> int:
        return (_now() - self.last_verified).days
    
    @property
    def confidence_label(self) -> str:
        c = self.effective_confidence
        if c >= 0.9: return "highly certain"
        if c >= 0.7: return "likely"
        if c >= 0.5: return "uncertain"
        if c >= 0.3: return "weak"
        return "unreliable"
    
    def touch(self):
        """Record an access."""
        self.access_count += 1
        self.last_accessed = _now()
    
    def verify(self):
        """Mark as re-verified now."""
        self.last_verified = _now()
    
    def to_dict(self) -> Dict:
        return {
            "content": self.content,
            "topic": self.topic,
            "tags": self.tags,
            "context": self.context,
            "confidence": self.confidence,
            "created": self.created.isoformat(),
            "last_verified": self.last_verified.isoformat(),
            "decay_rate": self.decay_rate,
            "sources": [s.to_dict() for s in self.sources],
            "contradictions": self.contradictions,
            "supports": self.supports,
            "depends_on": self.depends_on,
            "citations": self.citations,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "_id": self._id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "KnowledgeNode":
        node = cls(
            content=data["content"],
            topic=data.get("topic", ""),
            tags=data.get("tags", []),
            context=data.get("context", ""),
            confidence=data.get("confidence", 0.5),
            created=datetime.fromisoformat(data["created"]) if "created" in data else _now(),
            last_verified=datetime.fromisoformat(data["last_verified"]) if "last_verified" in data else _now(),
            decay_rate=data.get("decay_rate", 0.0),
            sources=[Source.from_dict(s) for s in data.get("sources", [])],
            contradictions=data.get("contradictions", []),
            supports=data.get("supports", []),
            depends_on=data.get("depends_on", []),
            citations=data.get("citations", []),
            access_count=data.get("access_count", 0),
        )
        node._id = data.get("_id", node._id)
        return node


@dataclass
class Contradiction:
    """Two pieces of knowledge that conflict."""
    node_a_id: str
    node_b_id: str
    severity: float  # 0.0 (minor) to 1.0 (critical)
    reason: str = ""
    detected: datetime = field(default_factory=_now)
    resolved: bool = False
    resolution: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "node_a_id": self.node_a_id,
            "node_b_id": self.node_b_id,
            "severity": self.severity,
            "reason": self.reason,
            "detected": self.detected.isoformat(),
            "resolved": self.resolved,
            "resolution": self.resolution,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Contradiction":
        return cls(
            node_a_id=data["node_a_id"],
            node_b_id=data["node_b_id"],
            severity=data.get("severity", 0.5),
            reason=data.get("reason", ""),
            detected=datetime.fromisoformat(data["detected"]) if "detected" in data else _now(),
            resolved=data.get("resolved", False),
            resolution=data.get("resolution", ""),
        )


@dataclass
class EpistemicAnswer:
    """Response to a knowledge query with honest uncertainty."""
    content: str
    confidence: float
    supporting: List[KnowledgeNode] = field(default_factory=list)
    contradicting: List[KnowledgeNode] = field(default_factory=list)
    stale_warnings: List[str] = field(default_factory=list)
    recommendation: str = ""
    provenance_chain: List[str] = field(default_factory=list)
    
    @property
    def confidence_label(self) -> str:
        c = self.confidence
        if c >= 0.9: return "highly certain"
        if c >= 0.7: return "likely"
        if c >= 0.5: return "uncertain"
        if c >= 0.3: return "weak"
        return "unreliable"
    
    def __str__(self) -> str:
        parts = []
        parts.append(f"[{self.confidence_label} ({self.confidence:.0%})]")
        parts.append(self.content)
        
        if self.stale_warnings:
            parts.append(f"\n⚠️  Stale: {'; '.join(self.stale_warnings)}")
        
        if self.contradicting:
            parts.append(f"\n⚠️  Contradicted by {len(self.contradicting)} source(s)")
        
        if self.recommendation:
            parts.append(f"\n→ {self.recommendation}")
        
        return "\n".join(parts)


class EpistemicOS:
    """Honest reasoning engine.
    
    Knowledge with confidence, decay, provenance, and contradiction detection.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        self.nodes: Dict[str, KnowledgeNode] = {}
        self.contradictions: List[Contradiction] = []
        self._storage_path = storage_path
        
        if storage_path and Path(storage_path).exists():
            self._load()
    
    # ── Core Operations ──
    
    def add(
        self,
        content: str,
        confidence: float = 0.5,
        topic: str = "",
        tags: Optional[List[str]] = None,
        context: str = "",
        sources: Optional[List[Source]] = None,
        decay_rate: float = 0.0,
        depends_on: Optional[List[str]] = None,
    ) -> KnowledgeNode:
        """Add a piece of knowledge with epistemic metadata."""
        node = KnowledgeNode(
            content=content,
            confidence=min(1.0, max(0.0, confidence)),
            topic=topic,
            tags=tags or [],
            context=context,
            sources=sources or [],
            decay_rate=decay_rate,
            depends_on=depends_on or [],
        )
        
        self.nodes[node.id] = node
        
        # Check for contradictions
        new_contradictions = self._check_contradictions(node)
        self.contradictions.extend(new_contradictions)
        
        # Persist
        if self._storage_path:
            self._save()
        
        return node
    
    def query(self, question: str, limit: int = 10) -> EpistemicAnswer:
        """Query knowledge with honest uncertainty."""
        # Find relevant nodes
        tokens = _tokenize(question)
        scored = []
        
        for node in self.nodes.values():
            score = _relevance_score(node, tokens)
            if score > 0:
                node.touch()
                scored.append((score, node))
        
        scored.sort(key=lambda x: x[0] * x[1].effective_confidence, reverse=True)
        relevant = [n for _, n in scored[:limit]]
        
        if not relevant:
            return EpistemicAnswer(
                content="No relevant knowledge found.",
                confidence=0.0,
                recommendation="This topic hasn't been documented yet.",
            )
        
        # Build answer
        supporting = relevant[:5]
        contradicting = []
        stale_warnings = []
        
        for node in supporting:
            if node.is_stale:
                stale_warnings.append(
                    f'"{_truncate(node.content, 50)}" is {node.age_days}d old '
                    f'({node.confidence_label})'
                )
            # Find contradictions
            for cid in node.contradictions:
                if cid in self.nodes:
                    contradicting.append(self.nodes[cid])
        
        # Aggregate confidence
        if supporting:
            avg_conf = sum(n.effective_confidence for n in supporting) / len(supporting)
            # Penalize for contradictions
            contradiction_penalty = len(contradicting) * 0.1
            final_conf = max(0.0, avg_conf - contradiction_penalty)
        else:
            final_conf = 0.0
        
        # Generate recommendation
        recommendation = self._generate_recommendation(
            supporting, contradicting, stale_warnings, final_conf
        )
        
        # Build content
        if len(supporting) == 1:
            content = supporting[0].content
        else:
            facts = [f"• {_truncate(n.content, 80)} ({n.confidence_label})" 
                     for n in supporting[:5]]
            content = "Based on " + str(len(supporting)) + " relevant facts:\n" + "\n".join(facts)
        
        # Provenance chain
        prov = []
        for n in supporting[:3]:
            for s in n.sources:
                prov.append(f"{s.type}: {s.ref}")
        
        answer = EpistemicAnswer(
            content=content,
            confidence=final_conf,
            supporting=supporting,
            contradicting=contradicting,
            stale_warnings=stale_warnings,
            recommendation=recommendation,
            provenance_chain=prov,
        )
        
        if self._storage_path:
            self._save()
        
        return answer
    
    def trace(self, content_or_id: str) -> List[Dict]:
        """Trace the provenance chain of a piece of knowledge."""
        node = self._find_node(content_or_id)
        if not node:
            return []
        
        chain = []
        visited = set()
        self._trace_recursive(node, chain, visited, depth=0)
        return chain
    
    def verify(self, content_or_id: str, new_confidence: Optional[float] = None) -> bool:
        """Re-verify a piece of knowledge."""
        node = self._find_node(content_or_id)
        if not node:
            return False
        
        node.verify()
        if new_confidence is not None:
            node.confidence = min(1.0, max(0.0, new_confidence))
        
        if self._storage_path:
            self._save()
        return True
    
    def update_node(
        self,
        node_id: str,
        confidence: Optional[float] = None,
        last_verified: Optional[datetime] = None,
        verification_method: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Update a knowledge node's metadata."""
        node = self._find_node(node_id)
        if not node:
            return False
        
        if confidence is not None:
            node.confidence = min(1.0, max(0.0, confidence))
        if last_verified is not None:
            node.last_verified = last_verified
        else:
            node.verify()  # Update last_verified to now
        if verification_method is not None:
            # Add to sources if not already there
            method_source = Source(type="verification", ref=verification_method)
            # Check if this source already exists
            existing_refs = {s.ref for s in node.sources if isinstance(s, Source)}
            if method_source.ref not in existing_refs:
                node.sources.append(method_source)
        if tags is not None:
            node.tags = list(set(node.tags + tags))
        
        if self._storage_path:
            self._save()
        return True
    
    # ── Analysis ──
    
    def detect_contradictions(self) -> List[Contradiction]:
        """Find all unresolved contradictions."""
        return [c for c in self.contradictions if not c.resolved]
    
    def stale_knowledge(self, threshold: float = 0.4) -> List[KnowledgeNode]:
        """Find knowledge that's become unreliable."""
        return [n for n in self.nodes.values() if n.current_confidence < threshold]
    
    def confidence_distribution(self) -> Dict[str, int]:
        """Distribution of confidence levels across all knowledge."""
        dist = {"highly_certain": 0, "likely": 0, "uncertain": 0, "weak": 0, "unreliable": 0}
        for node in self.nodes.values():
            label = node.confidence_label.replace(" ", "_")
            if label in dist:
                dist[label] += 1
        return dist
    
    def health_report(self) -> Dict:
        """Overall health of the knowledge base."""
        nodes = list(self.nodes.values())
        if not nodes:
            return {
                "total_knowledge": 0,
                "avg_confidence": 0.0,
                "stale_count": 0,
                "contradictions": 0,
                "topics": 0,
                "health_score": 0.0,
            }
        
        avg_conf = sum(n.current_confidence for n in nodes) / len(nodes)
        stale = len([n for n in nodes if n.is_stale])
        unresolved = len(self.detect_contradictions())
        topics = len(set(n.topic for n in nodes if n.topic))
        
        # Health score: 0-100
        score = (
            avg_conf * 40 +                          # 40% weight: avg confidence
            (1 - stale / max(1, len(nodes))) * 30 +   # 30% weight: freshness
            (1 - min(1, unresolved / 5)) * 20 +        # 20% weight: few contradictions
            min(1, topics / 3) * 10                     # 10% weight: topic diversity
        )
        
        return {
            "total_knowledge": len(nodes),
            "avg_confidence": avg_conf,
            "stale_count": stale,
            "contradictions": unresolved,
            "topics": topics,
            "health_score": score,
            "health_label": (
                "excellent" if score >= 80 else
                "good" if score >= 60 else
                "fair" if score >= 40 else
                "poor"
            ),
            "top_tags": _top_tags(nodes, 10),
            "source_types": _source_distribution(nodes),
            "confidence_distribution": self.confidence_distribution(),
        }
    
    def recommend_verification(self) -> List[Tuple[KnowledgeNode, str]]:
        """What should be verified next? (Highest impact of re-verification)"""
        candidates = []
        for node in self.nodes.values():
            # Impact = (uncertainty) * (citation_count + 1)
            uncertainty = 1.0 - node.current_confidence
            impact = uncertainty * (len(node.citations) + 1)
            reason = self._verification_reason(node)
            candidates.append((impact, node, reason))
        
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [(node, reason) for _, node, reason in candidates[:20]]
    
    # ── Propagation ──
    
    def propagate_confidence(self) -> Dict[str, float]:
        """Propagate confidence through dependency chains.
        
        If A depends on B, and B has low confidence → A's confidence drops.
        """
        updated = {}
        for node in self.nodes.values():
            if not node.depends_on:
                continue
            
            dep_confidences = []
            for dep_id in node.depends_on:
                if dep_id in self.nodes:
                    dep_confidences.append(self.nodes[dep_id].current_confidence)
            
            if dep_confidences:
                min_dep = min(dep_confidences)
                # If any dependency is weak, reduce this node's confidence
                if min_dep < node.current_confidence:
                    old = node.current_confidence
                    new = node.current_confidence * (0.5 + 0.5 * min_dep)
                    if abs(old - new) > 0.01:
                        updated[node.id] = new
        
        return updated
    
    # ── Integration with Memory Palace ──
    
    def from_memory_palace(self, palace_path: str):
        """Import memories from a Memory Palace JSON file."""
        path = Path(palace_path)
        if not path.exists():
            return
        
        data = json.loads(path.read_text())
        for mem_data in data.get("memories", []):
            outcome = mem_data.get("outcome", "unknown")
            confidence = (
                0.8 if outcome == "success" else
                0.3 if outcome == "failure" else
                0.5
            )
            
            tags = mem_data.get("tags", [])
            topic = tags[0] if tags else ""
            
            self.add(
                content=mem_data.get("decision", ""),
                confidence=confidence,
                topic=topic,
                tags=tags,
                context=str(mem_data.get("context", {})),
                decay_rate=0.02,  # Memories decay slowly
                sources=[Source(type="memory_palace", ref=str(path))],
            )
    
    # ── Persistence ──
    
    def _save(self):
        if not self._storage_path:
            return
        p = Path(self._storage_path)
        data = {
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "contradictions": [c.to_dict() for c in self.contradictions],
            "saved_at": _now().isoformat(),
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    
    def _load(self):
        data = json.loads(Path(self._storage_path).read_text())
        for nid, ndata in data.get("nodes", {}).items():
            self.nodes[nid] = KnowledgeNode.from_dict(ndata)
        for cdata in data.get("contradictions", []):
            self.contradictions.append(Contradiction.from_dict(cdata))
    
    # ── Internal helpers ──
    
    def _find_node(self, content_or_id: str) -> Optional[KnowledgeNode]:
        if content_or_id in self.nodes:
            return self.nodes[content_or_id]
        for node in self.nodes.values():
            if node.content == content_or_id:
                return node
        # Partial match
        lower = content_or_id.lower()
        for node in self.nodes.values():
            if lower in node.content.lower():
                return node
        return None
    
    def _check_contradictions(self, new_node: KnowledgeNode) -> List[Contradiction]:
        """Check if new node contradicts existing knowledge."""
        found = []
        new_tokens = _tokenize(new_node.content)
        
        for existing in self.nodes.values():
            if existing.id == new_node.id:
                continue
            
            # Same topic + different content = potential contradiction
            if existing.topic and new_node.topic and existing.topic == new_node.topic:
                if existing.content != new_node.content:
                    overlap = _token_overlap(new_tokens, _tokenize(existing.content))
                    if overlap > 0.3:  # Significant overlap suggests same subject
                        severity = overlap * abs(existing.confidence - new_node.confidence + 0.5)
                        new_node.contradictions.append(existing.id)
                        existing.contradictions.append(new_node.id)
                        found.append(Contradiction(
                            node_a_id=new_node.id,
                            node_b_id=existing.id,
                            severity=min(1.0, severity),
                            reason=f"Same topic ({new_node.topic}), overlapping content",
                        ))
        
        return found
    
    def _generate_recommendation(
        self,
        supporting: List[KnowledgeNode],
        contradicting: List[KnowledgeNode],
        stale: List[str],
        confidence: float,
    ) -> str:
        if confidence >= 0.8 and not contradicting and not stale:
            return "Knowledge is solid. No action needed."
        
        parts = []
        if stale:
            parts.append(f"Re-verify {len(stale)} stale fact(s)")
        if contradicting:
            parts.append(f"Resolve {len(contradicting)} contradiction(s)")
        if confidence < 0.5:
            parts.append("Gather more evidence before acting on this")
        if not parts:
            parts.append("Consider adding more sources to increase confidence")
        return ". ".join(parts) + "."
    
    def _trace_recursive(
        self, node: KnowledgeNode, chain: List[Dict], visited: Set[str], depth: int
    ):
        if node.id in visited or depth > 10:
            return
        visited.add(node.id)
        
        entry = {
            "depth": depth,
            "id": node.id,
            "content": node.content,
            "confidence": node.effective_confidence,
            "label": node.confidence_label,
            "sources": [f"{s.type}: {s.ref}" for s in node.sources],
        }
        chain.append(entry)
        
        for dep_id in node.depends_on:
            if dep_id in self.nodes:
                self._trace_recursive(self.nodes[dep_id], chain, visited, depth + 1)
    
    def _verification_reason(self, node: KnowledgeNode) -> str:
        reasons = []
        if node.age_days > 90:
            reasons.append(f"{node.age_days}d old")
        if node.current_confidence < 0.5:
            reasons.append(f"low confidence ({node.current_confidence:.0%})")
        if len(node.citations) > 3:
            reasons.append(f"used in {len(node.citations)} places")
        if node.decay_rate > 0:
            reasons.append(f"decays at {node.decay_rate:.0%}/mo")
        return ", ".join(reasons) if reasons else "routine check"


# ── Utility functions ──

def _hash_id(text: str) -> str:
    """Deterministic ID from content."""
    import hashlib
    normalized = text.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _tokenize(text: str) -> Set[str]:
    """Simple tokenization."""
    return set(re.findall(r'[a-zA-Z]+', text.lower()))


def _token_overlap(a: Set[str], b: Set[str]) -> float:
    """Jaccard similarity."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _relevance_score(node: KnowledgeNode, tokens: Set[str]) -> float:
    """How relevant is this node to the query?"""
    node_tokens = _tokenize(node.content + " " + node.topic + " " + " ".join(node.tags))
    overlap = len(tokens & node_tokens)
    if not tokens:
        return 0.0
    return overlap / len(tokens)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len-3] + "..."


def _top_tags(nodes: List[KnowledgeNode], n: int) -> List[Tuple[str, int]]:
    tag_counts = defaultdict(int)
    for node in nodes:
        for tag in node.tags:
            tag_counts[tag] += 1
    return sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:n]


def _source_distribution(nodes: List[KnowledgeNode]) -> Dict[str, int]:
    dist = defaultdict(int)
    for node in nodes:
        for source in node.sources:
            dist[source.type] += 1
    return dict(dist)
