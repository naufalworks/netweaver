"""Skill documentation extraction utilities for prompt templates.

Provides marker-based extraction, multi-format parsing (markdown, HTML, RST),
structured skill document extraction, and skill doc manipulation utilities.
"""

from __future__ import annotations

import html.parser
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SKILL_DOC_START = "<<<SKILL_DOC_START>>>"
SKILL_DOC_END = "<<<SKILL_DOC_END>>>"
SKILL_META_PATTERN = r"<<<SKILL_DOC_META:([^>]+)>>>"


# ── marker-based extraction (original API) ────────────────────────────


def extract_skill_doc(
    prompt: str,
    start_tag: str = SKILL_DOC_START,
    end_tag: str = SKILL_DOC_END,
) -> Optional[str]:
    """Extract content between start_tag and end_tag markers.

    Args:
        prompt: The prompt text containing skill doc markers.
        start_tag: Opening marker string.
        end_tag: Closing marker string.

    Returns:
        Content between markers, or None if markers not found.

    Raises:
        ValueError: If markers found but content is empty.
    """
    if start_tag not in prompt or end_tag not in prompt:
        return None
    idx_start = prompt.index(start_tag) + len(start_tag)
    idx_end = prompt.index(end_tag)
    content = prompt[idx_start:idx_end]
    if not content or content.isspace():
        raise ValueError("Empty skill doc content between markers")
    return content


def extract_skill_metadata(
    prompt: str,
    start_tag: str = SKILL_DOC_START,
    end_tag: str = SKILL_DOC_END,
) -> dict:
    """Extract and parse metadata from skill doc markers.

    If content is valid JSON, returns parsed dict.
    Otherwise returns {"raw_doc": content}.

    Args:
        prompt: The prompt text containing skill doc markers.
        start_tag: Opening marker string.
        end_tag: Closing marker string.

    Returns:
        Parsed metadata dict, or raw content wrapper.
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
    """Remove SKILL_DOC markers and their content from the prompt.

    Args:
        prompt: The prompt text to clean.

    Returns:
        Prompt with all skill doc markers removed.
    """
    result = prompt
    while SKILL_DOC_START in result and SKILL_DOC_END in result:
        idx_start = result.index(SKILL_DOC_START)
        idx_end = result.index(SKILL_DOC_END) + len(SKILL_DOC_END)
        result = result[:idx_start] + " " + result[idx_end:]
    result = re.sub(SKILL_META_PATTERN, "", result).strip()
    return result


def has_skill_doc(prompt: str) -> bool:
    """Check if prompt contains skill doc markers.

    Args:
        prompt: The prompt text to inspect.

    Returns:
        True if both start and end markers are present.
    """
    return SKILL_DOC_START in prompt and SKILL_DOC_END in prompt


def skill_view(agent: str = "") -> str:
    """Return skill documentation for cron prompt templates.

    Args:
        agent: Optional agent name for agent-specific skill docs.

    Returns:
        Skill documentation string.
    """
    docs = "Skill doc content"
    if agent:
        docs = f"Skill doc content for {agent}"
    return docs


# ── structured extraction result ──────────────────────────────────────


@dataclass
class ExtractedSection:
    """A section extracted from skill documentation."""

    heading: str
    body: str
    level: int = 1
    subsections: List["ExtractedSection"] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Structured result from multi-format skill doc extraction."""

    format: str  # "markdown", "html", "rst", "plain"
    title: str = ""
    sections: List[ExtractedSection] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    raw_content: str = ""

    def section_count(self) -> int:
        """Count total sections including nested."""
        count = len(self.sections)
        for section in self.sections:
            count += len(section.subsections)
        return count

    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "format": self.format,
            "title": self.title,
            "sections": [
                {
                    "heading": s.heading,
                    "body": s.body,
                    "level": s.level,
                    "subsections": [
                        {"heading": ss.heading, "body": ss.body, "level": ss.level}
                        for ss in s.subsections
                    ],
                }
                for s in self.sections
            ],
            "metadata": self.metadata,
            "raw_content": self.raw_content,
        }


# ── multi-format extraction ───────────────────────────────────────────


def _parse_markdown_heading(line: str) -> Optional[Tuple[int, str]]:
    """Parse a markdown heading line.

    Args:
        line: A line of text.

    Returns:
        Tuple of (level, heading_text) or None if not a heading.
    """
    match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
    if match:
        return len(match.group(1)), match.group(2).strip()
    return None


def extract_skill_doc_md(content: str) -> ExtractionResult:
    """Extract structured skill documentation from markdown content.

    Parses headings (H1-H6), extracts section bodies, and builds
    a structured ExtractionResult with title and sections.

    Args:
        content: Markdown content to parse.

    Returns:
        Structured ExtractionResult.
    """
    sections: List[ExtractedSection] = []
    current_section: Optional[ExtractedSection] = None
    current_body: List[str] = []
    metadata: Dict[str, str] = {}

    # Check for YAML frontmatter
    remaining = content
    if remaining.startswith("---"):
        end_idx = remaining.find("---", 3)
        if end_idx != -1:
            fm_lines = remaining[3:end_idx].strip().split("\n")
            for fm_line in fm_lines:
                if ":" in fm_line:
                    key, _, val = fm_line.partition(":")
                    metadata[key.strip()] = val.strip()
            remaining = remaining[end_idx + 3:].strip()

    lines = remaining.split("\n")
    title = ""
    first_heading_found = False

    for line in lines:
        heading = _parse_markdown_heading(line)

        if heading:
            level, text = heading
            if not first_heading_found and level == 1:
                title = text
                first_heading_found = True
                # flush any previous body
                section = ExtractedSection(heading=text, body="", level=level)
                sections.append(section)
                current_section = section
                current_body = []
            else:
                # flush current body
                if current_section is not None and current_body:
                    current_section.body = "\n".join(current_body).strip()
                    current_body = []
                section = ExtractedSection(heading=text, body="", level=level)
                # attach as subsection if level > parent
                if current_section and level > current_section.level:
                    current_section.subsections.append(section)
                else:
                    sections.append(section)
                current_section = section
        else:
            current_body.append(line)

    # flush remaining body
    if current_section is not None and current_body:
        current_section.body = "\n".join(current_body).strip()

    return ExtractionResult(
        format="markdown",
        title=title,
        sections=sections,
        metadata=metadata,
        raw_content=content,
    )


class _HTMLSkillParser(html.parser.HTMLParser):
    """HTML parser that extracts skill documentation structure."""

    def __init__(self) -> None:
        super().__init__()
        self.sections: List[ExtractedSection] = []
        self.current_tag: str = ""
        self.current_attrs: Dict[str, Optional[str]] = {}
        self.heading_text: str = ""
        self.body_text: List[str] = []
        self.in_body: bool = False
        self.title: str = ""
        self._skip_tags = {"script", "style", "nav", "footer"}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.current_tag = tag
        self.current_attrs = dict(attrs)
        if tag in self._skip_tags:
            self.in_body = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_text = ""
            self.in_body = False
        elif tag in ("p", "li", "div", "section", "pre", "code"):
            self.in_body = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            self.in_body = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            text = self.heading_text.strip()
            if level == 1 and not self.title:
                self.title = text
            section = ExtractedSection(
                heading=text, body="", level=level
            )
            self.sections.append(section)
            self.heading_text = ""
            self.in_body = False
        elif tag in ("p", "li"):
            if self.body_text:
                self.in_body = False

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        if self.current_tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_text += stripped + " "
        elif self.in_body and self.sections:
            self.body_text.append(stripped)
            # attach body to last section
            self.sections[-1].body = "\n".join(self.body_text)


def extract_skill_doc_html(content: str) -> ExtractionResult:
    """Extract structured skill documentation from HTML content.

    Parses heading tags (H1-H6), extracts section text content,
    and builds a structured ExtractionResult.

    Args:
        content: HTML content to parse.

    Returns:
        Structured ExtractionResult.
    """
    parser = _HTMLSkillParser()
    try:
        parser.feed(content)
    except Exception:
        # fallback: treat as plain text
        return ExtractionResult(
            format="html",
            title="",
            sections=[],
            metadata={},
            raw_content=content,
        )

    return ExtractionResult(
        format="html",
        title=parser.title,
        sections=parser.sections,
        metadata={},
        raw_content=content,
    )


def _parse_rst_heading(line: str, prev_line: str = "") -> Optional[Tuple[int, str]]:
    """Parse an RST heading (underlined with === or --- etc.).

    Args:
        line: Current content line.
        prev_line: Previous content line.

    Returns:
        Tuple of (level, heading_text) or None.
    """
    # RST headings are underlined: text then === or --- etc.
    # Also support overline variants: === then text then ===
    heading_match = re.match(r"^([A-Za-z][A-Za-z0-9_ \-]*)$", line.strip())
    if heading_match and prev_line:
        underline = prev_line.strip()
        if re.match(r"^[=\-~^]+$", underline):
            level = 1 if underline.startswith("=") else 2
            return level, heading_match.group(1).strip()
    return None


def extract_skill_doc_rst(content: str) -> ExtractionResult:
    """Extract structured skill documentation from reStructuredText content.

    Parses RST headings (underlined with ===, ---, ~~~, ^^^),
    extracts section bodies, and builds a structured ExtractionResult.

    Args:
        content: RST content to parse.

    Returns:
        Structured ExtractionResult.
    """
    lines = content.split("\n")
    sections: List[ExtractedSection] = []
    title = ""
    current_section: Optional[ExtractedSection] = None
    current_body: List[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for overline heading: ===\ntext\n===
        if re.match(r"^[=\-~^]{3,}$", stripped) and i + 2 < len(lines):
            next_line = lines[i + 1].strip()
            overline_underline = lines[i + 2].strip() if i + 2 < len(lines) else ""
            if re.match(r"^[=\-~^]{3,}$", overline_underline):
                level = 1 if overline_underline.startswith("=") else 2
                if not title:
                    title = next_line
                section = ExtractedSection(
                    heading=next_line, body="", level=level
                )
                sections.append(section)
                current_section = section
                current_body = []
                i += 3
                continue

        # Check for underline heading: text\n===
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            if re.match(r"^[=\-~^]{3,}$", next_line.strip()):
                text = stripped
                level = 1 if next_line.strip().startswith("=") else 2
                if not title and level == 1:
                    title = text
                # flush current body
                if current_section is not None and current_body:
                    current_section.body = "\n".join(current_body).strip()
                    current_body = []
                section = ExtractedSection(heading=text, body="", level=level)
                sections.append(section)
                current_section = section
                i += 2
                continue

        # regular body line
        if stripped:
            current_body.append(line)
        else:
            # blank line - flush body
            if current_body and current_section is not None:
                current_section.body = "\n".join(current_body).strip()
                current_body = []
        i += 1

    # flush remaining body
    if current_section is not None and current_body:
        current_section.body = "\n".join(current_body).strip()

    return ExtractionResult(
        format="rst",
        title=title,
        sections=sections,
        metadata={},
        raw_content=content,
    )


# ── auto-detect and extract ──────────────────────────────────────────


SUPPORTED_FORMATS = {"markdown", "md", "html", "rst", "plain"}


def detect_format(content: str) -> str:
    """Detect documentation format from content.

    Examines content for format-specific markers (HTML tags, markdown headings,
    RST underlines) and returns the detected format.

    Args:
        content: Documentation content to analyze.

    Returns:
        Detected format: "markdown", "html", "rst", or "plain".
    """
    stripped = content.strip()
    if not stripped:
        return "plain"

    # HTML detection: look for <html>, <!DOCTYPE>, or HTML tags
    if re.search(r"<!DOCTYPE\s+html", stripped, re.IGNORECASE) or re.search(
        r"<html[\s>]", stripped, re.IGNORECASE
    ):
        return "html"
    if re.search(r"<(h[1-6]|div|p|ul|ol|li|table)\b", stripped, re.IGNORECASE):
        return "html"

    # RST detection: look for underline-style headings
    lines = stripped.split("\n")
    for i in range(len(lines) - 1):
        if lines[i].strip() and re.match(r"^[=\-~^]{4,}$", lines[i + 1].strip()):
            return "rst"

    # Markdown detection: look for # headings or common MD patterns
    if re.search(r"^#{1,6}\s", stripped, re.MULTILINE):
        return "markdown"
    if re.search(r"^\*{3,}$", stripped, re.MULTILINE):
        return "markdown"

    return "plain"


def extract_skill_content(content: str, fmt: Optional[str] = None) -> ExtractionResult:
    """Extract structured skill documentation with auto-format detection.

    Args:
        content: Documentation content to extract.
        fmt: Explicit format name. If None, auto-detected.

    Returns:
        Structured ExtractionResult.
    """
    if fmt is None:
        fmt = detect_format(content)

    if fmt in ("markdown", "md"):
        return extract_skill_doc_md(content)
    elif fmt == "html":
        return extract_skill_doc_html(content)
    elif fmt == "rst":
        return extract_skill_doc_rst(content)
    else:
        return ExtractionResult(
            format="plain",
            title="",
            sections=[],
            metadata={},
            raw_content=content,
        )


# ── SkillExtractor class ──────────────────────────────────────────────


class SkillExtractor:
    """High-level extractor for skill documentation with format support.

    Provides a unified interface for extracting, parsing, and
    converting skill documentation across multiple formats.

    Attributes:
        default_format: Fallback format when auto-detection fails.
    """

    def __init__(self, default_format: str = "markdown") -> None:
        if default_format not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format '{default_format}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
            )
        self.default_format = default_format

    def extract(self, content: str, fmt: Optional[str] = None) -> ExtractionResult:
        """Extract structured documentation from content.

        Args:
            content: Documentation content to parse.
            fmt: Explicit format. Auto-detected if None.

        Returns:
            Structured ExtractionResult.
        """
        return extract_skill_content(content, fmt)

    def extract_section(
        self, content: str, heading: str, fmt: Optional[str] = None
    ) -> Optional[ExtractedSection]:
        """Find a specific section by heading name.

        Args:
            content: Documentation content to search.
            heading: Section heading to find.
            fmt: Format hint for parsing.

        Returns:
            Matching section, or None if not found.
        """
        result = self.extract(content, fmt)
        heading_lower = heading.lower()
        for section in result.sections:
            if section.heading.lower() == heading_lower:
                return section
            for sub in section.subsections:
                if sub.heading.lower() == heading_lower:
                    return sub
        return None

    def extract_metadata(self, content: str, fmt: Optional[str] = None) -> Dict[str, str]:
        """Extract metadata from documentation content.

        Args:
            content: Documentation content to search.
            fmt: Format hint for parsing.

        Returns:
            Dict of metadata key-value pairs.
        """
        result = self.extract(content, fmt)
        return result.metadata

    def to_markdown(self, result: ExtractionResult) -> str:
        """Convert an ExtractionResult back to markdown.

        Args:
            result: Structured extraction result.

        Returns:
            Markdown formatted string.
        """
        lines: List[str] = []
        if result.title:
            lines.append(f"# {result.title}")
            lines.append("")
        for section in result.sections:
            prefix = "#" * section.level
            lines.append(f"{prefix} {section.heading}")
            lines.append("")
            if section.body:
                lines.append(section.body)
                lines.append("")
            for sub in section.subsections:
                sub_prefix = "#" * sub.level
                lines.append(f"{sub_prefix} {sub.heading}")
                lines.append("")
                if sub.body:
                    lines.append(sub.body)
                    lines.append("")
        return "\n".join(lines).strip()

    def list_formats(self) -> List[str]:
        """Return list of supported extraction formats.

        Returns:
            List of format name strings.
        """
        return sorted(SUPPORTED_FORMATS)
