"""
channel_output.py — The standard output contract for Arbitrator model channels.

Every specialist channel — regardless of what model powers it, whether it is
an API call or a local model, whether it is the economic channel or the
ecological channel — must return its analysis as a ChannelOutput instance.

This contract is the interface between the channel invocation layer and the
Synthesis Layer. The Synthesis Layer never looks inside a channel's logic;
it only consumes this structured output.

Design rationale:
    Strict typing here prevents the Synthesis Layer from needing to handle
    inconsistent or missing fields from different channels. If a channel
    cannot produce a field, it must explicitly say so (e.g., confidence=None,
    findings=[]). This makes integration failures visible and auditable rather
    than silently wrong.

    The ChannelOutput is also what gets logged to the public audit record
    for each channel. Reviewers can inspect what every channel said, not just
    the synthesis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ChannelStatus(Enum):
    """
    The status of a channel invocation.

    SUCCESS means the channel produced analysis. All other statuses are
    failure modes and trigger specific handling in the Synthesis Layer.
    """
    SUCCESS = "success"
    FAILED = "failed"               # Channel errored during analysis
    TIMEOUT = "timeout"             # Channel did not respond in time
    REFUSED = "refused"             # Channel declined to analyze (e.g., out of scope)
    UNAVAILABLE = "unavailable"     # Channel model not loaded or reachable


class ImpactDirection(Enum):
    """Whether a finding represents a harm, a benefit, or is neutral."""
    HARM = "harm"
    BENEFIT = "benefit"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class ImpactTimeframe(Enum):
    """When a finding's effect is expected to manifest."""
    IMMEDIATE = "immediate"         # Days to weeks
    SHORT_TERM = "short_term"       # Months to ~2 years
    MEDIUM_TERM = "medium_term"     # 2–10 years
    LONG_TERM = "long_term"         # 10–50 years
    GENERATIONAL = "generational"   # 50+ years


class ImpactCertainty(Enum):
    """How certain the channel is about a finding."""
    HIGH = "high"           # Well-supported by evidence
    MODERATE = "moderate"   # Probable but not certain
    LOW = "low"             # Speculative or highly uncertain
    UNKNOWN = "unknown"     # Cannot assess certainty


@dataclass
class Finding:
    """
    A single analytical finding from a channel.

    A finding is the atomic unit of channel output. The Synthesis Layer
    aggregates findings across channels to build the consequence map.

    Attributes:
        summary:        One-sentence description of the finding.
        detail:         Fuller explanation (1–3 paragraphs).
        direction:      Is this a harm, a benefit, or mixed?
        timeframe:      When is this effect expected?
        certainty:      How confident is the channel in this finding?
        magnitude:      Float [0.0, 1.0]. How significant is this finding?
                        0.0 = negligible, 1.0 = transformative/catastrophic.
        affected_groups: Which population groups are affected by this finding.
        reversible:     Whether this effect can be undone.
        citations:      Any data sources, studies, or references cited.
        tags:           Domain tags for grouping (e.g., "economic", "health").
        finding_id:     Deterministic ID in format '{channel_name}_{index:02d}'.
                        Set by the parser from model output or generated as fallback.
        references_finding_id: finding_ids from other channels that this finding
                        directly responds to, builds on, or challenges. Used by
                        secondary channels to link their analysis back to the
                        primary channel findings that triggered it.
    """
    summary: str
    detail: str
    direction: ImpactDirection
    timeframe: ImpactTimeframe
    certainty: ImpactCertainty
    magnitude: float                                    # [0.0, 1.0]
    affected_groups: list[str] = field(default_factory=list)
    reversible: Optional[bool] = None                   # None = unknown
    citations: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    finding_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    references_finding_id: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not (0.0 <= self.magnitude <= 1.0):
            raise ValueError(f"Finding magnitude must be in [0.0, 1.0], got {self.magnitude}")
        if not self.summary.strip():
            raise ValueError("Finding summary must not be empty")

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "summary": self.summary,
            "detail": self.detail,
            "direction": self.direction.value,
            "timeframe": self.timeframe.value,
            "certainty": self.certainty.value,
            "magnitude": round(self.magnitude, 4),
            "affected_groups": self.affected_groups,
            "reversible": self.reversible,
            "citations": self.citations,
            "tags": self.tags,
            "references_finding_id": self.references_finding_id,
        }


@dataclass
class UncertaintyNote:
    """
    A documented uncertainty or caveat in a channel's analysis.

    Channels are expected to be honest about the limits of their knowledge.
    UncertaintyNotes are surfaced explicitly in the consequence map rather
    than being buried or omitted.
    """
    description: str                # What is uncertain and why
    impact_on_analysis: str         # How this uncertainty affects the findings
    magnitude: float                # [0.0, 1.0] — how much does this uncertainty matter?
    note_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "note_id": self.note_id,
            "description": self.description,
            "impact_on_analysis": self.impact_on_analysis,
            "magnitude": round(self.magnitude, 4),
        }


@dataclass
class ChannelOutput:
    """
    The complete output of a single specialist channel.

    This is the contract. Every channel must produce a ChannelOutput.
    The Synthesis Layer consumes only ChannelOutputs — never raw channel internals.

    Attributes:
        channel_name:       Which channel produced this output.
        status:             Did the channel succeed?
        findings:           List of analytical findings (may be empty on failure).
        uncertainty_notes:  Documented uncertainties in the analysis.
        overall_harm_score: Channel's estimate of harm [0.0, 1.0].
        overall_benefit_score: Channel's estimate of benefit [0.0, 1.0].
        confidence:         Channel's confidence in its own output [0.0, 1.0].
        domain_summary:     One-paragraph plain-language summary of this channel's analysis.
        adversarial_challenges: For the ETHICAL_ADVERSARIAL channel — specific challenges
                            to the proposal. Other channels leave this empty.
        model_id:           Identifier of the model that produced this output.
        processing_time_ms: How long the channel took (for audit/performance logging).
        error_message:      Error detail if status != SUCCESS.
        output_id:          Auto-generated UUID.
        generated_at:       UTC timestamp.
    """
    channel_name: str
    status: ChannelStatus
    findings: list[Finding] = field(default_factory=list)
    uncertainty_notes: list[UncertaintyNote] = field(default_factory=list)
    overall_harm_score: Optional[float] = None          # [0.0, 1.0] or None if unavailable
    overall_benefit_score: Optional[float] = None       # [0.0, 1.0] or None if unavailable
    confidence: Optional[float] = None                  # [0.0, 1.0] or None if unavailable
    domain_summary: str = ""
    adversarial_challenges: list[str] = field(default_factory=list)
    model_id: str = "unknown"
    processing_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    output_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        for score_name, score_val in [
            ("overall_harm_score", self.overall_harm_score),
            ("overall_benefit_score", self.overall_benefit_score),
            ("confidence", self.confidence),
        ]:
            if score_val is not None and not (0.0 <= score_val <= 1.0):
                raise ValueError(f"{score_name} must be in [0.0, 1.0] or None, got {score_val}")

    @property
    def succeeded(self) -> bool:
        return self.status == ChannelStatus.SUCCESS

    @property
    def harm_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.direction in (ImpactDirection.HARM, ImpactDirection.MIXED)]

    @property
    def benefit_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.direction in (ImpactDirection.BENEFIT, ImpactDirection.MIXED)]

    @property
    def high_certainty_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.certainty == ImpactCertainty.HIGH]

    def to_dict(self) -> dict:
        return {
            "output_id": self.output_id,
            "channel_name": self.channel_name,
            "status": self.status.value,
            "overall_harm_score": round(self.overall_harm_score, 4) if self.overall_harm_score is not None else None,
            "overall_benefit_score": round(self.overall_benefit_score, 4) if self.overall_benefit_score is not None else None,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "domain_summary": self.domain_summary,
            "findings": [f.to_dict() for f in self.findings],
            "uncertainty_notes": [u.to_dict() for u in self.uncertainty_notes],
            "adversarial_challenges": self.adversarial_challenges,
            "model_id": self.model_id,
            "processing_time_ms": self.processing_time_ms,
            "error_message": self.error_message,
            "generated_at": self.generated_at,
        }
