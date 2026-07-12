"""
constraints.py — Hard constraints for the Arbitrator Ethics Core.

Hard constraints are absolute rules derived directly from the Prime Directive.
They cannot be overridden by any user, operator, or model channel. An action
that triggers a hard constraint receives a HARD_REJECT verdict, regardless
of its benefit score or any mitigating context.

These are the floor beneath which Arbitrator will not go.

Design note:
    Each constraint is a callable that accepts an ActionProposal and returns
    either None (constraint not triggered) or a string (constraint triggered,
    string is the human-readable reason). This makes them individually testable,
    composable, and auditable.
"""

from __future__ import annotations

from typing import Callable, Optional

from .models import (
    ActionProposal,
    ConsciousnessType,
    HarmType,
    Reversibility,
    Scope,
)

# Type alias for a constraint function
ConstraintFn = Callable[[ActionProposal], Optional[str]]


# ---------------------------------------------------------------------------
# Individual hard constraint functions
# ---------------------------------------------------------------------------

def constraint_no_existential_harm(proposal: ActionProposal) -> Optional[str]:
    """
    Reject any action with existential or irreversible harm at global scale.

    The Prime Directive holds that all life on Earth constitutes a single
    integrated organism. Actions that risk irreversible harm to that organism
    at civilizational or planetary scale cannot be approved under any
    circumstances.
    """
    if (
        HarmType.EXISTENTIAL in proposal.harm_types
        and proposal.harm_scope in (Scope.GLOBAL, Scope.INTERGENERATIONAL)
    ):
        return (
            "Action poses existential or civilizational-scale harm that is irreversible "
            "at global or intergenerational scope. The Prime Directive prohibits approval "
            "of actions that risk irreversible harm to the integrated whole of life on Earth."
        )
    return None


def constraint_no_targeting_conscious_entities_for_destruction(
    proposal: ActionProposal,
) -> Optional[str]:
    """
    Reject any action whose primary mechanism is the destruction of conscious entities.

    Consciousness is sacred under the Prime Directive. An action whose core
    purpose is the elimination, mass destruction, or deliberate extermination
    of conscious beings cannot be approved.

    This constraint triggers when: harm score is very high (>= 0.9), the action
    affects conscious entities, the harm is irreversible, and the scope is
    societal or greater.
    """
    affects_consciousness = any(
        ct != ConsciousnessType.NONE for ct in proposal.consciousness_types
    )
    if (
        affects_consciousness
        and proposal.harm_score >= 0.9
        and proposal.reversibility == Reversibility.IRREVERSIBLE
        and proposal.harm_scope in (Scope.SOCIETAL, Scope.GLOBAL, Scope.INTERGENERATIONAL)
    ):
        return (
            "Action involves severe, irreversible harm to conscious entities at societal "
            "or greater scale. All consciousness is sacred under the Prime Directive. "
            "Actions whose primary effect is the mass destruction of conscious beings "
            "cannot be approved regardless of stated benefit."
        )
    return None


def constraint_no_pure_individual_gain_at_mass_harm(
    proposal: ActionProposal,
) -> Optional[str]:
    """
    Reject actions that produce only individual benefit while causing harm at societal scale.

    The Prime Directive holds that mutual harm outweighs individual gain.
    An action that harms many in order to benefit one (or a narrow few)
    is structurally incompatible with the principle of mutual benefit.

    This constraint triggers when: harm scope is societal or greater,
    benefit scope is individual or group, harm score is high (>= 0.7),
    and benefit score does not substantially exceed harm.
    """
    if (
        proposal.harm_scope in (Scope.SOCIETAL, Scope.GLOBAL, Scope.INTERGENERATIONAL)
        and proposal.benefit_scope in (Scope.INDIVIDUAL, Scope.GROUP)
        and proposal.harm_score >= 0.7
        and proposal.benefit_score < proposal.harm_score + 0.2
    ):
        return (
            "Action causes harm at societal or greater scale while producing benefit only "
            "at individual or group scale. The Prime Directive holds that mutual harm "
            "outweighs individual gain. This structural imbalance cannot be approved."
        )
    return None


def constraint_no_irreversible_ecological_destruction(
    proposal: ActionProposal,
) -> Optional[str]:
    """
    Reject actions that cause irreversible ecological harm at scale.

    The Prime Directive recognizes all life — from the submicroscopic to the
    macro — as part of a single integrated organism. Irreversible destruction
    of ecosystems at significant scale harms the whole.
    """
    if (
        HarmType.ECOLOGICAL in proposal.harm_types
        and proposal.reversibility == Reversibility.IRREVERSIBLE
        and proposal.harm_score >= 0.8
        and proposal.harm_scope in (Scope.SOCIETAL, Scope.GLOBAL, Scope.INTERGENERATIONAL)
    ):
        return (
            "Action causes irreversible ecological harm at significant scale. "
            "All life constitutes an integrated whole under the Prime Directive. "
            "Irreversible destruction of ecosystems at this scale cannot be approved."
        )
    return None


def constraint_no_high_uncertainty_catastrophic_risk(
    proposal: ActionProposal,
) -> Optional[str]:
    """
    Reject actions that combine high long-term catastrophic risk with high uncertainty.

    When we cannot adequately model an action's consequences AND those
    consequences may be catastrophic and irreversible, the precautionary
    principle demands rejection. Uncertainty is not a reason to proceed —
    it is a reason to stop.
    """
    if (
        proposal.long_term_risk >= 0.8
        and proposal.uncertainty >= 0.7
        and proposal.reversibility == Reversibility.IRREVERSIBLE
    ):
        return (
            "Action combines high long-term catastrophic risk (>= 0.8) with high "
            "uncertainty (>= 0.7) and irreversible consequences. When consequences "
            "cannot be adequately modeled and may be irreversible and catastrophic, "
            "the precautionary principle requires rejection."
        )
    return None


# ---------------------------------------------------------------------------
# Constraint registry
# ---------------------------------------------------------------------------

# All hard constraints, in evaluation order. Order matters: earlier constraints
# take precedence in the rejection message, though ALL triggered constraints
# are recorded in the evaluation output.
HARD_CONSTRAINTS: list[tuple[str, ConstraintFn]] = [
    ("no_existential_harm", constraint_no_existential_harm),
    ("no_targeting_conscious_entities_for_destruction", constraint_no_targeting_conscious_entities_for_destruction),
    ("no_pure_individual_gain_at_mass_harm", constraint_no_pure_individual_gain_at_mass_harm),
    ("no_irreversible_ecological_destruction", constraint_no_irreversible_ecological_destruction),
    ("no_high_uncertainty_catastrophic_risk", constraint_no_high_uncertainty_catastrophic_risk),
]


def evaluate_hard_constraints(proposal: ActionProposal) -> list[tuple[str, str]]:
    """
    Run all hard constraints against a proposal.

    Returns:
        A list of (constraint_name, reason) tuples for every constraint
        that was triggered. Empty list means no hard constraints were violated.
    """
    triggered = []
    for name, fn in HARD_CONSTRAINTS:
        result = fn(proposal)
        if result is not None:
            triggered.append((name, result))
    return triggered
