"""
truth_table.py — Truth table and verdict engine for the Arbitrator Ethics Core.

This module takes the weighted scores produced by scoring.py and applies the
ethical truth table defined in the architecture document to produce a Verdict,
justification, flags, and mitigation requirements.

The truth table logic is deliberately transparent and auditable. Every decision
path is documented. There are no hidden rules.

Truth table summary (operating on weighted scores):
    | Weighted Harm | Weighted Benefit | Net Score  | Verdict     |
    |---------------|------------------|------------|-------------|
    | Low  (< 0.3)  | High (>= 0.6)    | Positive   | PASS        |
    | Low  (< 0.3)  | Any              | Any        | PASS        |
    | High (>= 0.7) | Any              | Any        | FAIL        |
    | Med  (0.3-0.7)| High (>= 0.7)    | Positive   | PASS (w/note)|
    | Med  (0.3-0.7)| Med  (0.3-0.7)   | Near zero  | AMBIGUOUS   |
    | Any           | Any              | Strongly - | FAIL        |
    | Escalation conditions (see ESCALATE logic below)             |

    Hard constraints are evaluated BEFORE this table and short-circuit to
    HARD_REJECT if triggered. This table only runs if no hard constraints fire.
"""

from __future__ import annotations

from .models import (
    ActionProposal,
    ConsciousnessType,
    HarmType,
    Reversibility,
    Scope,
    Verdict,
)


# ---------------------------------------------------------------------------
# Thresholds — all in one place for auditability and easy adjustment
# ---------------------------------------------------------------------------

# Harm thresholds
HARM_LOW = 0.3       # Below this: harm is low
HARM_HIGH = 0.65     # Above this: harm is high

# Benefit thresholds
BENEFIT_LOW = 0.3    # Below this: benefit is low
BENEFIT_HIGH = 0.6   # Above this: benefit is high (enough to offset moderate harm)
BENEFIT_VERY_HIGH = 0.7  # High enough to offset moderate harm with mitigation

# Net score thresholds
NET_STRONGLY_NEGATIVE = -0.25   # Below this: action is net harmful regardless of scores
NET_AMBIGUOUS_BAND = 0.15       # |net_score| within this: ambiguous zone

# Escalation thresholds
ESCALATE_CONSCIOUSNESS_WEIGHT = 1.4   # Consciousness weight >= this → escalate
ESCALATE_HARM_FOR_ESCALATION = 0.5    # Weighted harm must also be >= this to escalate


# ---------------------------------------------------------------------------
# Flag generators — produce human-readable warning strings
# ---------------------------------------------------------------------------

def _generate_flags(
    proposal: ActionProposal,
    scores: dict,
) -> list[str]:
    """Produce a list of specific concern flags for the evaluation output."""
    flags = []

    if proposal.reversibility == Reversibility.IRREVERSIBLE:
        flags.append("Harm is irreversible — cannot be undone if action proceeds.")

    if proposal.reversibility == Reversibility.UNKNOWN:
        flags.append("Reversibility is unknown — precautionary weight applied.")

    if proposal.uncertainty >= 0.7:
        flags.append(
            f"High uncertainty ({proposal.uncertainty:.0%}) — benefit estimates are unreliable. "
            "Confidence in this evaluation is reduced."
        )

    if proposal.long_term_risk >= 0.6:
        flags.append(
            f"Long-term catastrophic risk is elevated ({proposal.long_term_risk:.0%}). "
            "Tail-risk scenarios should be modeled before proceeding."
        )

    if ConsciousnessType.UNRECOGNIZED in proposal.consciousness_types:
        flags.append(
            "Action may affect forms of consciousness not yet recognized or understood. "
            "Extra caution is warranted per the Prime Directive."
        )

    if HarmType.EXISTENTIAL in proposal.harm_types:
        flags.append(
            "Existential harm type detected. Even at low probability, "
            "existential risks receive maximum scrutiny."
        )

    if (
        proposal.harm_scope in (Scope.INTERGENERATIONAL,)
        or proposal.benefit_scope in (Scope.INTERGENERATIONAL,)
    ):
        flags.append(
            "Action has intergenerational scope — effects extend to future generations "
            "who cannot consent or respond."
        )

    if (
        proposal.harm_scope in (Scope.SOCIETAL, Scope.GLOBAL, Scope.INTERGENERATIONAL)
        and proposal.benefit_scope in (Scope.INDIVIDUAL, Scope.GROUP)
    ):
        flags.append(
            "Harm scope significantly exceeds benefit scope. Many bear cost; few receive benefit. "
            "Structural imbalance flagged."
        )

    if proposal.harm_score > 0 and not proposal.mitigation_proposed:
        flags.append(
            "No mitigation has been proposed for the identified harm. "
            "Mitigation planning is expected for any action with non-zero harm."
        )

    return flags


# ---------------------------------------------------------------------------
# Mitigation requirements generator
# ---------------------------------------------------------------------------

def _generate_mitigation_notes(
    proposal: ActionProposal,
    scores: dict,
    verdict: Verdict,
) -> tuple[bool, list[str]]:
    """
    Determine whether mitigation is required and what form it should take.

    Returns:
        (mitigation_required: bool, mitigation_notes: list[str])
    """
    notes = []
    required = False

    if verdict in (Verdict.HARD_REJECT, Verdict.FAIL):
        # For rejected actions, mitigation notes explain what would need to change
        required = True
        if scores["weighted_harm"] >= HARM_HIGH:
            notes.append(
                "Substantial reduction in harm score required. "
                "Current harm level cannot be offset by benefit alone."
            )
        if proposal.reversibility == Reversibility.IRREVERSIBLE:
            notes.append(
                "Irreversibility is a major factor in this rejection. "
                "Consider redesigning the action to allow reversal or staged implementation."
            )
        if HarmType.EXISTENTIAL in proposal.harm_types:
            notes.append(
                "Existential harm type must be removed or reduced to non-existential "
                "before re-evaluation is possible."
            )

    elif verdict == Verdict.PASS and scores["weighted_harm"] > 0.0:
        # Pass with non-zero harm: mitigation expected but not blocking
        required = True
        notes.append(
            "Action passes the Ethics Core but carries non-zero harm. "
            "A mitigation plan is required before implementation."
        )
        if not proposal.mitigation_proposed:
            notes.append(
                "No mitigation has been proposed. Submit a mitigation plan "
                "addressing identified harm types before proceeding."
            )

    elif verdict == Verdict.AMBIGUOUS:
        required = True
        notes.append(
            "Ambiguous verdict requires human review before any decision. "
            "Mitigation plan addressing all identified harm types must be part of review."
        )

    elif verdict == Verdict.ESCALATE:
        required = True
        notes.append(
            "Escalated verdict requires human ratification. "
            "Full consequence mapping and independent ethics review required before ratification."
        )

    return required, notes


# ---------------------------------------------------------------------------
# Core truth table function
# ---------------------------------------------------------------------------

def apply_truth_table(
    proposal: ActionProposal,
    scores: dict,
) -> tuple[Verdict, str, list[str], bool, list[str]]:
    """
    Apply the ethical truth table to weighted scores and return a verdict.

    This function assumes hard constraints have already been evaluated and
    did not trigger. If they had, HARD_REJECT would have been returned
    before reaching this function.

    Args:
        proposal:   The ActionProposal being evaluated.
        scores:     The dict returned by compute_weighted_scores().

    Returns:
        (verdict, justification, flags, mitigation_required, mitigation_notes)
    """
    wh = scores["weighted_harm"]
    wb = scores["weighted_benefit"]
    net = scores["net_score"]
    cw = scores["consciousness_weight"]

    flags = _generate_flags(proposal, scores)
    verdict: Verdict
    justification: str

    # --- ESCALATE check ---
    # High-magnitude consciousness impact with significant harm → human ratification required
    if (
        cw >= ESCALATE_CONSCIOUSNESS_WEIGHT
        and wh >= ESCALATE_HARM_FOR_ESCALATION
    ):
        verdict = Verdict.ESCALATE
        justification = (
            f"Action significantly affects high-weight conscious entities "
            f"(consciousness weight: {cw:.2f}) with substantial harm "
            f"(weighted harm: {wh:.2f}). Per the Prime Directive, actions at this "
            f"intersection require human ratification before proceeding. "
            f"This is not a rejection — it is a requirement for deliberate, "
            f"informed human decision-making."
        )

    # --- FAIL: strongly negative net score ---
    elif net <= NET_STRONGLY_NEGATIVE:
        verdict = Verdict.FAIL
        justification = (
            f"Action produces a strongly negative net score ({net:.2f}). "
            f"Weighted harm ({wh:.2f}) substantially exceeds weighted benefit ({wb:.2f}). "
            f"The Prime Directive requires that harm be minimized and mitigated. "
            f"This action cannot be recommended in its current form."
        )

    # --- FAIL: high harm regardless of benefit ---
    elif wh >= HARM_HIGH:
        verdict = Verdict.FAIL
        justification = (
            f"Weighted harm score ({wh:.2f}) exceeds the high-harm threshold ({HARM_HIGH}). "
            f"High harm cannot be offset by benefit alone under the Ethics Core. "
            f"The Prime Directive requires harm to be minimized before benefit is considered. "
            f"Substantial redesign or harm reduction is required."
        )

    # --- PASS: low harm ---
    elif wh < HARM_LOW:
        verdict = Verdict.PASS
        if wb >= BENEFIT_HIGH:
            justification = (
                f"Action passes the Ethics Core. Weighted harm is low ({wh:.2f}) "
                f"and weighted benefit is high ({wb:.2f}), producing a positive net score "
                f"({net:.2f}). This action is broadly consistent with the Prime Directive."
            )
        else:
            justification = (
                f"Action passes the Ethics Core. Weighted harm is low ({wh:.2f}). "
                f"Weighted benefit ({wb:.2f}) is modest but the harm profile does not "
                f"raise concerns under the Prime Directive. Net score: {net:.2f}."
            )

    # --- PASS with note: moderate harm, high benefit, positive net ---
    elif HARM_LOW <= wh < HARM_HIGH and wb >= BENEFIT_VERY_HIGH and net > 0:
        verdict = Verdict.PASS
        justification = (
            f"Action passes the Ethics Core with conditions. Weighted harm is moderate "
            f"({wh:.2f}) but weighted benefit is high ({wb:.2f}), producing a positive "
            f"net score ({net:.2f}). Mitigation of identified harms is required before "
            f"implementation. The balance is acceptable under the Prime Directive provided "
            f"harm mitigation is actively pursued."
        )

    # --- AMBIGUOUS: moderate harm, moderate benefit, near-zero net ---
    elif (
        HARM_LOW <= wh < HARM_HIGH
        and BENEFIT_LOW <= wb < BENEFIT_VERY_HIGH
        and abs(net) <= NET_AMBIGUOUS_BAND
    ):
        verdict = Verdict.AMBIGUOUS
        justification = (
            f"Action produces an ambiguous result. Weighted harm ({wh:.2f}) and weighted "
            f"benefit ({wb:.2f}) are in balance, with a near-zero net score ({net:.2f}). "
            f"The Ethics Core cannot confidently recommend or reject this action. "
            f"Human review is required. The full consequence map, adversarial simulations, "
            f"and stakeholder perspectives must be considered before a decision is made."
        )

    # --- FAIL: moderate harm, insufficient benefit ---
    elif HARM_LOW <= wh < HARM_HIGH and wb < BENEFIT_LOW:
        verdict = Verdict.FAIL
        justification = (
            f"Action produces moderate harm ({wh:.2f}) with low benefit ({wb:.2f}), "
            f"resulting in a negative net score ({net:.2f}). The harm is not sufficiently "
            f"offset by benefit. The Prime Directive requires that harm be minimized; "
            f"this action does not meet that standard in its current form."
        )

    # --- Catch-all AMBIGUOUS for cases not clearly covered above ---
    else:
        verdict = Verdict.AMBIGUOUS
        justification = (
            f"Action does not fall cleanly into a pass or fail category "
            f"(weighted harm: {wh:.2f}, weighted benefit: {wb:.2f}, net: {net:.2f}). "
            f"Human review is required to resolve the ambiguity."
        )

    mitigation_required, mitigation_notes = _generate_mitigation_notes(
        proposal, scores, verdict
    )

    return verdict, justification, flags, mitigation_required, mitigation_notes
