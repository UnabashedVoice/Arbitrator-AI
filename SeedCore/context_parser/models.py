"""
models.py — Data structures for the Arbitrator Context Parser.

The Context Parser transforms raw natural language input into a structured
ParsedContext, which drives the routing manifest and feeds downstream
components (the Ethics Core pre-screen, the channel invocation layer, etc.)

Everything produced here is auditable and published with every analysis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Channel(Enum):
    """
    The set of specialist model channels available to Arbitrator.

    Each channel represents a domain of analysis. The Context Parser
    determines which channels are relevant to a given input. Channels
    not deemed relevant are not invoked — saving compute and keeping
    outputs focused.
    """
    ECONOMIC = "economic"
    ECOLOGICAL = "ecological"
    SOCIAL_DEMOGRAPHIC = "social_demographic"
    HISTORICAL_PRECEDENT = "historical_precedent"
    LEGAL_INSTITUTIONAL = "legal_institutional"
    GEOPOLITICAL = "geopolitical"
    ETHICAL_ADVERSARIAL = "ethical_adversarial"
    UNCERTAINTY_MODELING = "uncertainty_modeling"


class InputScale(Enum):
    """The geographic/institutional scope of the proposed action."""
    LOCAL = "local"               # City, municipality, district
    REGIONAL = "regional"         # State, province, region
    NATIONAL = "national"         # Country-wide
    INTERNATIONAL = "international"  # Multi-country / treaty-level
    GLOBAL = "global"             # Planetary / civilizational


class TimeHorizon(Enum):
    """
    The primary time horizon of the action's effects.

    Used by downstream channels to calibrate their analysis depth
    and by the Ethics Core to apply appropriate long-term risk weighting.
    """
    IMMEDIATE = "immediate"           # Days to weeks
    SHORT_TERM = "short_term"         # Months to ~2 years
    MEDIUM_TERM = "medium_term"       # 2–10 years
    LONG_TERM = "long_term"           # 10–50 years
    GENERATIONAL = "generational"     # 50+ years / future generations
    UNKNOWN = "unknown"


class InputType(Enum):
    """
    The nature of the submitted input.

    Helps downstream components calibrate their framing of the output.
    """
    POLICY_PROPOSAL = "policy_proposal"         # A specific policy being considered
    LEGISLATIVE_PROPOSAL = "legislative_proposal"
    EXECUTIVE_ACTION = "executive_action"
    INFRASTRUCTURE_PROJECT = "infrastructure_project"
    ECONOMIC_INTERVENTION = "economic_intervention"
    SOCIAL_PROGRAM = "social_program"
    ENVIRONMENTAL_ACTION = "environmental_action"
    MILITARY_ACTION = "military_action"
    TREATY_OR_AGREEMENT = "treaty_or_agreement"
    REGULATORY_CHANGE = "regulatory_change"
    HYPOTHETICAL = "hypothetical"               # "What if..." framing
    GENERAL_QUERY = "general_query"             # Unclear / open-ended


# ---------------------------------------------------------------------------
# Channel routing entry
# ---------------------------------------------------------------------------

@dataclass
class ChannelRoute:
    """
    A single entry in the routing manifest.

    Represents the decision to invoke (or not invoke) a specific channel,
    along with the reasoning and confidence behind that decision.

    Attributes:
        channel:        The channel being considered.
        invoked:        Whether this channel will be called.
        relevance_score: Float in [0.0, 1.0] — how relevant this channel is.
        signals:        The specific keywords/phrases that drove this score.
        rationale:      Human-readable explanation of why this channel was
                        included or excluded.
    """
    channel: Channel
    invoked: bool
    relevance_score: float          # [0.0, 1.0]
    signals: list[str]              # matched signals that contributed to the score
    rationale: str

    def to_dict(self) -> dict:
        return {
            "channel": self.channel.value,
            "invoked": self.invoked,
            "relevance_score": round(self.relevance_score, 4),
            "signals": self.signals,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Primary output models
# ---------------------------------------------------------------------------

@dataclass
class ParsedContext:
    """
    The structured output of the Context Parser for a single input.

    This is published as part of every analysis in the audit log.
    Every field is populated by the parser — nothing is left implicit.

    Attributes:
        raw_input:              The original submitted text, verbatim.
        normalized_input:       Cleaned/lowercased version used for parsing.
        input_type:             What kind of action this appears to be.
        scale:                  Geographic/institutional scale.
        time_horizon:           Primary time horizon of effects.
        affected_populations:   List of population groups identified in the text.
        domains_mentioned:      High-level domain tags extracted from the text.
        explicit_assumptions:   Statements in the text that appear to be assumptions.
        implicit_flags:         Concerns or framings the parser detected but the
                                submitter did not explicitly state.
        key_entities:           Named entities extracted (organizations, places, etc.)
        urgency_detected:       Whether language suggesting urgency was found.
        controversy_signals:    Whether language suggesting political controversy
                                was detected.
        parser_confidence:      Float [0.0, 1.0] — confidence in the parse overall.
        parse_warnings:         Any issues or ambiguities detected during parsing.
        input_id:               UUID linking this parse to the original input.
        parsed_at:              UTC timestamp.
    """
    raw_input: str
    normalized_input: str
    input_type: InputType
    scale: InputScale
    time_horizon: TimeHorizon
    affected_populations: list[str] = field(default_factory=list)
    domains_mentioned: list[str] = field(default_factory=list)
    explicit_assumptions: list[str] = field(default_factory=list)
    implicit_flags: list[str] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    urgency_detected: bool = False
    controversy_signals: bool = False
    parser_confidence: float = 1.0
    parse_warnings: list[str] = field(default_factory=list)
    input_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parsed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "input_id": self.input_id,
            "input_type": self.input_type.value,
            "scale": self.scale.value,
            "time_horizon": self.time_horizon.value,
            "affected_populations": self.affected_populations,
            "domains_mentioned": self.domains_mentioned,
            "explicit_assumptions": self.explicit_assumptions,
            "implicit_flags": self.implicit_flags,
            "key_entities": self.key_entities,
            "urgency_detected": self.urgency_detected,
            "controversy_signals": self.controversy_signals,
            "parser_confidence": round(self.parser_confidence, 4),
            "parse_warnings": self.parse_warnings,
            "parsed_at": self.parsed_at,
        }


@dataclass
class RoutingManifest:
    """
    The complete output of the Context Parser: a parsed context plus
    a routing decision for every available channel.

    The RoutingManifest is the contract between the Context Parser and
    the channel invocation layer. It is published in full with every
    analysis in the public audit log.

    Attributes:
        context:            The parsed context derived from the input.
        routes:             One ChannelRoute per available channel.
        invoked_channels:   Convenience list of channels marked invoked=True.
        routing_version:    Version string for the routing logic. Allows
                            audit log readers to know which logic produced
                            a given manifest.
        manifest_id:        UUID for this specific manifest.
        generated_at:       UTC timestamp.
    """
    context: ParsedContext
    routes: list[ChannelRoute]
    routing_version: str = "0.1.0"
    manifest_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def invoked_channels(self) -> list[Channel]:
        return [r.channel for r in self.routes if r.invoked]

    @property
    def skipped_channels(self) -> list[Channel]:
        return [r.channel for r in self.routes if not r.invoked]

    def to_dict(self) -> dict:
        return {
            "manifest_id": self.manifest_id,
            "routing_version": self.routing_version,
            "generated_at": self.generated_at,
            "context": self.context.to_dict(),
            "routes": [r.to_dict() for r in self.routes],
            "invoked_channels": [c.value for c in self.invoked_channels],
            "skipped_channels": [c.value for c in self.skipped_channels],
        }
