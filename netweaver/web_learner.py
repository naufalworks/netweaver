"""NetWeaver Autonomous Web Explorer — Self-directed web interaction and skill learning.

Dynamically discovers and explores websites, learns from interactions,
builds scene graphs, and extracts reusable skills. Never repeats the same
site unnecessarily. All headless.

Design:
  - Autonomous site discovery (seed + follow links)
  - Visited registry (track URLs, success rates, last visit)
  - Adaptive exploration (prioritize unvisited + high-success sites)
  - Depth exploration (follow links to sub-pages)
  - Evidence-first execution via VerifiedExecutor
  - Skill learning via SkillLearner
  - Records outcomes to Epistemic OS + Competence Matrix
  - Graceful error handling — never crashes the daemon
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from netweaver.cloak_bridge import CloakBrowserBridge
from netweaver.executor import VerifiedExecutor, ExecutionStatus
from netweaver.wnal import ClickAction, FillAction, ActionType
from netweaver.scene_graph_builder import SceneGraphBuilder, BuilderConfig
from netweaver.site_skill import SkillStore
from netweaver.skill_learner import SkillLearner

logger = logging.getLogger("web_explorer")


# --- Seed sites for initial discovery ---
SEED_SITES = [
    "https://example.com",
    "https://httpbin.org/forms/post",
    "https://books.toscrape.com",
    "https://quotes.toscrape.com",
    "https://en.wikipedia.org/wiki/Web_scraping",
]

# Max depth to follow links from a page
MAX_EXPLORATION_DEPTH = 2

# How long before re-visiting a site (hours)
REVISIT_COOLDOWN_HOURS = 24

# Max sites to explore per cycle
MAX_SITES_PER_CYCLE = 5

# Max links to extract from a page for discovery
MAX_LINKS_TO_EXTRACT = 10


@dataclass
class VisitedSite:
    """Registry entry for a visited site."""
    url: str
    last_visited: str = ""
    success_count: int = 0
    fail_count: int = 0
    elements_found: int = 0
    actions_succeeded: int = 0
    discovered_links: List[str] = field(default_factory=list)
    error: str = ""

    def __post_init__(self):
        if not self.last_visited:
            self.last_visited = datetime.now().isoformat()

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def should_revisit(self) -> bool:
        """Check if enough time has passed to revisit."""
        try:
            last = datetime.fromisoformat(self.last_visited)
            return datetime.now() - last > timedelta(hours=REVISIT_COOLDOWN_HOURS)
        except (ValueError, TypeError):
            return True


@dataclass
class ExplorationResult:
    """Result of exploring a single site."""
    url: str
    success: bool
    elements_found: int = 0
    actions_succeeded: int = 0
    links_discovered: int = 0
    discovered_links_list: List[str] = field(default_factory=list)
    scene_graph_nodes: int = 0
    scene_graph_edges: int = 0
    duration_s: float = 0.0
    error: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class AutonomousWebExplorer:
    """Self-directed web exploration with dynamic discovery.

    Usage:
        explorer = AutonomousWebExplorer(registry_path=Path(".tini/web_explorer"))
        results = explorer.explore_cycle()
    """

    def __init__(
        self,
        registry_path: Optional[Path] = None,
        epistemic_daemon: Optional[Any] = None,
        competence_matrix: Optional[Any] = None,
        headless: bool = True,
    ):
        self.registry_path = registry_path or Path(".tini/web_explorer")
        self.registry_path.mkdir(parents=True, exist_ok=True)
        self.epistemic_daemon = epistemic_daemon
        self.competence_matrix = competence_matrix
        self.headless = headless

        # Persistent bridge
        self._bridge = CloakBrowserBridge()
        self._builder = SceneGraphBuilder(config=BuilderConfig(
            include_intent_nodes=True,
            include_network_nodes=True,
            include_visual_nodes=False,
            run_perspective_enrichment=False,
        ))

        # Load visited registry
        self._visited = self._load_registry()

        # Discovery queue (URLs to explore)
        self._discovery_queue: List[str] = []

    def _load_registry(self) -> Dict[str, VisitedSite]:
        """Load visited sites from disk."""
        registry_file = self.registry_path / "visited.json"
        if not registry_file.exists():
            return {}
        try:
            data = json.loads(registry_file.read_text())
            return {url: VisitedSite(**site) for url, site in data.items()}
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
            return {}

    def _save_registry(self):
        """Save visited sites to disk."""
        registry_file = self.registry_path / "visited.json"
        data = {url: {
            "url": site.url,
            "last_visited": site.last_visited,
            "success_count": site.success_count,
            "fail_count": site.fail_count,
            "elements_found": site.elements_found,
            "actions_succeeded": site.actions_succeeded,
            "discovered_links": site.discovered_links,
            "error": site.error,
        } for url, site in self._visited.items()}
        registry_file.write_text(json.dumps(data, indent=2))

    def _seed_discovery_queue(self):
        """Seed discovery queue with initial sites if empty."""
        if not self._discovery_queue:
            # Add seed sites that haven't been visited recently
            for url in SEED_SITES:
                if url not in self._visited or self._visited[url].should_revisit:
                    self._discovery_queue.append(url)

    def _select_next_sites(self) -> List[str]:
        """Select next sites to explore (prioritize unvisited + high success)."""
        candidates = []

        # Add from discovery queue
        while self._discovery_queue and len(candidates) < MAX_SITES_PER_CYCLE:
            url = self._discovery_queue.pop(0)
            if url not in self._visited or self._visited[url].should_revisit:
                candidates.append(url)

        # If not enough, revisit high-success sites
        if len(candidates) < MAX_SITES_PER_CYCLE:
            revisitable = [
                (url, site) for url, site in self._visited.items()
                if site.should_revisit and site.success_rate > 0.5
            ]
            revisitable.sort(key=lambda x: x[1].success_rate, reverse=True)
            for url, _ in revisitable[:MAX_SITES_PER_CYCLE - len(candidates)]:
                candidates.append(url)

        return candidates[:MAX_SITES_PER_CYCLE]

    def _extract_links(self, obs) -> List[str]:
        """Extract links from page for discovery using the browser."""
        try:
            # Use the bridge to extract links directly from the page
            if hasattr(self._bridge, '_page') and self._bridge._page:
                links = []
                # Get all anchor elements
                anchors = self._bridge._page.locator('a[href]').all()
                for anchor in anchors[:MAX_LINKS_TO_EXTRACT * 2]:  # Get more to filter
                    try:
                        href = anchor.get_attribute('href')
                        if href and href.startswith(('http://', 'https://')):
                            if href not in links:
                                links.append(href)
                                if len(links) >= MAX_LINKS_TO_EXTRACT:
                                    break
                    except Exception:
                        continue
                return links
        except Exception as e:
            logger.debug(f"Failed to extract links: {e}")
        return []

    def explore_cycle(self) -> List[ExplorationResult]:
        """Run one exploration cycle.

        Returns list of ExplorationResult for each site visited.
        """
        self._seed_discovery_queue()
        sites_to_explore = self._select_next_sites()

        if not sites_to_explore:
            logger.info("No sites to explore this cycle")
            return []

        results = []
        for url in sites_to_explore:
            try:
                result = self._explore_site(url, depth=0)
                results.append(result)

                # Update visited registry
                if url in self._visited:
                    site = self._visited[url]
                else:
                    site = VisitedSite(url=url)
                    self._visited[url] = site

                site.last_visited = datetime.now().isoformat()
                site.elements_found = result.elements_found
                site.actions_succeeded = result.actions_succeeded
                
                # Extract links for registry (separate call)
                try:
                    page_links = self._extract_links(
                        self._bridge.observe(url, headless=self.headless, timeout=10.0)
                    )[:5]
                    site.discovered_links = page_links
                except Exception:
                    site.discovered_links = []

                if result.success:
                    site.success_count += 1
                else:
                    site.fail_count += 1
                    site.error = result.error[:200] if result.error else ""

                # Add discovered links to queue
                for link in result.discovered_links_list:
                    if link not in self._discovery_queue:
                        self._discovery_queue.append(link)

                logger.info(
                    f"[{url[:50]}] {'✓' if result.success else '✗'} "
                    f"elements={result.elements_found} actions={result.actions_succeeded} "
                    f"links={result.links_discovered} ({result.duration_s:.1f}s)"
                )

            except Exception as e:
                logger.error(f"[{url[:50]}] Error: {e}")
                results.append(ExplorationResult(
                    url=url,
                    success=False,
                    error=str(e)[:200],
                ))

        # Save registry
        self._save_registry()

        return results

    def _explore_site(self, url: str, depth: int) -> ExplorationResult:
        """Explore a single site with optional depth."""
        t0 = time.time()

        # Re-navigate to target URL
        try:
            if hasattr(self._bridge, '_page') and self._bridge._page:
                self._bridge._page.goto(url, timeout=15000, wait_until="domcontentloaded")
        except Exception:
            pass

        # Observe the page
        obs = self._bridge.observe(url, headless=self.headless, timeout=15.0)
        elements_found = len(obs.interactive_elements)

        # Build scene graph
        sg_result = self._builder.build(obs)
        graph = sg_result.graph
        node_count = len(graph.nodes)
        edge_count = len(graph.edges)

        # Create executor
        executor = VerifiedExecutor(
            mode="live",
            cloak_bridge=self._bridge,
            scene_graph=graph,
        )

        # Try actions adaptively
        actions_succeeded = 0
        actions_to_try = self._select_actions(obs.interactive_elements)

        for action in actions_to_try:
            try:
                result = executor.execute(action, skip_perspective=True)
                if result.status == ExecutionStatus.SUCCESS:
                    actions_succeeded += 1
            except Exception as e:
                logger.debug(f"Action error on {url}: {e}")

        # Extract links for discovery
        discovered_links = self._extract_links(obs)
        links_discovered = len(discovered_links)

        # Depth exploration (follow one link if depth allows)
        if depth < MAX_EXPLORATION_DEPTH and discovered_links:
            # Pick first unvisited link
            for link in discovered_links:
                if link not in self._visited:
                    try:
                        sub_result = self._explore_site(link, depth=depth + 1)
                        actions_succeeded += sub_result.actions_succeeded
                        elements_found += sub_result.elements_found
                        break  # Only follow one link per page
                    except Exception:
                        pass

        success = actions_succeeded > 0 or elements_found > 0

        # Record to epistemic + competence
        if self.epistemic_daemon:
            try:
                self.epistemic_daemon.record_outcome(
                    task_id=f"explore_{url[:50]}",
                    success=success,
                    evidence={
                        "elements": elements_found,
                        "actions": actions_succeeded,
                        "links": links_discovered,
                        "depth": depth,
                    },
                )
            except Exception:
                pass

        if self.competence_matrix and success:
            try:
                self.competence_matrix.record_simple(
                    agent_id="web_explorer",
                    task_id=f"explore_{url[:50]}",
                    task_type="web_interaction",
                    success=True,
                    duration=time.time() - t0,
                )
            except Exception:
                pass

        return ExplorationResult(
            url=url,
            success=success,
            elements_found=elements_found,
            actions_succeeded=actions_succeeded,
            links_discovered=links_discovered,
            discovered_links_list=discovered_links,
            scene_graph_nodes=node_count,
            scene_graph_edges=edge_count,
            duration_s=time.time() - t0,
        )

    def _select_actions(self, elements: List) -> List[Any]:
        """Select actions to try based on available elements."""
        actions = []

        # Try clicking first link
        links = [e for e in elements if e.tag == "a"]
        if links:
            actions.append(ClickAction(
                action_id=f"explore-click-{links[0].selector[:20]}",
                target_ref=links[0].selector,
            ))

        # Try filling first input
        inputs = [e for e in elements if e.tag == "input"]
        if inputs:
            actions.append(FillAction(
                action_id="explore-fill-input",
                target_ref=inputs[0].selector,
                value="netweaver_test",
            ))

        return actions

    def close(self):
        """Clean up browser resources."""
        self._bridge.close()

    def summary(self, results: List[ExplorationResult]) -> str:
        """Format exploration results as a readable summary."""
        total_sites = len(results)
        successes = sum(1 for r in results if r.success)
        total_elements = sum(r.elements_found for r in results)
        total_actions = sum(r.actions_succeeded for r in results)
        total_links = sum(r.links_discovered for r in results)
        total_time = sum(r.duration_s for r in results)

        lines = [
            f"═══ Autonomous Web Exploration Report ═══",
            f"Sites explored: {successes}/{total_sites} successful",
            f"Elements found: {total_elements}",
            f"Actions executed: {total_actions}",
            f"Links discovered: {total_links}",
            f"Total time: {total_time:.1f}s",
            f"Visited registry: {len(self._visited)} sites",
            f"Discovery queue: {len(self._discovery_queue)} pending",
            "",
        ]

        for r in results:
            status = "✓" if r.success else "✗"
            err = f" ({r.error[:50]})" if r.error else ""
            lines.append(
                f"  {status} {r.url[:60]}: {r.elements_found} elements, "
                f"{r.actions_succeeded} actions, "
                f"{r.links_discovered} links, "
                f"graph({r.scene_graph_nodes}n/{r.scene_graph_edges}e), "
                f"{r.duration_s:.1f}s{err}"
            )

        return "\n".join(lines)
