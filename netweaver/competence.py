"""Competence Matrix — Agent specialization tracking and task routing.

Tracks what each agent is good at using Bayesian scoring from execution history.
Routes tasks to the most competent agent based on:
- Historical success rate per task type
- File familiarity
- Current load
- Epistemic confidence scores

This transforms multi-agent orchestration from round-robin to intelligent routing.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict


def _now() -> datetime:
    return datetime.now()


@dataclass
class TaskRecord:
    """A record of an agent's task execution."""
    agent_id: str
    task_id: str
    task_type: str          # "architecture", "bugfix", "refactor", "test", "feature"
    files_touched: List[str]
    success: bool
    duration_seconds: float
    timestamp: datetime = field(default_factory=_now)
    context: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "files_touched": self.files_touched,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TaskRecord":
        return cls(
            agent_id=data["agent_id"],
            task_id=data["task_id"],
            task_type=data["task_type"],
            files_touched=data.get("files_touched", []),
            success=data["success"],
            duration_seconds=data.get("duration_seconds", 0),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else _now(),
            context=data.get("context", {}),
        )


@dataclass
class AgentCompetence:
    """Competence profile for a single agent."""
    agent_id: str
    total_tasks: int = 0
    successful_tasks: int = 0
    task_type_stats: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: {"success": 0, "total": 0}))
    file_familiarity: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    avg_duration: float = 0.0
    last_active: datetime = field(default_factory=_now)
    specializations: List[str] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.5  # Prior: assume 50% until we know
        return self.successful_tasks / self.total_tasks
    
    def task_type_rate(self, task_type: str) -> float:
        """Success rate for a specific task type."""
        stats = self.task_type_stats.get(task_type, {"success": 0, "total": 0})
        if stats["total"] == 0:
            return 0.5  # Prior
        return stats["success"] / stats["total"]
    
    def file_familiarity_score(self, files: List[str]) -> float:
        """Score how familiar agent is with a set of files."""
        if not files:
            return 0.5
        familiar = sum(1 for f in files if f in self.file_familiarity)
        return familiar / len(files)
    
    def competence_score(self, task_type: str, files: Optional[List[str]] = None) -> float:
        """Overall competence score for a task."""
        type_rate = self.task_type_rate(task_type)
        file_score = self.file_familiarity_score(files or [])
        overall_rate = self.success_rate
        
        # Weighted combination
        # Task type matters most (50%), file familiarity (30%), overall (20%)
        score = (type_rate * 0.5) + (file_score * 0.3) + (overall_rate * 0.2)
        return min(1.0, max(0.0, score))
    
    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "task_type_stats": dict(self.task_type_stats),
            "file_familiarity": dict(self.file_familiarity),
            "avg_duration": self.avg_duration,
            "last_active": self.last_active.isoformat(),
            "specializations": self.specializations,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "AgentCompetence":
        comp = cls(agent_id=data["agent_id"])
        comp.total_tasks = data.get("total_tasks", 0)
        comp.successful_tasks = data.get("successful_tasks", 0)
        comp.task_type_stats = defaultdict(lambda: {"success": 0, "total": 0})
        comp.task_type_stats.update(data.get("task_type_stats", {}))
        comp.file_familiarity = defaultdict(int)
        comp.file_familiarity.update(data.get("file_familiarity", {}))
        comp.avg_duration = data.get("avg_duration", 0.0)
        comp.last_active = datetime.fromisoformat(data["last_active"]) if "last_active" in data else _now()
        comp.specializations = data.get("specializations", [])
        return comp


class CompetenceMatrix:
    """Tracks agent competence and routes tasks intelligently."""
    
    def __init__(
        self,
        workdir: Optional[Path] = None,
        epistemic_os=None,
    ):
        self.workdir = workdir or Path.home() / "Documents" / "myhermes"
        self.epistemic_os = epistemic_os
        self.agents: Dict[str, AgentCompetence] = {}
        self.records: List[TaskRecord] = []
        self._load()
    
    # ── Recording ──
    
    def record_task(self, record: TaskRecord):
        """Record a task execution result."""
        self.records.append(record)
        
        # Update agent competence
        if record.agent_id not in self.agents:
            self.agents[record.agent_id] = AgentCompetence(agent_id=record.agent_id)
        
        agent = self.agents[record.agent_id]
        agent.total_tasks += 1
        if record.success:
            agent.successful_tasks += 1
        
        # Update task type stats
        stats = agent.task_type_stats[record.task_type]
        stats["total"] += 1
        if record.success:
            stats["success"] += 1
        
        # Update file familiarity
        for f in record.files_touched:
            agent.file_familiarity[f] += 1
        
        # Update average duration
        if agent.total_tasks == 1:
            agent.avg_duration = record.duration_seconds
        else:
            agent.avg_duration = (
                (agent.avg_duration * (agent.total_tasks - 1) + record.duration_seconds)
                / agent.total_tasks
            )
        
        agent.last_active = _now()
        
        # Update specializations
        self._update_specializations(agent)
        
        # Store in Epistemic OS if available
        if self.epistemic_os:
            self._store_outcome(record)
        
        self._save()
    
    def record_simple(
        self,
        agent_id: str,
        task_id: str,
        task_type: str,
        success: bool,
        files: Optional[List[str]] = None,
        duration: float = 0,
    ):
        """Convenience method for recording a task."""
        record = TaskRecord(
            agent_id=agent_id,
            task_id=task_id,
            task_type=task_type,
            files_touched=files or [],
            success=success,
            duration_seconds=duration,
        )
        self.record_task(record)
    
    def _update_specializations(self, agent: AgentCompetence):
        """Determine agent's specializations based on performance."""
        specializations = []
        
        for task_type, stats in agent.task_type_stats.items():
            if stats["total"] >= 3:  # Need at least 3 attempts
                rate = stats["success"] / stats["total"]
                if rate >= 0.7:  # 70%+ success rate
                    specializations.append(task_type)
        
        agent.specializations = specializations
    
    def _store_outcome(self, record: TaskRecord):
        """Store task outcome in Epistemic OS."""
        try:
            content = f"Agent {record.agent_id} {'succeeded' if record.success else 'failed'} at {record.task_type} task {record.task_id}"
            confidence = 0.85 if record.success else 0.3
            self.epistemic_os.add(
                content=content,
                confidence=confidence,
                topic="competence",
                tags=["agent", record.agent_id, record.task_type, "outcome"],
                context=json.dumps({
                    "success": record.success,
                    "duration": record.duration_seconds,
                    "files": record.files_touched[:5],
                }),
                decay_rate=0.02,
            )
        except Exception:
            pass
    
    # ── Routing ──
    
    def route_task(
        self,
        task_type: str,
        files: Optional[List[str]] = None,
        exclude_agents: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Route a task to the most competent agent."""
        if not self.agents:
            return None
        
        exclude = set(exclude_agents or [])
        candidates = {
            aid: agent for aid, agent in self.agents.items()
            if aid not in exclude
        }
        
        if not candidates:
            return None
        
        # Score each agent
        scores = {
            aid: agent.competence_score(task_type, files)
            for aid, agent in candidates.items()
        }
        
        # Return highest scoring agent
        best_agent = max(scores, key=lambda k: scores[k])
        return best_agent
    
    def route_with_scores(
        self,
        task_type: str,
        files: Optional[List[str]] = None,
    ) -> List[Tuple[str, float]]:
        """Route a task and return all agents with their scores."""
        scores = []
        for aid, agent in self.agents.items():
            score = agent.competence_score(task_type, files)
            scores.append((aid, score))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores
    
    # ── Analysis ──
    
    def get_agent(self, agent_id: str) -> Optional[AgentCompetence]:
        """Get competence profile for an agent."""
        return self.agents.get(agent_id)
    
    def all_agents(self) -> List[AgentCompetence]:
        """Get all agent competence profiles."""
        return list(self.agents.values())
    
    def top_agents_by_type(self, task_type: str, limit: int = 3) -> List[Tuple[str, float]]:
        """Get top agents for a specific task type."""
        scores = []
        for aid, agent in self.agents.items():
            rate = agent.task_type_rate(task_type)
            stats = agent.task_type_stats.get(task_type, {"total": 0})
            # Weight by experience (more tasks = more reliable score)
            experience_factor = min(1.0, stats["total"] / 10)
            weighted = rate * (0.5 + 0.5 * experience_factor)
            scores.append((aid, weighted))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]
    
    def detect_imbalances(self) -> List[Dict]:
        """Detect workload imbalances across agents."""
        imbalances = []
        
        if len(self.agents) < 2:
            return imbalances
        
        task_counts = {aid: agent.total_tasks for aid, agent in self.agents.items()}
        avg_tasks = sum(task_counts.values()) / len(task_counts) if task_counts else 0
        
        for aid, count in task_counts.items():
            if avg_tasks > 0 and abs(count - avg_tasks) / avg_tasks > 0.5:
                imbalances.append({
                    "agent_id": aid,
                    "tasks": count,
                    "avg": avg_tasks,
                    "ratio": count / avg_tasks if avg_tasks > 0 else 0,
                    "issue": "overloaded" if count > avg_tasks else "underutilized",
                })
        
        return imbalances
    
    def team_report(self) -> Dict[str, Any]:
        """Generate a team competence report."""
        if not self.agents:
            return {"total_agents": 0, "total_tasks": 0}
        
        total_tasks = sum(a.total_tasks for a in self.agents.values())
        total_success = sum(a.successful_tasks for a in self.agents.values())
        
        # Find best agent per task type
        best_by_type = {}
        task_types = set()
        for agent in self.agents.values():
            for tt in agent.task_type_stats:
                task_types.add(tt)
        
        for tt in task_types:
            top = self.top_agents_by_type(tt, limit=1)
            if top:
                best_by_type[tt] = {"agent": top[0][0], "score": top[0][1]}
        
        return {
            "total_agents": len(self.agents),
            "total_tasks": total_tasks,
            "overall_success_rate": total_success / total_tasks if total_tasks > 0 else 0,
            "agents": {
                aid: {
                    "success_rate": agent.success_rate,
                    "total_tasks": agent.total_tasks,
                    "specializations": agent.specializations,
                    "avg_duration": agent.avg_duration,
                }
                for aid, agent in self.agents.items()
            },
            "best_by_type": best_by_type,
            "imbalances": self.detect_imbalances(),
        }
    
    # ── Import from existing data ──
    
    def from_memory_palace(self, palace_path: str):
        """Import execution history from Memory Palace."""
        path = Path(palace_path)
        if not path.exists():
            return
        
        try:
            data = json.loads(path.read_text())
            memories = data.get("memories", [])
            
            for memory in memories:
                # Look for execution records
                content = memory.get("content", "")
                if "executed" in content.lower() or "completed" in content.lower():
                    # Try to extract agent and outcome
                    agent = memory.get("agent", "unknown")
                    outcome = memory.get("outcome", "unknown")
                    
                    self.record_simple(
                        agent_id=agent,
                        task_id=memory.get("id", "imported"),
                        task_type="imported",
                        success=outcome == "success",
                        duration=memory.get("duration", 0),
                    )
        except Exception:
            pass
    
    # ── Persistence ──
    
    def _save(self):
        """Save competence data to disk."""
        save_path = self.workdir / ".tini" / "competence.json"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "agents": {aid: agent.to_dict() for aid, agent in self.agents.items()},
            "records": [r.to_dict() for r in self.records[-1000:]],  # Keep last 1000
            "updated": _now().isoformat(),
        }
        save_path.write_text(json.dumps(data, indent=2))
    
    def _load(self):
        """Load competence data from disk."""
        save_path = self.workdir / ".tini" / "competence.json"
        if not save_path.exists():
            return
        try:
            data = json.loads(save_path.read_text())
            self.agents = {
                aid: AgentCompetence.from_dict(ad)
                for aid, ad in data.get("agents", {}).items()
            }
            self.records = [
                TaskRecord.from_dict(r) for r in data.get("records", [])
            ]
        except Exception:
            self.agents = {}
            self.records = []
