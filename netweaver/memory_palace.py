"""Agent Memory Palace — Persistent memory for autonomous agents.

Each agent (reviewer, worker, daemon) gets a persistent memory store.
Memories are decisions + outcomes that inform future decisions.

Architecture:
- JSON-backed storage (one file per agent type)
- Semantic fingerprinting for similarity queries
- Temporal decay (older memories weighted less)
- Outcome tracking (success/failure patterns)
- Auto-pruning of low-value memories

Usage:
    palace = MemoryPalace("reviewer")
    palace.remember(decision="approved NW-027", context={"scope": "test-healer", "files": ["netweaver/test_healer.py"]}, outcome="success")
    similar = palace.recall(query={"scope": "test-healer"}, limit=5)
    insight = palace.introspect()  # What patterns lead to success?
"""

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


MEMORY_DIR = Path.home() / "Documents/myhermes/.tini/memory_palace"
MAX_MEMORIES_PER_AGENT = 500
DECAY_HALFLIFE_DAYS = 30  # Memory weight halves every 30 days
SIMILARITY_THRESHOLD = 0.3  # Minimum similarity to consider a match


@dataclass
class Memory:
    """A single memory entry."""
    id: str
    agent_type: str  # "reviewer", "worker", "daemon"
    decision: str  # What was decided
    context: Dict[str, Any]  # Context around the decision
    outcome: str  # "success", "failure", "partial", "pending"
    outcome_details: str = ""  # What happened after
    timestamp: float = 0.0
    access_count: int = 0
    last_accessed: float = 0.0
    tags: List[str] = field(default_factory=list)
    related_memory_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if self.last_accessed == 0.0:
            self.last_accessed = self.timestamp
        if not self.id:
            self.id = self._generate_id()

    def _generate_id(self) -> str:
        """Generate unique ID from content + timestamp."""
        content = f"{self.agent_type}:{self.decision}:{self.timestamp}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def age_days(self) -> float:
        """How old is this memory in days."""
        return (time.time() - self.timestamp) / 86400

    def decay_weight(self) -> float:
        """Temporal decay factor (1.0 = fresh, approaches 0 over time)."""
        return math.exp(-0.693 * self.age_days() / DECAY_HALFLIFE_DAYS)

    def relevance_score(self) -> float:
        """Combined score: decay × access_frequency × outcome_weight."""
        outcome_weight = {
            "success": 1.0,
            "partial": 0.7,
            "pending": 0.5,
            "failure": 0.8,  # Failures are still informative
        }.get(self.outcome, 0.5)

        access_bonus = min(1.0 + math.log1p(self.access_count) * 0.1, 2.0)

        return self.decay_weight() * access_bonus * outcome_weight

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Memory":
        """Deserialize from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _tokenize(text: str) -> set:
    """Extract meaningful tokens from text."""
    # Lowercase, split on non-alphanumeric, remove short tokens
    tokens = re.findall(r"[a-z][a-z0-9_]+", text.lower())
    return set(t for t in tokens if len(t) > 2)


def _context_fingerprint(context: Dict[str, Any]) -> set:
    """Create a fingerprint from context dict for similarity matching."""
    tokens = set()
    for key, value in context.items():
        tokens.add(f"k:{key}")
        if isinstance(value, str):
            tokens.update(_tokenize(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    tokens.update(_tokenize(item))
        elif isinstance(value, dict):
            tokens.update(_context_fingerprint(value))
        else:
            tokens.add(f"v:{value}")
    return tokens


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


class MemoryPalace:
    """Persistent memory store for an autonomous agent.

    Each agent type gets its own palace. Memories are stored as JSON
    with semantic fingerprinting for similarity queries.
    """

    def __init__(self, agent_type: str, memory_dir: Optional[Path] = None):
        """Initialize memory palace for an agent type.

        Args:
            agent_type: One of "reviewer", "worker", "daemon", "planner"
            memory_dir: Override storage directory (default: .tini/memory_palace/)
        """
        self.agent_type = agent_type
        self.memory_dir = memory_dir or MEMORY_DIR
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.memory_dir / f"{agent_type}.json"
        self._memories: Dict[str, Memory] = {}
        self._load()

    def _load(self) -> None:
        """Load memories from disk."""
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text())
                for entry in data.get("memories", []):
                    mem = Memory.from_dict(entry)
                    self._memories[mem.id] = mem
            except (json.JSONDecodeError, OSError, TypeError):
                self._memories = {}

    def _save(self) -> None:
        """Persist memories to disk."""
        data = {
            "agent_type": self.agent_type,
            "updated": datetime.now(timezone.utc).isoformat(),
            "count": len(self._memories),
            "memories": [m.to_dict() for m in self._memories.values()],
        }
        self._file.write_text(json.dumps(data, indent=2, default=str))

    @property
    def count(self) -> int:
        """Number of memories stored."""
        return len(self._memories)

    def remember(
        self,
        decision: str,
        context: Dict[str, Any],
        outcome: str = "pending",
        outcome_details: str = "",
        tags: Optional[List[str]] = None,
    ) -> Memory:
        """Store a new memory.

        Args:
            decision: What was decided (e.g., "approved plan NW-027")
            context: Context dict (scope, files, constraints, etc.)
            outcome: "success", "failure", "partial", "pending"
            outcome_details: What happened after the decision
            tags: Optional tags for filtering

        Returns:
            The created Memory object
        """
        mem = Memory(
            id="",
            agent_type=self.agent_type,
            decision=decision,
            context=context,
            outcome=outcome,
            outcome_details=outcome_details,
            tags=tags or [],
        )
        mem.id = mem._generate_id()
        self._memories[mem.id] = mem

        # Auto-prune if over limit
        if len(self._memories) > MAX_MEMORIES_PER_AGENT:
            self._prune()

        self._save()
        return mem

    def recall(
        self,
        query: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        outcome: Optional[str] = None,
        limit: int = 10,
        min_similarity: float = SIMILARITY_THRESHOLD,
    ) -> List[Tuple[Memory, float]]:
        """Recall similar memories.

        Args:
            query: Context dict to match against (similarity search)
            tags: Filter by tags (any match)
            outcome: Filter by outcome ("success", "failure", etc.)
            limit: Max results
            min_similarity: Minimum Jaccard similarity threshold

        Returns:
            List of (Memory, similarity_score) tuples, sorted by relevance
        """
        results: List[Tuple[Memory, float]] = []
        query_fp = _context_fingerprint(query) if query else None

        for mem in self._memories.values():
            # Filter by outcome
            if outcome and mem.outcome != outcome:
                continue

            # Filter by tags
            if tags and not any(t in mem.tags for t in tags):
                continue

            # Compute similarity
            if query_fp:
                mem_fp = _context_fingerprint(mem.context)
                similarity = _jaccard_similarity(query_fp, mem_fp)
                if similarity < min_similarity:
                    continue
            else:
                similarity = 1.0  # No query = return all (sorted by relevance)

            # Weighted score: similarity × relevance
            score = similarity * mem.relevance_score()
            results.append((mem, score))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)

        # Mark accessed
        now = time.time()
        for mem, _ in results[:limit]:
            mem.access_count += 1
            mem.last_accessed = now

        if results:
            self._save()

        return results[:limit]

    def update_outcome(self, memory_id: str, outcome: str, details: str = "") -> bool:
        """Update the outcome of an existing memory.

        Args:
            memory_id: ID of the memory to update
            outcome: New outcome ("success", "failure", etc.)
            details: Outcome details

        Returns:
            True if memory was found and updated
        """
        if memory_id not in self._memories:
            return False

        mem = self._memories[memory_id]
        mem.outcome = outcome
        if details:
            mem.outcome_details = details
        self._save()
        return True

    def forget(self, memory_id: str) -> bool:
        """Remove a memory.

        Args:
            memory_id: ID of the memory to remove

        Returns:
            True if memory was found and removed
        """
        if memory_id in self._memories:
            del self._memories[memory_id]
            self._save()
            return True
        return False

    def introspect(self) -> Dict[str, Any]:
        """Analyze memory patterns and extract insights.

        Returns:
            Dict with insights about the agent's decision patterns
        """
        if not self._memories:
            return {
                "total_memories": 0,
                "success_rate": 0.0,
                "top_patterns": [],
                "insights": ["No memories yet — agent is learning."],
            }

        memories = list(self._memories.values())

        # Outcome distribution
        outcomes = {}
        for m in memories:
            outcomes[m.outcome] = outcomes.get(m.outcome, 0) + 1

        success_rate = outcomes.get("success", 0) / len(memories) if memories else 0

        # Tag frequency
        tag_freq: Dict[str, int] = {}
        for m in memories:
            for tag in m.tags:
                tag_freq[tag] = tag_freq.get(tag, 0) + 1
        top_tags = sorted(tag_freq.items(), key=lambda x: x[1], reverse=True)[:10]

        # Success patterns — what contexts lead to success?
        success_contexts: Dict[str, int] = {}
        failure_contexts: Dict[str, int] = {}
        for m in memories:
            bucket = success_contexts if m.outcome == "success" else failure_contexts
            for key in m.context:
                bucket[key] = bucket.get(key, 0) + 1

        # Generate insights
        insights = []
        if success_rate > 0.8:
            insights.append(f"High success rate ({success_rate:.0%}) — agent decisions are reliable.")
        elif success_rate < 0.4:
            insights.append(f"Low success rate ({success_rate:.0%}) — agent may need constraint tightening.")

        if outcomes.get("failure", 0) > 0:
            fail_tags = [t for t, _ in top_tags if any(
                t in m.tags and m.outcome == "failure" for m in memories
            )]
            if fail_tags:
                insights.append(f"Failures correlate with tags: {', '.join(fail_tags[:3])}")

        # Oldest vs newest memory
        oldest = min(m.timestamp for m in memories)
        newest = max(m.timestamp for m in memories)
        span_days = (newest - oldest) / 86400
        insights.append(f"Memory span: {span_days:.1f} days ({len(memories)} memories)")

        # Decision velocity
        if span_days > 0:
            velocity = len(memories) / span_days
            insights.append(f"Decision rate: {velocity:.1f}/day")

        return {
            "total_memories": len(memories),
            "success_rate": success_rate,
            "outcome_distribution": outcomes,
            "top_tags": top_tags,
            "success_context_keys": sorted(success_contexts.items(), key=lambda x: x[1], reverse=True)[:5],
            "failure_context_keys": sorted(failure_contexts.items(), key=lambda x: x[1], reverse=True)[:5],
            "insights": insights,
        }

    def _prune(self) -> None:
        """Remove lowest-value memories to stay under limit."""
        if len(self._memories) <= MAX_MEMORIES_PER_AGENT:
            return

        # Score all memories
        scored = [(m, m.relevance_score()) for m in self._memories.values()]
        scored.sort(key=lambda x: x[1])  # Lowest score first

        # Remove bottom 20%
        to_remove = len(self._memories) - int(MAX_MEMORIES_PER_AGENT * 0.8)
        for mem, _ in scored[:to_remove]:
            del self._memories[mem.id]

        self._save()

    def clear(self) -> int:
        """Remove all memories.

        Returns:
            Number of memories removed
        """
        count = len(self._memories)
        self._memories.clear()
        self._save()
        return count

    def export(self) -> List[Dict[str, Any]]:
        """Export all memories as list of dicts."""
        return [m.to_dict() for m in self._memories.values()]

    def __len__(self) -> int:
        return len(self._memories)

    def __repr__(self) -> str:
        return f"MemoryPalace(agent_type='{self.agent_type}', memories={len(self._memories)})"
