"""NetWeaver Web Learner — Autonomous live web interaction and skill learning.

Periodically visits target websites, observes them, executes actions,
builds scene graphs, and learns reusable site skills. All headless.

Design:
  - Uses CloakBrowserBridge (persistent session, headless)
  - Evidence-first execution via VerifiedExecutor
  - Skill learning via SkillLearner
  - Records outcomes to Epistemic OS + Competence Matrix
  - Graceful error handling — never crashes the daemon
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from netweaver.cloak_bridge import CloakBrowserBridge
from netweaver.executor import VerifiedExecutor, ExecutionStatus
from netweaver.wnal import ClickAction, FillAction, ActionType
from netweaver.scene_graph_builder import SceneGraphBuilder, BuilderConfig
from netweaver.site_skill import SkillStore
from netweaver.skill_learner import SkillLearner
from netweaver.action_orchestrator import ActionOrchestrator, ActionPlan

logger = logging.getLogger("web_learner")


# --- Target sites for learning ---
DEFAULT_TARGETS = [
    {
        "name": "example",
        "url": "https://example.com",
        "goal": "navigate and click links",
        "actions": ["click_first_link"],
    },
    {
        "name": "httpbin_forms",
        "url": "https://httpbin.org/forms/post",
        "goal": "fill and submit forms",
        "actions": ["observe_form", "fill_input"],
    },
    {
        "name": "books_toscrape",
        "url": "https://books.toscrape.com",
        "goal": "browse catalog and click items",
        "actions": ["click_first_book"],
    },
    {
        "name": "quotes_toscrape",
        "url": "https://quotes.toscrape.com",
        "goal": "navigate pages and extract quotes",
        "actions": ["click_next_page"],
    },
    {
        "name": "wikipedia",
        "url": "https://en.wikipedia.org/wiki/Web_scraping",
        "goal": "navigate links and read content",
        "actions": ["click_first_link"],
    },
]


@dataclass
class LearningResult:
    """Result of a single learning session."""
    site_name: str
    url: str
    success: bool
    elements_found: int = 0
    actions_executed: int = 0
    skills_learned: int = 0
    scene_graph_nodes: int = 0
    scene_graph_edges: int = 0
    duration_s: float = 0.0
    error: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class WebLearner:
    """Autonomous web interaction and skill learning engine.

    Usage:
        learner = WebLearner(skills_dir=Path(".tini/netweaver/skills"))
        results = learner.learn_cycle(targets=DEFAULT_TARGETS)
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        epistemic_daemon: Optional[Any] = None,
        competence_matrix: Optional[Any] = None,
        headless: bool = True,
    ):
        self.skills_dir = skills_dir or Path(".tini/netweaver/skills")
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.epistemic_daemon = epistemic_daemon
        self.competence_matrix = competence_matrix
        self.headless = headless

        # Persistent bridge (shared across sessions)
        self._bridge = CloakBrowserBridge()
        self._skill_store = SkillStore(self.skills_dir)
        self._skill_learner = SkillLearner(self._skill_store)
        self._builder = SceneGraphBuilder(config=BuilderConfig(
            include_intent_nodes=True,
            include_network_nodes=True,
            include_visual_nodes=False,
            run_perspective_enrichment=False,
        ))

    def learn_cycle(self, targets: Optional[List[Dict]] = None) -> List[LearningResult]:
        """Run one learning cycle across all target sites.

        Returns list of LearningResult for each site visited.
        """
        targets = targets or DEFAULT_TARGETS
        results = []

        for target in targets:
            try:
                result = self._learn_site(target)
                results.append(result)
                logger.info(
                    f"[{target['name']}] {'✓' if result.success else '✗'} "
                    f"elements={result.elements_found} actions={result.actions_executed} "
                    f"skills={result.skills_learned} ({result.duration_s:.1f}s)"
                )
            except Exception as e:
                logger.error(f"[{target['name']}] Error: {e}")
                results.append(LearningResult(
                    site_name=target["name"],
                    url=target["url"],
                    success=False,
                    error=str(e)[:200],
                ))

        return results

    def _learn_site(self, target: Dict) -> LearningResult:
        """Learn from a single site."""
        t0 = time.time()
        name = target["name"]
        url = target["url"]
        actions_to_try = target.get("actions", ["click_first_link"])

        # Step 1: Observe the page
        obs = self._bridge.observe(url, headless=self.headless, timeout=15.0)
        elements_found = len(obs.interactive_elements)

        # Step 2: Build scene graph
        sg_result = self._builder.build(obs)
        graph = sg_result.graph
        node_count = len(graph.nodes)
        edge_count = len(graph.edges)

        # Step 3: Create executor with live bridge
        executor = VerifiedExecutor(
            mode="live",
            cloak_bridge=self._bridge,
            scene_graph=graph,
        )

        # Step 4: Try actions
        actions_executed = 0
        skills_learned = 0

        for action_name in actions_to_try:
            action = self._build_action(action_name, obs.interactive_elements)
            if action is None:
                continue

            try:
                result = executor.execute(action, skip_perspective=True)
                if result.status == ExecutionStatus.SUCCESS:
                    actions_executed += 1
                elif result.status == ExecutionStatus.PRECONDITION_FAILED:
                    logger.debug(f"[{name}] Precondition failed for {action_name}: {result.error}")
                else:
                    logger.debug(f"[{name}] Action {action_name} status: {result.status}")
            except Exception as e:
                logger.debug(f"[{name}] Action {action_name} error: {e}")

        # Step 5: Record to epistemic + competence
        success = actions_executed > 0 or elements_found > 0
        if self.epistemic_daemon:
            try:
                self.epistemic_daemon.record_outcome(
                    task_id=f"web_learn_{name}",
                    success=success,
                    evidence={
                        "elements": elements_found,
                        "actions": actions_executed,
                        "nodes": node_count,
                    },
                )
            except Exception:
                pass

        if self.competence_matrix and success:
            try:
                self.competence_matrix.record_simple(
                    agent_id="web_learner",
                    task_id=f"web_{name}",
                    task_type="web_interaction",
                    success=True,
                    duration=time.time() - t0,
                )
            except Exception:
                pass

        return LearningResult(
            site_name=name,
            url=url,
            success=success,
            elements_found=elements_found,
            actions_executed=actions_executed,
            skills_learned=skills_learned,
            scene_graph_nodes=node_count,
            scene_graph_edges=edge_count,
            duration_s=time.time() - t0,
        )

    def _build_action(self, action_name: str, elements: List) -> Optional[Any]:
        """Build a typed action from an action name and available elements."""
        if not elements:
            return None

        if action_name == "click_first_link":
            links = [e for e in elements if e.tag == "a"]
            if links:
                return ClickAction(
                    action_id=f"learn-click-{links[0].selector[:20]}",
                    target_ref=links[0].selector,
                )

        elif action_name == "click_first_book":
            # books.toscrape.com uses h3 > a for book links
            book_links = [e for e in elements if e.tag == "a" and "catalogue" in (e.selector or "")]
            if book_links:
                return ClickAction(
                    action_id="learn-click-book",
                    target_ref=book_links[0].selector,
                )
            # Fallback: any link
            links = [e for e in elements if e.tag == "a"]
            if links:
                return ClickAction(
                    action_id="learn-click-link",
                    target_ref=links[0].selector,
                )

        elif action_name == "click_next_page":
            next_links = [e for e in elements if e.tag == "a" and "next" in (e.selector or "").lower()]
            if next_links:
                return ClickAction(
                    action_id="learn-click-next",
                    target_ref=next_links[0].selector,
                )

        elif action_name == "fill_input":
            inputs = [e for e in elements if e.tag == "input"]
            if inputs:
                return FillAction(
                    action_id="learn-fill-input",
                    target_ref=inputs[0].selector,
                    value="netweaver_test",
                )

        elif action_name == "observe_form":
            # No action needed — observation already done
            return None

        return None

    def close(self):
        """Clean up browser resources."""
        self._bridge.close()

    def summary(self, results: List[LearningResult]) -> str:
        """Format learning results as a readable summary."""
        total_sites = len(results)
        successes = sum(1 for r in results if r.success)
        total_elements = sum(r.elements_found for r in results)
        total_actions = sum(r.actions_executed for r in results)
        total_time = sum(r.duration_s for r in results)

        lines = [
            f"═══ Web Learning Report ═══",
            f"Sites visited: {successes}/{total_sites} successful",
            f"Elements found: {total_elements}",
            f"Actions executed: {total_actions}",
            f"Total time: {total_time:.1f}s",
            "",
        ]

        for r in results:
            status = "✓" if r.success else "✗"
            err = f" ({r.error[:50]})" if r.error else ""
            lines.append(
                f"  {status} {r.site_name}: {r.elements_found} elements, "
                f"{r.actions_executed} actions, "
                f"graph({r.scene_graph_nodes}n/{r.scene_graph_edges}e), "
                f"{r.duration_s:.1f}s{err}"
            )

        return "\n".join(lines)
