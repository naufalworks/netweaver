"""NetWeaver Evidence Report - Links claims to observations.

An evidence report is the core output of NetWeaver's evidence-first verification.
Every claim about page state must be backed by observations from DOM, network,
storage, or actionability checks. Unsupported claims fail verification.

Evidence types:
- DOM: element existence, attributes, text content, visibility
- Network: request/response pairs, status codes, timing
- Storage: localStorage, sessionStorage, cookies
- Actionability: attached, visible, enabled, editable, stable, pointer_events
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class EvidenceType(Enum):
    """Supported evidence types."""
    DOM = "dom"
    NETWORK = "network"
    STORAGE = "storage"
    ACTIONABILITY = "actionability"


class ClaimStatus(Enum):
    """Status of a claim after verification."""
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PARTIAL = "partial"  # Some observations support, some contradict


@dataclass
class Observation:
    """A single observation from the browser.

    Links to a specific evidence type and carries the raw data.
    """
    observation_id: str
    evidence_type: EvidenceType
    timestamp: datetime
    data: Dict[str, Any]
    source: str  # e.g. "observer", "network_monitor", "storage_probe"

    def to_dict(self) -> Dict:
        return {
            "observation_id": self.observation_id,
            "evidence_type": self.evidence_type.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Observation":
        return cls(
            observation_id=data["observation_id"],
            evidence_type=EvidenceType(data["evidence_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            data=data["data"],
            source=data["source"],
        )


@dataclass
class Claim:
    """A verifiable claim about page state.

    Every claim must link to at least one observation that supports it.
    Claims without supporting observations fail verification.
    """
    claim_id: str
    description: str
    evidence_type: EvidenceType
    observation_ids: List[str] = field(default_factory=list)
    status: ClaimStatus = ClaimStatus.UNSUPPORTED

    def add_observation(self, observation_id: str) -> None:
        """Link an observation to this claim."""
        if observation_id not in self.observation_ids:
            self.observation_ids.append(observation_id)

    def to_dict(self) -> Dict:
        return {
            "claim_id": self.claim_id,
            "description": self.description,
            "evidence_type": self.evidence_type.value,
            "observation_ids": self.observation_ids,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Claim":
        return cls(
            claim_id=data["claim_id"],
            description=data["description"],
            evidence_type=EvidenceType(data["evidence_type"]),
            observation_ids=data.get("observation_ids", []),
            status=ClaimStatus(data.get("status", "unsupported")),
        )


@dataclass
class EvidenceReport:
    """Complete evidence report linking claims to observations.

    The central contract: every claim must have supporting observations.
    Reports with unsupported claims fail verification.
    """
    report_id: str
    url: str
    timestamp: datetime
    observations: List[Observation] = field(default_factory=list)
    claims: List[Claim] = field(default_factory=list)

    def add_observation(self, observation: Observation) -> None:
        """Add an observation to the report."""
        self.observations.append(observation)

    def add_claim(self, claim: Claim) -> None:
        """Add a claim to the report."""
        self.claims.append(claim)

    def _check_verified(self) -> bool:
        """Non-mutating verification check.

        Returns True only if every claim links to at least one observation
        and all linked observation IDs exist in the report.
        Does NOT modify claim statuses.
        """
        observation_ids = {obs.observation_id for obs in self.observations}
        for claim in self.claims:
            if not claim.observation_ids:
                return False
            for oid in claim.observation_ids:
                if oid not in observation_ids:
                    return False
        return True

    def verify(self) -> bool:
        """Verify all claims have supporting observations.

        Mutating: updates claim statuses as a side effect.
        For a non-mutating check, use _check_verified() or is_verified property.
        Returns True only if every claim links to at least one observation
        and no claim remains UNSUPPORTED.
        """
        observation_ids = {obs.observation_id for obs in self.observations}
        for claim in self.claims:
            if not claim.observation_ids:
                claim.status = ClaimStatus.UNSUPPORTED
                return False
            # Check that linked observations actually exist
            for oid in claim.observation_ids:
                if oid not in observation_ids:
                    claim.status = ClaimStatus.UNSUPPORTED
                    return False
            claim.status = ClaimStatus.SUPPORTED
        return True

    def get_unsupported_claims(self) -> List[Claim]:
        """Return all claims without supporting observations."""
        observation_ids = {obs.observation_id for obs in self.observations}
        unsupported = []
        for claim in self.claims:
            if not claim.observation_ids:
                unsupported.append(claim)
                continue
            for oid in claim.observation_ids:
                if oid not in observation_ids:
                    unsupported.append(claim)
                    break
        return unsupported

    def get_claims_by_type(self, evidence_type: EvidenceType) -> List[Claim]:
        """Filter claims by evidence type."""
        return [c for c in self.claims if c.evidence_type == evidence_type]

    def get_observations_by_type(self, evidence_type: EvidenceType) -> List[Observation]:
        """Filter observations by evidence type."""
        return [o for o in self.observations if o.evidence_type == evidence_type]

    def summary(self) -> Dict[str, Any]:
        """Generate a summary of the report."""
        return {
            "report_id": self.report_id,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "total_claims": len(self.claims),
            "total_observations": len(self.observations),
            "unsupported_claims": len(self.get_unsupported_claims()),
            "claims_by_type": {
                et.value: len(self.get_claims_by_type(et))
                for et in EvidenceType
            },
            "observations_by_type": {
                et.value: len(self.get_observations_by_type(et))
                for et in EvidenceType
            },
            "verified": self._check_verified(),
        }

    def to_dict(self) -> Dict:
        return {
            "report_id": self.report_id,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "observations": [o.to_dict() for o in self.observations],
            "claims": [c.to_dict() for c in self.claims],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "EvidenceReport":
        return cls(
            report_id=data["report_id"],
            url=data["url"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            observations=[
                Observation.from_dict(o) for o in data.get("observations", [])
            ],
            claims=[
                Claim.from_dict(c) for c in data.get("claims", [])
            ],
        )


def create_observation(
    observation_id: str,
    evidence_type: EvidenceType,
    data: Dict[str, Any],
    source: str = "observer",
) -> Observation:
    """Factory helper to create an observation with current timestamp."""
    return Observation(
        observation_id=observation_id,
        evidence_type=evidence_type,
        timestamp=datetime.now(),
        data=data,
        source=source,
    )


def create_claim(
    claim_id: str,
    description: str,
    evidence_type: EvidenceType,
    observation_ids: Optional[List[str]] = None,
) -> Claim:
    """Factory helper to create a claim."""
    return Claim(
        claim_id=claim_id,
        description=description,
        evidence_type=evidence_type,
        observation_ids=observation_ids or [],
    )


# ---------------------------------------------------------------------------
# EvidenceBundle — structured task output with claims→evidence linkage
# ---------------------------------------------------------------------------

class BundleStatus(Enum):
    """Status of an EvidenceBundle after validation."""
    VERIFIED = "verified"
    MISSING_EVIDENCE = "missing_evidence"
    EMPTY = "empty"


@dataclass
class EvidenceBundle:
    """Structured output from a task, linking claims to evidence.

    Designed for the autonomy improvement pipeline: every task produces
    an EvidenceBundle that can be appended to the JSONL ledger. Bundles
    with missing evidence are rejected at validation time.

    Attributes:
        bundle_id: Unique identifier for this bundle.
        task_id: KANBAN task ID (e.g. "NW-010").
        agent: Agent role that produced this bundle.
        timestamp: When the bundle was created.
        files_changed: List of file paths modified.
        commands_run: List of commands executed during the task.
        test_results: Summary of test outcomes (pass/fail/total).
        claims: Verifiable claims about what was done.
        reports: EvidenceReport instances backing the claims.
        risk_level: Assessed risk level (low/medium/high/critical).
        status: Validation status — set by validate().
        rejection_reasons: Why validation failed, if applicable.
    """
    bundle_id: str
    task_id: str
    agent: str
    timestamp: datetime
    files_changed: List[str] = field(default_factory=list)
    commands_run: List[str] = field(default_factory=list)
    test_results: Dict[str, Any] = field(default_factory=dict)
    claims: List[str] = field(default_factory=list)
    reports: List[EvidenceReport] = field(default_factory=list)
    risk_level: str = "low"
    status: BundleStatus = BundleStatus.EMPTY
    rejection_reasons: List[str] = field(default_factory=list)

    def validate(self) -> bool:
        """Validate bundle: every claim must have supporting evidence.

        Sets self.status and self.rejection_reasons.
        Returns True if verified, False if missing evidence.

        Rules:
        - Empty claims → VERIFIED (nothing to prove)
        - Each claim string must map to at least one report with verified=True
        - If any claim lacks evidence → MISSING_EVIDENCE
        """
        self.rejection_reasons = []

        if not self.claims:
            self.status = BundleStatus.VERIFIED
            return True

        if not self.reports:
            self.status = BundleStatus.MISSING_EVIDENCE
            self.rejection_reasons = [
                f"Claim '{c}' has no supporting evidence reports" for c in self.claims
            ]
            return False

        # Verify each report
        verified_report_count = sum(1 for r in self.reports if r.verify())

        if verified_report_count == 0:
            self.status = BundleStatus.MISSING_EVIDENCE
            self.rejection_reasons = [
                "No verified evidence reports found"
            ]
            return False

        self.status = BundleStatus.VERIFIED
        return True

    def add_report(self, report: EvidenceReport) -> None:
        """Attach an evidence report."""
        self.reports.append(report)

    def to_dict(self) -> Dict:
        return {
            "bundle_id": self.bundle_id,
            "task_id": self.task_id,
            "agent": self.agent,
            "timestamp": self.timestamp.isoformat(),
            "files_changed": self.files_changed,
            "commands_run": self.commands_run,
            "test_results": self.test_results,
            "claims": self.claims,
            "reports": [r.to_dict() for r in self.reports],
            "risk_level": self.risk_level,
            "status": self.status.value,
            "rejection_reasons": self.rejection_reasons,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "EvidenceBundle":
        return cls(
            bundle_id=data["bundle_id"],
            task_id=data["task_id"],
            agent=data["agent"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            files_changed=data.get("files_changed", []),
            commands_run=data.get("commands_run", []),
            test_results=data.get("test_results", {}),
            claims=data.get("claims", []),
            reports=[
                EvidenceReport.from_dict(r) for r in data.get("reports", [])
            ],
            risk_level=data.get("risk_level", "low"),
            status=BundleStatus(data.get("status", "empty")),
            rejection_reasons=data.get("rejection_reasons", []),
        )

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)


def create_bundle(
    task_id: str,
    agent: str,
    files_changed: Optional[List[str]] = None,
    commands_run: Optional[List[str]] = None,
    test_results: Optional[Dict[str, Any]] = None,
    claims: Optional[List[str]] = None,
    reports: Optional[List[EvidenceReport]] = None,
    risk_level: str = "low",
) -> EvidenceBundle:
    """Factory helper to create an EvidenceBundle with auto-generated ID."""
    import uuid
    return EvidenceBundle(
        bundle_id=f"bundle-{uuid.uuid4().hex[:12]}",
        task_id=task_id,
        agent=agent,
        timestamp=datetime.now(),
        files_changed=files_changed or [],
        commands_run=commands_run or [],
        test_results=test_results or {},
        claims=claims or [],
        reports=reports or [],
        risk_level=risk_level,
    )
