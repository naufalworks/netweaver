"""Skill documentation extraction utilities for prompt templates."""
from __future__ import annotations

import json
import re
from typing import Optional

SKILL_DOC_START = "<<<SKILL_DOC_START>>>"
SKILL_DOC_END = "<<<SKILL_DOC_END>>>"
SKILL_META_PATTERN = r"<<<SKILL_DOC_META:([^>]+)>>>"


def extract_skill_doc(prompt: str, start_tag: str = SKILL_DOC_START, end_tag: str = SKILL_DOC_END) -> Optional[str]:
    """Extract content between start_tag and end_tag markers.

    Returns None if markers not found.
    Raises ValueError if markers found but content is empty.
    """
    if start_tag not in prompt or end_tag not in prompt:
        return None
    idx_start = prompt.index(start_tag) + len(start_tag)
    idx_end = prompt.index(end_tag)
    content = prompt[idx_start:idx_end]
    if not content:
        raise ValueError("Empty skill doc content between markers")
    return content


def extract_skill_metadata(prompt: str, start_tag: str = SKILL_DOC_START, end_tag: str = SKILL_DOC_END) -> dict:
    """Extract and parse metadata from skill doc markers.

    If content is valid JSON, returns parsed dict.
    Otherwise returns {"raw_doc": content}.
    """
    content = extract_skill_doc(prompt, start_tag, end_tag)
    if content is None:
        return {}
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return {"raw_doc": content}


def remove_skill_doc(prompt: str) -> str:
    """Remove SKILL_DOC markers and their content from the prompt."""
    result = prompt
    space_end = ""
    while SKILL_DOC_START in result and SKILL_DOC_END in result:
        idx_start = result.index(SKILL_DOC_START)
        idx_end = result.index(SKILL_DOC_END) + len(SKILL_DOC_END)
        result = result[:idx_start] + " " + result[idx_end:]
        space_end = " "
    result = re.sub(SKILL_META_PATTERN, "", result).strip()
    return result


def has_skill_doc(prompt: str) -> bool:
    """Check if prompt contains skill doc markers."""
    return SKILL_DOC_START in prompt and SKILL_DOC_END in prompt


def skill_view(agent: str = "") -> str:
    """Return skill documentation for cron prompt templates."""
    docs = "Skill doc content"
    if agent:
        docs = f"Skill doc content for {agent}"
    return docs
