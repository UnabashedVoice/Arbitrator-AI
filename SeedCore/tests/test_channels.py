"""
test_channels.py — Test suite for all eight Arbitrator specialist channels.

Tests are organized by layer:
    - TestMockBackend               — backend interface and mock behavior
    - TestResponseParser            — JSON extraction and field parsing
    - TestBaseChannel               — shared prompt/invoke infrastructure
    - TestPrimaryChannels           — economic, ecological, social, adversarial
    - TestSecondaryChannels         — historical, legal, geopolitical, uncertainty
    - TestChannelPrompts            — prompt content and cross-domain signal structure
    - TestChannelRegistry           — registry after real implementations registered
    - TestEndToEnd                  — full channel → ChannelOutput flow

Run with:
    python -m unittest SeedCore/tests/test_channels.py -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from SeedCore.channels import (
    EconomicChannel, EcologicalChannel, SocialDemographicChannel,
    EthicalAdversarialChannel, HistoricalPrecedentChannel,
    LegalInstitutionalChannel, GeopoliticalChannel, UncertaintyModelingChannel,
    MockBackend, BackendError,
    parse_channel_response, RESPONSE_SCHEMA,
    BaseChannel,
)
from SeedCore.channels.backend import _default_mock_response
from SeedCore.orchestrator import (
    CHANNEL_REGISTRY, invoke_channel, is_stub,
    implemented_channels, stub_channels,
)
from SeedCore.synthesis.channel_output import (
    ChannelOutput, ChannelStatus, ImpactDirection,
    ImpactTimeframe, ImpactCertainty, Finding, UncertaintyNote,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_CHANNELS = [
    "economic", "ecological", "social_demographic", "ethical_adversarial",
    "historical_precedent", "legal_institutional", "geopolitical", "uncertainty_modeling",
]

PRIMARY_CHANNELS = [
    "economic", "ecological", "social_demographic", "ethical_adversarial",
]

SECONDARY_CHANNELS = [
    "historical_precedent", "legal_institutional", "geopolitical", "uncertainty_modeling",
]

SAMPLE_INPUT = (
    "Proposed legislation: a national carbon tax of $50 per tonne on all "
    "fossil fuel emissions, phased in over 5 years, with revenue redistributed "
    "as dividend payments to low-income households."
)

SAMPLE_CONTEXT = {
    "input_type": "legislative_proposal",
    "scale": "national",
    "time_horizon": "long_term",
    "affected_populations": ["low-income households", "fossil fuel workers", "rural communities"],
    "domains_mentioned": ["economic", "ecological", "social"],
    "implicit_flags": [
        "may disproportionately burden rural and low-income communities in transition"
    ],
    "parser_confidence": 0.82,
    "parse_warnings": [],
}

def make_mock_channel(channel_name: str, custom_response: dict = None) -> BaseChannel:
    """Create a channel instance with a mock backend."""
    mock = MockBackend()
    if custom_response:
        mock.add_response(channel_name, custom_response)
    classes = {
        "economic": EconomicChannel,
        "ecological": EcologicalChannel,
        "social_demographic": SocialDemographicChannel,
        "ethical_adversarial": EthicalAdversarialChannel,
        "historical_precedent": HistoricalPrecedentChannel,
        "legal_institutional": LegalInstitutionalChannel,
        "geopolitical": GeopoliticalChannel,
        "uncertainty_modeling": UncertaintyModelingChannel,
    }
    return classes[channel_name](backend=mock)


def make_valid_response(channel_name: str, n_findings: int = 3) -> dict:
    """Build a fully valid mock response for a channel."""
    findings = []
    for i in range(n_findings):
        findings.append({
            "summary": f"Finding {i+1} from {channel_name} analysis.",
            "detail": f"Detailed analysis for finding {i+1}.",
            "direction": "harm" if i % 2 == 0 else "benefit",
            "timeframe": "medium_term",
            "certainty": "moderate",
            "magnitude": 0.4 + (i * 0.1),
            "affected_groups": ["general population"],
            "reversible": i % 2 == 0,
            "citations": [],
            "tags": [channel_name],
        })
    return {
        "domain_summary": f"Comprehensive {channel_name} analysis of the proposal.",
        "overall_harm_score": 0.35,
        "overall_benefit_score": 0.65,
        "confidence": 0.72,
        "findings": findings,
        "uncertainty_notes": [
            {
                "description": "Behavioral responses are uncertain.",
                "impact_on_analysis": "Actual uptake may differ from projected.",
                "magnitude": 0.4,
            }
        ],
        "adversarial_challenges": [] if channel_name != "ethical_adversarial" else [
            "Who primarily benefits from this policy design?",
            "Could this mechanism be captured by industry interests?",
        ],
    }


# ---------------------------------------------------------------------------
# MockBackend tests
# ---------------------------------------------------------------------------

class TestMockBackend(unittest.TestCase):

    def test_complete_returns_string(self):
        mock = MockBackend()
        result = mock.complete("CHANNEL: economic\nSystem.", "User prompt.")
        self.assertIsInstance(result, str)

    def test_complete_returns_valid_json(self):
        mock = MockBackend()
        result = mock.complete("CHANNEL: economic\nSystem.", "User prompt.")
        data = json.loads(result)
        self.assertIsInstance(data, dict)

    def test_channel_name_extracted_from_system_prompt(self):
        mock = MockBackend()
        mock.add_response("economic", {"domain_summary": "Custom economic response",
                                        "overall_harm_score": 0.1,
                                        "overall_benefit_score": 0.9,
                                        "confidence": 0.8,
                                        "findings": [], "uncertainty_notes": [],
                                        "adversarial_challenges": []})
        result = mock.complete("CHANNEL: economic\nSystem.", "User.")
        data = json.loads(result)
        self.assertEqual(data["domain_summary"], "Custom economic response")

    def test_default_response_for_unregistered_channel(self):
        mock = MockBackend()
        result = mock.complete("CHANNEL: unknown_channel\nSystem.", "User.")
        data = json.loads(result)
        self.assertIn("domain_summary", data)

    def test_call_log_records_invocations(self):
        mock = MockBackend()
        mock.complete("CHANNEL: economic\nSystem.", "User.")
        mock.complete("CHANNEL: ecological\nSystem.", "User.")
        self.assertEqual(len(mock.call_log), 2)

    def test_reset_clears_call_log(self):
        mock = MockBackend()
        mock.complete("CHANNEL: economic\nSystem.", "User.")
        mock.reset()
        self.assertEqual(len(mock.call_log), 0)

    def test_is_available_always_true(self):
        mock = MockBackend()
        self.assertTrue(mock.is_available())

    def test_model_id(self):
        mock = MockBackend()
        self.assertIn("mock", mock.model_id.lower())


# ---------------------------------------------------------------------------
# ResponseParser tests
# ---------------------------------------------------------------------------

class TestResponseParser(unittest.TestCase):

    def test_parses_clean_json(self):
        response = json.dumps(make_valid_response("economic"))
        output = parse_channel_response(response, "economic", "test-model")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    def test_parses_json_with_markdown_fence(self):
        data = make_valid_response("ecological")
        response = f"```json\n{json.dumps(data)}\n```"
        output = parse_channel_response(response, "ecological", "test-model")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    def test_parses_json_with_preamble(self):
        data = make_valid_response("social_demographic")
        response = f"Here is my analysis:\n\n{json.dumps(data)}"
        output = parse_channel_response(response, "social_demographic", "test-model")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    def test_fails_on_invalid_json(self):
        output = parse_channel_response("This is not JSON at all.", "economic", "test-model")
        self.assertEqual(output.status, ChannelStatus.FAILED)
        self.assertIsNotNone(output.error_message)

    def test_findings_parsed_correctly(self):
        response = json.dumps(make_valid_response("economic", n_findings=4))
        output = parse_channel_response(response, "economic", "test-model")
        self.assertEqual(len(output.findings), 4)

    def test_finding_direction_parsed(self):
        data = make_valid_response("economic", n_findings=2)
        data["findings"][0]["direction"] = "harm"
        data["findings"][1]["direction"] = "benefit"
        output = parse_channel_response(json.dumps(data), "economic", "test-model")
        self.assertEqual(output.findings[0].direction, ImpactDirection.HARM)
        self.assertEqual(output.findings[1].direction, ImpactDirection.BENEFIT)

    def test_finding_timeframe_parsed(self):
        data = make_valid_response("economic", n_findings=1)
        data["findings"][0]["timeframe"] = "generational"
        output = parse_channel_response(json.dumps(data), "economic", "test-model")
        self.assertEqual(output.findings[0].timeframe, ImpactTimeframe.GENERATIONAL)

    def test_finding_certainty_parsed(self):
        data = make_valid_response("economic", n_findings=1)
        data["findings"][0]["certainty"] = "high"
        output = parse_channel_response(json.dumps(data), "economic", "test-model")
        self.assertEqual(output.findings[0].certainty, ImpactCertainty.HIGH)

    def test_channel_name_added_to_tags(self):
        data = make_valid_response("ecological", n_findings=1)
        data["findings"][0]["tags"] = []
        output = parse_channel_response(json.dumps(data), "ecological", "test-model")
        self.assertIn("ecological", output.findings[0].tags)

    def test_scores_clamped_to_01(self):
        data = make_valid_response("economic")
        data["overall_harm_score"] = 1.5
        data["overall_benefit_score"] = -0.3
        output = parse_channel_response(json.dumps(data), "economic", "test-model")
        self.assertEqual(output.overall_harm_score, 1.0)
        self.assertEqual(output.overall_benefit_score, 0.0)

    def test_uncertainty_notes_parsed(self):
        data = make_valid_response("economic")
        output = parse_channel_response(json.dumps(data), "economic", "test-model")
        self.assertEqual(len(output.uncertainty_notes), 1)
        self.assertIsInstance(output.uncertainty_notes[0], UncertaintyNote)

    def test_adversarial_challenges_parsed(self):
        data = make_valid_response("ethical_adversarial")
        output = parse_channel_response(json.dumps(data), "ethical_adversarial", "test-model")
        self.assertEqual(len(output.adversarial_challenges), 2)

    def test_missing_findings_defaults_to_empty(self):
        data = make_valid_response("economic")
        del data["findings"]
        output = parse_channel_response(json.dumps(data), "economic", "test-model")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)
        self.assertEqual(output.findings, [])

    def test_lenient_direction_aliases(self):
        for alias, expected in [("negative", ImpactDirection.HARM),
                                 ("positive", ImpactDirection.BENEFIT),
                                 ("both", ImpactDirection.MIXED)]:
            data = make_valid_response("economic", n_findings=1)
            data["findings"][0]["direction"] = alias
            output = parse_channel_response(json.dumps(data), "economic", "test-model")
            self.assertEqual(output.findings[0].direction, expected)

    def test_processing_time_preserved(self):
        data = make_valid_response("economic")
        output = parse_channel_response(json.dumps(data), "economic", "test-model",
                                        processing_time_ms=250)
        self.assertEqual(output.processing_time_ms, 250)


# ---------------------------------------------------------------------------
# BaseChannel / prompt infrastructure tests
# ---------------------------------------------------------------------------

class TestBaseChannel(unittest.TestCase):

    def test_channel_is_callable(self):
        ch = make_mock_channel("economic")
        self.assertTrue(callable(ch))

    def test_analyze_returns_channel_output(self):
        ch = make_mock_channel("economic", make_valid_response("economic"))
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertIsInstance(output, ChannelOutput)

    def test_call_operator_works(self):
        ch = make_mock_channel("economic", make_valid_response("economic"))
        output = ch(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertIsInstance(output, ChannelOutput)

    def test_system_prompt_contains_channel_marker(self):
        ch = make_mock_channel("economic")
        prompt = ch._build_system_prompt()
        self.assertIn("CHANNEL: economic", prompt)

    def test_system_prompt_contains_prime_directive(self):
        ch = make_mock_channel("ecological")
        prompt = ch._build_system_prompt()
        self.assertIn("PRIME DIRECTIVE", prompt)

    def test_system_prompt_contains_response_schema(self):
        ch = make_mock_channel("social_demographic")
        prompt = ch._build_system_prompt()
        self.assertIn("domain_summary", prompt)
        self.assertIn("overall_harm_score", prompt)
        self.assertIn("findings", prompt)

    def test_user_prompt_contains_input(self):
        ch = make_mock_channel("economic")
        prompt = ch._build_user_prompt(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertIn(SAMPLE_INPUT, prompt)

    def test_user_prompt_contains_context_fields(self):
        ch = make_mock_channel("economic")
        prompt = ch._build_user_prompt(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertIn("national", prompt)      # scale
        self.assertIn("long_term", prompt)     # time_horizon

    def test_user_prompt_contains_affected_populations(self):
        ch = make_mock_channel("social_demographic")
        prompt = ch._build_user_prompt(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertIn("low-income", prompt)

    def test_user_prompt_contains_implicit_flags(self):
        ch = make_mock_channel("ethical_adversarial")
        prompt = ch._build_user_prompt(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertIn("disproportionately", prompt)

    def test_backend_error_returns_failed_output(self):
        from SeedCore.channels.backend import ModelBackend
        class FailingBackend(ModelBackend):
            @property
            def model_id(self): return "failing"
            def complete(self, *args, **kwargs):
                raise BackendError("Backend is down")
        ch = EconomicChannel(backend=FailingBackend(), max_retries=0)
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertEqual(output.status, ChannelStatus.FAILED)
        self.assertIsNotNone(output.error_message)

    def test_domain_tags_on_all_channels(self):
        expected_first_tag = {
            "economic": "economic", "ecological": "ecological",
            "social_demographic": "social", "ethical_adversarial": "adversarial",
            "historical_precedent": "historical", "legal_institutional": "legal",
            "geopolitical": "geopolitical", "uncertainty_modeling": "uncertainty",
        }
        for name in ALL_CHANNELS:
            ch = make_mock_channel(name)
            self.assertIsInstance(ch.domain_tags, list)
            self.assertGreater(len(ch.domain_tags), 0)
            self.assertIn(expected_first_tag[name], ch.domain_tags)


# ---------------------------------------------------------------------------
# Primary channel-specific content tests
# ---------------------------------------------------------------------------

class TestPrimaryChannels(unittest.TestCase):

    def _invoke(self, channel_name: str) -> ChannelOutput:
        ch = make_mock_channel(channel_name, make_valid_response(channel_name))
        return ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)

    # Economic
    def test_economic_channel_name(self):
        self.assertEqual(EconomicChannel(backend=MockBackend()).channel_name, "economic")

    def test_economic_instructions_mention_incidence(self):
        ch = EconomicChannel(backend=MockBackend())
        self.assertIn("INCIDENCE", ch.analysis_instructions)

    def test_economic_instructions_mention_distributional(self):
        ch = EconomicChannel(backend=MockBackend())
        self.assertIn("DISTRIBUTIONAL", ch.analysis_instructions)

    def test_economic_instructions_contain_cross_domain_flags(self):
        ch = EconomicChannel(backend=MockBackend())
        for flag in ["flag_legal", "flag_geopolitical", "flag_historical", "flag_uncertainty"]:
            self.assertIn(flag, ch.analysis_instructions)

    def test_economic_analyze_returns_success(self):
        output = self._invoke("economic")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    def test_economic_analyze_has_findings(self):
        output = self._invoke("economic")
        self.assertGreater(len(output.findings), 0)

    # Ecological
    def test_ecological_channel_name(self):
        self.assertEqual(EcologicalChannel(backend=MockBackend()).channel_name, "ecological")

    def test_ecological_instructions_mention_irreversibility(self):
        ch = EcologicalChannel(backend=MockBackend())
        self.assertIn("IRREVERSIBLE", ch.analysis_instructions)

    def test_ecological_instructions_mention_biodiversity(self):
        ch = EcologicalChannel(backend=MockBackend())
        self.assertIn("BIODIVERSITY", ch.analysis_instructions)

    def test_ecological_instructions_mention_non_human(self):
        ch = EcologicalChannel(backend=MockBackend())
        self.assertIn("non-human", ch.analysis_instructions.lower())

    def test_ecological_instructions_contain_cross_domain_flags(self):
        ch = EcologicalChannel(backend=MockBackend())
        for flag in ["flag_legal", "flag_geopolitical", "flag_historical", "flag_uncertainty"]:
            self.assertIn(flag, ch.analysis_instructions)

    def test_ecological_analyze_returns_success(self):
        output = self._invoke("ecological")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    # Social/Demographic
    def test_social_channel_name(self):
        self.assertEqual(SocialDemographicChannel(backend=MockBackend()).channel_name, "social_demographic")

    def test_social_instructions_mention_disaggregation(self):
        ch = SocialDemographicChannel(backend=MockBackend())
        self.assertIn("DISAGGREGATION", ch.analysis_instructions)

    def test_social_instructions_mention_civil_liberties(self):
        ch = SocialDemographicChannel(backend=MockBackend())
        self.assertIn("CIVIL LIBERTIES", ch.analysis_instructions)

    def test_social_instructions_contain_cross_domain_flags(self):
        ch = SocialDemographicChannel(backend=MockBackend())
        for flag in ["flag_legal", "flag_historical", "flag_geopolitical", "flag_uncertainty"]:
            self.assertIn(flag, ch.analysis_instructions)

    def test_social_analyze_returns_success(self):
        output = self._invoke("social_demographic")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    # Ethical Adversarial
    def test_adversarial_channel_name(self):
        self.assertEqual(EthicalAdversarialChannel(backend=MockBackend()).channel_name, "ethical_adversarial")

    def test_adversarial_instructions_mention_seven_analyses(self):
        ch = EthicalAdversarialChannel(backend=MockBackend())
        self.assertIn("SEVEN", ch.analysis_instructions)

    def test_adversarial_instructions_mention_power_concentration(self):
        ch = EthicalAdversarialChannel(backend=MockBackend())
        self.assertIn("POWER CONCENTRATION", ch.analysis_instructions)

    def test_adversarial_instructions_mention_beneficiary_capture(self):
        ch = EthicalAdversarialChannel(backend=MockBackend())
        self.assertIn("beneficiary_capture", ch.analysis_instructions)

    def test_adversarial_instructions_mention_lock_in(self):
        ch = EthicalAdversarialChannel(backend=MockBackend())
        self.assertIn("lock_in", ch.analysis_instructions)

    def test_adversarial_instructions_mention_prime_directive_stress(self):
        ch = EthicalAdversarialChannel(backend=MockBackend())
        self.assertIn("prime_directive_stress", ch.analysis_instructions)

    def test_adversarial_analyze_returns_success(self):
        response = make_valid_response("ethical_adversarial")
        response["adversarial_challenges"] = [
            "Who actually benefits most from this policy?",
            "Could enforcement mechanisms be captured by regulated industries?",
        ]
        ch = make_mock_channel("ethical_adversarial", response)
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertEqual(output.status, ChannelStatus.SUCCESS)
        self.assertGreater(len(output.adversarial_challenges), 0)


# ---------------------------------------------------------------------------
# Secondary channel-specific content tests
# ---------------------------------------------------------------------------

class TestSecondaryChannels(unittest.TestCase):

    def _invoke(self, channel_name: str) -> ChannelOutput:
        ch = make_mock_channel(channel_name, make_valid_response(channel_name))
        return ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)

    # Historical
    def test_historical_channel_name(self):
        self.assertEqual(HistoricalPrecedentChannel(backend=MockBackend()).channel_name, "historical_precedent")

    def test_historical_instructions_mention_flag_signal_processing(self):
        ch = HistoricalPrecedentChannel(backend=MockBackend())
        self.assertIn("flag_historical", ch.analysis_instructions)

    def test_historical_instructions_mention_prediction_accuracy(self):
        ch = HistoricalPrecedentChannel(backend=MockBackend())
        self.assertIn("PREDICTION ACCURACY", ch.analysis_instructions)

    def test_historical_instructions_mention_specificity(self):
        ch = HistoricalPrecedentChannel(backend=MockBackend())
        # Should require specific case naming, not vague references
        self.assertIn("specific", ch.analysis_instructions.lower())

    def test_historical_analyze_returns_success(self):
        output = self._invoke("historical_precedent")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    # Legal/Institutional
    def test_legal_channel_name(self):
        self.assertEqual(LegalInstitutionalChannel(backend=MockBackend()).channel_name, "legal_institutional")

    def test_legal_instructions_mention_flag_signal_processing(self):
        ch = LegalInstitutionalChannel(backend=MockBackend())
        self.assertIn("flag_legal", ch.analysis_instructions)

    def test_legal_instructions_mention_enforcement_design(self):
        ch = LegalInstitutionalChannel(backend=MockBackend())
        self.assertIn("ENFORCEMENT DESIGN", ch.analysis_instructions)

    def test_legal_instructions_mention_institutional_integrity(self):
        ch = LegalInstitutionalChannel(backend=MockBackend())
        self.assertIn("INSTITUTIONAL INTEGRITY", ch.analysis_instructions)

    def test_legal_instructions_mention_accountability(self):
        ch = LegalInstitutionalChannel(backend=MockBackend())
        self.assertIn("accountability", ch.analysis_instructions.lower())

    def test_legal_analyze_returns_success(self):
        output = self._invoke("legal_institutional")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    # Geopolitical
    def test_geopolitical_channel_name(self):
        self.assertEqual(GeopoliticalChannel(backend=MockBackend()).channel_name, "geopolitical")

    def test_geopolitical_instructions_mention_flag_signal_processing(self):
        ch = GeopoliticalChannel(backend=MockBackend())
        self.assertIn("flag_geopolitical", ch.analysis_instructions)

    def test_geopolitical_instructions_mention_alliance_analysis(self):
        ch = GeopoliticalChannel(backend=MockBackend())
        self.assertIn("ALLIANCE", ch.analysis_instructions)

    def test_geopolitical_instructions_mention_smaller_states(self):
        ch = GeopoliticalChannel(backend=MockBackend())
        self.assertIn("smaller", ch.analysis_instructions.lower())

    def test_geopolitical_analyze_returns_success(self):
        output = self._invoke("geopolitical")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)

    # Uncertainty
    def test_uncertainty_channel_name(self):
        self.assertEqual(UncertaintyModelingChannel(backend=MockBackend()).channel_name, "uncertainty_modeling")

    def test_uncertainty_instructions_mention_flag_signal_processing(self):
        ch = UncertaintyModelingChannel(backend=MockBackend())
        self.assertIn("flag_uncertainty", ch.analysis_instructions)

    def test_uncertainty_instructions_mention_sensitivity_analysis(self):
        ch = UncertaintyModelingChannel(backend=MockBackend())
        self.assertIn("SENSITIVITY ANALYSIS", ch.analysis_instructions)

    def test_uncertainty_instructions_mention_tail_risks(self):
        ch = UncertaintyModelingChannel(backend=MockBackend())
        self.assertIn("TAIL RISK", ch.analysis_instructions)

    def test_uncertainty_instructions_mention_three_scenarios(self):
        ch = UncertaintyModelingChannel(backend=MockBackend())
        for scenario in ["OPTIMISTIC", "BASE", "PESSIMISTIC"]:
            self.assertIn(scenario, ch.analysis_instructions)

    def test_uncertainty_instructions_mention_data_gaps(self):
        ch = UncertaintyModelingChannel(backend=MockBackend())
        self.assertIn("DATA GAP", ch.analysis_instructions)

    def test_uncertainty_analyze_returns_success(self):
        output = self._invoke("uncertainty_modeling")
        self.assertEqual(output.status, ChannelStatus.SUCCESS)


# ---------------------------------------------------------------------------
# Cross-domain signal structure tests
# ---------------------------------------------------------------------------

class TestChannelPrompts(unittest.TestCase):
    """
    Verify that the cross-domain signal architecture is correctly embedded
    in the primary channel prompts, and that secondary channels explicitly
    declare they process those signals.
    """

    def test_all_primary_channels_emit_flag_legal(self):
        for name in PRIMARY_CHANNELS:
            if name == "ethical_adversarial":
                continue  # adversarial uses different tag structure
            ch = make_mock_channel(name)
            self.assertIn("flag_legal", ch.analysis_instructions,
                          f"{name} should emit flag_legal signals")

    def test_all_primary_channels_emit_flag_historical(self):
        for name in PRIMARY_CHANNELS:
            if name == "ethical_adversarial":
                continue
            ch = make_mock_channel(name)
            self.assertIn("flag_historical", ch.analysis_instructions,
                          f"{name} should emit flag_historical signals")

    def test_all_primary_channels_emit_flag_geopolitical(self):
        for name in PRIMARY_CHANNELS:
            if name == "ethical_adversarial":
                continue
            ch = make_mock_channel(name)
            self.assertIn("flag_geopolitical", ch.analysis_instructions,
                          f"{name} should emit flag_geopolitical signals")

    def test_all_primary_channels_emit_flag_uncertainty(self):
        for name in PRIMARY_CHANNELS:
            if name == "ethical_adversarial":
                continue
            ch = make_mock_channel(name)
            self.assertIn("flag_uncertainty", ch.analysis_instructions,
                          f"{name} should emit flag_uncertainty signals")

    def test_historical_processes_flag_historical(self):
        ch = make_mock_channel("historical_precedent")
        self.assertIn("flag_historical", ch.analysis_instructions)

    def test_legal_processes_flag_legal(self):
        ch = make_mock_channel("legal_institutional")
        self.assertIn("flag_legal", ch.analysis_instructions)

    def test_geopolitical_processes_flag_geopolitical(self):
        ch = make_mock_channel("geopolitical")
        self.assertIn("flag_geopolitical", ch.analysis_instructions)

    def test_uncertainty_processes_flag_uncertainty(self):
        ch = make_mock_channel("uncertainty_modeling")
        self.assertIn("flag_uncertainty", ch.analysis_instructions)

    def test_all_channels_mention_prime_directive_in_system_prompt(self):
        for name in ALL_CHANNELS:
            ch = make_mock_channel(name)
            system = ch._build_system_prompt()
            self.assertIn("PRIME DIRECTIVE", system,
                          f"{name} system prompt should contain Prime Directive")

    def test_secondary_channels_acknowledge_primary_four_signals(self):
        """Each secondary channel explicitly names which primary channels feed it."""
        signal_map = {
            "historical_precedent": "flag_historical",
            "legal_institutional":  "flag_legal",
            "geopolitical":         "flag_geopolitical",
            "uncertainty_modeling": "flag_uncertainty",
        }
        for sec_name, expected_flag in signal_map.items():
            ch = make_mock_channel(sec_name)
            desc = ch.domain_description
            instr = ch.analysis_instructions
            combined = desc + instr
            self.assertIn(expected_flag, combined,
                          f"{sec_name} should explicitly reference {expected_flag}")

    def test_adversarial_channel_emits_seven_tag_types(self):
        ch = make_mock_channel("ethical_adversarial")
        expected_tags = [
            "beneficiary_capture", "power_concentration", "unintended_consequence",
            "framing_trap", "lock_in", "ethical_incoherence", "prime_directive_stress",
        ]
        for tag in expected_tags:
            self.assertIn(tag, ch.analysis_instructions,
                          f"Adversarial channel missing tag: {tag}")


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestChannelRegistry(unittest.TestCase):

    def test_all_eight_channels_in_registry(self):
        for name in ALL_CHANNELS:
            self.assertIn(name, CHANNEL_REGISTRY)

    def test_no_stubs_in_registry(self):
        self.assertEqual(stub_channels(), [],
                         "All channels should be implemented — no stubs expected")

    def test_all_channels_implemented(self):
        self.assertEqual(sorted(implemented_channels()), sorted(ALL_CHANNELS))

    def test_registry_callables_are_base_channel_instances(self):
        for name in ALL_CHANNELS:
            ch = CHANNEL_REGISTRY[name]
            self.assertIsInstance(ch, BaseChannel,
                                  f"{name} should be a BaseChannel instance")

    def test_invoke_channel_returns_channel_output(self):
        for name in ALL_CHANNELS:
            output = invoke_channel(name, SAMPLE_INPUT, SAMPLE_CONTEXT)
            self.assertIsInstance(output, ChannelOutput,
                                  f"invoke_channel({name}) should return ChannelOutput")

    def test_invoke_unknown_channel_returns_failed(self):
        output = invoke_channel("nonexistent", "input", {})
        self.assertEqual(output.status, ChannelStatus.FAILED)

    def test_invoke_channel_never_raises(self):
        """Even if a channel implementation raises, invoke_channel should catch it."""
        from SeedCore.channels.backend import ModelBackend
        class ExplodingBackend(ModelBackend):
            @property
            def model_id(self): return "exploding"
            def complete(self, *args, **kwargs): raise RuntimeError("BOOM")

        # Temporarily replace one channel's backend
        original = CHANNEL_REGISTRY["economic"]
        try:
            CHANNEL_REGISTRY["economic"] = EconomicChannel(
                backend=ExplodingBackend(), max_retries=0
            )
            output = invoke_channel("economic", "input", {})
            self.assertEqual(output.status, ChannelStatus.FAILED)
        finally:
            CHANNEL_REGISTRY["economic"] = original


# ---------------------------------------------------------------------------
# End-to-end tests
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):
    """
    Full channel flow: build prompt → mock backend → parse response → ChannelOutput
    """

    def test_economic_full_flow(self):
        response = make_valid_response("economic", n_findings=5)
        ch = make_mock_channel("economic", response)
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)

        self.assertEqual(output.status, ChannelStatus.SUCCESS)
        self.assertEqual(output.channel_name, "economic")
        self.assertEqual(len(output.findings), 5)
        self.assertAlmostEqual(output.overall_harm_score, 0.35, places=2)
        self.assertAlmostEqual(output.overall_benefit_score, 0.65, places=2)
        self.assertAlmostEqual(output.confidence, 0.72, places=2)

    def test_ecological_full_flow(self):
        response = make_valid_response("ecological", n_findings=4)
        response["findings"][0]["reversible"] = False
        response["findings"][0]["tags"] = ["ecological", "irreversible"]
        ch = make_mock_channel("ecological", response)
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)

        self.assertEqual(output.status, ChannelStatus.SUCCESS)
        irreversible = [f for f in output.findings if f.reversible == False]
        self.assertGreater(len(irreversible), 0)

    def test_social_full_flow_with_disaggregated_groups(self):
        response = make_valid_response("social_demographic", n_findings=3)
        response["findings"][0]["affected_groups"] = ["low-income households", "rural communities"]
        response["findings"][1]["affected_groups"] = ["fossil fuel workers"]
        ch = make_mock_channel("social_demographic", response)
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)

        self.assertEqual(output.status, ChannelStatus.SUCCESS)
        all_groups = []
        for f in output.findings:
            all_groups.extend(f.affected_groups)
        self.assertIn("low-income households", all_groups)

    def test_adversarial_full_flow_with_challenges(self):
        response = make_valid_response("ethical_adversarial", n_findings=4)
        response["adversarial_challenges"] = [
            "Who lobbied for the $50/tonne figure specifically?",
            "Could the dividend mechanism be redirected away from low-income households by future administrations?",
            "Does the phase-in timeline provide sufficient cover for fossil fuel industries to delay adaptation?",
        ]
        ch = make_mock_channel("ethical_adversarial", response)
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)

        self.assertEqual(output.status, ChannelStatus.SUCCESS)
        self.assertEqual(len(output.adversarial_challenges), 3)

    def test_uncertainty_channel_produces_uncertainty_notes(self):
        response = make_valid_response("uncertainty_modeling", n_findings=3)
        response["uncertainty_notes"] = [
            {
                "description": "Behavioral response to carbon pricing is uncertain.",
                "impact_on_analysis": "Actual emission reductions could be 30-70% of projected.",
                "magnitude": 0.7,
            },
            {
                "description": "Political sustainability of the dividend mechanism is uncertain.",
                "impact_on_analysis": "Redistribution may be reduced in future budget cycles.",
                "magnitude": 0.6,
            },
        ]
        ch = make_mock_channel("uncertainty_modeling", response)
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)

        self.assertEqual(output.status, ChannelStatus.SUCCESS)
        self.assertEqual(len(output.uncertainty_notes), 2)
        self.assertGreater(output.uncertainty_notes[0].magnitude, 0.5)

    def test_all_channels_produce_valid_output_with_mock(self):
        """All eight channels complete successfully with valid mock responses."""
        for name in ALL_CHANNELS:
            ch = make_mock_channel(name, make_valid_response(name))
            output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)
            self.assertEqual(output.status, ChannelStatus.SUCCESS,
                             f"{name} should succeed with valid mock response")
            self.assertEqual(output.channel_name, name)
            self.assertGreater(len(output.findings), 0)

    def test_channel_output_is_serializable(self):
        """All outputs must be dict-serializable (for audit log)."""
        for name in ALL_CHANNELS:
            ch = make_mock_channel(name, make_valid_response(name))
            output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)
            d = output.to_dict()
            json.dumps(d)  # should not raise

    def test_model_id_propagated_from_backend(self):
        mock = MockBackend()
        ch = EconomicChannel(backend=mock)
        response = make_valid_response("economic")
        mock.add_response("economic", response)
        output = ch.analyze(SAMPLE_INPUT, SAMPLE_CONTEXT)
        self.assertEqual(output.model_id, mock.model_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
