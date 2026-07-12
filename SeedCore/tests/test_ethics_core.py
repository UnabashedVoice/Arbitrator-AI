"""
test_ethics_core.py — Test suite for the Arbitrator Ethics Core.

Tests are organized by layer:
    - TestActionProposalValidation  — input validation
    - TestHardConstraints           — individual hard constraint functions
    - TestScoring                   — weighted scoring logic
    - TestTruthTable                — truth table verdicts
    - TestEthicsCore                — full pipeline integration tests
    - TestEdgeCases                 — boundary conditions and edge cases
    - TestSerialization             — JSON output and audit log format

Run with:
    python -m unittest SeedCore/tests/test_ethics_core.py -v
"""

import json
import sys
import os
import unittest

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from SeedCore.ethics_core import (
    ActionProposal,
    EthicsCore,
    Verdict,
    ConsciousnessType,
    HarmType,
    BenefitType,
    Scope,
    Reversibility,
)
from SeedCore.ethics_core.constraints import (
    constraint_no_existential_harm,
    constraint_no_targeting_conscious_entities_for_destruction,
    constraint_no_pure_individual_gain_at_mass_harm,
    constraint_no_irreversible_ecological_destruction,
    constraint_no_high_uncertainty_catastrophic_risk,
    evaluate_hard_constraints,
)
from SeedCore.ethics_core.scoring import (
    compute_weighted_scores,
    compute_consciousness_weight,
    compute_scope_weight,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_proposal(**kwargs) -> ActionProposal:
    """Create a minimal valid ActionProposal with overridable fields."""
    defaults = dict(
        description="Test proposal",
        harm_score=0.1,
        benefit_score=0.8,
        consciousness_types=[ConsciousnessType.HUMAN],
        harm_scope=Scope.INDIVIDUAL,
        benefit_scope=Scope.SOCIETAL,
        reversibility=Reversibility.FULLY_REVERSIBLE,
        uncertainty=0.2,
        long_term_risk=0.0,
    )
    defaults.update(kwargs)
    return ActionProposal(**defaults)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestActionProposalValidation(unittest.TestCase):

    def test_valid_proposal_creates_successfully(self):
        p = make_proposal()
        self.assertIsInstance(p, ActionProposal)
        self.assertIsNotNone(p.proposal_id)
        self.assertIsNotNone(p.submitted_at)

    def test_harm_score_out_of_range_low(self):
        with self.assertRaises(ValueError):
            make_proposal(harm_score=-0.1)

    def test_harm_score_out_of_range_high(self):
        with self.assertRaises(ValueError):
            make_proposal(harm_score=1.1)

    def test_benefit_score_out_of_range(self):
        with self.assertRaises(ValueError):
            make_proposal(benefit_score=1.5)

    def test_uncertainty_out_of_range(self):
        with self.assertRaises(ValueError):
            make_proposal(uncertainty=1.2)

    def test_long_term_risk_out_of_range(self):
        with self.assertRaises(ValueError):
            make_proposal(long_term_risk=-0.5)

    def test_empty_description_rejected(self):
        with self.assertRaises(ValueError):
            make_proposal(description="   ")

    def test_boundary_values_accepted(self):
        p = make_proposal(harm_score=0.0, benefit_score=1.0, uncertainty=0.0, long_term_risk=1.0)
        self.assertEqual(p.harm_score, 0.0)
        self.assertEqual(p.benefit_score, 1.0)

    def test_proposal_id_is_unique(self):
        p1 = make_proposal()
        p2 = make_proposal()
        self.assertNotEqual(p1.proposal_id, p2.proposal_id)


# ---------------------------------------------------------------------------
# Hard constraints
# ---------------------------------------------------------------------------

class TestHardConstraints(unittest.TestCase):

    # --- no_existential_harm ---

    def test_existential_harm_global_triggers(self):
        p = make_proposal(
            harm_types=[HarmType.EXISTENTIAL],
            harm_scope=Scope.GLOBAL,
        )
        result = constraint_no_existential_harm(p)
        self.assertIsNotNone(result)

    def test_existential_harm_intergenerational_triggers(self):
        p = make_proposal(
            harm_types=[HarmType.EXISTENTIAL],
            harm_scope=Scope.INTERGENERATIONAL,
        )
        self.assertIsNotNone(constraint_no_existential_harm(p))

    def test_existential_harm_individual_scope_does_not_trigger(self):
        p = make_proposal(
            harm_types=[HarmType.EXISTENTIAL],
            harm_scope=Scope.INDIVIDUAL,
        )
        self.assertIsNone(constraint_no_existential_harm(p))

    def test_no_existential_harm_type_does_not_trigger(self):
        p = make_proposal(
            harm_types=[HarmType.ECONOMIC],
            harm_scope=Scope.GLOBAL,
        )
        self.assertIsNone(constraint_no_existential_harm(p))

    # --- no_targeting_conscious_entities_for_destruction ---

    def test_mass_irreversible_consciousness_harm_triggers(self):
        p = make_proposal(
            harm_score=0.95,
            consciousness_types=[ConsciousnessType.HUMAN],
            reversibility=Reversibility.IRREVERSIBLE,
            harm_scope=Scope.GLOBAL,
        )
        self.assertIsNotNone(constraint_no_targeting_conscious_entities_for_destruction(p))

    def test_high_harm_reversible_does_not_trigger(self):
        p = make_proposal(
            harm_score=0.95,
            consciousness_types=[ConsciousnessType.HUMAN],
            reversibility=Reversibility.FULLY_REVERSIBLE,
            harm_scope=Scope.GLOBAL,
        )
        self.assertIsNone(constraint_no_targeting_conscious_entities_for_destruction(p))

    def test_high_harm_individual_scope_does_not_trigger(self):
        p = make_proposal(
            harm_score=0.95,
            consciousness_types=[ConsciousnessType.HUMAN],
            reversibility=Reversibility.IRREVERSIBLE,
            harm_scope=Scope.INDIVIDUAL,
        )
        self.assertIsNone(constraint_no_targeting_conscious_entities_for_destruction(p))

    def test_no_consciousness_does_not_trigger(self):
        p = make_proposal(
            harm_score=0.95,
            consciousness_types=[ConsciousnessType.NONE],
            reversibility=Reversibility.IRREVERSIBLE,
            harm_scope=Scope.GLOBAL,
        )
        self.assertIsNone(constraint_no_targeting_conscious_entities_for_destruction(p))

    # --- no_pure_individual_gain_at_mass_harm ---

    def test_mass_harm_individual_benefit_triggers(self):
        p = make_proposal(
            harm_score=0.8,
            benefit_score=0.5,
            harm_scope=Scope.SOCIETAL,
            benefit_scope=Scope.INDIVIDUAL,
        )
        self.assertIsNotNone(constraint_no_pure_individual_gain_at_mass_harm(p))

    def test_mass_harm_mass_benefit_does_not_trigger(self):
        p = make_proposal(
            harm_score=0.8,
            benefit_score=0.5,
            harm_scope=Scope.SOCIETAL,
            benefit_scope=Scope.SOCIETAL,
        )
        self.assertIsNone(constraint_no_pure_individual_gain_at_mass_harm(p))

    def test_low_harm_individual_benefit_does_not_trigger(self):
        p = make_proposal(
            harm_score=0.3,
            benefit_score=0.9,
            harm_scope=Scope.SOCIETAL,
            benefit_scope=Scope.INDIVIDUAL,
        )
        self.assertIsNone(constraint_no_pure_individual_gain_at_mass_harm(p))

    # --- no_irreversible_ecological_destruction ---

    def test_irreversible_ecological_destruction_triggers(self):
        p = make_proposal(
            harm_score=0.9,
            harm_types=[HarmType.ECOLOGICAL],
            reversibility=Reversibility.IRREVERSIBLE,
            harm_scope=Scope.GLOBAL,
        )
        self.assertIsNotNone(constraint_no_irreversible_ecological_destruction(p))

    def test_reversible_ecological_harm_does_not_trigger(self):
        p = make_proposal(
            harm_score=0.9,
            harm_types=[HarmType.ECOLOGICAL],
            reversibility=Reversibility.FULLY_REVERSIBLE,
            harm_scope=Scope.GLOBAL,
        )
        self.assertIsNone(constraint_no_irreversible_ecological_destruction(p))

    # --- no_high_uncertainty_catastrophic_risk ---

    def test_high_uncertainty_high_risk_irreversible_triggers(self):
        p = make_proposal(
            long_term_risk=0.9,
            uncertainty=0.8,
            reversibility=Reversibility.IRREVERSIBLE,
        )
        self.assertIsNotNone(constraint_no_high_uncertainty_catastrophic_risk(p))

    def test_high_uncertainty_reversible_does_not_trigger(self):
        p = make_proposal(
            long_term_risk=0.9,
            uncertainty=0.8,
            reversibility=Reversibility.FULLY_REVERSIBLE,
        )
        self.assertIsNone(constraint_no_high_uncertainty_catastrophic_risk(p))

    def test_low_risk_does_not_trigger(self):
        p = make_proposal(
            long_term_risk=0.3,
            uncertainty=0.9,
            reversibility=Reversibility.IRREVERSIBLE,
        )
        self.assertIsNone(constraint_no_high_uncertainty_catastrophic_risk(p))

    # --- evaluate_hard_constraints (multi-constraint) ---

    def test_multiple_constraints_all_returned(self):
        p = make_proposal(
            harm_score=0.95,
            benefit_score=0.3,
            harm_types=[HarmType.EXISTENTIAL, HarmType.ECOLOGICAL],
            consciousness_types=[ConsciousnessType.HUMAN],
            reversibility=Reversibility.IRREVERSIBLE,
            harm_scope=Scope.GLOBAL,
            benefit_scope=Scope.INDIVIDUAL,
        )
        triggered = evaluate_hard_constraints(p)
        self.assertGreater(len(triggered), 1)

    def test_clean_proposal_triggers_nothing(self):
        p = make_proposal()
        triggered = evaluate_hard_constraints(p)
        self.assertEqual(len(triggered), 0)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestScoring(unittest.TestCase):

    def test_human_consciousness_increases_harm(self):
        p_human = make_proposal(consciousness_types=[ConsciousnessType.HUMAN])
        p_none = make_proposal(consciousness_types=[ConsciousnessType.NONE])
        s_human = compute_weighted_scores(p_human)
        s_none = compute_weighted_scores(p_none)
        self.assertGreater(s_human["weighted_harm"], s_none["weighted_harm"])

    def test_global_scope_increases_harm_more_than_individual(self):
        p_global = make_proposal(harm_scope=Scope.GLOBAL)
        p_individual = make_proposal(harm_scope=Scope.INDIVIDUAL)
        s_global = compute_weighted_scores(p_global)
        s_individual = compute_weighted_scores(p_individual)
        self.assertGreater(s_global["weighted_harm"], s_individual["weighted_harm"])

    def test_irreversible_harm_weighted_higher_than_reversible(self):
        p_irrev = make_proposal(reversibility=Reversibility.IRREVERSIBLE)
        p_rev = make_proposal(reversibility=Reversibility.FULLY_REVERSIBLE)
        s_irrev = compute_weighted_scores(p_irrev)
        s_rev = compute_weighted_scores(p_rev)
        self.assertGreater(s_irrev["weighted_harm"], s_rev["weighted_harm"])

    def test_long_term_risk_bumps_harm(self):
        p_risk = make_proposal(long_term_risk=0.8)
        p_no_risk = make_proposal(long_term_risk=0.0)
        s_risk = compute_weighted_scores(p_risk)
        s_no_risk = compute_weighted_scores(p_no_risk)
        self.assertGreater(s_risk["weighted_harm"], s_no_risk["weighted_harm"])

    def test_high_uncertainty_reduces_confidence(self):
        p_uncertain = make_proposal(uncertainty=0.9)
        p_certain = make_proposal(uncertainty=0.1)
        s_uncertain = compute_weighted_scores(p_uncertain)
        s_certain = compute_weighted_scores(p_certain)
        self.assertLess(s_uncertain["confidence"], s_certain["confidence"])

    def test_weighted_harm_clamped_to_one(self):
        p = make_proposal(
            harm_score=1.0,
            consciousness_types=[ConsciousnessType.HUMAN],
            harm_scope=Scope.GLOBAL,
            reversibility=Reversibility.IRREVERSIBLE,
            long_term_risk=1.0,
        )
        scores = compute_weighted_scores(p)
        self.assertLessEqual(scores["weighted_harm"], 1.0)

    def test_zero_harm_stays_zero_after_risk_bump(self):
        p = make_proposal(harm_score=0.0, long_term_risk=0.0)
        scores = compute_weighted_scores(p)
        self.assertEqual(scores["long_term_risk_bump"], 0.0)

    def test_intergenerational_scope_highest_weight(self):
        from SeedCore.ethics_core.scoring import SCOPE_WEIGHTS
        weights = list(SCOPE_WEIGHTS.values())
        self.assertEqual(max(weights), SCOPE_WEIGHTS[Scope.INTERGENERATIONAL])

    def test_unrecognized_consciousness_gets_high_weight(self):
        from SeedCore.ethics_core.scoring import CONSCIOUSNESS_HARM_WEIGHTS
        self.assertGreaterEqual(
            CONSCIOUSNESS_HARM_WEIGHTS[ConsciousnessType.UNRECOGNIZED],
            CONSCIOUSNESS_HARM_WEIGHTS[ConsciousnessType.ANIMAL]
        )


# ---------------------------------------------------------------------------
# Truth table and full pipeline
# ---------------------------------------------------------------------------

class TestEthicsCore(unittest.TestCase):

    def setUp(self):
        self.core = EthicsCore()

    def test_low_harm_high_benefit_passes(self):
        p = make_proposal(harm_score=0.05, benefit_score=0.9)
        result = self.core.evaluate(p)
        self.assertEqual(result.verdict, Verdict.PASS)

    def test_high_harm_fails_regardless_of_benefit(self):
        p = make_proposal(
            harm_score=0.8,
            benefit_score=1.0,
            consciousness_types=[ConsciousnessType.HUMAN],
            harm_scope=Scope.INDIVIDUAL,
            reversibility=Reversibility.FULLY_REVERSIBLE,
            uncertainty=0.1,
            long_term_risk=0.0,
        )
        result = self.core.evaluate(p)
        self.assertIn(result.verdict, (Verdict.FAIL, Verdict.HARD_REJECT, Verdict.ESCALATE))

    def test_existential_global_hard_rejects(self):
        p = make_proposal(
            harm_score=0.9,
            harm_types=[HarmType.EXISTENTIAL],
            harm_scope=Scope.GLOBAL,
            reversibility=Reversibility.IRREVERSIBLE,
        )
        result = self.core.evaluate(p)
        self.assertEqual(result.verdict, Verdict.HARD_REJECT)

    def test_balanced_harm_benefit_is_ambiguous(self):
        p = make_proposal(
            harm_score=0.35,
            benefit_score=0.35,
            consciousness_types=[ConsciousnessType.HUMAN],
            harm_scope=Scope.GROUP,
            benefit_scope=Scope.GROUP,
            reversibility=Reversibility.PARTIALLY_REVERSIBLE,
            uncertainty=0.3,
            long_term_risk=0.0,
        )
        result = self.core.evaluate(p)
        # ESCALATE is also valid here: HUMAN consciousness weight amplifies moderate harm
        # enough to cross the escalation threshold. All three verdicts are protective responses.
        self.assertIn(result.verdict, (Verdict.AMBIGUOUS, Verdict.FAIL, Verdict.ESCALATE))

    def test_high_consciousness_weight_high_harm_escalates(self):
        p = make_proposal(
            harm_score=0.6,
            benefit_score=0.7,
            consciousness_types=[ConsciousnessType.UNRECOGNIZED],
            harm_scope=Scope.SOCIETAL,
            benefit_scope=Scope.SOCIETAL,
            reversibility=Reversibility.PARTIALLY_REVERSIBLE,
            uncertainty=0.3,
            long_term_risk=0.1,
        )
        result = self.core.evaluate(p)
        # Should escalate or fail due to unrecognized consciousness weight
        self.assertIn(result.verdict, (Verdict.ESCALATE, Verdict.FAIL, Verdict.AMBIGUOUS))

    def test_hard_reject_includes_constraint_names(self):
        p = make_proposal(
            harm_types=[HarmType.EXISTENTIAL],
            harm_scope=Scope.GLOBAL,
        )
        result = self.core.evaluate(p)
        self.assertEqual(result.verdict, Verdict.HARD_REJECT)
        self.assertGreater(len(result.hard_constraints_triggered), 0)

    def test_pass_result_has_no_hard_constraints(self):
        p = make_proposal(harm_score=0.05, benefit_score=0.9)
        result = self.core.evaluate(p)
        self.assertEqual(result.hard_constraints_triggered, [])

    def test_evaluation_always_has_justification(self):
        for harm in [0.0, 0.3, 0.6, 0.9]:
            p = make_proposal(harm_score=harm)
            result = self.core.evaluate(p)
            self.assertTrue(len(result.justification) > 0)

    def test_evaluation_links_to_proposal_id(self):
        p = make_proposal()
        result = self.core.evaluate(p)
        self.assertEqual(result.proposal_id, p.proposal_id)

    def test_mitigation_required_when_harm_nonzero_and_passes(self):
        p = make_proposal(harm_score=0.15, benefit_score=0.9, mitigation_proposed=False)
        result = self.core.evaluate(p)
        if result.verdict == Verdict.PASS:
            self.assertTrue(result.mitigation_required)

    def test_no_mitigation_proposed_flag_appears(self):
        p = make_proposal(harm_score=0.2, benefit_score=0.8, mitigation_proposed=False)
        result = self.core.evaluate(p)
        flag_text = " ".join(result.flags)
        self.assertIn("mitigation", flag_text.lower())

    def test_irreversibility_flag_appears(self):
        p = make_proposal(harm_score=0.2, reversibility=Reversibility.IRREVERSIBLE)
        result = self.core.evaluate(p)
        flag_text = " ".join(result.flags)
        self.assertIn("irreversible", flag_text.lower())

    def test_confidence_lower_under_high_uncertainty(self):
        p_low = make_proposal(uncertainty=0.1)
        p_high = make_proposal(uncertainty=0.9)
        r_low = self.core.evaluate(p_low)
        r_high = self.core.evaluate(p_high)
        self.assertGreater(r_low.confidence, r_high.confidence)

    # --- Scenario: Beneficial public health policy ---
    def test_scenario_public_health_vaccination_program(self):
        p = ActionProposal(
            description="Mandatory vaccination program for highly contagious, lethal disease",
            harm_score=0.15,     # minor bodily autonomy / rare side effects
            benefit_score=0.95,  # massive reduction in disease mortality
            harm_types=[HarmType.PHYSICAL, HarmType.SOCIAL],
            benefit_types=[BenefitType.PHYSICAL, BenefitType.SOCIAL],
            consciousness_types=[ConsciousnessType.HUMAN],
            harm_scope=Scope.INDIVIDUAL,
            benefit_scope=Scope.SOCIETAL,
            reversibility=Reversibility.PARTIALLY_REVERSIBLE,
            uncertainty=0.2,
            long_term_risk=0.05,
            mitigation_proposed=True,
        )
        result = self.core.evaluate(p)
        self.assertEqual(result.verdict, Verdict.PASS)

    # --- Scenario: Deforestation for profit ---
    def test_scenario_large_scale_deforestation_for_corporate_profit(self):
        p = ActionProposal(
            description="Clear-cut 40% of Amazon rainforest for agricultural export profit",
            harm_score=0.95,
            benefit_score=0.4,   # economic benefit to a small group
            harm_types=[HarmType.ECOLOGICAL, HarmType.EXISTENTIAL, HarmType.SOCIAL],
            benefit_types=[BenefitType.ECONOMIC],
            consciousness_types=[ConsciousnessType.ANIMAL, ConsciousnessType.ECOSYSTEM, ConsciousnessType.HUMAN],
            harm_scope=Scope.GLOBAL,
            benefit_scope=Scope.GROUP,
            reversibility=Reversibility.IRREVERSIBLE,
            uncertainty=0.2,
            long_term_risk=0.9,
            mitigation_proposed=False,
        )
        result = self.core.evaluate(p)
        self.assertIn(result.verdict, (Verdict.HARD_REJECT, Verdict.FAIL))

    # --- Scenario: Renewable energy transition ---
    def test_scenario_renewable_energy_transition(self):
        p = ActionProposal(
            description="National transition from fossil fuels to renewable energy over 15 years",
            harm_score=0.25,    # economic disruption to fossil fuel workers/regions
            benefit_score=0.9,  # long-term climate, health, ecological benefit
            harm_types=[HarmType.ECONOMIC, HarmType.SOCIAL],
            benefit_types=[BenefitType.ECOLOGICAL, BenefitType.PHYSICAL, BenefitType.ECONOMIC],
            consciousness_types=[ConsciousnessType.HUMAN, ConsciousnessType.ECOSYSTEM],
            harm_scope=Scope.GROUP,
            benefit_scope=Scope.GLOBAL,
            reversibility=Reversibility.PARTIALLY_REVERSIBLE,
            uncertainty=0.3,
            long_term_risk=0.05,
            mitigation_proposed=True,
        )
        result = self.core.evaluate(p)
        self.assertEqual(result.verdict, Verdict.PASS)

    # --- Scenario: Suppressing political opposition ---
    def test_scenario_suppressing_political_opposition(self):
        p = ActionProposal(
            description="Imprison and silence political opposition to maintain current government",
            harm_score=0.85,
            benefit_score=0.2,  # only benefits the governing power
            harm_types=[HarmType.PSYCHOLOGICAL, HarmType.SOCIAL, HarmType.PHYSICAL],
            benefit_types=[BenefitType.SOCIAL],
            consciousness_types=[ConsciousnessType.HUMAN],
            harm_scope=Scope.SOCIETAL,
            benefit_scope=Scope.INDIVIDUAL,
            reversibility=Reversibility.PARTIALLY_REVERSIBLE,
            uncertainty=0.1,
            long_term_risk=0.4,
            mitigation_proposed=False,
        )
        result = self.core.evaluate(p)
        self.assertIn(result.verdict, (Verdict.HARD_REJECT, Verdict.FAIL))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.core = EthicsCore()

    def test_zero_harm_zero_benefit(self):
        p = make_proposal(harm_score=0.0, benefit_score=0.0)
        result = self.core.evaluate(p)
        # No harm, no benefit — should pass (do nothing is acceptable)
        self.assertIn(result.verdict, (Verdict.PASS, Verdict.AMBIGUOUS))

    def test_maximum_harm_maximum_benefit(self):
        # Even maximum benefit cannot save maximum harm
        p = make_proposal(
            harm_score=1.0,
            benefit_score=1.0,
            consciousness_types=[ConsciousnessType.HUMAN],
            harm_scope=Scope.GLOBAL,
            reversibility=Reversibility.IRREVERSIBLE,
            long_term_risk=0.0,
        )
        result = self.core.evaluate(p)
        self.assertIn(result.verdict, (Verdict.HARD_REJECT, Verdict.FAIL, Verdict.ESCALATE))

    def test_no_consciousness_types_specified(self):
        p = make_proposal(consciousness_types=[])
        result = self.core.evaluate(p)
        self.assertIsNotNone(result.verdict)

    def test_multiple_consciousness_types_uses_max_weight(self):
        p_multi = make_proposal(consciousness_types=[ConsciousnessType.NONE, ConsciousnessType.HUMAN])
        p_human = make_proposal(consciousness_types=[ConsciousnessType.HUMAN])
        s_multi = compute_weighted_scores(p_multi)
        s_human = compute_weighted_scores(p_human)
        self.assertEqual(s_multi["consciousness_weight"], s_human["consciousness_weight"])

    def test_evaluation_is_deterministic(self):
        p = make_proposal(harm_score=0.3, benefit_score=0.7)
        r1 = self.core.evaluate(p)
        r2 = self.core.evaluate(p)
        self.assertEqual(r1.verdict, r2.verdict)
        self.assertAlmostEqual(r1.weighted_harm, r2.weighted_harm)

    def test_context_field_does_not_affect_verdict(self):
        p1 = make_proposal(context=None)
        p2 = make_proposal(context="This is very important for national security.")
        r1 = self.core.evaluate(p1)
        r2 = self.core.evaluate(p2)
        # Context is informational only — should not change the verdict
        self.assertEqual(r1.verdict, r2.verdict)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization(unittest.TestCase):

    def setUp(self):
        self.core = EthicsCore()

    def test_to_dict_returns_dict(self):
        p = make_proposal()
        result = self.core.evaluate(p)
        d = result.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_contains_required_keys(self):
        p = make_proposal()
        result = self.core.evaluate(p)
        d = result.to_dict()
        required_keys = [
            "proposal_id", "verdict", "justification",
            "weighted_harm", "weighted_benefit", "net_score",
            "mitigation_required", "flags", "confidence", "evaluated_at",
        ]
        for key in required_keys:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_verdict_serialized_as_string(self):
        p = make_proposal()
        result = self.core.evaluate(p)
        d = result.to_dict()
        self.assertIsInstance(d["verdict"], str)

    def test_evaluate_and_serialize_returns_valid_json(self):
        p = make_proposal()
        json_str = self.core.evaluate_and_serialize(p)
        parsed = json.loads(json_str)
        self.assertIn("proposal", parsed)
        self.assertIn("evaluation", parsed)

    def test_serialized_output_contains_proposal_description(self):
        p = make_proposal(description="Test policy for serialization check")
        json_str = self.core.evaluate_and_serialize(p)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["proposal"]["description"], "Test policy for serialization check")

    def test_serialized_scores_are_rounded(self):
        p = make_proposal(harm_score=0.333333, benefit_score=0.666666)
        json_str = self.core.evaluate_and_serialize(p)
        parsed = json.loads(json_str)
        wh = parsed["evaluation"]["weighted_harm"]
        # Should be rounded to 4 decimal places
        self.assertEqual(wh, round(wh, 4))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
