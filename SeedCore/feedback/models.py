"""
models.py — Core data models for the Arbitrator Feedback System.

The Feedback System implements a trust-weighted, role-tiered model for
incorporating human responses to published consequence maps. This design
reflects the Prime Directive's commitment to collective intelligence
while preventing capture by any single voice — including powerful ones.

DESIGN PHILOSOPHY:

Trust-weighted means that identical feedback from two different roles
does not carry identical analytical weight. A domain expert's factual
correction to an economic finding carries more weight than a general
sentiment. An affected party's account of concrete harm carries more
weight in the social domain than in the legal domain. Trust is not
a single scalar — it is role-relative and domain-relative.

Role-tiered means that different roles unlock different feedback types.
A citizen can submit general comments and escalation requests. A domain
expert can submit finding challenges with citations. A reviewer can
approve or reject the consequence map. This is not elitism — it is
epistemic hygiene. Restricting data corrections to those who can cite
evidence prevents pollution of the analytical record.

Trust can be earned over time. A citizen whose factual claims are
consistently verified by domain experts accumulates trust. A domain
expert whose challenges are consistently upheld accumulates trust.
The system learns who to weight more heavily within each domain.

All feedback is logged to the tamper-evident audit chain. Every
submission, weighting, and aggregation decision is inspectable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class FeedbackRole(Enum):
    """
    The role of the feedback submitter.

    Roles determine baseline trust weights and which feedback types
    are available to the submitter.

    Trust weights are domain-relative. See ROLE_DOMAIN_TRUST for the
    full trust matrix.
    """
    CITIZEN           = "citizen"           # General public
    AFFECTED_PARTY    = "affected_party"    # Directly impacted by the proposal
    DOMAIN_EXPERT     = "domain_expert"     # Subject-matter expert with credentials
    POLICYMAKER       = "policymaker"       # Government or institutional decision-maker
    ETHICIST          = "ethicist"          # Professional ethicist or moral philosopher
    REVIEWER          = "reviewer"          # Assigned human reviewer (audit role)


# ---------------------------------------------------------------------------
# Trust matrix
# ---------------------------------------------------------------------------

# ROLE_DOMAIN_TRUST[role][domain] → base trust weight [0.0, 1.0]
# Domain keys match channel names from the thalamus model.
# "general" applies to domains not explicitly listed.
#
# Design rationale:
#   - Domain experts have high trust in their own domain, moderate elsewhere
#   - Affected parties have high trust for social/demographic claims (they
#     have lived experience), lower trust for technical domains
#   - Policymakers have high institutional trust but lower domain trust
#     (they are generalists with decision authority, not analysts)
#   - Ethicists have high trust on ethical/adversarial challenges
#   - Reviewers have universal high trust (they are auditors, not analysts)
#   - Citizens have low base trust but this can be elevated by verification

ROLE_DOMAIN_TRUST: dict[str, dict[str, float]] = {
    FeedbackRole.CITIZEN.value: {
        "general":              0.20,
        "social_demographic":   0.35,   # lived experience carries weight
        "ecological":           0.25,
        "economic":             0.15,
        "ethical_adversarial":  0.30,   # moral intuitions matter
        "historical_precedent": 0.15,
        "legal_institutional":  0.10,
        "geopolitical":         0.15,
        "uncertainty_modeling": 0.10,
    },
    FeedbackRole.AFFECTED_PARTY.value: {
        "general":              0.40,
        "social_demographic":   0.70,   # highest trust: direct harm claims
        "ecological":           0.55,   # environmental harm claims
        "economic":             0.45,   # economic harm claims
        "ethical_adversarial":  0.60,   # "this harms me" is adversarial evidence
        "historical_precedent": 0.30,
        "legal_institutional":  0.35,
        "geopolitical":         0.25,
        "uncertainty_modeling": 0.25,
    },
    FeedbackRole.DOMAIN_EXPERT.value: {
        "general":              0.60,
        "social_demographic":   0.75,
        "ecological":           0.75,
        "economic":             0.75,
        "ethical_adversarial":  0.65,
        "historical_precedent": 0.75,
        "legal_institutional":  0.75,
        "geopolitical":         0.75,
        "uncertainty_modeling": 0.70,
    },
    FeedbackRole.POLICYMAKER.value: {
        "general":              0.50,
        "social_demographic":   0.45,
        "ecological":           0.40,
        "economic":             0.50,
        "ethical_adversarial":  0.45,
        "historical_precedent": 0.45,
        "legal_institutional":  0.60,   # institutional knowledge
        "geopolitical":         0.55,
        "uncertainty_modeling": 0.40,
    },
    FeedbackRole.ETHICIST.value: {
        "general":              0.65,
        "social_demographic":   0.65,
        "ecological":           0.60,
        "economic":             0.50,
        "ethical_adversarial":  0.85,   # highest trust: primary domain
        "historical_precedent": 0.60,
        "legal_institutional":  0.55,
        "geopolitical":         0.50,
        "uncertainty_modeling": 0.55,
    },
    FeedbackRole.REVIEWER.value: {
        "general":              0.90,
        "social_demographic":   0.90,
        "ecological":           0.90,
        "economic":             0.90,
        "ethical_adversarial":  0.90,
        "historical_precedent": 0.90,
        "legal_institutional":  0.90,
        "geopolitical":         0.90,
        "uncertainty_modeling": 0.90,
    },
}


def get_trust_weight(
    role: FeedbackRole,
    domain: str,
    earned_trust_modifier: float = 0.0,
) -> float:
    """
    Return the effective trust weight for a role in a given domain.

    Args:
        role:                   The submitter's role.
        domain:                 The channel domain this feedback targets.
                                Use "general" for non-domain-specific feedback.
        earned_trust_modifier:  A modifier in [-0.3, +0.3] representing
                                accumulated trust earned through verified submissions.
                                Starts at 0.0 for new submitters.

    Returns:
        Trust weight in [0.05, 1.0]. Never zero (all voices are heard);
        never above 1.0 (no single voice is absolute).
    """
    role_weights = ROLE_DOMAIN_TRUST.get(role.value, {})
    base = role_weights.get(domain, role_weights.get("general", 0.20))
    effective = base + earned_trust_modifier
    return max(0.05, min(1.0, round(effective, 4)))


# ---------------------------------------------------------------------------
# Feedback types
# ---------------------------------------------------------------------------

class FeedbackType(Enum):
    """
    The type of feedback being submitted.

    Each type has different implications for how it is processed
    and which roles can submit it.
    """
    FINDING_CHALLENGE      = "finding_challenge"      # Disputes a specific finding
    FINDING_SUPPORT        = "finding_support"        # Corroborates a specific finding
    DATA_CORRECTION        = "data_correction"        # Submits corrected or new data
    ADVERSARIAL_CHALLENGE  = "adversarial_challenge"  # Adds a challenge the adversarial channel missed
    MITIGATION_SUGGESTION  = "mitigation_suggestion"  # Proposes a concrete mitigation
    GENERAL_COMMENT        = "general_comment"        # Narrative, lower weight
    ESCALATION_REQUEST     = "escalation_request"     # Requests human review


# Role permissions: which roles may submit which feedback types
ROLE_PERMISSIONS: dict[FeedbackRole, set[FeedbackType]] = {
    FeedbackRole.CITIZEN: {
        FeedbackType.FINDING_SUPPORT,
        FeedbackType.GENERAL_COMMENT,
        FeedbackType.ESCALATION_REQUEST,
        FeedbackType.ADVERSARIAL_CHALLENGE,
        FeedbackType.MITIGATION_SUGGESTION,
    },
    FeedbackRole.AFFECTED_PARTY: {
        FeedbackType.FINDING_CHALLENGE,
        FeedbackType.FINDING_SUPPORT,
        FeedbackType.DATA_CORRECTION,
        FeedbackType.ADVERSARIAL_CHALLENGE,
        FeedbackType.MITIGATION_SUGGESTION,
        FeedbackType.GENERAL_COMMENT,
        FeedbackType.ESCALATION_REQUEST,
    },
    FeedbackRole.DOMAIN_EXPERT: {
        FeedbackType.FINDING_CHALLENGE,
        FeedbackType.FINDING_SUPPORT,
        FeedbackType.DATA_CORRECTION,
        FeedbackType.ADVERSARIAL_CHALLENGE,
        FeedbackType.MITIGATION_SUGGESTION,
        FeedbackType.GENERAL_COMMENT,
        FeedbackType.ESCALATION_REQUEST,
    },
    FeedbackRole.POLICYMAKER: {
        FeedbackType.FINDING_CHALLENGE,
        FeedbackType.FINDING_SUPPORT,
        FeedbackType.DATA_CORRECTION,
        FeedbackType.ADVERSARIAL_CHALLENGE,
        FeedbackType.MITIGATION_SUGGESTION,
        FeedbackType.GENERAL_COMMENT,
        FeedbackType.ESCALATION_REQUEST,
    },
    FeedbackRole.ETHICIST: {
        FeedbackType.FINDING_CHALLENGE,
        FeedbackType.FINDING_SUPPORT,
        FeedbackType.DATA_CORRECTION,
        FeedbackType.ADVERSARIAL_CHALLENGE,
        FeedbackType.MITIGATION_SUGGESTION,
        FeedbackType.GENERAL_COMMENT,
        FeedbackType.ESCALATION_REQUEST,
    },
    FeedbackRole.REVIEWER: {
        # Reviewers can submit all types
        FeedbackType.FINDING_CHALLENGE,
        FeedbackType.FINDING_SUPPORT,
        FeedbackType.DATA_CORRECTION,
        FeedbackType.ADVERSARIAL_CHALLENGE,
        FeedbackType.MITIGATION_SUGGESTION,
        FeedbackType.GENERAL_COMMENT,
        FeedbackType.ESCALATION_REQUEST,
    },
}


def can_submit(role: FeedbackRole, feedback_type: FeedbackType) -> bool:
    """Return True if the given role may submit the given feedback type."""
    return feedback_type in ROLE_PERMISSIONS.get(role, set())


# ---------------------------------------------------------------------------
# Submitter identity
# ---------------------------------------------------------------------------

@dataclass
class Submitter:
    """
    The identity and trust profile of a feedback submitter.

    Submitter identities are pseudonymous by default — the system does
    not require real names. The submitter_id is a stable identifier
    assigned by the operator (could be a hash of a public key, a
    registered username, or an anonymized token).

    earned_trust is a dict mapping domain names to accumulated trust
    modifiers in [-0.3, +0.3]. It starts empty (all zeros) and is
    updated by the TrustLedger as submissions are verified or refuted.

    Attributes:
        submitter_id:       Stable pseudonymous identifier.
        role:               The submitter's claimed role.
        domain_expertise:   For DOMAIN_EXPERT role — which domains.
        earned_trust:       Domain → modifier mapping. Updated over time.
        submission_count:   Total verified submissions from this submitter.
        verified:           Whether the submitter's role has been verified
                            by an operator (e.g., credentials checked).
    """
    submitter_id: str
    role: FeedbackRole
    domain_expertise: list[str] = field(default_factory=list)
    earned_trust: dict[str, float] = field(default_factory=dict)
    submission_count: int = 0
    verified: bool = False

    def trust_in(self, domain: str) -> float:
        """Return effective trust weight for this submitter in a domain."""
        modifier = self.earned_trust.get(domain, self.earned_trust.get("general", 0.0))
        # Verified submitters get a small bonus
        verification_bonus = 0.05 if self.verified else 0.0
        return get_trust_weight(self.role, domain, modifier + verification_bonus)

    def to_dict(self) -> dict:
        return {
            "submitter_id": self.submitter_id,
            "role": self.role.value,
            "domain_expertise": self.domain_expertise,
            "earned_trust": self.earned_trust,
            "submission_count": self.submission_count,
            "verified": self.verified,
        }


# ---------------------------------------------------------------------------
# Core feedback entry
# ---------------------------------------------------------------------------

@dataclass
class FeedbackEntry:
    """
    A single feedback submission against a published consequence map.

    Attributes:
        map_id:             The consequence map this feedback targets.
        session_id:         The pipeline session that produced the map.
        submitter:          The submitter's identity and trust profile.
        feedback_type:      What kind of feedback this is.
        content:            The feedback text (required for all types).
        target_finding_id:  For FINDING_CHALLENGE/SUPPORT — the specific
                            Finding being addressed. None for general types.
        target_domain:      The channel domain this feedback primarily
                            addresses. Used for trust weight lookup.
        citations:          Any references, data sources, or evidence
                            the submitter provides to support their claim.
        suggested_correction: For DATA_CORRECTION — the corrected value
                            or new data being submitted.
        escalation_reason:  For ESCALATION_REQUEST — why the submitter
                            believes human review is needed.
        trust_weight:       Computed at submission time from submitter role
                            and domain. Immutable after creation.
        feedback_id:        Auto-generated UUID.
        submitted_at:       UTC timestamp.
        status:             Processing status of this feedback entry.
    """
    map_id: str
    session_id: str
    submitter: Submitter
    feedback_type: FeedbackType
    content: str
    target_finding_id: Optional[str] = None
    target_domain: str = "general"
    citations: list[str] = field(default_factory=list)
    suggested_correction: Optional[str] = None
    escalation_reason: Optional[str] = None
    trust_weight: float = field(init=False)
    feedback_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: "FeedbackStatus" = field(default=None)

    def __post_init__(self):
        # Compute trust weight at creation time — immutable thereafter
        self.trust_weight = self.submitter.trust_in(self.target_domain)

        # Set default status
        if self.status is None:
            self.status = FeedbackStatus.RECEIVED

        # Validate role permission
        if not can_submit(self.submitter.role, self.feedback_type):
            raise PermissionError(
                f"Role {self.submitter.role.value!r} may not submit "
                f"{self.feedback_type.value!r} feedback."
            )

        # Validate required fields per type
        if self.feedback_type == FeedbackType.DATA_CORRECTION:
            if not self.suggested_correction:
                raise ValueError(
                    "DATA_CORRECTION feedback requires a suggested_correction."
                )
        if self.feedback_type == FeedbackType.ESCALATION_REQUEST:
            if not self.escalation_reason:
                raise ValueError(
                    "ESCALATION_REQUEST feedback requires an escalation_reason."
                )
        if self.feedback_type in (
            FeedbackType.FINDING_CHALLENGE, FeedbackType.FINDING_SUPPORT
        ):
            if not self.target_finding_id:
                raise ValueError(
                    f"{self.feedback_type.value} feedback requires a target_finding_id."
                )

        if not self.content.strip():
            raise ValueError("Feedback content must not be empty.")

    def to_dict(self) -> dict:
        return {
            "feedback_id": self.feedback_id,
            "map_id": self.map_id,
            "session_id": self.session_id,
            "submitter_id": self.submitter.submitter_id,
            "submitter_role": self.submitter.role.value,
            "feedback_type": self.feedback_type.value,
            "content": self.content,
            "target_finding_id": self.target_finding_id,
            "target_domain": self.target_domain,
            "citations": self.citations,
            "suggested_correction": self.suggested_correction,
            "escalation_reason": self.escalation_reason,
            "trust_weight": round(self.trust_weight, 4),
            "submitted_at": self.submitted_at,
            "status": self.status.value if self.status else None,
        }


# ---------------------------------------------------------------------------
# Feedback status lifecycle
# ---------------------------------------------------------------------------

class FeedbackStatus(Enum):
    """
    The processing lifecycle of a feedback entry.

    RECEIVED  → VALIDATED  → INTEGRATED (normal path)
              → REJECTED   (failed validation or permission check)
    VALIDATED → ESCALATED  (triggers escalation review)
    """
    RECEIVED   = "received"    # Just submitted, not yet validated
    VALIDATED  = "validated"   # Passed validation, queued for integration
    INTEGRATED = "integrated"  # Incorporated into the aggregated feedback
    REJECTED   = "rejected"    # Failed validation or permission check
    ESCALATED  = "escalated"   # Triggered human review escalation


# ---------------------------------------------------------------------------
# Aggregated signals per finding
# ---------------------------------------------------------------------------

@dataclass
class FindingSignal:
    """
    The aggregated feedback signal for a single Finding.

    Accumulates all FINDING_CHALLENGE and FINDING_SUPPORT submissions
    targeting the same finding_id, weighted by submitter trust.

    Attributes:
        finding_id:         The Finding this signal is about.
        support_weight:     Sum of trust weights from FINDING_SUPPORT submissions.
        challenge_weight:   Sum of trust weights from FINDING_CHALLENGE submissions.
        net_signal:         support_weight - challenge_weight. Positive = supported.
        support_count:      Number of support submissions (unweighted).
        challenge_count:    Number of challenge submissions (unweighted).
        challenges:         The actual challenge feedback entries.
        supports:           The actual support feedback entries.
        data_corrections:   DATA_CORRECTION entries targeting this finding's domain.
    """
    finding_id: str
    support_weight: float = 0.0
    challenge_weight: float = 0.0
    support_count: int = 0
    challenge_count: int = 0
    challenges: list[FeedbackEntry] = field(default_factory=list)
    supports: list[FeedbackEntry] = field(default_factory=list)
    data_corrections: list[FeedbackEntry] = field(default_factory=list)

    @property
    def net_signal(self) -> float:
        """Positive = net support. Negative = net challenge. Range: unbounded."""
        return round(self.support_weight - self.challenge_weight, 4)

    @property
    def is_contested(self) -> bool:
        """True if this finding has substantial challenge weight."""
        return self.challenge_weight >= 0.5 and self.challenge_count >= 2

    @property
    def is_corroborated(self) -> bool:
        """True if this finding has substantial support weight."""
        return self.support_weight >= 0.5 and self.support_count >= 2

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "support_weight": round(self.support_weight, 4),
            "challenge_weight": round(self.challenge_weight, 4),
            "net_signal": self.net_signal,
            "support_count": self.support_count,
            "challenge_count": self.challenge_count,
            "is_contested": self.is_contested,
            "is_corroborated": self.is_corroborated,
            "challenges": [e.to_dict() for e in self.challenges],
            "supports": [e.to_dict() for e in self.supports],
            "data_corrections": [e.to_dict() for e in self.data_corrections],
        }


# ---------------------------------------------------------------------------
# Feedback summary for a consequence map
# ---------------------------------------------------------------------------

@dataclass
class FeedbackSummary:
    """
    The complete aggregated feedback state for a single consequence map.

    This is the primary output of the FeedbackAggregator. It represents
    the full picture of what humans have said about a published analysis —
    weighted by their roles and earned trust.

    Attributes:
        map_id:                 The consequence map this summary covers.
        session_id:             The originating session.
        total_submissions:      Total feedback entries received.
        finding_signals:        Per-finding aggregated signals.
        contested_findings:     Finding IDs with net challenge weight >= 0.5.
        corroborated_findings:  Finding IDs with net support weight >= 0.5.
        adversarial_challenges: All adversarial challenges submitted by humans.
        mitigation_suggestions: All mitigation suggestions submitted.
        general_comments:       All general comments.
        escalation_pressure:    Weighted sum of escalation request trust weights.
                                Threshold for triggering human review: >= 1.0.
        escalation_requests:    All escalation request entries.
        requires_escalation:    Whether escalation_pressure >= threshold.
        data_corrections:       All data correction submissions.
        net_sentiment:          Overall sentiment across all feedback.
                                Derived from finding signals + general weight.
        role_breakdown:         Count of submissions per role.
        generated_at:           UTC timestamp of aggregation.
        summary_id:             UUID.
    """
    map_id: str
    session_id: str
    total_submissions: int = 0
    finding_signals: dict[str, FindingSignal] = field(default_factory=dict)
    contested_findings: list[str] = field(default_factory=list)
    corroborated_findings: list[str] = field(default_factory=list)
    adversarial_challenges: list[FeedbackEntry] = field(default_factory=list)
    mitigation_suggestions: list[FeedbackEntry] = field(default_factory=list)
    general_comments: list[FeedbackEntry] = field(default_factory=list)
    escalation_pressure: float = 0.0
    escalation_requests: list[FeedbackEntry] = field(default_factory=list)
    data_corrections: list[FeedbackEntry] = field(default_factory=list)
    net_sentiment: float = 0.0     # [-1.0, 1.0]: -1 = strong challenge, +1 = strong support
    role_breakdown: dict[str, int] = field(default_factory=dict)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    summary_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    ESCALATION_THRESHOLD: float = 1.0   # escalation_pressure to trigger review

    @property
    def requires_escalation(self) -> bool:
        """True when accumulated escalation pressure crosses the threshold."""
        return self.escalation_pressure >= self.ESCALATION_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "summary_id": self.summary_id,
            "map_id": self.map_id,
            "session_id": self.session_id,
            "total_submissions": self.total_submissions,
            "finding_signals": {
                k: v.to_dict() for k, v in self.finding_signals.items()
            },
            "contested_findings": self.contested_findings,
            "corroborated_findings": self.corroborated_findings,
            "adversarial_challenges": [e.to_dict() for e in self.adversarial_challenges],
            "mitigation_suggestions": [e.to_dict() for e in self.mitigation_suggestions],
            "general_comments": [e.to_dict() for e in self.general_comments],
            "escalation_pressure": round(self.escalation_pressure, 4),
            "escalation_requests": [e.to_dict() for e in self.escalation_requests],
            "data_corrections": [e.to_dict() for e in self.data_corrections],
            "net_sentiment": round(self.net_sentiment, 4),
            "role_breakdown": self.role_breakdown,
            "requires_escalation": self.requires_escalation,
            "generated_at": self.generated_at,
        }
