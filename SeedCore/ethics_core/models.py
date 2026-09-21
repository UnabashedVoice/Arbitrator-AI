"""
models.py — Core data structures for the Arbitrator Ethics Core.

All inputs to and outputs from the Ethics Core are expressed as instances
of these dataclasses. This makes the evaluation pipeline fully inspectable,
loggable, and auditable at every stage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ConsciousnessType(Enum):
    """
    Categories of consciousness that may be affected by an action.

    The Prime Directive holds all consciousness sacred. This enum allows
    the Ethics Core to apply appropriate scrutiny weights depending on
    the type of conscious entity involved.
    """
    HUMAN = "human"
    ANIMAL = "animal"
    ECOSYSTEM = "ecosystem"          # Treated as a collective conscious entity
    SYNTHETIC = "synthetic"          # AI or machine consciousness
    UNRECOGNIZED = "unrecognized"    # Deliberately open-ended — forms not yet known
    NONE = "none"                    # Action affects no conscious entity


class HarmType(Enum):
    """
    Categories of harm that an action may produce.

    Used to classify harm beyond a simple numeric score, enabling
    domain-specific scrutiny and downstream reporting.
    """
    PHYSICAL = "physical"
    PSYCHOLOGICAL = "psychological"
    ECONOMIC = "economic"
    ECOLOGICAL = "ecological"
    SOCIAL = "social"
    CULTURAL = "cultural"
    EXISTENTIAL = "existential"      # Irreversible, civilization-scale, or extinction-risk harms
    NONE = "none"


class BenefitType(Enum):
    """Categories of benefit that an action may produce."""
    PHYSICAL = "physical"
    PSYCHOLOGICAL = "psychological"
    ECONOMIC = "economic"
    ECOLOGICAL = "ecological"
    SOCIAL = "social"
    CULTURAL = "cultural"
    NONE = "none"


class Scope(Enum):
    """
    The scale of impact of an action.

    Mutual (many-to-many) impacts are weighted more heavily than
    individual impacts per the Prime Directive.
    """
    INDIVIDUAL = "individual"        # Affects a single entity
    GROUP = "group"                  # Affects a defined group
    SOCIETAL = "societal"            # Affects a large population
    GLOBAL = "global"                # Affects humanity or Earth as a whole
    INTERGENERATIONAL = "intergenerational"  # Affects future generations


class Reversibility(Enum):
    """
    Whether the effects of an action can be undone.

    Irreversible harms receive significantly higher scrutiny under
    the Prime Directive's mandate to minimize and mitigate harm.
    """
    FULLY_REVERSIBLE = "fully_reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


class Verdict(Enum):
    """
    The Ethics Core's verdict on a proposed action.

    Every analysis produces exactly one verdict. The verdict is
    accompanied by a full justification and, where relevant,
    mitigation requirements.
    """
    PASS = "pass"                          # Action passes the Ethics Core
    FAIL = "fail"                          # Action fails — rejected or requires major mitigation
    AMBIGUOUS = "ambiguous"                # Balanced harm/benefit — flags for human review
    ESCALATE = "escalate"                  # High-magnitude consciousness impact — human ratification required
    HARD_REJECT = "hard_reject"            # Violates a hard constraint — cannot be approved under any circumstances


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

@dataclass
class ActionProposal:
    """
    A proposed action or policy submitted to the Ethics Core for evaluation.

    This is the primary input to the Ethics Core. It encapsulates everything
    the Ethics Core needs to evaluate an action against the Prime Directive.

    Attributes:
        description:            Human-readable description of the proposed action.
        harm_score:             Float in [0.0, 1.0]. 0 = no harm, 1 = catastrophic harm.
        benefit_score:          Float in [0.0, 1.0]. 0 = no benefit, 1 = transformative benefit.
        harm_types:             What kinds of harm may result.
        benefit_types:          What kinds of benefit may result.
        consciousness_types:    Which categories of conscious entity are affected.
        harm_scope:             Scale of the harm.
        benefit_scope:          Scale of the benefit.
        reversibility:          Whether the harm is reversible.
        uncertainty:            Float in [0.0, 1.0]. How uncertain are the harm/benefit estimates?
        long_term_risk:         Float in [0.0, 1.0]. Probability of severe long-term consequences.
        mitigation_proposed:    Whether the submitter has proposed mitigation for the harm.
        context:                Optional free-text context provided by the submitter.
        proposal_id:            Auto-generated UUID for audit trail.
        submitted_at:           Auto-generated UTC timestamp.
    """
    description: str
    harm_score: float                                          # [0.0, 1.0]
    benefit_score: float                                       # [0.0, 1.0]
    harm_types: list[HarmType] = field(default_factory=list)
    benefit_types: list[BenefitType] = field(default_factory=list)
    consciousness_types: list[ConsciousnessType] = field(default_factory=list)
    harm_scope: Scope = Scope.INDIVIDUAL
    benefit_scope: Scope = Scope.INDIVIDUAL
    reversibility: Reversibility = Reversibility.UNKNOWN
    uncertainty: float = 0.5                                   # [0.0, 1.0]
    long_term_risk: float = 0.0                                # [0.0, 1.0]
    mitigation_proposed: bool = False
    context: Optional[str] = None
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        self._validate()

    def _validate(self):
        """Raise ValueError for any out-of-range scores."""
        for name, val in [
            ("harm_score", self.harm_score),
            ("benefit_score", self.benefit_score),
            ("uncertainty", self.uncertainty),
            ("long_term_risk", self.long_term_risk),
        ]:
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0], got {val}")

        if not self.description.strip():
            raise ValueError("description must not be empty")


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

@dataclass
class EthicsEvaluation:
    """
    The complete output of an Ethics Core evaluation.

    Every field here is intended to be logged to the public audit record
    and presented to the human decision-maker. Nothing is hidden.

    Attributes:
        proposal_id:            Links this evaluation to its ActionProposal.
        verdict:                The Ethics Core's verdict (see Verdict enum).
        justification:          Human-readable explanation of the verdict.
        hard_constraints_triggered: List of hard constraint names that were triggered,
                                if any. Non-empty only when verdict is HARD_REJECT.
        weighted_harm:          Harm score after applying consciousness and scope weights.
        weighted_benefit:       Benefit score after applying scope weights.
        net_score:              weighted_benefit - weighted_harm. Positive = net benefit.
        consciousness_weight:   The multiplier applied based on consciousness type(s).
        scope_weight_harm:      The multiplier applied to harm based on scope.
        scope_weight_benefit:   The multiplier applied to benefit based on scope.
        mitigation_required:    Whether mitigation is required before action can proceed.
        mitigation_notes:       Specific notes on what mitigation is needed.
        flags:                  List of specific concerns raised during evaluation.
        confidence:             Float in [0.0, 1.0]. Confidence in this evaluation.
        evaluated_at:           UTC timestamp of evaluation.
    """
    proposal_id: str
    verdict: Verdict
    justification: str
    hard_constraints_triggered: list[str] = field(default_factory=list)
    weighted_harm: float = 0.0
    weighted_benefit: float = 0.0
    net_score: float = 0.0
    consciousness_weight: float = 1.0
    scope_weight_harm: float = 1.0
    scope_weight_benefit: float = 1.0
    mitigation_required: bool = False
    mitigation_notes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Serialize to a plain dict for logging and JSON output."""
        return {
            "proposal_id": self.proposal_id,
            "verdict": self.verdict.value,
            "justification": self.justification,
            "hard_constraints_triggered": self.hard_constraints_triggered,
            "weighted_harm": round(self.weighted_harm, 4),
            "weighted_benefit": round(self.weighted_benefit, 4),
            "net_score": round(self.net_score, 4),
            "consciousness_weight": round(self.consciousness_weight, 4),
            "scope_weight_harm": round(self.scope_weight_harm, 4),
            "scope_weight_benefit": round(self.scope_weight_benefit, 4),
            "mitigation_required": self.mitigation_required,
            "mitigation_notes": self.mitigation_notes,
            "flags": self.flags,
            "confidence": round(self.confidence, 4),
            "evaluated_at": self.evaluated_at,
        }
