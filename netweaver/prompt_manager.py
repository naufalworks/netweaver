"""Prompt-as-Code — versioned prompt management with auto-optimization.

Prompts stored as .prompt files under .tini/prompts/<agent-name>/v<N>.prompt
A 'current' file holds the active version number.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class PromptVersion:
    """A single prompt version with metadata."""

    def __init__(
        self,
        version: int,
        agent: str,
        content: str,
        success_rate: float = 1.0,
        avg_tokens: int = 0,
        failures: Optional[list[str]] = None,
        parent: Optional[int] = None,
        author: str = "system",
        reason: str = "",
        created_at: Optional[str] = None,
    ):
        self.version = version
        self.agent = agent
        self.content = content
        self.success_rate = success_rate
        self.avg_tokens = avg_tokens
        self.failures = failures or []
        self.parent = parent
        self.author = author
        self.reason = reason
        self.created_at = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    @property
    def token_estimate(self) -> int:
        """Rough estimate: ~4 chars per token for English text."""
        return len(self.content) // 4

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "agent": self.agent,
            "content": self.content,
            "success_rate": self.success_rate,
            "avg_tokens": self.avg_tokens,
            "failures": self.failures,
            "parent": self.parent,
            "author": self.author,
            "reason": self.reason,
            "created_at": self.created_at,
            "token_estimate": self.token_estimate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PromptVersion":
        return cls(
            version=d["version"],
            agent=d["agent"],
            content=d["content"],
            success_rate=d.get("success_rate", 1.0),
            avg_tokens=d.get("avg_tokens", 0),
            failures=d.get("failures", []),
            parent=d.get("parent"),
            author=d.get("author", "system"),
            reason=d.get("reason", ""),
            created_at=d.get("created_at"),
        )


# Module-level for test mocking
def skill_view(agent: str = "") -> str:
    """Return skill documentation for cron prompt templates."""
    docs = "Skill doc content"
    if agent:
        docs = f"Skill doc content for {agent}"
    return docs


class PromptManager:
    """Versioned prompt manager with auto-optimization.

    Directory structure:
        .tini/prompts/<agent-name>/
            registry.json       — version manifest
            current             — file with active version number
            v1.prompt
            v2.prompt
            ...
    """

    SKILL_SNIPPET = """## Available Skills

{%- for skill in skills %}
- **{skill.name}** — {skill.description}
{%- endfor %}
"""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _agent_dir(self, agent: str) -> Path:
        d = self.root / ".tini" / "prompts" / agent
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _registry_path(self, agent: str) -> Path:
        return self._agent_dir(agent) / "registry.json"

    def _prompt_path(self, agent: str, version: int) -> Path:
        return self._agent_dir(agent) / f"v{version}.prompt"

    def _current_path(self, agent: str) -> Path:
        return self._agent_dir(agent) / "current"

    # ── read ─────────────────────────────────────────────────────────

    def load_registry(self, agent: str) -> list[PromptVersion]:
        """Load all registered versions for an agent."""
        path = self._registry_path(agent)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            return [PromptVersion.from_dict(v) for v in data]
        except (json.JSONDecodeError, KeyError):
            return []

    def current_version(self, agent: str) -> Optional[PromptVersion]:
        """Get the current active prompt with fallback to last registry entry."""
        current_path = self._current_path(agent)
        registry = self.load_registry(agent)
        if not registry:
            return None
        if current_path.exists():
            try:
                version_num = int(current_path.read_text().strip())
                for v in registry:
                    if v.version == version_num:
                        return v
            except (ValueError, OSError):
                pass
        return registry[-1]

    def get_version(self, agent: str, version: int) -> Optional[PromptVersion]:
        """Get a specific version by number."""
        path = self._prompt_path(agent, version)
        if not path.exists():
            return None
        content = path.read_text()
        return PromptVersion(
            version=version,
            agent=agent,
            content=content,
        )

    # ── write ─────────────────────────────────────────────────────────

    def save_version(self, agent: str, content: str, reason: str = "", author: str = "system") -> PromptVersion:
        """Save a new prompt version and set it as current."""
        registry = self.load_registry(agent)
        next_version = (registry[-1].version + 1) if registry else 1

        self._prompt_path(agent, next_version).write_text(content)

        version = PromptVersion(
            version=next_version,
            agent=agent,
            content=content,
            author=author,
            reason=reason,
            parent=registry[-1].version if registry else None,
        )
        registry.append(version)
        self._registry_path(agent).write_text(json.dumps([v.to_dict() for v in registry], indent=2))
        self._current_path(agent).write_text(str(next_version))
        return version

    def save_prompt(self, agent: str, content: str) -> PromptVersion:
        """Alias for save_version."""
        return self.save_version(agent, content)

    # ── record run ───────────────────────────────────────────────────

    def record_run(self, agent: str, success: bool, tokens_used: int = 0, error: str = "") -> None:
        """Record an execution result for the current prompt.

        Updates registry with EMA success_rate, max avg_tokens,
        deduplicated and trimmed (to 10) failure list.
        """
        registry = self.load_registry(agent)
        if not registry:
            return
        cur = registry[-1]
        alpha = 0.1
        cur.success_rate = cur.success_rate * (1 - alpha) + (1.0 if success else 0.0) * alpha
        if tokens_used > cur.avg_tokens:
            cur.avg_tokens = tokens_used
        if not success and error:
            if error not in cur.failures:
                cur.failures.append(error)
                if len(cur.failures) > 10:
                    cur.failures = cur.failures[-10:]
        self._registry_path(agent).write_text(json.dumps([v.to_dict() for v in registry], indent=2))

    # ── rollback ─────────────────────────────────────────────────────

    def rollback(self, agent: str, target_version: Optional[int] = None) -> Optional[int]:
        """Roll back to a target version or the previous version."""
        registry = self.load_registry(agent)
        if not registry:
            return None
        if target_version is not None:
            if not any(v.version == target_version for v in registry):
                return None
            self._current_path(agent).write_text(str(target_version))
            return target_version
        current_path = self._current_path(agent)
        if not current_path.exists():
            return None
        try:
            cur_ver = int(current_path.read_text().strip())
        except (ValueError, OSError):
            return None
        sorted_vers = sorted(v.version for v in registry)
        if cur_ver == sorted_vers[0]:
            return None
        prev = sorted_vers[sorted_vers.index(cur_ver) - 1]
        current_path.write_text(str(prev))
        return prev

    # ── convenience ──────────────────────────────────────────────────

    def current_prompt_text(self, agent: str) -> str:
        v = self.current_version(agent)
        return v.content if v else ""

    def list_versions(self, agent: str) -> list[int]:
        return [v.version for v in self.load_registry(agent)]

    def all_agents(self) -> list[str]:
        agents_dir = self.root / ".tini" / "prompts"
        if not agents_dir.exists():
            return []
        return sorted(d.name for d in agents_dir.iterdir() if d.is_dir() and (d / "registry.json").exists())

    # ── optimization ─────────────────────────────────────────────────

    def needs_optimization(self, agent: str) -> Optional[str]:
        """Check if prompt needs optimization.

        Returns reason string or None.
        """
        registry = self.load_registry(agent)
        if not registry:
            return "no_prompt"
        cur = registry[-1]
        reasons = []
        if len(cur.failures) >= 3:
            reasons.append("repeated_failures")
        if cur.success_rate < 0.5:
            reasons.append("low_success_rate")
        if cur.token_estimate > 2000:
            reasons.append("large_prompt")
        return " + ".join(reasons) if reasons else None

    def optimize(self, agent: str, content: str) -> int:
        """Optimize a prompt by saving a new version.

        Returns the version number of the new prompt.
        """
        self.save_version(agent, content, reason="optimization")
        v = self.current_version(agent)
        return v.version if v else 1

    # ── template helpers ──────────────────────────────────────────────

    def build_cron_prompt(self, agent: str, task: str) -> str:
        """Build cron prompt template with skill documentation."""
        return f"""### Cron Task for {agent}

Task: {task}

### Skill Documentation
{skill_view(agent)}

Execute the above task using the skills above.
Respond with JSON containing: success (bool), output (str), errors (list[str]).
"""
