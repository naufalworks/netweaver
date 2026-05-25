"""NetWeaver Goal-to-Plan Translator — Template-based plan generation.

Bridges natural language intent to typed ActionPlans via deterministic
template matching + graph validation. No LLM/API/browser imports — pure
rule-based matching with GraphQuery integration.

Core concepts:
  - PlanTemplate: reusable blueprint with keywords and required affordances
  - PlanResult: translated plan with confidence and validation metadata
  - GoalTranslator: goal + WebSceneGraph → ActionPlan via template matching

Design principles:
  - Deterministic: keyword-based matching, no randomness
  - Graph-aware: validates template targets exist in current scene graph
  - Fallback: unknown goals produce minimal single-step plan
  - Composable: default templates cover common flows; custom templates extend
  - No browser/Playwright/vendor imports
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from netweaver.action_orchestrator import ActionPlan, ActionStep, ActionType
from netweaver.graph_query import find_actionable_nodes, IntentType
from netweaver.scene_graph import WebSceneGraph


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PlanTemplate:
    """A reusable plan blueprint matched by intent keywords.

    Attributes:
        name: Unique template identifier (e.g., "login", "search").
        keywords: Words/phrases that trigger this template.
        steps: Ordered list of ActionStep blueprints.
        required_affordances: Affordances that must exist in the graph
            for this template to be valid (e.g., ["clickable", "fillable"]).
    """
    name: str
    keywords: List[str]
    steps: List[ActionStep]
    required_affordances: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "keywords": self.keywords,
            "steps": [
                {
                    "action_type": s.action_type.value,
                    "description": s.description,
                    "intent": s.intent,
                    "text": s.text,
                    "condition": s.condition,
                    "timeout_ms": s.timeout_ms,
                    "pre_condition": s.pre_condition,
                    "post_condition": s.post_condition,
                }
                for s in self.steps
            ],
            "required_affordances": self.required_affordances,
        }


@dataclass
class PlanResult:
    """Result of translating a goal into an action plan.

    Attributes:
        plan: The generated ActionPlan.
        template_name: Name of the matched template, or None for fallback.
        confidence: Match confidence (0.0-1.0). Higher = better template match.
        graph_validation: Whether the plan's required affordances exist in graph.
    """
    plan: ActionPlan
    template_name: Optional[str]
    confidence: float
    graph_validation: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "template_name": self.template_name,
            "confidence": self.confidence,
            "graph_validation": self.graph_validation,
        }


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

_MIN_TOKEN_LEN = 2

# Words to ignore during keyword extraction
_STOP_WORDS: frozenset = frozenset({
    "a", "an", "the", "i", "me", "my", "we", "our", "you", "your",
    "it", "its", "is", "am", "are", "was", "were", "be", "been",
    "do", "does", "did", "have", "has", "had", "will", "would",
    "can", "could", "should", "shall", "may", "might", "must",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "and", "or", "but", "not", "no", "so", "if", "then", "than",
    "that", "this", "these", "those", "here", "there", "now",
    "just", "also", "very", "too", "up", "out", "into", "about",
})


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from a goal string.

    Lowercases, strips punctuation, removes stop words, keeps tokens ≥ 2 chars.

    Args:
        text: Natural language goal string.

    Returns:
        List of lowercase keywords.
    """
    # Remove punctuation, lowercase, split
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = cleaned.split()
    # Filter stop words and short tokens
    return [t for t in tokens if len(t) >= _MIN_TOKEN_LEN and t not in _STOP_WORDS]


# ---------------------------------------------------------------------------
# Affordance → IntentType mapping
# ---------------------------------------------------------------------------

_AFFORDANCE_TO_INTENT: Dict[str, IntentType] = {
    "clickable": IntentType.CLICK,
    "fillable": IntentType.FILL,
    "navigable": IntentType.NAVIGATE,
    "selectable": IntentType.SELECT,
    "toggleable": IntentType.TOGGLE,
}


# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------

def _default_templates() -> List[PlanTemplate]:
    """Return the 10 built-in plan templates.

    Templates cover the most common web interaction patterns:
      1. login — fill username, fill password, click submit
      2. search — fill search box, click search, wait for results
      3. navigate — click link, wait for page load
      4. fill-form — fill field, click submit
      5. click-confirm — click button, wait for response
      6. register — fill name/email/password fields, click submit
      7. logout — click user menu, click logout link
      8. select — click dropdown, click option
      9. toggle — click toggle/switch control, wait for state change
     10. download — click download button, wait for download start
    """
    return [
        PlanTemplate(
            name="login",
            keywords=["login", "log in", "sign in", "signin", "authenticate", "auth"],
            steps=[
                ActionStep(
                    action_type=ActionType.FILL,
                    description="username or email input",
                    intent="enter username",
                    text="{{username}}",
                    pre_condition="username field visible and empty",
                    post_condition="username field populated",
                ),
                ActionStep(
                    action_type=ActionType.FILL,
                    description="password input",
                    intent="enter password",
                    text="{{password}}",
                    pre_condition="password field visible and empty",
                    post_condition="password field populated",
                ),
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="submit or login button",
                    intent="submit login form",
                    pre_condition="submit button visible and enabled",
                    post_condition="form submitted, page transition",
                ),
            ],
            required_affordances=["fillable", "clickable"],
        ),
        PlanTemplate(
            name="register",
            keywords=["register", "sign up", "signup", "create account", "join", "enroll"],
            steps=[
                ActionStep(
                    action_type=ActionType.FILL,
                    description="name or display name input",
                    intent="enter name",
                    text="{{name}}",
                    pre_condition="name field visible and empty",
                    post_condition="name field populated",
                ),
                ActionStep(
                    action_type=ActionType.FILL,
                    description="email input",
                    intent="enter email address",
                    text="{{email}}",
                    pre_condition="email field visible and empty",
                    post_condition="email field populated",
                ),
                ActionStep(
                    action_type=ActionType.FILL,
                    description="password input",
                    intent="enter password",
                    text="{{password}}",
                    pre_condition="password field visible and empty",
                    post_condition="password field populated",
                ),
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="register or create account button",
                    intent="submit registration form",
                    pre_condition="register button visible and enabled",
                    post_condition="registration submitted",
                ),
            ],
            required_affordances=["fillable", "clickable"],
        ),
        PlanTemplate(
            name="search",
            keywords=["search", "find", "look up", "query", "look for"],
            steps=[
                ActionStep(
                    action_type=ActionType.FILL,
                    description="search input field",
                    intent="enter search query",
                    text="{{query}}",
                    pre_condition="search field visible",
                    post_condition="search field populated",
                ),
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="search button or submit",
                    intent="execute search",
                    pre_condition="search button visible",
                    post_condition="search results loading",
                ),
                ActionStep(
                    action_type=ActionType.WAIT,
                    description="search results",
                    intent="wait for search results to load",
                    pre_condition="search initiated",
                    post_condition="search results visible",
                ),
            ],
            required_affordances=["fillable", "clickable"],
        ),
        PlanTemplate(
            name="navigate",
            keywords=["navigate", "go to", "open", "visit", "browse"],
            steps=[
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="navigation link or button",
                    intent="navigate to target page",
                    pre_condition="link visible",
                    post_condition="page loaded",
                ),
                ActionStep(
                    action_type=ActionType.WAIT,
                    description="page content",
                    intent="wait for page to load",
                    pre_condition="navigation initiated",
                    post_condition="target page loaded",
                ),
            ],
            required_affordances=["clickable"],
        ),
        PlanTemplate(
            name="fill-form",
            keywords=["fill", "submit form", "complete form", "enter data", "form"],
            steps=[
                ActionStep(
                    action_type=ActionType.FILL,
                    description="form input field",
                    intent="fill form field",
                    text="{{value}}",
                    pre_condition="form field visible and editable",
                    post_condition="form field populated",
                ),
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="submit button",
                    intent="submit form",
                    pre_condition="submit button visible and enabled",
                    post_condition="form submitted",
                ),
            ],
            required_affordances=["fillable", "clickable"],
        ),
        PlanTemplate(
            name="click-confirm",
            keywords=["click", "confirm", "accept", "agree", "ok", "yes", "proceed", "continue"],
            steps=[
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="confirm or action button",
                    intent="confirm action",
                    pre_condition="confirm button visible",
                    post_condition="action confirmed",
                ),
                ActionStep(
                    action_type=ActionType.WAIT,
                    description="response or next state",
                    intent="wait for response after confirmation",
                    pre_condition="click executed",
                    post_condition="response received",
                ),
            ],
            required_affordances=["clickable"],
        ),
        PlanTemplate(
            name="logout",
            keywords=["logout", "sign out", "signout", "log off", "logoff"],
            steps=[
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="user menu or profile dropdown",
                    intent="open user menu",
                    pre_condition="user menu visible",
                    post_condition="dropdown menu open",
                ),
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="logout or sign out link",
                    intent="click logout",
                    pre_condition="logout link visible",
                    post_condition="logged out",
                ),
                ActionStep(
                    action_type=ActionType.WAIT,
                    description="login page or home page",
                    intent="wait for logout to complete",
                    pre_condition="logout clicked",
                    post_condition="redirected to login or home page",
                ),
            ],
            required_affordances=["clickable"],
        ),
        PlanTemplate(
            name="select",
            keywords=["select", "choose", "pick", "dropdown", "option", "choose from"],
            steps=[
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="dropdown or select element",
                    intent="open dropdown",
                    pre_condition="dropdown visible",
                    post_condition="dropdown options visible",
                ),
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="target option in dropdown",
                    intent="select option",
                    pre_condition="option visible",
                    post_condition="option selected",
                ),
                ActionStep(
                    action_type=ActionType.WAIT,
                    description="selection result",
                    intent="wait for selection to take effect",
                    pre_condition="option clicked",
                    post_condition="selection applied",
                ),
            ],
            required_affordances=["clickable"],
        ),
        PlanTemplate(
            name="toggle",
            keywords=["toggle", "switch", "enable", "disable", "turn on", "turn off", "checkbox", "check", "uncheck"],
            steps=[
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="toggle or switch control",
                    intent="toggle state",
                    pre_condition="toggle visible",
                    post_condition="toggle clicked",
                ),
                ActionStep(
                    action_type=ActionType.WAIT,
                    description="state change confirmation",
                    intent="wait for toggle state to update",
                    pre_condition="toggle clicked",
                    post_condition="state changed",
                ),
            ],
            required_affordances=["clickable"],
        ),
        PlanTemplate(
            name="download",
            keywords=["download", "save", "export", "get file"],
            steps=[
                ActionStep(
                    action_type=ActionType.CLICK,
                    description="download button or link",
                    intent="start download",
                    pre_condition="download button visible",
                    post_condition="download initiated",
                ),
                ActionStep(
                    action_type=ActionType.WAIT,
                    description="download completion",
                    intent="wait for download to start or complete",
                    pre_condition="download clicked",
                    post_condition="file downloaded or download dialog appeared",
                ),
            ],
            required_affordances=["clickable"],
        ),
    ]


# ---------------------------------------------------------------------------
# Template matching
# ---------------------------------------------------------------------------

def _match_template(
    keywords: List[str],
    templates: List[PlanTemplate],
) -> Optional[PlanTemplate]:
    """Find the best matching template for extracted keywords.

    Scoring: number of template keywords found in the goal keywords,
    divided by total template keywords (precision-based).

    Ties broken by template order (first defined wins).

    Args:
        keywords: Extracted goal keywords.
        templates: Available plan templates.

    Returns:
        Best matching PlanTemplate, or None if no match.
    """
    if not keywords:
        return None

    best_template: Optional[PlanTemplate] = None
    best_score = 0.0

    keyword_set = set(keywords)

    # Also build a full token set from the raw text for multi-word matching
    # (includes stop words that were filtered from keywords)
    # We reconstruct this from keywords + stop words + short tokens
    all_tokens = set(keywords) | set(k for k in _STOP_WORDS if len(k) >= _MIN_TOKEN_LEN)

    for template in templates:
        # Each template keyword can be multi-word; check both directions
        hits = 0
        total = len(template.keywords)

        for tk in template.keywords:
            tk_lower = tk.lower()
            # Multi-word keyword: check if it appears in the original goal
            # by looking at consecutive token pairs/triples
            tk_words = tk_lower.split()
            if len(tk_words) == 1:
                if tk_lower in keyword_set:
                    hits += 1
            else:
                # Multi-word: check if all component words appear in all_tokens
                # (includes stop words for proper multi-word matching like "log in")
                if all(w in all_tokens or w in keyword_set or len(w) < _MIN_TOKEN_LEN
                       for w in tk_words):
                    hits += 1

        if total == 0:
            continue

        score = hits / total
        if score > best_score:
            best_score = score
            best_template = template

    # Require at least one keyword match
    if best_score == 0.0:
        return None

    return best_template


# ---------------------------------------------------------------------------
# Graph validation
# ---------------------------------------------------------------------------

def _validate_against_graph(
    template: PlanTemplate,
    graph: WebSceneGraph,
) -> bool:
    """Check if the graph has nodes with the template's required affordances.

    Uses GraphQuery.find_actionable_nodes() to verify each required
    affordance has at least one matching node in the graph.

    Args:
        template: The plan template to validate.
        graph: Current scene graph.

    Returns:
        True if all required affordances have matching nodes.
    """
    if not template.required_affordances:
        return True

    for affordance in template.required_affordances:
        intent = _AFFORDANCE_TO_INTENT.get(affordance, IntentType.ANY)
        matches = find_actionable_nodes(graph, intent, min_evidence=0)
        if not matches:
            return False

    return True


# ---------------------------------------------------------------------------
# GoalTranslator
# ---------------------------------------------------------------------------

class GoalTranslator:
    """Translate natural language goals into typed ActionPlans.

    Uses template matching against predefined plan blueprints, validated
    against the current scene graph. Falls back to a minimal single-step
    plan when no template matches.

    Usage:
        translator = GoalTranslator()
        result = translator.translate("log into the website", graph)
        # result.plan is an ActionPlan
        # result.template_name is "login" or None for fallback
        # result.confidence is 0.0-1.0
        # result.graph_validation is True/False
    """

    def __init__(self, templates: Optional[List[PlanTemplate]] = None):
        """Initialize with optional custom templates.

        Args:
            templates: Custom plan templates. Defaults to built-in templates.
        """
        self.templates = templates if templates is not None else _default_templates()

    def translate(self, goal: str, graph: WebSceneGraph) -> PlanResult:
        """Translate a goal string into an ActionPlan.

        Args:
            goal: Natural language goal (e.g., "log into the website").
            graph: Current scene graph for validation.

        Returns:
            PlanResult with plan, template info, confidence, and validation.
        """
        keywords = _extract_keywords(goal)
        template = _match_template(keywords, self.templates)

        if template is None:
            # Fallback: minimal single-step plan with raw goal
            return PlanResult(
                plan=ActionPlan(
                    description=goal,
                    steps=[
                        ActionStep(
                            action_type=ActionType.CLICK,
                            description=goal,
                            intent=goal,
                        )
                    ],
                ),
                template_name=None,
                confidence=0.0,
                graph_validation=False,
            )

        # Build plan from template steps
        plan = ActionPlan(
            description=goal,
            steps=list(template.steps),  # copy to avoid mutation
        )

        # Validate against graph
        graph_valid = _validate_against_graph(template, graph)

        # Confidence based on keyword match ratio
        keyword_set = set(keywords)
        matched_kw = sum(
            1 for tk in template.keywords
            if tk.lower() in keyword_set
            or all(w in keyword_set for w in tk.lower().split() if len(w) >= _MIN_TOKEN_LEN)
        )
        total_kw = len(template.keywords)
        confidence = matched_kw / total_kw if total_kw > 0 else 0.0

        # Boost confidence if graph validates
        if graph_valid:
            confidence = min(1.0, confidence + 0.1)

        return PlanResult(
            plan=plan,
            template_name=template.name,
            confidence=confidence,
            graph_validation=graph_valid,
        )

    def add_template(self, template: PlanTemplate) -> None:
        """Add a custom template to the translator."""
        self.templates.append(template)

    def remove_template(self, name: str) -> bool:
        """Remove a template by name. Returns True if found and removed."""
        for i, t in enumerate(self.templates):
            if t.name == name:
                self.templates.pop(i)
                return True
        return False

    def list_templates(self) -> List[str]:
        """List all template names."""
        return [t.name for t in self.templates]
