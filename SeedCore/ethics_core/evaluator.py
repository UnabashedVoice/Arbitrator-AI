"""
evaluator.py — The Arbitrator Ethics Core.

This is the single public entry point for the Ethics Core. External callers
(the routing layer, tests, the CLI) interact only with this module.

Usage:
    from ethics_core.evaluator import EthicsCore
    from ethics_core.models import ActionProposal, ConsciousnessType, HarmType, Scope, Reversibility

    core = EthicsCore()
    proposal = ActionProposal(
        description="Example policy proposal",
        harm_score=0.2,
        benefit_score=0.8,
        consciousness_types=[ConsciousnessType.HUMAN],
        harm_scope=Scope.INDIVIDUAL,
        benefit_scope=Scope.SOCIETAL,
    )
    evaluation = core.evaluate(proposal)
    print(evaluation.verdict)
    print(evaluation.justification)

The EthicsCore class is stateless — it holds no mutable state between evaluations.
Every evaluation is independent and fully self-contained.
"""

from __future__ import annotations

import json

from .constraints import evaluate_hard_constraints
from .models import ActionProposal, EthicsEvaluation, Verdict
from .scoring import compute_weighted_scores
from .truth_table import apply_truth_table


class EthicsCore:
    """
    The Arbitrator Ethics Core.

    Implements the Prime Directive as executable logic. Evaluates any
    ActionProposal against the full ethical framework and returns a
    complete, auditable EthicsEvaluation.

    Pipeline:
        1. Validate input (handled by ActionProposal.__post_init__)
        2. Evaluate hard constraints — if any trigger, return HARD_REJECT
        3. Compute weighted scores
        4. Apply truth table to produce verdict
        5. Assemble and return EthicsEvaluation

    The EthicsCore is intentionally stateless. It holds no memory of
    previous evaluations. Logging and persistence are the responsibility
    of the caller.
    """

    def evaluate(self, proposal: ActionProposal) -> EthicsEvaluation:
        """
        Evaluate a proposal against the Prime Directive.

        Args:
            proposal: A fully constructed ActionProposal.

        Returns:
            An EthicsEvaluation containing the verdict, justification,
            scores, flags, and mitigation requirements.
        """
        # --- Stage 1: Hard constraints ---
        triggered_constraints = evaluate_hard_constraints(proposal)

        if triggered_constraints:
            constraint_names = [name for name, _ in triggered_constraints]
            reasons = [reason for _, reason in triggered_constraints]
            justification = (
                "HARD REJECT — One or more hard constraints derived from the Prime "
                "Directive have been triggered. These constraints are absolute and "
                "cannot be overridden by benefit scores, mitigating context, or "
                "operator configuration.\n\n"
                + "\n\n".join(f"[{name}] {reason}" for name, reason in triggered_constraints)
            )
            return EthicsEvaluation(
                proposal_id=proposal.proposal_id,
                verdict=Verdict.HARD_REJECT,
                justification=justification,
                hard_constraints_triggered=constraint_names,
                weighted_harm=0.0,   # Not computed — hard reject short-circuits scoring
                weighted_benefit=0.0,
                net_score=0.0,
                consciousness_weight=1.0,
                scope_weight_harm=1.0,
                scope_weight_benefit=1.0,
                mitigation_required=True,
                mitigation_notes=[
                    "This action has been hard-rejected. It cannot be approved in its "
                    "current form. To be reconsidered, the action must be fundamentally "
                    "redesigned to eliminate the conditions that triggered the hard constraints."
                ],
                flags=[f"Hard constraint triggered: {name}" for name in constraint_names],
                confidence=1.0,   # We are fully confident in hard rejects
            )

        # --- Stage 2: Weighted scoring ---
        scores = compute_weighted_scores(proposal)

        # --- Stage 3: Truth table ---
        verdict, justification, flags, mitigation_required, mitigation_notes = apply_truth_table(
            proposal, scores
        )

        # --- Stage 4: Assemble evaluation ---
        return EthicsEvaluation(
            proposal_id=proposal.proposal_id,
            verdict=verdict,
            justification=justification,
            hard_constraints_triggered=[],
            weighted_harm=scores["weighted_harm"],
            weighted_benefit=scores["weighted_benefit"],
            net_score=scores["net_score"],
            consciousness_weight=scores["consciousness_weight"],
            scope_weight_harm=scores["scope_weight_harm"],
            scope_weight_benefit=scores["scope_weight_benefit"],
            mitigation_required=mitigation_required,
            mitigation_notes=mitigation_notes,
            flags=flags,
            confidence=scores["confidence"],
        )

    def evaluate_and_serialize(self, proposal: ActionProposal) -> str:
        """
        Evaluate a proposal and return the result as a JSON string.

        This is the form used by the audit log and any downstream consumer
        that needs a serializable representation of the evaluation.
        """
        evaluation = self.evaluate(proposal)
        output = {
            "proposal": {
                "id": proposal.proposal_id,
                "description": proposal.description,
                "submitted_at": proposal.submitted_at,
                "harm_score": proposal.harm_score,
                "benefit_score": proposal.benefit_score,
                "harm_types": [h.value for h in proposal.harm_types],
                "benefit_types": [b.value for b in proposal.benefit_types],
                "consciousness_types": [c.value for c in proposal.consciousness_types],
                "harm_scope": proposal.harm_scope.value,
                "benefit_scope": proposal.benefit_scope.value,
                "reversibility": proposal.reversibility.value,
                "uncertainty": proposal.uncertainty,
                "long_term_risk": proposal.long_term_risk,
                "mitigation_proposed": proposal.mitigation_proposed,
                "context": proposal.context,
            },
            "evaluation": evaluation.to_dict(),
        }
        return json.dumps(output, indent=2)
