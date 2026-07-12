"""
test_synthesis.py — Test suite for the Arbitrator Synthesis Layer.

Tests are organized by layer:
    - TestFindingValidation         — Finding input validation
    - TestChannelOutputValidation   — ChannelOutput contract validation
    - TestScoreAggregation          — Weighted score aggregation logic
    - TestTimeframeOrganization     — Grouping findings by timeframe
    - TestPopulationOrganization    — Grouping findings by population
    - TestRippleDetection           — Cross-domain ripple effect detection
    - TestVerdictDerivation         — OverallVerdict logic
    - TestFailureAccounting         — Failed channel handling
    - TestSynthesizer               — Full pipeline integration tests
    - TestConsequenceMapOutput      — Output structure and serialization
    - TestRealWorldScenarios        — Realistic multi-channel scenarios

Run with:
    python -m unittest SeedCore/tests/test_synthesis.py -v
"""

import json
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from SeedCore.synthesis import (
    Synthesizer,
    ChannelOutput,
    ChannelStatus,
    Finding,
    UncertaintyNote,
    ImpactDirection,
    ImpactTimeframe,
    ImpactCertainty,
    OverallVerdict,
    ConsequenceMap,
)
from SeedCore.synthesis.synthesizer import (
    _aggregate_scores,
    _organize_by_timeframe,
    _organize_by_population,
    _detect_ripple_effects,
    _derive_verdict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_finding(
    summary="Test finding",
    detail="Detail text for test finding.",
    direction=ImpactDirection.HARM,
    timeframe=ImpactTimeframe.SHORT_TERM,
    certainty=ImpactCertainty.MODERATE,
    magnitude=0.5,
    affected_groups=None,
    tags=None,
    reversible=True,
) -> Finding:
    return Finding(
        summary=summary,
        detail=detail,
        direction=direction,
        timeframe=timeframe,
        certainty=certainty,
        magnitude=magnitude,
        affected_groups=affected_groups or [],
        tags=tags or [],
        reversible=reversible,
    )


def make_output(
    channel_name="economic",
    status=ChannelStatus.SUCCESS,
    findings=None,
    overall_harm_score=0.3,
    overall_benefit_score=0.7,
    confidence=0.8,
    domain_summary="Test channel summary.",
    adversarial_challenges=None,
    uncertainty_notes=None,
    error_message=None,
) -> ChannelOutput:
    return ChannelOutput(
        channel_name=channel_name,
        status=status,
        findings=findings or [],
        overall_harm_score=overall_harm_score,
        overall_benefit_score=overall_benefit_score,
        confidence=confidence,
        domain_summary=domain_summary,
        adversarial_challenges=adversarial_challenges or [],
        uncertainty_notes=uncertainty_notes or [],
        error_message=error_message,
    )


def make_failed_output(channel_name="geopolitical", status=ChannelStatus.FAILED) -> ChannelOutput:
    return ChannelOutput(
        channel_name=channel_name,
        status=status,
        error_message="Model unavailable.",
    )


# ---------------------------------------------------------------------------
# Finding validation
# ---------------------------------------------------------------------------

class TestFindingValidation(unittest.TestCase):

    def test_valid_finding_creates_successfully(self):
        f = make_finding()
        self.assertIsInstance(f, Finding)
        self.assertIsNotNone(f.finding_id)

    def test_magnitude_out_of_range_high(self):
        with self.assertRaises(ValueError):
            make_finding(magnitude=1.5)

    def test_magnitude_out_of_range_low(self):
        with self.assertRaises(ValueError):
            make_finding(magnitude=-0.1)

    def test_empty_summary_rejected(self):
        with self.assertRaises(ValueError):
            make_finding(summary="   ")

    def test_boundary_magnitude_zero(self):
        f = make_finding(magnitude=0.0)
        self.assertEqual(f.magnitude, 0.0)

    def test_boundary_magnitude_one(self):
        f = make_finding(magnitude=1.0)
        self.assertEqual(f.magnitude, 1.0)

    def test_finding_id_unique(self):
        f1 = make_finding()
        f2 = make_finding()
        self.assertNotEqual(f1.finding_id, f2.finding_id)

    def test_to_dict_contains_required_fields(self):
        f = make_finding()
        d = f.to_dict()
        for key in ["finding_id", "summary", "direction", "timeframe", "certainty", "magnitude"]:
            self.assertIn(key, d)

    def test_direction_serialized_as_string(self):
        f = make_finding(direction=ImpactDirection.HARM)
        d = f.to_dict()
        self.assertEqual(d["direction"], "harm")


# ---------------------------------------------------------------------------
# ChannelOutput validation
# ---------------------------------------------------------------------------

class TestChannelOutputValidation(unittest.TestCase):

    def test_valid_output_creates_successfully(self):
        o = make_output()
        self.assertIsInstance(o, ChannelOutput)

    def test_harm_score_out_of_range(self):
        with self.assertRaises(ValueError):
            make_output(overall_harm_score=1.5)

    def test_benefit_score_out_of_range(self):
        with self.assertRaises(ValueError):
            make_output(overall_benefit_score=-0.1)

    def test_confidence_out_of_range(self):
        with self.assertRaises(ValueError):
            make_output(confidence=1.1)

    def test_none_scores_are_allowed(self):
        o = make_output(overall_harm_score=None, overall_benefit_score=None, confidence=None)
        self.assertIsNone(o.overall_harm_score)

    def test_succeeded_property_true_on_success(self):
        o = make_output(status=ChannelStatus.SUCCESS)
        self.assertTrue(o.succeeded)

    def test_succeeded_property_false_on_failure(self):
        o = make_failed_output()
        self.assertFalse(o.succeeded)

    def test_harm_findings_filter(self):
        findings = [
            make_finding(direction=ImpactDirection.HARM),
            make_finding(direction=ImpactDirection.BENEFIT),
            make_finding(direction=ImpactDirection.MIXED),
        ]
        o = make_output(findings=findings)
        self.assertEqual(len(o.harm_findings), 2)  # HARM + MIXED

    def test_benefit_findings_filter(self):
        findings = [
            make_finding(direction=ImpactDirection.HARM),
            make_finding(direction=ImpactDirection.BENEFIT),
        ]
        o = make_output(findings=findings)
        self.assertEqual(len(o.benefit_findings), 1)

    def test_to_dict_contains_required_fields(self):
        o = make_output()
        d = o.to_dict()
        for key in ["output_id", "channel_name", "status", "findings", "overall_harm_score"]:
            self.assertIn(key, d)


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------

class TestScoreAggregation(unittest.TestCase):

    def test_no_outputs_returns_zeros(self):
        harm, benefit, conf = _aggregate_scores([])
        self.assertEqual(harm, 0.0)
        self.assertEqual(benefit, 0.0)
        self.assertEqual(conf, 0.0)

    def test_all_failed_returns_zeros(self):
        outputs = [make_failed_output(), make_failed_output("ecological")]
        harm, benefit, conf = _aggregate_scores(outputs)
        self.assertEqual(harm, 0.0)
        self.assertEqual(benefit, 0.0)

    def test_single_successful_channel(self):
        o = make_output(overall_harm_score=0.3, overall_benefit_score=0.7, confidence=0.9)
        harm, benefit, conf = _aggregate_scores([o])
        self.assertAlmostEqual(harm, 0.3, places=2)
        self.assertAlmostEqual(benefit, 0.7, places=2)

    def test_higher_confidence_weighs_more(self):
        o_high = make_output(channel_name="eco", overall_harm_score=0.8, overall_benefit_score=0.2, confidence=0.9)
        o_low = make_output(channel_name="econ", overall_harm_score=0.1, overall_benefit_score=0.9, confidence=0.1)
        harm, benefit, _ = _aggregate_scores([o_high, o_low])
        # High confidence channel dominates
        self.assertGreater(harm, 0.4)
        self.assertLess(benefit, 0.5)

    def test_scores_clamped_to_one(self):
        o1 = make_output(overall_harm_score=1.0, overall_benefit_score=1.0, confidence=1.0)
        o2 = make_output(channel_name="eco", overall_harm_score=1.0, overall_benefit_score=1.0, confidence=1.0)
        harm, benefit, _ = _aggregate_scores([o1, o2])
        self.assertLessEqual(harm, 1.0)
        self.assertLessEqual(benefit, 1.0)

    def test_confidence_none_treated_as_half(self):
        o = make_output(overall_harm_score=0.5, overall_benefit_score=0.5, confidence=None)
        harm, benefit, conf = _aggregate_scores([o])
        self.assertIsNotNone(harm)
        self.assertAlmostEqual(conf, 0.5, places=2)

    def test_findings_used_when_no_overall_score(self):
        findings = [
            make_finding(direction=ImpactDirection.HARM, magnitude=0.6, certainty=ImpactCertainty.HIGH),
            make_finding(direction=ImpactDirection.BENEFIT, magnitude=0.8, certainty=ImpactCertainty.HIGH),
        ]
        o = make_output(
            findings=findings,
            overall_harm_score=None,
            overall_benefit_score=None,
            confidence=0.8
        )
        harm, benefit, _ = _aggregate_scores([o])
        self.assertGreater(harm, 0.0)
        self.assertGreater(benefit, 0.0)


# ---------------------------------------------------------------------------
# Timeframe organization
# ---------------------------------------------------------------------------

class TestTimeframeOrganization(unittest.TestCase):

    def test_findings_grouped_by_timeframe(self):
        findings = [
            make_finding(timeframe=ImpactTimeframe.IMMEDIATE, direction=ImpactDirection.HARM),
            make_finding(timeframe=ImpactTimeframe.LONG_TERM, direction=ImpactDirection.BENEFIT),
        ]
        o = make_output(findings=findings)
        summaries = _organize_by_timeframe([o])
        timeframes = {s.timeframe for s in summaries}
        self.assertIn(ImpactTimeframe.IMMEDIATE, timeframes)
        self.assertIn(ImpactTimeframe.LONG_TERM, timeframes)

    def test_summaries_ordered_chronologically(self):
        findings = [
            make_finding(timeframe=ImpactTimeframe.LONG_TERM),
            make_finding(timeframe=ImpactTimeframe.IMMEDIATE),
            make_finding(timeframe=ImpactTimeframe.SHORT_TERM),
        ]
        o = make_output(findings=findings)
        summaries = _organize_by_timeframe([o])
        order = [s.timeframe for s in summaries]
        expected = [ImpactTimeframe.IMMEDIATE, ImpactTimeframe.SHORT_TERM, ImpactTimeframe.LONG_TERM]
        self.assertEqual(order, expected)

    def test_failed_channel_findings_excluded(self):
        findings = [make_finding(timeframe=ImpactTimeframe.IMMEDIATE)]
        failed = make_failed_output()
        failed.findings = findings  # Even if somehow populated, should be excluded
        summaries = _organize_by_timeframe([failed])
        self.assertEqual(len(summaries), 0)

    def test_summary_has_text(self):
        findings = [make_finding(direction=ImpactDirection.HARM, magnitude=0.7)]
        o = make_output(findings=findings)
        summaries = _organize_by_timeframe([o])
        self.assertTrue(all(s.summary_text for s in summaries))

    def test_net_direction_benefit_when_benefit_dominates(self):
        findings = [
            make_finding(direction=ImpactDirection.BENEFIT, magnitude=0.8),
            make_finding(direction=ImpactDirection.HARM, magnitude=0.2),
        ]
        o = make_output(findings=findings)
        summaries = _organize_by_timeframe([o])
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].net_direction, ImpactDirection.BENEFIT)

    def test_net_direction_harm_when_harm_dominates(self):
        findings = [
            make_finding(direction=ImpactDirection.HARM, magnitude=0.9),
            make_finding(direction=ImpactDirection.BENEFIT, magnitude=0.1),
        ]
        o = make_output(findings=findings)
        summaries = _organize_by_timeframe([o])
        self.assertEqual(summaries[0].net_direction, ImpactDirection.HARM)


# ---------------------------------------------------------------------------
# Population impact organization
# ---------------------------------------------------------------------------

class TestPopulationOrganization(unittest.TestCase):

    def test_findings_grouped_by_population(self):
        findings = [
            make_finding(direction=ImpactDirection.HARM, affected_groups=["children", "elderly"]),
            make_finding(direction=ImpactDirection.BENEFIT, affected_groups=["workers"]),
        ]
        o = make_output(findings=findings)
        impacts = _organize_by_population([o])
        populations = {i.population for i in impacts}
        self.assertIn("children", populations)
        self.assertIn("elderly", populations)
        self.assertIn("workers", populations)

    def test_no_affected_groups_produces_no_population_impacts(self):
        findings = [make_finding(affected_groups=[])]
        o = make_output(findings=findings)
        impacts = _organize_by_population([o])
        self.assertEqual(len(impacts), 0)

    def test_population_net_direction_correct(self):
        findings = [
            make_finding(direction=ImpactDirection.BENEFIT, magnitude=0.8, affected_groups=["workers"]),
            make_finding(direction=ImpactDirection.HARM, magnitude=0.2, affected_groups=["workers"]),
        ]
        o = make_output(findings=findings)
        impacts = _organize_by_population([o])
        worker_impact = next(i for i in impacts if i.population == "workers")
        self.assertEqual(worker_impact.net_direction, ImpactDirection.BENEFIT)

    def test_population_impact_has_summary_text(self):
        findings = [make_finding(affected_groups=["low-income populations"])]
        o = make_output(findings=findings)
        impacts = _organize_by_population([o])
        self.assertTrue(all(i.summary_text for i in impacts))


# ---------------------------------------------------------------------------
# Ripple effect detection
# ---------------------------------------------------------------------------

class TestRippleDetection(unittest.TestCase):

    def test_economic_harm_triggers_social_ripple(self):
        findings = [make_finding(
            direction=ImpactDirection.HARM,
            magnitude=0.7,
            tags=["economic"],
        )]
        o = make_output(findings=findings)
        ripples = _detect_ripple_effects([o])
        affected_domains = [domain for r in ripples for domain in r.affected_domains]
        self.assertTrue(any("social" in d for d in affected_domains))

    def test_ecological_harm_triggers_economic_ripple(self):
        findings = [make_finding(
            direction=ImpactDirection.HARM,
            magnitude=0.6,
            tags=["ecological"],
        )]
        o = make_output(findings=findings)
        ripples = _detect_ripple_effects([o])
        self.assertGreater(len(ripples), 0)

    def test_low_magnitude_does_not_trigger_ripple(self):
        findings = [make_finding(
            direction=ImpactDirection.HARM,
            magnitude=0.1,   # Below all thresholds
            tags=["economic"],
        )]
        o = make_output(findings=findings)
        ripples = _detect_ripple_effects([o])
        # No rule should fire at magnitude 0.1
        self.assertEqual(len(ripples), 0)

    def test_benefit_direction_triggers_benefit_ripple(self):
        findings = [make_finding(
            direction=ImpactDirection.BENEFIT,
            magnitude=0.7,
            tags=["economic"],
        )]
        o = make_output(findings=findings)
        ripples = _detect_ripple_effects([o])
        benefit_ripples = [r for r in ripples if r.direction == ImpactDirection.BENEFIT]
        self.assertGreater(len(benefit_ripples), 0)

    def test_ripple_includes_source_finding_ids(self):
        finding = make_finding(direction=ImpactDirection.HARM, magnitude=0.6, tags=["ecological"])
        o = make_output(findings=[finding])
        ripples = _detect_ripple_effects([o])
        if ripples:
            self.assertIn(finding.finding_id, ripples[0].source_finding_ids)

    def test_no_duplicate_ripples(self):
        # Two channels with the same type of finding should not produce duplicate ripples
        finding1 = make_finding(direction=ImpactDirection.HARM, magnitude=0.6, tags=["ecological"])
        finding2 = make_finding(direction=ImpactDirection.HARM, magnitude=0.7, tags=["ecological"])
        o1 = make_output(channel_name="eco1", findings=[finding1])
        o2 = make_output(channel_name="eco2", findings=[finding2])
        ripples = _detect_ripple_effects([o1, o2])
        descriptions = [r.description for r in ripples]
        # Descriptions should be unique
        self.assertEqual(len(descriptions), len(set(descriptions)))

    def test_ripple_has_certainty_note(self):
        finding = make_finding(direction=ImpactDirection.HARM, magnitude=0.6, tags=["economic"])
        o = make_output(findings=[finding])
        ripples = _detect_ripple_effects([o])
        if ripples:
            self.assertTrue(all(r.certainty_note for r in ripples))


# ---------------------------------------------------------------------------
# Verdict derivation
# ---------------------------------------------------------------------------

class TestVerdictDerivation(unittest.TestCase):

    def test_no_successful_channels_returns_insufficient_data(self):
        v = _derive_verdict(0.0, 0.0, 0.0, successful_count=0, total_invoked=3)
        self.assertEqual(v, OverallVerdict.INSUFFICIENT_DATA)

    def test_low_coverage_returns_requires_review(self):
        v = _derive_verdict(0.4, 0.6, 0.8, successful_count=1, total_invoked=5)
        self.assertEqual(v, OverallVerdict.REQUIRES_REVIEW)

    def test_high_benefit_net_returns_beneficial(self):
        v = _derive_verdict(0.1, 0.8, 0.9, successful_count=5, total_invoked=5)
        self.assertEqual(v, OverallVerdict.NET_BENEFICIAL)

    def test_high_harm_net_returns_harmful(self):
        v = _derive_verdict(0.8, 0.1, 0.9, successful_count=5, total_invoked=5)
        self.assertEqual(v, OverallVerdict.NET_HARMFUL)

    def test_balanced_high_scores_returns_mixed(self):
        v = _derive_verdict(0.6, 0.6, 0.8, successful_count=4, total_invoked=4)
        self.assertEqual(v, OverallVerdict.MIXED)

    def test_low_confidence_near_zero_net_returns_requires_review(self):
        v = _derive_verdict(0.35, 0.4, 0.25, successful_count=3, total_invoked=4)
        self.assertEqual(v, OverallVerdict.REQUIRES_REVIEW)


# ---------------------------------------------------------------------------
# Failure accounting
# ---------------------------------------------------------------------------

class TestFailureAccounting(unittest.TestCase):

    def setUp(self):
        self.synth = Synthesizer()

    def test_failed_channels_recorded_in_map(self):
        outputs = [
            make_output(channel_name="economic"),
            make_failed_output(channel_name="geopolitical", status=ChannelStatus.TIMEOUT),
        ]
        cmap = self.synth.synthesize("Test proposal", "manifest-123", outputs)
        failed_names = [f["channel"] for f in cmap.channels_failed]
        self.assertIn("geopolitical", failed_names)

    def test_failed_channels_not_in_succeeded(self):
        outputs = [
            make_output(channel_name="economic"),
            make_failed_output(channel_name="ecological"),
        ]
        cmap = self.synth.synthesize("Test proposal", "manifest-123", outputs)
        self.assertNotIn("ecological", cmap.channels_succeeded)

    def test_data_gaps_populated_for_failures(self):
        outputs = [make_failed_output(channel_name="geopolitical")]
        cmap = self.synth.synthesize("Test proposal", "manifest-123", outputs)
        self.assertGreater(len(cmap.data_gaps), 0)

    def test_all_failed_produces_insufficient_data(self):
        outputs = [
            make_failed_output("economic"),
            make_failed_output("ecological"),
        ]
        cmap = self.synth.synthesize("Test proposal", "manifest-123", outputs)
        self.assertEqual(cmap.overall_verdict, OverallVerdict.INSUFFICIENT_DATA)

    def test_empty_outputs_produces_insufficient_data(self):
        cmap = self.synth.synthesize("Test proposal", "manifest-123", [])
        self.assertEqual(cmap.overall_verdict, OverallVerdict.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# Full Synthesizer integration
# ---------------------------------------------------------------------------

class TestSynthesizer(unittest.TestCase):

    def setUp(self):
        self.synth = Synthesizer()

    def test_returns_consequence_map(self):
        outputs = [make_output()]
        cmap = self.synth.synthesize("A test proposal.", "m-001", outputs)
        self.assertIsInstance(cmap, ConsequenceMap)

    def test_empty_proposal_raises(self):
        with self.assertRaises(ValueError):
            self.synth.synthesize("   ", "m-001", [make_output()])

    def test_executive_summary_always_populated(self):
        outputs = [make_output()]
        cmap = self.synth.synthesize("A policy proposal.", "m-001", outputs)
        self.assertTrue(len(cmap.executive_summary) > 0)

    def test_map_id_is_unique(self):
        outputs = [make_output()]
        c1 = self.synth.synthesize("Proposal A", "m-001", outputs)
        c2 = self.synth.synthesize("Proposal B", "m-002", outputs)
        self.assertNotEqual(c1.map_id, c2.map_id)

    def test_manifest_id_preserved(self):
        outputs = [make_output()]
        cmap = self.synth.synthesize("Proposal", "manifest-xyz", outputs)
        self.assertEqual(cmap.manifest_id, "manifest-xyz")

    def test_ethics_evaluation_id_preserved(self):
        outputs = [make_output()]
        cmap = self.synth.synthesize("Proposal", "m-001", outputs, ethics_evaluation_id="ethics-abc")
        self.assertEqual(cmap.ethics_evaluation_id, "ethics-abc")

    def test_channel_outputs_logged(self):
        outputs = [make_output(channel_name="economic"), make_output(channel_name="ecological")]
        cmap = self.synth.synthesize("Proposal", "m-001", outputs)
        self.assertEqual(len(cmap.channel_outputs), 2)

    def test_adversarial_challenges_collected(self):
        output = make_output(
            channel_name="ethical_adversarial",
            adversarial_challenges=["Challenge 1", "Challenge 2"],
        )
        cmap = self.synth.synthesize("Proposal", "m-001", [output])
        self.assertEqual(len(cmap.adversarial_challenges), 2)

    def test_uncertainty_register_populated(self):
        note = UncertaintyNote(
            description="Long-term economic effects are highly speculative.",
            impact_on_analysis="Benefit estimates may be overstated.",
            magnitude=0.6,
        )
        output = make_output(uncertainty_notes=[note])
        cmap = self.synth.synthesize("Proposal", "m-001", [output])
        self.assertEqual(len(cmap.uncertainty_register), 1)

    def test_mitigations_collected_for_high_harm_findings(self):
        findings = [make_finding(direction=ImpactDirection.HARM, magnitude=0.8)]
        output = make_output(findings=findings)
        cmap = self.synth.synthesize("Proposal", "m-001", [output])
        self.assertGreater(len(cmap.recommended_mitigations), 0)

    def test_net_score_is_benefit_minus_harm(self):
        output = make_output(overall_harm_score=0.3, overall_benefit_score=0.7, confidence=1.0)
        cmap = self.synth.synthesize("Proposal", "m-001", [output])
        self.assertAlmostEqual(cmap.net_score, cmap.overall_benefit_score - cmap.overall_harm_score, places=3)

    def test_high_benefit_low_harm_verdict_is_beneficial(self):
        outputs = [
            make_output("eco", overall_harm_score=0.05, overall_benefit_score=0.9, confidence=0.9),
            make_output("social", overall_harm_score=0.1, overall_benefit_score=0.85, confidence=0.85),
            make_output("legal", overall_harm_score=0.05, overall_benefit_score=0.7, confidence=0.8),
        ]
        cmap = self.synth.synthesize("Clean energy transition", "m-001", outputs)
        self.assertEqual(cmap.overall_verdict, OverallVerdict.NET_BENEFICIAL)

    def test_high_harm_low_benefit_verdict_is_harmful(self):
        outputs = [
            make_output("eco", overall_harm_score=0.9, overall_benefit_score=0.1, confidence=0.9),
            make_output("social", overall_harm_score=0.85, overall_benefit_score=0.15, confidence=0.85),
        ]
        cmap = self.synth.synthesize("Deforestation project", "m-001", outputs)
        self.assertEqual(cmap.overall_verdict, OverallVerdict.NET_HARMFUL)

    def test_ripple_effects_in_consequence_map(self):
        findings = [
            make_finding(direction=ImpactDirection.HARM, magnitude=0.7, tags=["ecological"]),
        ]
        output = make_output(findings=findings)
        cmap = self.synth.synthesize("Mining operation", "m-001", [output])
        self.assertGreater(len(cmap.ripple_effects), 0)


# ---------------------------------------------------------------------------
# Consequence map output and serialization
# ---------------------------------------------------------------------------

class TestConsequenceMapOutput(unittest.TestCase):

    def setUp(self):
        self.synth = Synthesizer()
        findings = [
            make_finding(
                summary="Economic disruption to fossil fuel sector",
                direction=ImpactDirection.HARM,
                timeframe=ImpactTimeframe.SHORT_TERM,
                magnitude=0.5,
                affected_groups=["fossil fuel workers"],
                tags=["economic"],
            ),
            make_finding(
                summary="Long-term reduction in carbon emissions",
                direction=ImpactDirection.BENEFIT,
                timeframe=ImpactTimeframe.LONG_TERM,
                magnitude=0.8,
                affected_groups=["future generations"],
                tags=["ecological"],
            ),
        ]
        self.outputs = [
            make_output(
                channel_name="economic",
                findings=findings,
                overall_harm_score=0.35,
                overall_benefit_score=0.75,
                confidence=0.8,
                adversarial_challenges=["Does this disproportionately burden rural communities?"],
            )
        ]
        self.cmap = self.synth.synthesize(
            "National carbon tax policy", "m-001", self.outputs, ethics_evaluation_id="ethics-001"
        )

    def test_to_dict_is_valid_json(self):
        d = self.cmap.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        self.assertIsInstance(parsed, dict)

    def test_to_dict_has_required_top_level_keys(self):
        d = self.cmap.to_dict()
        for key in [
            "map_id", "overall_verdict", "overall_harm_score", "overall_benefit_score",
            "net_score", "synthesis_confidence", "executive_summary",
            "timeframe_impacts", "population_impacts", "ripple_effects",
            "adversarial_challenges", "uncertainty_register",
            "channels_invoked", "channels_succeeded", "channels_failed",
            "data_gaps", "recommended_mitigations", "channel_outputs",
        ]:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_timeframe_impacts_in_output(self):
        d = self.cmap.to_dict()
        self.assertGreater(len(d["timeframe_impacts"]), 0)

    def test_population_impacts_in_output(self):
        d = self.cmap.to_dict()
        self.assertGreater(len(d["population_impacts"]), 0)

    def test_adversarial_challenges_in_output(self):
        d = self.cmap.to_dict()
        self.assertGreater(len(d["adversarial_challenges"]), 0)

    def test_verdict_serialized_as_string(self):
        d = self.cmap.to_dict()
        self.assertIsInstance(d["overall_verdict"], str)

    def test_scores_rounded_in_output(self):
        d = self.cmap.to_dict()
        for key in ["overall_harm_score", "overall_benefit_score", "net_score"]:
            val = d[key]
            self.assertEqual(val, round(val, 4))

    def test_high_magnitude_harm_properties(self):
        high_harm = self.cmap.high_magnitude_harms
        # No findings with magnitude >= 0.6 in HARM direction were added
        self.assertIsInstance(high_harm, list)

    def test_all_harm_findings_property(self):
        harms = self.cmap.all_harm_findings
        self.assertIsInstance(harms, list)

    def test_all_benefit_findings_property(self):
        benefits = self.cmap.all_benefit_findings
        self.assertIsInstance(benefits, list)
        self.assertGreater(len(benefits), 0)


# ---------------------------------------------------------------------------
# Real-world scenarios
# ---------------------------------------------------------------------------

class TestRealWorldScenarios(unittest.TestCase):

    def setUp(self):
        self.synth = Synthesizer()

    def test_scenario_carbon_tax(self):
        """Carbon tax: moderate short-term harm, major long-term ecological benefit."""
        outputs = [
            make_output("economic",
                overall_harm_score=0.35, overall_benefit_score=0.55, confidence=0.75,
                findings=[
                    make_finding("Fossil fuel job losses in transition regions",
                        direction=ImpactDirection.HARM, timeframe=ImpactTimeframe.SHORT_TERM,
                        magnitude=0.5, affected_groups=["fossil fuel workers", "rural communities"],
                        tags=["economic"]),
                    make_finding("Revenue for green investment and worker transition funds",
                        direction=ImpactDirection.BENEFIT, timeframe=ImpactTimeframe.MEDIUM_TERM,
                        magnitude=0.6, affected_groups=["workers"], tags=["economic"]),
                ],
            ),
            make_output("ecological",
                overall_harm_score=0.05, overall_benefit_score=0.85, confidence=0.85,
                findings=[
                    make_finding("Significant reduction in greenhouse gas emissions",
                        direction=ImpactDirection.BENEFIT, timeframe=ImpactTimeframe.LONG_TERM,
                        magnitude=0.85, affected_groups=["future generations"],
                        tags=["ecological"]),
                ],
            ),
            make_output("social_demographic",
                overall_harm_score=0.25, overall_benefit_score=0.6, confidence=0.7,
                adversarial_challenges=[
                    "Carbon taxes are regressive — low-income households pay a higher share of income.",
                    "Rural communities have fewer alternatives to fossil fuels and will bear disproportionate cost.",
                ],
            ),
        ]
        cmap = self.synth.synthesize("National carbon tax $50/tonne", "m-carbon", outputs)
        self.assertEqual(cmap.overall_verdict, OverallVerdict.NET_BENEFICIAL)
        self.assertGreater(len(cmap.adversarial_challenges), 0)
        self.assertGreater(len(cmap.timeframe_impacts), 0)
        # Should detect ripple from ecological benefit
        self.assertIsInstance(cmap.ripple_effects, list)

    def test_scenario_deforestation(self):
        """Deforestation: major ecological harm, narrow economic benefit."""
        outputs = [
            make_output("ecological",
                overall_harm_score=0.92, overall_benefit_score=0.05, confidence=0.9,
                findings=[
                    make_finding("Permanent loss of biodiversity in cleared areas",
                        direction=ImpactDirection.HARM, timeframe=ImpactTimeframe.IMMEDIATE,
                        magnitude=0.95, reversible=False,
                        affected_groups=["animals and wildlife", "indigenous peoples"],
                        tags=["ecological"]),
                    make_finding("Accelerated carbon release from forest burning",
                        direction=ImpactDirection.HARM, timeframe=ImpactTimeframe.SHORT_TERM,
                        magnitude=0.8, affected_groups=["future generations"], tags=["ecological"]),
                ],
            ),
            make_output("economic",
                overall_harm_score=0.3, overall_benefit_score=0.4, confidence=0.7,
                findings=[
                    make_finding("Short-term agricultural export revenue for corporate operators",
                        direction=ImpactDirection.BENEFIT, timeframe=ImpactTimeframe.SHORT_TERM,
                        magnitude=0.4, affected_groups=["large corporations"], tags=["economic"]),
                ],
            ),
            make_output("ethical_adversarial",
                overall_harm_score=0.9, overall_benefit_score=0.1, confidence=0.95,
                adversarial_challenges=[
                    "Benefits accrue to a narrow corporate class while harms are distributed globally.",
                    "Indigenous communities face displacement without consent.",
                    "Irreversible destruction cannot be justified by short-term profit.",
                ],
            ),
        ]
        cmap = self.synth.synthesize("Amazon deforestation for agriculture", "m-deforest", outputs)
        self.assertEqual(cmap.overall_verdict, OverallVerdict.NET_HARMFUL)
        self.assertGreater(len(cmap.adversarial_challenges), 0)
        irreversible_harms = [f for f in cmap.all_harm_findings if f.reversible is False]
        self.assertGreater(len(irreversible_harms), 0)

    def test_scenario_universal_healthcare(self):
        """Universal healthcare: mixed economic picture, major social benefit."""
        outputs = [
            make_output("economic",
                overall_harm_score=0.3, overall_benefit_score=0.6, confidence=0.65,
                uncertainty_notes=[
                    UncertaintyNote(
                        description="Long-term fiscal impact depends heavily on administrative efficiency assumptions.",
                        impact_on_analysis="Benefit estimates may be overoptimistic.",
                        magnitude=0.6,
                    )
                ],
            ),
            make_output("social_demographic",
                overall_harm_score=0.1, overall_benefit_score=0.88, confidence=0.85,
                findings=[
                    make_finding("Elimination of medical bankruptcy for low-income families",
                        direction=ImpactDirection.BENEFIT, timeframe=ImpactTimeframe.SHORT_TERM,
                        magnitude=0.8, affected_groups=["low-income populations", "elderly"],
                        tags=["social"]),
                    make_finding("Improved preventive care access reduces long-term mortality",
                        direction=ImpactDirection.BENEFIT, timeframe=ImpactTimeframe.LONG_TERM,
                        magnitude=0.75, affected_groups=["children and youth", "elderly"],
                        tags=["social"]),
                ],
            ),
            make_output("legal_institutional",
                overall_harm_score=0.2, overall_benefit_score=0.5, confidence=0.7,
                adversarial_challenges=[
                    "Mandatory participation may conflict with individual autonomy rights.",
                ],
            ),
        ]
        cmap = self.synth.synthesize("Universal healthcare legislation", "m-health", outputs)
        self.assertIn(cmap.overall_verdict, [OverallVerdict.NET_BENEFICIAL, OverallVerdict.MIXED])
        populations = {p.population for p in cmap.population_impacts}
        self.assertIn("low-income populations", populations)
        self.assertGreater(len(cmap.uncertainty_register), 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
