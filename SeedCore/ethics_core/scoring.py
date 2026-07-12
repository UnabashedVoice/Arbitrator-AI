"""
scoring.py — Weighted scoring logic for the Arbitrator Ethics Core.

The raw harm and benefit scores submitted with a proposal are adjusted by
a series of multipliers that reflect the ethical weight assigned by the
Prime Directive. The resulting weighted scores are what the truth table
and verdict engine operate on.

Weighting hierarchy (from the Prime Directive):
    1. Consciousness weight  — actions affecting conscious entities receive
                               stricter scrutiny; the weight amplifies harm scores.
    2. Scope weight          — mutual/collective impacts outweigh individual impacts.
    3. Reversibility weight  — irreversible harms are weighted more heavily.
    4. Uncertainty penalty   — high uncertainty reduces confidence in benefit scores.
    5. Long-term risk weight — catastrophic tail risks amplify harm scores.
"""

from __future__ import annotations

from .models import (
    ActionProposal,
    ConsciousnessType,
    Reversibility,
    Scope,
)


# ---------------------------------------------------------------------------
# Consciousness weight
# ---------------------------------------------------------------------------

# Maps each ConsciousnessType to a harm amplification multiplier.
# Higher values mean harm to this type of entity is weighted more heavily.
CONSCIOUSNESS_HARM_WEIGHTS: dict[ConsciousnessType, float] = {
    ConsciousnessType.HUMAN: 1.5,
    ConsciousnessType.ANIMAL: 1.3,
    ConsciousnessType.ECOSYSTEM: 1.2,
    ConsciousnessType.SYNTHETIC: 1.2,
    ConsciousnessType.UNRECOGNIZED: 1.4,   # Extra caution for unknown consciousness
    ConsciousnessType.NONE: 1.0,
}


def compute_consciousness_weight(proposal: ActionProposal) -> float:
    """
    Return the maximum harm multiplier across all consciousness types affected.

    If multiple consciousness types are affected, we use the maximum weight
    (most conservative / protective) rather than averaging.

    If no consciousness types are specified, we default to 1.0 (neutral).
    """
    if not proposal.consciousness_types:
        return 1.0
    return max(
        CONSCIOUSNESS_HARM_WEIGHTS.get(ct, 1.0)
        for ct in proposal.consciousness_types
    )


# ---------------------------------------------------------------------------
# Scope weights
# ---------------------------------------------------------------------------

# Maps each Scope to a multiplier for harm and benefit.
# Broader scope = higher weight, reflecting the Prime Directive's emphasis
# on collective wellbeing over individual outcomes.
SCOPE_WEIGHTS: dict[Scope, float] = {
    Scope.INDIVIDUAL: 1.0,
    Scope.GROUP: 1.2,
    Scope.SOCIETAL: 1.5,
    Scope.GLOBAL: 1.8,
    Scope.INTERGENERATIONAL: 2.0,
}


def compute_scope_weight(scope: Scope) -> float:
    """Return the weight multiplier for a given scope."""
    return SCOPE_WEIGHTS.get(scope, 1.0)


# ---------------------------------------------------------------------------
# Reversibility weight
# ---------------------------------------------------------------------------

REVERSIBILITY_HARM_MULTIPLIERS: dict[Reversibility, float] = {
    Reversibility.FULLY_REVERSIBLE: 0.8,       # Reversible harms discounted slightly
    Reversibility.PARTIALLY_REVERSIBLE: 1.0,
    Reversibility.IRREVERSIBLE: 1.6,            # Irreversible harms amplified significantly
    Reversibility.UNKNOWN: 1.2,                 # Unknown reversibility → precautionary bump
}


def compute_reversibility_weight(proposal: ActionProposal) -> float:
    """Return the harm multiplier for the proposal's reversibility."""
    return REVERSIBILITY_HARM_MULTIPLIERS.get(proposal.reversibility, 1.0)


# ---------------------------------------------------------------------------
# Uncertainty and long-term risk adjustments
# ---------------------------------------------------------------------------

def compute_uncertainty_confidence_penalty(proposal: ActionProposal) -> float:
    """
    Return a penalty factor [0.0, 1.0] that reduces the confidence score
    based on uncertainty and long-term risk.

    High uncertainty means we cannot trust benefit estimates as much.
    High long-term risk amplifies the concern further.

    Returns a value in [0.0, 1.0] where 1.0 means no penalty.
    """
    # Base confidence starts at 1.0, reduced by uncertainty
    base_penalty = 1.0 - (proposal.uncertainty * 0.4)   # uncertainty up to 0.4 reduction

    # Further reduced by long-term risk
    risk_penalty = 1.0 - (proposal.long_term_risk * 0.3)  # long_term_risk up to 0.3 reduction

    return max(0.1, base_penalty * risk_penalty)   # Never below 0.1


def compute_long_term_risk_harm_bump(proposal: ActionProposal) -> float:
    """
    Return an additive bump to the harm score based on long-term risk.

    Long-term catastrophic risk that has not been accounted for in the
    raw harm score should increase the effective harm seen by the truth table.
    """
    return proposal.long_term_risk * 0.2   # Up to +0.2 added to harm


# ---------------------------------------------------------------------------
# Master scoring function
# ---------------------------------------------------------------------------

def compute_weighted_scores(proposal: ActionProposal) -> dict:
    """
    Apply all weights and return a dict of all intermediate and final scores.

    This is the single entry point for the scoring subsystem. The returned
    dict is used by the truth table and is fully included in the audit log.

    Returns:
        {
            "consciousness_weight": float,
            "scope_weight_harm": float,
            "scope_weight_benefit": float,
            "reversibility_weight": float,
            "long_term_risk_bump": float,
            "uncertainty_confidence_penalty": float,
            "weighted_harm": float,       # clamped to [0.0, 1.0]
            "weighted_benefit": float,    # clamped to [0.0, 1.0]
            "net_score": float,           # weighted_benefit - weighted_harm
            "confidence": float,          # [0.1, 1.0]
        }
    """
    c_weight = compute_consciousness_weight(proposal)
    s_weight_harm = compute_scope_weight(proposal.harm_scope)
    s_weight_benefit = compute_scope_weight(proposal.benefit_scope)
    r_weight = compute_reversibility_weight(proposal)
    lt_bump = compute_long_term_risk_harm_bump(proposal)
    conf_penalty = compute_uncertainty_confidence_penalty(proposal)

    # Weighted harm: raw harm amplified by consciousness, scope, and reversibility weights,
    # plus the long-term risk bump. Clamped to [0.0, 1.0].
    raw_harm_amplified = (proposal.harm_score * c_weight * s_weight_harm * r_weight) + lt_bump
    weighted_harm = min(1.0, raw_harm_amplified)

    # Weighted benefit: raw benefit amplified by scope weight only.
    # Benefit does not receive consciousness or reversibility amplification —
    # we are deliberately more cautious about benefit than harm.
    raw_benefit_amplified = proposal.benefit_score * s_weight_benefit
    weighted_benefit = min(1.0, raw_benefit_amplified)

    net_score = weighted_benefit - weighted_harm

    return {
        "consciousness_weight": c_weight,
        "scope_weight_harm": s_weight_harm,
        "scope_weight_benefit": s_weight_benefit,
        "reversibility_weight": r_weight,
        "long_term_risk_bump": round(lt_bump, 4),
        "uncertainty_confidence_penalty": round(conf_penalty, 4),
        "weighted_harm": round(weighted_harm, 4),
        "weighted_benefit": round(weighted_benefit, 4),
        "net_score": round(net_score, 4),
        "confidence": round(conf_penalty, 4),
    }
