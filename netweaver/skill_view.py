"""Skill documentation extraction for cron prompt templates."""

from typing import Optional


# Template for skill listing in prompts
SKILL_SNIPPET = """## Available Skills

{%- for skill in skills %}
- **{skill.name}** — {skill.description}
{%- endfor %}
"""


def skill_view(agent: str = "") -> str:
    """Return skill documentation for cron prompt templates.

    Extracts inline documentation from prompt management system
    to reduce context bloat in prompt templates.

    Args:
        agent: Optional agent name for agent-specific skill docs.

    Returns:
        Formatted skill documentation string.
    """
    # Return agent-specific doc if agent provided
    if agent:
        return f"Skill documentation for agent: {agent}\n{SKILL_SNIPPET}"

    # Default: return template with placeholder
    return SKILL_SNIPPET
