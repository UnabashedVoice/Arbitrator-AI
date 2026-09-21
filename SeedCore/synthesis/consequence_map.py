"""
consequence_map.py — The unified consequence map produced by the Synthesis Layer.

The ConsequenceMap is what the human decision-maker sees. It is the product
of integrating all channel outputs through the Ethics Core. It is structured
to be honest, complete, and resistant to false confidence.

Design principles:
    - Every section is populated even if its content is "no data available."
      Silent omissions are not permitted.
    - Uncertainty is a first-class citizen — the map has a dedicated section
      for what we don't know, and the overall confidence score reflects it.
    - Adversarial challenges are always surfaced, never buried.
    - The consequence map is not a recommendation. It is an analysis. The
      recommendation layer (when built) sits above this and is a separate concern.
    - The full consequence map is published to the audit log, verbatim.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .channel_output import Finding, ImpactDirection, ImpactTimeframe, UncertaintyNote


class OverallVerdict(Enum):
    """
    The synthesis-level verdict on the proposed action.

    This is distinct from the Ethics Core verdict. The Ethics Core evaluates
    against the Prime Directive. The OverallVerdict is the synthesis layer's
    integration of all channel findings into a coherent picture.

    The two verdicts are both surfaced in the final output. They may agree
    or they may diverge — and divergence is itself informative.
    """
    NET_BENEFICIAL = "net_beneficial"       # Benefits clearly outweigh harms
    NET_HARMFUL = "net_harmful"             # Harms clearly outweigh benefits
    MIXED = "mixed"                         # Significant harms and benefits present
    INSUFFICIENT_DATA = "insufficient_data" # Too few channels succeeded to synthesize
    REQUIRES_REVIEW = "requires_review"     # Complexity or uncertainty demands human review


@dataclass
class ImpactSummary:
    """
    A synthesized summary of impacts within a single timeframe.

    The consequence map groups findings by timeframe so the human
    can see immediate effects separately from long-term ones.
    """
    timeframe: ImpactTimeframe
    harm_findings: list[Finding] = field(default_factory=list)
    benefit_findings: list[Finding] = field(default_factory=list)
    neutral_findings: list[Finding] = field(default_factory=list)
    net_direction: ImpactDirection = ImpactDirection.NEUTRAL
    net_magnitude: float = 0.0      # [0.0, 1.0] — magnitude of net impact in this timeframe
    summary_text: str = ""          # Plain-language summary for this timeframe

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe.value,
            "net_direction": self.net_direction.value,
            "net_magnitude": round(self.net_magnitude, 4),
            "summary_text": self.summary_text,
            "harm_findings": [f.to_dict() for f in self.harm_findings],
            "benefit_findings": [f.to_dict() for f in self.benefit_findings],
            "neutral_findings": [f.to_dict() for f in self.neutral_findings],
        }


@dataclass
class PopulationImpact:
    """
    The aggregate impact on a specific population group across all channels.
    """
    population: str
    harm_findings: list[Finding] = field(default_factory=list)
    benefit_findings: list[Finding] = field(default_factory=list)
    net_direction: ImpactDirection = ImpactDirection.NEUTRAL
    net_magnitude: float = 0.0
    summary_text: str = ""

    def to_dict(self) -> dict:
        return {
            "population": self.population,
            "net_direction": self.net_direction.value,
            "net_magnitude": round(self.net_magnitude, 4),
            "summary_text": self.summary_text,
            "harm_findings": [f.to_dict() for f in self.harm_findings],
            "benefit_findings": [f.to_dict() for f in self.benefit_findings],
        }


@dataclass
class RippleEffect:
    """
    A second-order or indirect consequence identified during synthesis.

    Ripple effects are consequences that are not the direct result of the
    action but emerge from the interaction of its direct effects with other
    systems. They are often where the most important and least-anticipated
    consequences live.
    """
    description: str
    source_finding_ids: list[str]   # Which primary findings generated this ripple
    direction: ImpactDirection
    certainty_note: str             # How confident we are about this ripple
    affected_domains: list[str]     # Which analysis domains this touches
    ripple_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "ripple_id": self.ripple_id,
            "description": self.description,
            "source_finding_ids": self.source_finding_ids,
            "direction": self.direction.value,
            "certainty_note": self.certainty_note,
            "affected_domains": self.affected_domains,
        }


@dataclass
class ConsequenceMap:
    """
    The complete consequence map — the primary output of the Synthesis Layer.

    This is what gets delivered to the human decision-maker and logged
    to the public audit record. Every field is populated; nothing is omitted.

    Attributes:
        proposal_description:   The original proposal text.
        manifest_id:            Links to the RoutingManifest that drove channel invocation.
        ethics_evaluation_id:   Links to the EthicsCore evaluation.

        overall_verdict:        The synthesis-level verdict.
        overall_harm_score:     Weighted aggregate harm score [0.0, 1.0].
        overall_benefit_score:  Weighted aggregate benefit score [0.0, 1.0].
        net_score:              benefit - harm [-1.0, 1.0].
        synthesis_confidence:   Confidence in the synthesis [0.0, 1.0].

        executive_summary:      Plain-language 1-paragraph synthesis for the decision-maker.
        timeframe_impacts:      Impact summaries organized by timeframe.
        population_impacts:     Impact summaries organized by affected population.
        ripple_effects:         Second-order and indirect consequences.
        adversarial_challenges: All challenges from the ethical adversarial channel.
        uncertainty_register:   All uncertainty notes from all channels.

        channel_outputs:        The raw channel outputs (for audit log).
        channels_invoked:       Which channels were called.
        channels_succeeded:     Which channels returned SUCCESS.
        channels_failed:        Which channels failed (with reasons).

        data_gaps:              Explicitly documented gaps in the analysis.
        recommended_mitigations: Mitigation steps identified across channels.

        map_id:                 UUID for this consequence map.
        generated_at:           UTC timestamp.
    """
    proposal_description: str
    manifest_id: str
    ethics_evaluation_id: Optional[str]

    overall_verdict: OverallVerdict
    overall_harm_score: float           # [0.0, 1.0]
    overall_benefit_score: float        # [0.0, 1.0]
    net_score: float                    # [-1.0, 1.0]
    synthesis_confidence: float         # [0.0, 1.0]

    executive_summary: str
    timeframe_impacts: list[ImpactSummary] = field(default_factory=list)
    population_impacts: list[PopulationImpact] = field(default_factory=list)
    ripple_effects: list[RippleEffect] = field(default_factory=list)
    adversarial_challenges: list[str] = field(default_factory=list)
    uncertainty_register: list[UncertaintyNote] = field(default_factory=list)

    channel_outputs: list[dict] = field(default_factory=list)  # serialized ChannelOutputs
    channels_invoked: list[str] = field(default_factory=list)
    channels_succeeded: list[str] = field(default_factory=list)
    channels_failed: list[dict] = field(default_factory=list)   # {channel, reason}

    data_gaps: list[str] = field(default_factory=list)
    recommended_mitigations: list[str] = field(default_factory=list)

    map_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def all_harm_findings(self) -> list[Finding]:
        findings = []
        for ti in self.timeframe_impacts:
            findings.extend(ti.harm_findings)
        return findings

    @property
    def all_benefit_findings(self) -> list[Finding]:
        findings = []
        for ti in self.timeframe_impacts:
            findings.extend(ti.benefit_findings)
        return findings

    @property
    def high_magnitude_harms(self) -> list[Finding]:
        return [f for f in self.all_harm_findings if f.magnitude >= 0.6]

    @property
    def high_magnitude_benefits(self) -> list[Finding]:
        return [f for f in self.all_benefit_findings if f.magnitude >= 0.6]

    def to_dict(self) -> dict:
        return {
            "map_id": self.map_id,
            "generated_at": self.generated_at,
            "proposal_description": self.proposal_description,
            "manifest_id": self.manifest_id,
            "ethics_evaluation_id": self.ethics_evaluation_id,

            "overall_verdict": self.overall_verdict.value,
            "overall_harm_score": round(self.overall_harm_score, 4),
            "overall_benefit_score": round(self.overall_benefit_score, 4),
            "net_score": round(self.net_score, 4),
            "synthesis_confidence": round(self.synthesis_confidence, 4),

            "executive_summary": self.executive_summary,
            "timeframe_impacts": [t.to_dict() for t in self.timeframe_impacts],
            "population_impacts": [p.to_dict() for p in self.population_impacts],
            "ripple_effects": [r.to_dict() for r in self.ripple_effects],
            "adversarial_challenges": self.adversarial_challenges,
            "uncertainty_register": [u.to_dict() for u in self.uncertainty_register],

            "channels_invoked": self.channels_invoked,
            "channels_succeeded": self.channels_succeeded,
            "channels_failed": self.channels_failed,
            "data_gaps": self.data_gaps,
            "recommended_mitigations": self.recommended_mitigations,

            "channel_outputs": self.channel_outputs,
        }
