"""Skill documentation extraction and rendering for prompt templates.

Provides rendering, filtering, and export format support for
skill documentation used in cron prompt templates.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Template for skill listing in prompts
SKILL_SNIPPET = """## Available Skills

{%- for skill in skills %}
- **{skill.name}** — {skill.description}
{%- endfor %}
"""


class SkillDoc:
    """A skill documentation entry with metadata."""

    def __init__(
        self,
        name: str,
        description: str = "",
        category: str = "",
        tags: Optional[List[str]] = None,
        author: str = "",
        version: str = "",
        content: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.category = category
        self.tags = tags or []
        self.author = author or "system"
        self.version = version or "1.0.0"
        self.content = content or description
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.updated_at = self.created_at

    def matches_filter(self, query: str) -> bool:
        """Check if skill matches a text query.

        Searches name, description, category, tags.
        Case-insensitive substring matching.
        """
        query_lower = query.lower()
        return (
            query_lower in self.name.lower()
            or query_lower in self.description.lower()
            or query_lower in self.category.lower()
            or any(query_lower in tag.lower() for tag in self.tags)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "author": self.author,
            "version": self.version,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SkillDoc":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            category=d.get("category", ""),
            tags=d.get("tags", []),
            author=d.get("author", "system"),
            version=d.get("version", "1.0.0"),
            content=d.get("content", ""),
        )


def skill_view(agent: str = "") -> str:
    """Return skill documentation for cron prompt templates.

    Args:
        agent: Optional agent name for agent-specific skill docs.

    Returns:
        Formatted skill documentation string.
    """
    if agent:
        return f"Skill documentation for agent: {agent}\n{SKILL_SNIPPET}"
    return SKILL_SNIPPET


def render_skills_markdown(skills: List[SkillDoc]) -> str:
    """Render a list of SkillDoc objects as formatted markdown.

    Args:
        skills: List of SkillDoc objects.

    Returns:
        Markdown formatted string.
    """
    lines = ["## Available Skills", ""]
    for skill in skills:
        tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
        cat_str = f" *(category: {skill.category})*" if skill.category else ""
        lines.append(f"- **{skill.name}**{tags_str}{cat_str} — {skill.description}")
    if not skills:
        lines.append("*No skills available.*")
    return "\n".join(lines)


def render_skills_json(skills: List[SkillDoc], indent: int = 2) -> str:
    """Render a list of SkillDoc objects as JSON.

    Args:
        skills: List of SkillDoc objects.
        indent: JSON indentation level.

    Returns:
        JSON formatted string.
    """
    return json.dumps([s.to_dict() for s in skills], indent=indent)


def render_skills_html(skills: List[SkillDoc]) -> str:
    """Render a list of SkillDoc objects as HTML.

    Args:
        skills: List of SkillDoc objects.

    Returns:
        HTML formatted string.
    """
    parts = ["<h2>Available Skills</h2>", "<ul>"]
    for skill in skills:
        tags_html = "".join(f'<span class="tag">{t}</span> ' for t in skill.tags)
        cat_html = f' <em>({skill.category})</em>' if skill.category else ""
        parts.append(
            f'<li><strong>{skill.name}</strong>{cat_html}'
            f' {tags_html}— {skill.description}</li>'
        )
    parts.append("</ul>")
    return "\n".join(parts)


def render_skills_rst(skills: List[SkillDoc]) -> str:
    """Render a list of SkillDoc objects as reStructuredText.

    Args:
        skills: List of SkillDoc objects.

    Returns:
        RST formatted string.
    """
    lines = [
        "Available Skills",
        "=================",
        "",
    ]
    for skill in skills:
        tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
        lines.append(f"- **{skill.name}**{tags_str}")
        lines.append(f"  {skill.description}")
        if skill.category:
            lines.append(f"  *Category: {skill.category}*")
        lines.append("")
    if not skills:
        lines.append("*No skills available.*")
    return "\n".join(lines)


def filter_skills(
    skills: List[SkillDoc],
    query: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> List[SkillDoc]:
    """Filter a list of SkillDoc objects by query, category, and tags.

    Args:
        skills: List of SkillDoc objects to filter.
        query: Optional text query for name/description/category/tags match.
        category: Optional exact category match.
        tags: Optional tag filter (any matching tag includes the skill).

    Returns:
        Filtered list of SkillDoc objects.
    """
    result = skills
    if query:
        result = [s for s in result if s.matches_filter(query)]
    if category:
        result = [s for s in result if s.category == category]
    if tags:
        result = [s for s in result if any(t in s.tags for t in tags)]
    return result


def export_skills(
    skills: List[SkillDoc],
    fmt: str = "markdown",
) -> str:
    """Export skills in the specified format.

    Args:
        skills: List of SkillDoc objects.
        fmt: Export format. One of "markdown", "json", "html", "rst".

    Returns:
        Formatted string in the requested format.

    Raises:
        ValueError: If format is not supported.
    """
    if fmt == "markdown":
        return render_skills_markdown(skills)
    elif fmt == "json":
        return render_skills_json(skills)
    elif fmt == "html":
        return render_skills_html(skills)
    elif fmt == "rst":
        return render_skills_rst(skills)
    else:
        raise ValueError(f"Unsupported export format: {fmt}")
