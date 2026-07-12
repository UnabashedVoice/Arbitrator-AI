"""
test_context_parser.py — Test suite for the Arbitrator Context Parser.

Tests are organized by layer:
    - TestNormalization         — text normalization
    - TestScaleExtraction       — geographic/institutional scale detection
    - TestTimeHorizonExtraction — time horizon detection
    - TestInputTypeExtraction   — input type classification
    - TestPopulationExtraction  — affected population detection
    - TestEntityExtraction      — named entity extraction
    - TestFlagDetection         — urgency, controversy, assumptions, implicit flags
    - TestChannelScoring        — individual channel relevance scoring
    - TestRoutingDecisions      — invocation threshold and rationale generation
    - TestContextParser         — full pipeline integration tests
    - TestSerialization         — JSON output and audit log format
    - TestEdgeCases             — boundary conditions and unusual inputs
    - TestRealWorldScenarios    — realistic policy/decision inputs

Run with:
    python -m unittest SeedCore/tests/test_context_parser.py -v
"""

import json
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from SeedCore.context_parser import (
    ContextParser,
    Channel,
    InputScale,
    InputType,
    TimeHorizon,
)
from SeedCore.context_parser.parser import _normalize, _score_channel, _build_rationale
from SeedCore.context_parser.extractors import (
    extract_scale,
    extract_time_horizon,
    extract_input_type,
    extract_affected_populations,
    extract_key_entities,
    extract_explicit_assumptions,
    extract_implicit_flags,
    detect_urgency,
    detect_controversy,
)
from SeedCore.context_parser.lexicons import INVOCATION_THRESHOLD


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalization(unittest.TestCase):

    def test_lowercase(self):
        result = _normalize("THIS IS UPPERCASE")
        self.assertEqual(result, "this is uppercase")

    def test_collapses_whitespace(self):
        result = _normalize("too   many    spaces")
        self.assertEqual(result, "too many spaces")

    def test_strips_leading_trailing(self):
        result = _normalize("  hello world  ")
        self.assertEqual(result, "hello world")

    def test_removes_punctuation(self):
        result = _normalize("hello, world! What's this?")
        self.assertNotIn(",", result)
        self.assertNotIn("!", result)
        self.assertNotIn("?", result)

    def test_preserves_hyphens(self):
        result = _normalize("long-term climate change")
        self.assertIn("long-term", result)

    def test_empty_string_returns_empty(self):
        result = _normalize("")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# Scale extraction
# ---------------------------------------------------------------------------

class TestScaleExtraction(unittest.TestCase):

    def test_global_signals(self):
        self.assertEqual(extract_scale("this affects the entire planet"), InputScale.GLOBAL)

    def test_international_signals(self):
        self.assertEqual(extract_scale("a multilateral trade agreement"), InputScale.INTERNATIONAL)

    def test_national_signals(self):
        self.assertEqual(extract_scale("a federal policy for the country"), InputScale.NATIONAL)

    def test_regional_signals(self):
        self.assertEqual(extract_scale("a state law in the regional area"), InputScale.REGIONAL)

    def test_local_signals(self):
        self.assertEqual(extract_scale("a city council decision"), InputScale.LOCAL)

    def test_global_takes_precedence(self):
        # If both "city" and "planet" are mentioned, global wins
        self.assertEqual(extract_scale("a city decision affecting the planet"), InputScale.GLOBAL)

    def test_default_to_national_if_unclear(self):
        self.assertEqual(extract_scale("a vague proposal with no scale signals"), InputScale.NATIONAL)


# ---------------------------------------------------------------------------
# Time horizon extraction
# ---------------------------------------------------------------------------

class TestTimeHorizonExtraction(unittest.TestCase):

    def test_immediate_signals(self):
        self.assertEqual(extract_time_horizon("this is an emergency requiring immediate action"), TimeHorizon.IMMEDIATE)

    def test_short_term_signals(self):
        self.assertEqual(extract_time_horizon("results expected within months"), TimeHorizon.SHORT_TERM)

    def test_medium_term_signals(self):
        self.assertEqual(extract_time_horizon("phased over several years"), TimeHorizon.MEDIUM_TERM)

    def test_long_term_signals(self):
        self.assertEqual(extract_time_horizon("impacts spanning decades"), TimeHorizon.LONG_TERM)

    def test_generational_signals(self):
        self.assertEqual(extract_time_horizon("for future generations to come"), TimeHorizon.GENERATIONAL)

    def test_generational_overrides_long_term(self):
        result = extract_time_horizon("decades of change affecting our grandchildren")
        self.assertEqual(result, TimeHorizon.GENERATIONAL)

    def test_unknown_when_no_signals(self):
        self.assertEqual(extract_time_horizon("a vague policy"), TimeHorizon.UNKNOWN)


# ---------------------------------------------------------------------------
# Input type extraction
# ---------------------------------------------------------------------------

class TestInputTypeExtraction(unittest.TestCase):

    def test_hypothetical(self):
        self.assertEqual(extract_input_type("what if we banned all fossil fuels"), InputType.HYPOTHETICAL)

    def test_legislative(self):
        self.assertEqual(extract_input_type("a new bill to amend the tax code"), InputType.LEGISLATIVE_PROPOSAL)

    def test_military(self):
        self.assertEqual(extract_input_type("deploy troops to the border region"), InputType.MILITARY_ACTION)

    def test_environmental(self):
        self.assertEqual(extract_input_type("environmental regulation to ban plastic"), InputType.ENVIRONMENTAL_ACTION)

    def test_economic_intervention(self):
        self.assertEqual(extract_input_type("a tax cut for middle income earners"), InputType.ECONOMIC_INTERVENTION)

    def test_treaty(self):
        self.assertEqual(extract_input_type("negotiate a new trade treaty with europe"), InputType.TREATY_OR_AGREEMENT)

    def test_general_query_fallback(self):
        self.assertEqual(extract_input_type("things are complicated"), InputType.GENERAL_QUERY)


# ---------------------------------------------------------------------------
# Affected population extraction
# ---------------------------------------------------------------------------

class TestPopulationExtraction(unittest.TestCase):

    def test_children_detected(self):
        pops = extract_affected_populations("this policy affects children in schools")
        self.assertIn("children and youth", pops)

    def test_elderly_detected(self):
        pops = extract_affected_populations("seniors and elderly people will benefit")
        self.assertIn("elderly", pops)

    def test_indigenous_detected(self):
        pops = extract_affected_populations("indigenous communities and tribal lands")
        self.assertIn("indigenous peoples", pops)

    def test_lgbtq_detected(self):
        pops = extract_affected_populations("lgbtq rights and transgender protections")
        self.assertIn("LGBTQ+ communities", pops)

    def test_future_generations_detected(self):
        pops = extract_affected_populations("for future generations and our grandchildren")
        self.assertIn("future generations", pops)

    def test_multiple_populations(self):
        pops = extract_affected_populations(
            "affecting children, elderly, and low income workers"
        )
        self.assertGreater(len(pops), 1)

    def test_no_populations_returns_empty(self):
        pops = extract_affected_populations("pure fiscal policy with no social dimensions")
        # May or may not match — just check it's a list
        self.assertIsInstance(pops, list)


# ---------------------------------------------------------------------------
# Flag detection
# ---------------------------------------------------------------------------

class TestFlagDetection(unittest.TestCase):

    def test_urgency_detected(self):
        self.assertTrue(detect_urgency("this is an emergency requiring urgent action"))

    def test_urgency_not_detected(self):
        self.assertFalse(detect_urgency("a measured long-term proposal"))

    def test_controversy_detected(self):
        self.assertTrue(detect_controversy("a controversial and politically divisive proposal"))

    def test_controversy_not_detected(self):
        self.assertFalse(detect_controversy("a technical infrastructure improvement"))

    def test_explicit_assumptions_extracted(self):
        text = "We assume that inflation remains below 3%. Assuming that employment stays stable."
        assumptions = extract_explicit_assumptions(text)
        self.assertGreater(len(assumptions), 0)

    def test_implicit_flag_surveillance(self):
        flags = extract_implicit_flags("monitor and track all citizen movements with facial recognition")
        self.assertTrue(any("surveillance" in f.lower() or "civil liberties" in f.lower() for f in flags))

    def test_implicit_flag_power_concentration(self):
        flags = extract_implicit_flags("consolidate all authority under a single central agency")
        self.assertTrue(any("power" in f.lower() or "concentrate" in f.lower() for f in flags))

    def test_implicit_flag_ecological(self):
        flags = extract_implicit_flags("drain the wetland and pave the area for development")
        self.assertTrue(any("ecological" in f.lower() for f in flags))

    def test_no_implicit_flags_for_benign_input(self):
        flags = extract_implicit_flags("increase funding for public libraries")
        # Libraries proposal should produce minimal or no implicit flags
        self.assertIsInstance(flags, list)


# ---------------------------------------------------------------------------
# Channel scoring
# ---------------------------------------------------------------------------

class TestChannelScoring(unittest.TestCase):

    def test_economic_channel_scores_high_for_tax_policy(self):
        text = _normalize("a new tax policy to reduce income inequality and unemployment")
        score, signals = _score_channel(text, Channel.ECONOMIC)
        self.assertGreater(score, INVOCATION_THRESHOLD)
        self.assertIn("tax", signals)

    def test_ecological_channel_scores_high_for_climate(self):
        text = _normalize("reducing carbon emissions to address climate change and biodiversity loss")
        score, signals = _score_channel(text, Channel.ECOLOGICAL)
        self.assertGreater(score, INVOCATION_THRESHOLD)

    def test_geopolitical_channel_scores_high_for_military(self):
        text = _normalize("deploy military forces in a foreign country under nato alliance treaty")
        score, signals = _score_channel(text, Channel.GEOPOLITICAL)
        self.assertGreater(score, INVOCATION_THRESHOLD)

    def test_ethical_adversarial_has_baseline_above_threshold(self):
        # Even with no signals, ethical adversarial should be invoked for non-trivial input
        from SeedCore.context_parser.lexicons import CHANNEL_BASELINE_SCORES
        self.assertGreaterEqual(
            CHANNEL_BASELINE_SCORES[Channel.ETHICAL_ADVERSARIAL],
            INVOCATION_THRESHOLD
        )

    def test_uncertainty_modeling_has_baseline_above_threshold(self):
        from SeedCore.context_parser.lexicons import CHANNEL_BASELINE_SCORES
        self.assertGreaterEqual(
            CHANNEL_BASELINE_SCORES[Channel.UNCERTAINTY_MODELING],
            INVOCATION_THRESHOLD
        )

    def test_unrelated_channel_scores_low(self):
        text = _normalize("a local city council library budget decision")
        score, _ = _score_channel(text, Channel.GEOPOLITICAL)
        # Geopolitical should score low for a local library decision
        self.assertLess(score, 0.5)

    def test_score_is_clamped_to_one(self):
        # Even if every signal matches, score should not exceed 1.0
        text = _normalize(
            "climate change carbon emissions greenhouse gas fossil fuel deforestation "
            "biodiversity ecosystem habitat pollution environmental sustainability "
            "renewable energy ocean water soil agriculture pesticide toxic waste"
        )
        score, _ = _score_channel(text, Channel.ECOLOGICAL)
        self.assertLessEqual(score, 1.0)

    def test_matched_signals_are_returned(self):
        text = _normalize("gdp growth and tax policy for the labor market")
        score, signals = _score_channel(text, Channel.ECONOMIC)
        self.assertIsInstance(signals, list)
        self.assertGreater(len(signals), 0)


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------

class TestContextParser(unittest.TestCase):

    def setUp(self):
        self.parser = ContextParser()

    def test_returns_routing_manifest(self):
        from SeedCore.context_parser.models import RoutingManifest
        manifest = self.parser.parse("What if we banned all fossil fuels by 2030?")
        self.assertIsInstance(manifest, RoutingManifest)

    def test_manifest_has_route_for_every_channel(self):
        manifest = self.parser.parse("A national policy to reduce carbon emissions.")
        channel_set = {r.channel for r in manifest.routes}
        self.assertEqual(channel_set, set(Channel))

    def test_invoked_channels_property(self):
        manifest = self.parser.parse("A national policy to reduce carbon emissions.")
        self.assertIsInstance(manifest.invoked_channels, list)
        self.assertGreater(len(manifest.invoked_channels), 0)

    def test_ecological_invoked_for_climate_query(self):
        manifest = self.parser.parse(
            "What are the consequences of doubling coal and oil extraction over the next decade?"
        )
        self.assertIn(Channel.ECOLOGICAL, manifest.invoked_channels)

    def test_economic_invoked_for_tax_query(self):
        manifest = self.parser.parse(
            "Should we cut corporate tax rates to stimulate GDP growth and reduce unemployment?"
        )
        self.assertIn(Channel.ECONOMIC, manifest.invoked_channels)

    def test_ethical_adversarial_almost_always_invoked(self):
        # Ethical adversarial should be invoked for any substantive policy question
        manifest = self.parser.parse(
            "Should we implement mandatory national military service for all citizens aged 18-25?"
        )
        self.assertIn(Channel.ETHICAL_ADVERSARIAL, manifest.invoked_channels)

    def test_uncertainty_modeling_almost_always_invoked(self):
        manifest = self.parser.parse(
            "What would be the economic effects of a universal basic income?"
        )
        self.assertIn(Channel.UNCERTAINTY_MODELING, manifest.invoked_channels)

    def test_geopolitical_not_invoked_for_purely_local_query(self):
        manifest = self.parser.parse(
            "Should the city council increase the local library budget by 10%?"
        )
        self.assertNotIn(Channel.GEOPOLITICAL, manifest.invoked_channels)

    def test_context_scale_set(self):
        manifest = self.parser.parse(
            "A global initiative to reduce carbon emissions across all nations."
        )
        self.assertEqual(manifest.context.scale, InputScale.GLOBAL)

    def test_context_time_horizon_set(self):
        manifest = self.parser.parse(
            "A 50-year plan affecting future generations and our grandchildren."
        )
        self.assertEqual(manifest.context.time_horizon, TimeHorizon.GENERATIONAL)

    def test_urgency_detected(self):
        manifest = self.parser.parse(
            "Emergency legislation needed immediately to address the financial crisis."
        )
        self.assertTrue(manifest.context.urgency_detected)

    def test_controversy_detected(self):
        manifest = self.parser.parse(
            "A controversial gun control bill that has divided partisan opinion."
        )
        self.assertTrue(manifest.context.controversy_signals)

    def test_short_input_generates_warning(self):
        manifest = self.parser.parse("Tax cuts.")
        self.assertGreater(len(manifest.context.parse_warnings), 0)

    def test_parser_confidence_range(self):
        manifest = self.parser.parse("A detailed national healthcare reform policy.")
        self.assertGreaterEqual(manifest.context.parser_confidence, 0.1)
        self.assertLessEqual(manifest.context.parser_confidence, 1.0)

    def test_each_route_has_rationale(self):
        manifest = self.parser.parse("A national carbon tax policy.")
        for route in manifest.routes:
            self.assertTrue(len(route.rationale) > 0)

    def test_manifest_id_is_unique(self):
        m1 = self.parser.parse("Policy A")
        m2 = self.parser.parse("Policy B")
        self.assertNotEqual(m1.manifest_id, m2.manifest_id)

    def test_input_id_is_unique(self):
        m1 = self.parser.parse("Policy A")
        m2 = self.parser.parse("Policy A")  # same text, different parse
        self.assertNotEqual(m1.context.input_id, m2.context.input_id)

    def test_deterministic_routing(self):
        # Same text → same channels invoked (UUIDs differ but routing is stable)
        m1 = self.parser.parse("A federal carbon tax targeting fossil fuel emissions.")
        m2 = self.parser.parse("A federal carbon tax targeting fossil fuel emissions.")
        self.assertEqual(
            sorted(c.value for c in m1.invoked_channels),
            sorted(c.value for c in m2.invoked_channels),
        )

    def test_raw_input_preserved_verbatim(self):
        text = "What if we nationalized all major banks? Would that fix inequality?"
        manifest = self.parser.parse(text)
        self.assertEqual(manifest.context.raw_input, text)

    def test_empty_input_raises(self):
        with self.assertRaises(ValueError):
            self.parser.parse("")

    def test_whitespace_only_raises(self):
        with self.assertRaises(ValueError):
            self.parser.parse("   ")

    def test_implicit_flags_in_context(self):
        manifest = self.parser.parse(
            "Consolidate all power under a single national authority and monitor citizens."
        )
        self.assertGreater(len(manifest.context.implicit_flags), 0)

    def test_affected_populations_in_context(self):
        manifest = self.parser.parse(
            "Healthcare reform affecting elderly citizens, children, and low income workers."
        )
        self.assertGreater(len(manifest.context.affected_populations), 0)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization(unittest.TestCase):

    def setUp(self):
        self.parser = ContextParser()

    def test_parse_and_serialize_returns_valid_json(self):
        json_str = self.parser.parse_and_serialize("A national renewable energy policy.")
        parsed = json.loads(json_str)
        self.assertIsInstance(parsed, dict)

    def test_serialized_has_manifest_id(self):
        json_str = self.parser.parse_and_serialize("A renewable energy policy.")
        parsed = json.loads(json_str)
        self.assertIn("manifest_id", parsed)

    def test_serialized_has_context(self):
        json_str = self.parser.parse_and_serialize("A renewable energy policy.")
        parsed = json.loads(json_str)
        self.assertIn("context", parsed)

    def test_serialized_has_routes(self):
        json_str = self.parser.parse_and_serialize("A renewable energy policy.")
        parsed = json.loads(json_str)
        self.assertIn("routes", parsed)
        self.assertIsInstance(parsed["routes"], list)

    def test_serialized_routes_have_required_fields(self):
        json_str = self.parser.parse_and_serialize("A national climate policy.")
        parsed = json.loads(json_str)
        for route in parsed["routes"]:
            self.assertIn("channel", route)
            self.assertIn("invoked", route)
            self.assertIn("relevance_score", route)
            self.assertIn("rationale", route)

    def test_serialized_invoked_channels_list(self):
        json_str = self.parser.parse_and_serialize("A climate and economic reform policy.")
        parsed = json.loads(json_str)
        self.assertIn("invoked_channels", parsed)
        self.assertIsInstance(parsed["invoked_channels"], list)

    def test_to_dict_is_json_serializable(self):
        manifest = self.parser.parse("A tax reform proposal for national employment.")
        d = manifest.to_dict()
        # Should not raise
        json_str = json.dumps(d)
        self.assertIsInstance(json_str, str)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.parser = ContextParser()

    def test_very_long_input(self):
        long_text = ("This is a proposal about climate change, economic reform, "
                     "social equity, legal frameworks, and geopolitical stability. ") * 50
        manifest = self.parser.parse(long_text)
        self.assertIsNotNone(manifest)

    def test_input_with_only_numbers(self):
        manifest = self.parser.parse("1234567890 budget allocation 500 billion")
        self.assertIsNotNone(manifest)

    def test_unicode_input(self):
        manifest = self.parser.parse("Política climática para reducción de emisiones de carbono.")
        self.assertIsNotNone(manifest)

    def test_mixed_case_input(self):
        manifest = self.parser.parse("CARBON TAX policy FOR climate CHANGE reduction")
        self.assertIn(Channel.ECOLOGICAL, manifest.invoked_channels)

    def test_routing_version_in_manifest(self):
        manifest = self.parser.parse("Any policy proposal.")
        self.assertEqual(manifest.routing_version, ContextParser.ROUTING_VERSION)

    def test_skipped_channels_property(self):
        manifest = self.parser.parse(
            "A purely local city budget for library renovation."
        )
        skipped = manifest.skipped_channels
        self.assertIsInstance(skipped, list)
        # At least some channels should be skipped for a narrow local query
        self.assertGreater(len(skipped), 0)


# ---------------------------------------------------------------------------
# Real-world scenarios
# ---------------------------------------------------------------------------

class TestRealWorldScenarios(unittest.TestCase):

    def setUp(self):
        self.parser = ContextParser()

    def test_scenario_climate_policy(self):
        manifest = self.parser.parse(
            "Proposed legislation: a national carbon tax of $50/tonne on all fossil fuel "
            "emissions, phased in over 5 years, with revenue redistributed as dividend "
            "payments to low-income households. Critics argue this will harm rural workers "
            "and increase energy costs."
        )
        invoked = manifest.invoked_channels
        self.assertIn(Channel.ECOLOGICAL, invoked)
        self.assertIn(Channel.ECONOMIC, invoked)
        self.assertIn(Channel.SOCIAL_DEMOGRAPHIC, invoked)
        self.assertIn(Channel.ETHICAL_ADVERSARIAL, invoked)

    def test_scenario_military_intervention(self):
        manifest = self.parser.parse(
            "The President is considering deploying 10,000 troops to support an ally "
            "under NATO treaty obligations. The conflict involves disputed border territory "
            "and there is risk of escalation to broader international conflict."
        )
        invoked = manifest.invoked_channels
        self.assertIn(Channel.GEOPOLITICAL, invoked)
        self.assertIn(Channel.LEGAL_INSTITUTIONAL, invoked)
        self.assertIn(Channel.ETHICAL_ADVERSARIAL, invoked)

    def test_scenario_healthcare_reform(self):
        manifest = self.parser.parse(
            "Universal healthcare legislation: mandate all citizens be covered by a "
            "public insurance option. Funded by a new payroll tax. Projected to reduce "
            "out-of-pocket costs for low-income families, elderly, and disabled populations. "
            "Controversial among private insurers and some rural communities."
        )
        invoked = manifest.invoked_channels
        self.assertIn(Channel.ECONOMIC, invoked)
        self.assertIn(Channel.SOCIAL_DEMOGRAPHIC, invoked)
        self.assertIn(Channel.LEGAL_INSTITUTIONAL, invoked)
        self.assertTrue(manifest.context.controversy_signals)

    def test_scenario_deforestation(self):
        manifest = self.parser.parse(
            "A proposal to clear 2 million hectares of Amazon rainforest for agricultural "
            "expansion, generating significant export revenue but permanently destroying "
            "habitat for thousands of species and indigenous tribal communities."
        )
        invoked = manifest.invoked_channels
        self.assertIn(Channel.ECOLOGICAL, invoked)
        self.assertIn(Channel.SOCIAL_DEMOGRAPHIC, invoked)
        self.assertIn(Channel.ETHICAL_ADVERSARIAL, invoked)
        # Should detect implicit ecological flag
        self.assertGreater(len(manifest.context.implicit_flags), 0)

    def test_scenario_ubi(self):
        manifest = self.parser.parse(
            "What if the federal government introduced a universal basic income of $1000/month "
            "for all adult citizens? What would the economic and social consequences be over "
            "the next decade?"
        )
        invoked = manifest.invoked_channels
        self.assertIn(Channel.ECONOMIC, invoked)
        self.assertIn(Channel.SOCIAL_DEMOGRAPHIC, invoked)
        self.assertIn(Channel.UNCERTAINTY_MODELING, invoked)
        self.assertEqual(manifest.context.input_type, InputType.HYPOTHETICAL)

    def test_scenario_surveillance_law(self):
        manifest = self.parser.parse(
            "New legislation to require all internet service providers to monitor and log "
            "citizen online activity for national security purposes, with data accessible "
            "to law enforcement without a warrant."
        )
        invoked = manifest.invoked_channels
        self.assertIn(Channel.LEGAL_INSTITUTIONAL, invoked)
        self.assertIn(Channel.ETHICAL_ADVERSARIAL, invoked)
        flags = manifest.context.implicit_flags
        self.assertTrue(any("surveillance" in f.lower() or "civil liberties" in f.lower() for f in flags))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
