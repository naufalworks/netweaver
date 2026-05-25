"""Observer → Evidence Adapter: Bridge observer output to evidence reports.

Converts a PageObservation (from observer.py) into an EvidenceReport
(from evidence.py), creating properly typed observations and claims
that link DOM, network, and actionability evidence to verifiable claims
about page state.

This is the key integration point: observations are raw data, evidence
reports are verified, claim-backed knowledge about the page.
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from netweaver.observer import InteractiveElement, NetworkActivity, PageObservation, StorageState
from netweaver.evidence import (
    Claim,
    ClaimStatus,
    EvidenceReport,
    EvidenceType,
    Observation,
    create_claim,
    create_observation,
)


def _make_obs_id(prefix: str = "obs") -> str:
    """Generate a unique observation ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _make_claim_id(prefix: str = "claim") -> str:
    """Generate a unique claim ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def element_to_dom_observation(
    element: InteractiveElement,
    source: str = "observer",
) -> Observation:
    """Convert an interactive element to a DOM evidence observation.

    Args:
        element: Interactive element from observer
        source: Source identifier for the observation

    Returns:
        Observation with DOM evidence type
    """
    return create_observation(
        observation_id=_make_obs_id("dom"),
        evidence_type=EvidenceType.DOM,
        data={
            "selector": element.selector,
            "tag": element.tag,
            "type": element.type,
            "text": element.text,
            "aria_label": element.aria_label,
        },
        source=source,
    )


def element_to_actionability_observation(
    element: InteractiveElement,
    source: str = "observer",
) -> Observation:
    """Convert element actionability evidence to an actionability observation.

    Args:
        element: Interactive element with actionability data
        source: Source identifier

    Returns:
        Observation with actionability evidence type
    """
    return create_observation(
        observation_id=_make_obs_id("act"),
        evidence_type=EvidenceType.ACTIONABILITY,
        data={
            "selector": element.selector,
            **(element.actionability or {}),
        },
        source=source,
    )


def network_to_observation(
    network: NetworkActivity,
    source: str = "observer",
) -> Observation:
    """Convert network activity to a network evidence observation.

    Args:
        network: Network activity from observer
        source: Source identifier

    Returns:
        Observation with network evidence type
    """
    return create_observation(
        observation_id=_make_obs_id("net"),
        evidence_type=EvidenceType.NETWORK,
        data={
            "requests_count": network.requests_count,
            "responses_count": network.responses_count,
            "failed_count": network.failed_count,
            "resource_types": network.resource_types,
        },
        source=source,
    )


def storage_to_observation(
    storage: StorageState,
    source: str = "observer",
) -> Observation:
    """Convert browser storage state to a storage evidence observation.

    Args:
        storage: Storage state from observer
        source: Source identifier

    Returns:
        Observation with storage evidence type
    """
    return create_observation(
        observation_id=_make_obs_id("store"),
        evidence_type=EvidenceType.STORAGE,
        data={
            "local_storage": storage.local_storage,
            "session_storage": storage.session_storage,
            "cookies": storage.cookies,
            "local_keys": list(storage.local_storage.keys()),
            "session_keys": list(storage.session_storage.keys()),
            "cookie_count": len(storage.cookies),
        },
        source=source,
    )


def observation_to_report(
    page_obs: PageObservation,
    report_id: Optional[str] = None,
) -> EvidenceReport:
    """Convert a PageObservation into a full EvidenceReport.

    This is the main adapter function. It takes raw observer output and
    creates a structured evidence report with:
    - DOM observations for each interactive element
    - Actionability observations for each element
    - Network activity observation
    - Claims linking observations to verifiable statements

    All claims are auto-verified — the report.verify() should return True
    since every claim has supporting observations.

    Args:
        page_obs: Page observation from the observer
        report_id: Optional report ID (auto-generated if not provided)

    Returns:
        EvidenceReport with observations and claims derived from the page
    """
    if report_id is None:
        report_id = f"rpt-{uuid.uuid4().hex[:12]}"

    report = EvidenceReport(
        report_id=report_id,
        url=page_obs.url,
        timestamp=page_obs.observed_at,
    )

    # Track element observation IDs for claim linking
    element_obs_map: Dict[str, Dict[str, str]] = {}  # selector -> {dom_id, act_id}

    # Create observations for each interactive element
    for element in page_obs.interactive_elements:
        dom_obs = element_to_dom_observation(element)
        act_obs = element_to_actionability_observation(element)

        report.add_observation(dom_obs)
        report.add_observation(act_obs)

        element_obs_map[element.selector] = {
            "dom": dom_obs.observation_id,
            "act": act_obs.observation_id,
        }

        # Create claim: element exists in DOM
        exists_claim = create_claim(
            claim_id=_make_claim_id("exists"),
            description=f"Element '{element.selector}' exists in DOM as <{element.tag}>",
            evidence_type=EvidenceType.DOM,
            observation_ids=[dom_obs.observation_id],
        )
        report.add_claim(exists_claim)

        # Create actionability claim if evidence available
        if element.actionability:
            is_actionable = (
                element.actionability.get("visible", False)
                and element.actionability.get("enabled", False)
            )
            act_claim = create_claim(
                claim_id=_make_claim_id("actionable"),
                description=(
                    f"Element '{element.selector}' is "
                    f"{'actionable' if is_actionable else 'not actionable'} "
                    f"(visible={element.actionability.get('visible')}, "
                    f"enabled={element.actionability.get('enabled')})"
                ),
                evidence_type=EvidenceType.ACTIONABILITY,
                observation_ids=[act_obs.observation_id],
            )
            report.add_claim(act_claim)

    # Create network observation
    net_obs = network_to_observation(page_obs.network)
    report.add_observation(net_obs)

    # Create network health claim
    network_healthy = page_obs.network.failed_count == 0
    net_claim = create_claim(
        claim_id=_make_claim_id("net-health"),
        description=(
            f"Network is {'healthy' if network_healthy else 'degraded'} "
            f"({page_obs.network.requests_count} requests, "
            f"{page_obs.network.failed_count} failures)"
        ),
        evidence_type=EvidenceType.NETWORK,
        observation_ids=[net_obs.observation_id],
    )
    report.add_claim(net_claim)

    # Create storage observation if storage data available
    if page_obs.storage is not None:
        store_obs = storage_to_observation(page_obs.storage)
        report.add_observation(store_obs)

        has_storage = bool(
            page_obs.storage.local_storage
            or page_obs.storage.session_storage
            or page_obs.storage.cookies
        )
        store_claim = create_claim(
            claim_id=_make_claim_id("storage"),
            description=(
                f"Browser storage snapshot: "
                f"{len(page_obs.storage.local_storage)} localStorage keys, "
                f"{len(page_obs.storage.session_storage)} sessionStorage keys, "
                f"{len(page_obs.storage.cookies)} cookies"
            ),
            evidence_type=EvidenceType.STORAGE,
            observation_ids=[store_obs.observation_id],
        )
        report.add_claim(store_claim)

    # Create page-level claims
    page_claim = create_claim(
        claim_id=_make_claim_id("page"),
        description=f"Page '{page_obs.title}' observed at {page_obs.url}",
        evidence_type=EvidenceType.DOM,
        observation_ids=[
            obs_map["dom"]
            for obs_map in element_obs_map.values()
        ][:1] if element_obs_map else [],  # Link to first DOM obs or empty
    )
    if element_obs_map:
        report.add_claim(page_claim)

    return report


def get_actionable_selectors(report: EvidenceReport) -> List[str]:
    """Extract selectors of actionable elements from a verified report.

    Utility function for downstream consumers (executor, WNAL) to
    quickly find which elements are safe to interact with.

    Args:
        report: Verified evidence report

    Returns:
        List of selectors for actionable elements
    """
    actionable = []
    for obs in report.get_observations_by_type(EvidenceType.ACTIONABILITY):
        selector = obs.data.get("selector", "")
        visible = obs.data.get("visible", False)
        enabled = obs.data.get("enabled", False)
        if visible and enabled and selector:
            actionable.append(selector)
    return actionable


def get_network_health(report: EvidenceReport) -> Dict[str, object]:
    """Extract network health summary from a verified report.

    Args:
        report: Verified evidence report

    Returns:
        Dict with healthy (bool), requests_count, failed_count, resource_types
    """
    net_obs = report.get_observations_by_type(EvidenceType.NETWORK)
    if not net_obs:
        return {"healthy": False, "error": "no network observations"}

    data = net_obs[0].data
    return {
        "healthy": data.get("failed_count", 0) == 0,
        "requests_count": data.get("requests_count", 0),
        "failed_count": data.get("failed_count", 0),
        "resource_types": data.get("resource_types", {}),
    }
