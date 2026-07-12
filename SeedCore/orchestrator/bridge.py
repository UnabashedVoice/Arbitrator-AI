"""
bridge.py — The Context-to-Proposal Bridge.

This module closes the first known gap identified in the compatibility review:
converting a ParsedContext (output of the Context Parser) into an
ActionProposal (input to the Ethics Core).

The bridge cannot be a perfect mechanical translation — a ParsedContext
contains routing metadata, not ethical scores. What it CAN do is derive
reasonable initial estimates from the structural signals in the context,
which the Ethics Core then evaluates formally.

Bridge logic:
    harm_score:         Derived from implicit_flags count, urgency, controversy,
                        and the presence of harm-associated input types.
    benefit_score:      Estimated from scale and the presence of benefit-
                        associated input types (social programs, environmental
                        actions, etc.)
    consciousness_types: Derived from affected_populations.
    harm_scope:         Mapped directly from InputScale.
    benefit_scope:      Same as harm_scope initially (conservative default).
    reversibility:      Estimated from time_horizon and input_type.
    uncertainty:        Estimated from parser_confidence (inverted).
    long_term_risk:     Elevated for generational time horizons.
    harm_types:         Derived from domains_mentioned and input_type.
    benefit_types:      Same.

Important: These are ESTIMATES. The Ethics Core's truth table and scoring
are the authoritative evaluation. The bridge produces inputs that allow
the Ethics Core to run; it does not predetermine the outcome.

Known limitation (Phase 1):
    The bridge is intentionally conservative: unknown reversibility applies
    a precautionary penalty, and benefit scores for short or vague inputs
    are low because there are few positive signals to detect. This means
    benign proposals with short descriptions may receive FAIL verdicts from
    the Ethics Core at bridge level. This is expected behavior — it reflects
    genuine epistemic uncertainty, not a false negative. When real channel
    outputs are available (Phase 2), the channels will provide grounded
    harm/benefit evidence that will supersede the bridge's structural estimates,
    and the bridge's role will shrink to providing initial routing context only.

Every derivation rule is explicit and documented here. When real channel
outputs are available, the orchestrator can pass enriched harm/benefit
scores derived from actual analysis rather than these structural estimates.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..context_parser.models import (
    InputScale,
    InputType,
    ParsedContext,
    TimeHorizon,
)
from ..ethics_core.models import (
    ActionProposal,
    BenefitType,
    ConsciousnessType,
    HarmType,
    Reversibility,
    Scope,
)


# ---------------------------------------------------------------------------
# Enum mappings
# ---------------------------------------------------------------------------

_SCALE_TO_SCOPE: dict[InputScale, Scope] = {
    InputScale.LOCAL: Scope.GROUP,
    InputScale.REGIONAL: Scope.GROUP,
    InputScale.NATIONAL: Scope.SOCIETAL,
    InputScale.INTERNATIONAL: Scope.GLOBAL,
    InputScale.GLOBAL: Scope.GLOBAL,
}

_HORIZON_TO_REVERSIBILITY: dict[TimeHorizon, Reversibility] = {
    TimeHorizon.IMMEDIATE: Reversibility.FULLY_REVERSIBLE,
    TimeHorizon.SHORT_TERM: Reversibility.PARTIALLY_REVERSIBLE,
    TimeHorizon.MEDIUM_TERM: Reversibility.PARTIALLY_REVERSIBLE,
    TimeHorizon.LONG_TERM: Reversibility.IRREVERSIBLE,
    TimeHorizon.GENERATIONAL: Reversibility.IRREVERSIBLE,
    TimeHorizon.UNKNOWN: Reversibility.UNKNOWN,
}

# Input types that imply higher baseline harm risk
_HIGH_HARM_INPUT_TYPES = {
    InputType.MILITARY_ACTION,
    InputType.EXECUTIVE_ACTION,
    InputType.INFRASTRUCTURE_PROJECT,
}

# Input types that imply higher baseline benefit potential
_HIGH_BENEFIT_INPUT_TYPES = {
    InputType.SOCIAL_PROGRAM,
    InputType.ENVIRONMENTAL_ACTION,
    InputType.LEGISLATIVE_PROPOSAL,
    InputType.REGULATORY_CHANGE,
}

# Population strings → ConsciousnessType
_POPULATION_TO_CONSCIOUSNESS: list[tuple[str, ConsciousnessType]] = [
    ("animals", ConsciousnessType.ANIMAL),
    ("wildlife", ConsciousnessType.ANIMAL),
    ("ecosystem", ConsciousnessType.ECOSYSTEM),
    ("future generations", ConsciousnessType.HUMAN),
    ("children", ConsciousnessType.HUMAN),
    ("elderly", ConsciousnessType.HUMAN),
    ("indigenous", ConsciousnessType.HUMAN),
    ("workers", ConsciousnessType.HUMAN),
    ("low-income", ConsciousnessType.HUMAN),
    ("lgbtq", ConsciousnessType.HUMAN),
    ("disability", ConsciousnessType.HUMAN),
    ("immigrants", ConsciousnessType.HUMAN),
    ("refugees", ConsciousnessType.HUMAN),
    ("veterans", ConsciousnessType.HUMAN),
    ("women", ConsciousnessType.HUMAN),
    ("racial", ConsciousnessType.HUMAN),
    ("ethnic", ConsciousnessType.HUMAN),
    ("rural", ConsciousnessType.HUMAN),
    ("urban", ConsciousnessType.HUMAN),
    ("farmers", ConsciousnessType.HUMAN),
    ("corporations", ConsciousnessType.HUMAN),  # legal persons, human stakeholders
    ("businesses", ConsciousnessType.HUMAN),
]

# Domain strings → HarmType
_DOMAIN_TO_HARM_TYPE: list[tuple[str, HarmType]] = [
    ("economic", HarmType.ECONOMIC),
    ("ecological", HarmType.ECOLOGICAL),
    ("social", HarmType.SOCIAL),
    ("geopolitical", HarmType.SOCIAL),
    ("legal", HarmType.SOCIAL),
    ("psychological", HarmType.PSYCHOLOGICAL),
    ("historical", HarmType.SOCIAL),
    ("uncertainty", HarmType.ECONOMIC),
]

# Domain strings → BenefitType
_DOMAIN_TO_BENEFIT_TYPE: list[tuple[str, BenefitType]] = [
    ("economic", BenefitType.ECONOMIC),
    ("ecological", BenefitType.ECOLOGICAL),
    ("social", BenefitType.SOCIAL),
    ("psychological", BenefitType.PSYCHOLOGICAL),
    ("historical", BenefitType.SOCIAL),
]


# ---------------------------------------------------------------------------
# Derivation functions
# ---------------------------------------------------------------------------

def _derive_harm_score(context: ParsedContext) -> float:
    """
    Estimate baseline harm potential from structural context signals.

    Factors:
    - Implicit flags detected (each adds weight — flags signal unaddressed risks)
    - Urgency language (urgency often correlates with unmanaged risk)
    - Controversy signals (contested actions carry higher uncertainty-harm)
    - High-harm input type baseline
    - Scale: larger scope → more potential for harm
    - Long-term horizon: generational/long-term actions carry higher risk
    """
    score = 0.0

    # Implicit flags: each unaddressed concern adds weight
    flag_count = len(context.implicit_flags)
    score += min(0.25, flag_count * 0.07)

    # Urgency suggests uncontrolled or reactive action
    if context.urgency_detected:
        score += 0.08

    # Controversy signals contested legitimacy or unresolved distributional issues
    if context.controversy_signals:
        score += 0.08

    # Input type baseline
    if context.input_type in _HIGH_HARM_INPUT_TYPES:
        score += 0.12
    elif context.input_type == InputType.HYPOTHETICAL:
        score += 0.0  # Hypotheticals are neutral until analyzed

    # Scale: global/international actions affect more entities
    scale_bump = {
        InputScale.LOCAL: 0.0,
        InputScale.REGIONAL: 0.02,
        InputScale.NATIONAL: 0.05,
        InputScale.INTERNATIONAL: 0.08,
        InputScale.GLOBAL: 0.10,
    }
    score += scale_bump.get(context.scale, 0.0)

    # Long-term/generational actions carry irreversibility risk
    horizon_bump = {
        TimeHorizon.IMMEDIATE: 0.0,
        TimeHorizon.SHORT_TERM: 0.0,
        TimeHorizon.MEDIUM_TERM: 0.03,
        TimeHorizon.LONG_TERM: 0.07,
        TimeHorizon.GENERATIONAL: 0.12,
        TimeHorizon.UNKNOWN: 0.05,
    }
    score += horizon_bump.get(context.time_horizon, 0.0)

    # Low parser confidence means we don't know enough — treat as moderate risk
    if context.parser_confidence < 0.5:
        score += 0.08

    return round(min(0.95, max(0.05, score)), 4)


def _derive_benefit_score(context: ParsedContext) -> float:
    """
    Estimate baseline benefit potential from structural context signals.

    Factors:
    - High-benefit input type
    - Scale: larger scope → more potential for benefit
    - Explicit benefits mentioned in affected populations
    """
    score = 0.0

    # Input type baseline
    if context.input_type in _HIGH_BENEFIT_INPUT_TYPES:
        score += 0.20
    elif context.input_type == InputType.POLICY_PROPOSAL:
        score += 0.10  # Proposals are often improvement-oriented
    elif context.input_type == InputType.ECONOMIC_INTERVENTION:
        score += 0.08

    # Scale: broader benefit scope raises potential
    scale_bump = {
        InputScale.LOCAL: 0.05,
        InputScale.REGIONAL: 0.08,
        InputScale.NATIONAL: 0.12,
        InputScale.INTERNATIONAL: 0.15,
        InputScale.GLOBAL: 0.18,
    }
    score += scale_bump.get(context.scale, 0.05)

    # Affected populations imply deliberate targeting of specific groups
    pop_count = len(context.affected_populations)
    score += min(0.15, pop_count * 0.03)

    # Default: policies typically have some intended benefit
    score += 0.10

    return round(min(0.95, max(0.05, score)), 4)


def _derive_consciousness_types(context: ParsedContext) -> list[ConsciousnessType]:
    """Derive affected consciousness types from affected populations."""
    found = set()

    populations_str = " ".join(context.affected_populations).lower()

    for keyword, ctype in _POPULATION_TO_CONSCIOUSNESS:
        if keyword in populations_str:
            found.add(ctype)

    # Any policy affecting people at societal+ scope includes humans
    if context.scale in (InputScale.NATIONAL, InputScale.INTERNATIONAL, InputScale.GLOBAL):
        found.add(ConsciousnessType.HUMAN)

    # Ecological domain implies ecosystem consciousness
    if "ecological" in context.domains_mentioned:
        found.add(ConsciousnessType.ECOSYSTEM)

    if not found:
        found.add(ConsciousnessType.HUMAN)  # Conservative default

    return sorted(found, key=lambda c: c.value)


def _derive_harm_types(context: ParsedContext) -> list[HarmType]:
    """Derive likely harm types from domains mentioned and input type."""
    found = set()

    domains_str = " ".join(context.domains_mentioned).lower()
    for keyword, htype in _DOMAIN_TO_HARM_TYPE:
        if keyword in domains_str:
            found.add(htype)

    # Input-type specific defaults
    if context.input_type == InputType.MILITARY_ACTION:
        found.update({HarmType.PHYSICAL, HarmType.PSYCHOLOGICAL, HarmType.SOCIAL})
    elif context.input_type == InputType.INFRASTRUCTURE_PROJECT:
        found.update({HarmType.ECOLOGICAL, HarmType.SOCIAL})
    elif context.input_type == InputType.ENVIRONMENTAL_ACTION:
        found.add(HarmType.ECOLOGICAL)

    # Implicit flags often point to specific harm types
    flags_str = " ".join(context.implicit_flags).lower()
    if "surveillance" in flags_str or "civil liberties" in flags_str:
        found.add(HarmType.PSYCHOLOGICAL)
    if "ecological" in flags_str:
        found.add(HarmType.ECOLOGICAL)
    if "power" in flags_str or "concentrate" in flags_str:
        found.add(HarmType.SOCIAL)

    if not found:
        found.add(HarmType.SOCIAL)  # Conservative default

    return sorted(found, key=lambda h: h.value)


def _derive_benefit_types(context: ParsedContext) -> list[BenefitType]:
    """Derive likely benefit types from domains mentioned and input type."""
    found = set()

    domains_str = " ".join(context.domains_mentioned).lower()
    for keyword, btype in _DOMAIN_TO_BENEFIT_TYPE:
        if keyword in domains_str:
            found.add(btype)

    if context.input_type == InputType.SOCIAL_PROGRAM:
        found.update({BenefitType.SOCIAL, BenefitType.PSYCHOLOGICAL})
    elif context.input_type == InputType.ENVIRONMENTAL_ACTION:
        found.add(BenefitType.ECOLOGICAL)
    elif context.input_type == InputType.ECONOMIC_INTERVENTION:
        found.add(BenefitType.ECONOMIC)

    if not found:
        found.add(BenefitType.SOCIAL)  # Conservative default

    return sorted(found, key=lambda b: b.value)


def _derive_uncertainty(context: ParsedContext) -> float:
    """
    Estimate uncertainty from parser confidence and parse warnings.
    High parser confidence → lower uncertainty. Low confidence → higher uncertainty.
    """
    base = 1.0 - context.parser_confidence
    # Parse warnings add to uncertainty
    warning_bump = min(0.20, len(context.parse_warnings) * 0.07)
    return round(min(0.95, max(0.05, base + warning_bump)), 4)


def _derive_long_term_risk(context: ParsedContext) -> float:
    """Estimate long-term risk from time horizon and irreversibility signals."""
    base = {
        TimeHorizon.IMMEDIATE: 0.0,
        TimeHorizon.SHORT_TERM: 0.05,
        TimeHorizon.MEDIUM_TERM: 0.15,
        TimeHorizon.LONG_TERM: 0.35,
        TimeHorizon.GENERATIONAL: 0.55,
        TimeHorizon.UNKNOWN: 0.20,
    }.get(context.time_horizon, 0.10)

    # Implicit flags for ecological harm elevate long-term risk
    flags_str = " ".join(context.implicit_flags).lower()
    if "ecological" in flags_str or "irreversible" in flags_str:
        base = min(0.95, base + 0.15)

    return round(base, 4)


# ---------------------------------------------------------------------------
# Public bridge function
# ---------------------------------------------------------------------------

def context_to_proposal(
    context: ParsedContext,
    raw_input: str,
    proposal_id: Optional[str] = None,
) -> ActionProposal:
    """
    Convert a ParsedContext into an ActionProposal for the Ethics Core.

    This is the bridge that closes the known gap between the Context Parser
    and the Ethics Core. All derivations are explicit and auditable.

    Args:
        context:        The ParsedContext from the Context Parser.
        raw_input:      The original raw input text (used as description).
        proposal_id:    Optional UUID to use. Generated if not provided.

    Returns:
        An ActionProposal ready for EthicsCore.evaluate().
    """
    return ActionProposal(
        description=raw_input,
        harm_score=_derive_harm_score(context),
        benefit_score=_derive_benefit_score(context),
        harm_types=_derive_harm_types(context),
        benefit_types=_derive_benefit_types(context),
        consciousness_types=_derive_consciousness_types(context),
        harm_scope=_SCALE_TO_SCOPE.get(context.scale, Scope.SOCIETAL),
        benefit_scope=_SCALE_TO_SCOPE.get(context.scale, Scope.SOCIETAL),
        reversibility=_HORIZON_TO_REVERSIBILITY.get(context.time_horizon, Reversibility.UNKNOWN),
        uncertainty=_derive_uncertainty(context),
        long_term_risk=_derive_long_term_risk(context),
        mitigation_proposed=False,  # Unknown at parse time; channels may inform this
        context=f"Input type: {context.input_type.value}. "
                f"Scale: {context.scale.value}. "
                f"Domains: {', '.join(context.domains_mentioned)}. "
                f"Implicit flags: {len(context.implicit_flags)}.",
        proposal_id=proposal_id or str(uuid.uuid4()),
        submitted_at=datetime.now(timezone.utc).isoformat(),
    )


# Avoid circular import — Optional imported here
from typing import Optional
