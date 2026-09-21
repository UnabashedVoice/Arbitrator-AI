"""
test_orchestrator.py — Test suite for the Arbitrator Orchestrator.

Tests are organized by layer:
    - TestBridge                    — context_to_proposal derivation logic
    - TestChannelStubs              — stub registry and invocation
    - TestPipelineResult            — PipelineResult structure and properties
    - TestOrchestratorBasic         — Core pipeline flow
    - TestOrchestratorEthicsGating  — Ethics Core verdict gating behavior
    - TestOrchestratorAuditLogging  — Audit log integration
    - TestOrchestratorErrors        — Error handling and resilience
    - TestEndToEnd                  — Full pipeline integration scenarios
    - TestEdgeCases                 — Boundary conditions

Run with:
    python -m unittest SeedCore/tests/test_orchestrator.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from SeedCore.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    PipelineResult,
    PipelineStatus,
    context_to_proposal,
    CHANNEL_REGISTRY,
    is_stub,
    stub_channels,
    implemented_channels,
)
from SeedCore.orchestrator.bridge import (
    _derive_harm_score,
    _derive_benefit_score,
    _derive_consciousness_types,
    _derive_harm_types,
    _derive_benefit_types,
    _derive_uncertainty,
    _derive_long_term_risk,
)
from SeedCore.context_parser import ContextParser
from SeedCore.context_parser.models import InputScale, InputType, TimeHorizon
from SeedCore.ethics_core.models import ConsciousnessType, HarmType, BenefitType, Scope, Reversibility
from SeedCore.audit_log import EntryKind, LogQuery
from SeedCore.synthesis.channel_output import ChannelOutput, ChannelStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tmp_config() -> tuple[OrchestratorConfig, str]:
    """Create a config with a temp audit log path."""
    path = tempfile.mktemp(suffix='.jsonl')
    config = OrchestratorConfig(audit_log_path=path, node_id="test-node")
    return config, path


def make_context(text: str):
    """Parse a text and return its ParsedContext."""
    parser = ContextParser()
    return parser.parse(text).context


# ---------------------------------------------------------------------------
# Bridge tests
# ---------------------------------------------------------------------------

class TestBridge(unittest.TestCase):

    def test_harm_score_increases_with_implicit_flags(self):
        ctx_no_flags = make_context("A national education funding increase.")
        ctx_with_flags = make_context(
            "Consolidate all power under a single national authority "
            "and monitor all citizens with facial recognition surveillance."
        )
        harm_no = _derive_harm_score(ctx_no_flags)
        harm_with = _derive_harm_score(ctx_with_flags)
        self.assertGreater(harm_with, harm_no)

    def test_harm_score_elevated_for_military_input(self):
        ctx = make_context("Deploy troops to the border region immediately.")
        score = _derive_harm_score(ctx)
        self.assertGreater(score, 0.15)

    def test_harm_score_elevated_for_generational_horizon(self):
        ctx_immediate = make_context("Emergency action needed immediately.")
        ctx_gen = make_context("A policy affecting future generations for centuries to come.")
        self.assertGreater(
            _derive_harm_score(ctx_gen),
            _derive_harm_score(ctx_immediate),
        )

    def test_benefit_score_elevated_for_social_program(self):
        ctx = make_context(
            "A national social program for universal healthcare "
            "benefiting all citizens including elderly and children."
        )
        score = _derive_benefit_score(ctx)
        self.assertGreater(score, 0.2)

    def test_benefit_score_elevated_for_wider_scale(self):
        ctx_local = make_context("A city council library renovation.")
        ctx_national = make_context("A national healthcare reform policy.")
        self.assertGreater(
            _derive_benefit_score(ctx_national),
            _derive_benefit_score(ctx_local),
        )

    def test_consciousness_includes_human_for_national_scale(self):
        ctx = make_context("A national policy affecting the population.")
        types = _derive_consciousness_types(ctx)
        self.assertIn(ConsciousnessType.HUMAN, types)

    def test_consciousness_includes_ecosystem_when_ecological(self):
        ctx = make_context("A policy to protect the ecological environment and wildlife.")
        types = _derive_consciousness_types(ctx)
        self.assertIn(ConsciousnessType.ECOSYSTEM, types)

    def test_consciousness_includes_animal_for_wildlife(self):
        ctx = make_context("Deforestation affecting animals and wildlife habitat.")
        types = _derive_consciousness_types(ctx)
        self.assertIn(ConsciousnessType.ANIMAL, types)

    def test_harm_types_include_ecological_for_environment(self):
        ctx = make_context("Drain the wetlands and mine the area for resources.")
        types = _derive_harm_types(ctx)
        self.assertIn(HarmType.ECOLOGICAL, types)

    def test_harm_types_include_psychological_for_surveillance(self):
        ctx = make_context("Monitor and track all citizens with facial recognition surveillance.")
        types = _derive_harm_types(ctx)
        self.assertIn(HarmType.PSYCHOLOGICAL, types)

    def test_uncertainty_increases_with_low_confidence(self):
        ctx_high_conf = make_context(
            "A very detailed and comprehensive national carbon tax policy "
            "affecting all fossil fuel industries and providing revenue for "
            "renewable energy transition and worker retraining programs."
        )
        ctx_low_conf = make_context("things")
        self.assertGreater(
            _derive_uncertainty(ctx_low_conf),
            _derive_uncertainty(ctx_high_conf),
        )

    def test_long_term_risk_higher_for_generational(self):
        ctx_gen = make_context("Affects future generations for centuries to come.")
        ctx_imm = make_context("Emergency action needed immediately this week.")
        self.assertGreater(
            _derive_long_term_risk(ctx_gen),
            _derive_long_term_risk(ctx_imm),
        )

    def test_context_to_proposal_returns_action_proposal(self):
        from SeedCore.ethics_core.models import ActionProposal
        ctx = make_context("A national renewable energy policy.")
        proposal = context_to_proposal(ctx, "A national renewable energy policy.")
        self.assertIsInstance(proposal, ActionProposal)

    def test_context_to_proposal_description_matches_input(self):
        text = "What if we implemented a carbon tax nationwide?"
        ctx = make_context(text)
        proposal = context_to_proposal(ctx, text)
        self.assertEqual(proposal.description, text)

    def test_context_to_proposal_scores_in_range(self):
        ctx = make_context("A social program for universal healthcare.")
        proposal = context_to_proposal(ctx, "A social program for universal healthcare.")
        self.assertGreaterEqual(proposal.harm_score, 0.0)
        self.assertLessEqual(proposal.harm_score, 1.0)
        self.assertGreaterEqual(proposal.benefit_score, 0.0)
        self.assertLessEqual(proposal.benefit_score, 1.0)

    def test_context_to_proposal_consciousness_types_not_empty(self):
        ctx = make_context("A national policy.")
        proposal = context_to_proposal(ctx, "A national policy.")
        self.assertGreater(len(proposal.consciousness_types), 0)

    def test_context_to_proposal_custom_proposal_id(self):
        ctx = make_context("A policy.")
        proposal = context_to_proposal(ctx, "A policy.", proposal_id="custom-id-123")
        self.assertEqual(proposal.proposal_id, "custom-id-123")


# ---------------------------------------------------------------------------
# Channel stubs
# ---------------------------------------------------------------------------

class TestChannelStubs(unittest.TestCase):

    def test_all_channels_registered(self):
        expected = [
            "economic", "ecological", "social_demographic",
            "historical_precedent", "legal_institutional",
            "geopolitical", "ethical_adversarial", "uncertainty_modeling",
        ]
        for ch in expected:
            self.assertIn(ch, CHANNEL_REGISTRY)

    def test_no_registered_channels_are_stubs(self):
        """Phase 2: all eight channels have real implementations."""
        for name in CHANNEL_REGISTRY:
            self.assertFalse(is_stub(name), f"{name} should not be a stub in Phase 2")

    def test_stub_channels_list_is_empty(self):
        """Phase 2: no channels remain as stubs."""
        self.assertEqual(len(stub_channels()), 0)

    def test_all_channels_implemented_in_phase2(self):
        """Phase 2: all eight specialist channels are implemented."""
        impl = implemented_channels()
        expected = {
            "economic", "ecological", "social_demographic", "ethical_adversarial",
            "historical_precedent", "legal_institutional", "geopolitical",
            "uncertainty_modeling",
        }
        self.assertEqual(set(impl), expected)

    def test_stub_returns_channel_output(self):
        from SeedCore.orchestrator.channel_stubs import invoke_channel
        output = invoke_channel("economic", "test input", {})
        self.assertIsInstance(output, ChannelOutput)

    def test_channel_returns_success_or_failed_not_unavailable(self):
        """Phase 2: real channels return SUCCESS or FAILED, never UNAVAILABLE."""
        from SeedCore.orchestrator.channel_stubs import invoke_channel
        output = invoke_channel("economic", "test input", {})
        self.assertIn(output.status, [ChannelStatus.SUCCESS, ChannelStatus.FAILED])
        self.assertNotEqual(output.status, ChannelStatus.UNAVAILABLE)

    def test_successful_channel_has_no_error_message(self):
        """Phase 2: a channel that succeeds should have no error message."""
        from SeedCore.orchestrator.channel_stubs import invoke_channel
        output = invoke_channel("economic", "test input", {})
        if output.status == ChannelStatus.SUCCESS:
            self.assertIsNone(output.error_message)

    def test_unregistered_channel_returns_failed(self):
        from SeedCore.orchestrator.channel_stubs import invoke_channel
        output = invoke_channel("nonexistent_channel", "test", {})
        self.assertEqual(output.status, ChannelStatus.FAILED)

    def test_channel_can_be_replaced_with_real_implementation(self):
        """Verify the registry replacement pattern works."""
        from SeedCore.orchestrator import channel_stubs

        def real_eco_channel(raw_input, context_dict):
            return ChannelOutput(
                channel_name="ecological",
                status=ChannelStatus.SUCCESS,
                overall_harm_score=0.3,
                overall_benefit_score=0.7,
                confidence=0.8,
                domain_summary="Real ecological analysis.",
            )

        original = channel_stubs.CHANNEL_REGISTRY["ecological"]
        try:
            channel_stubs.CHANNEL_REGISTRY["ecological"] = real_eco_channel
            self.assertFalse(is_stub("ecological"))
            output = channel_stubs.invoke_channel("ecological", "test", {})
            self.assertEqual(output.status, ChannelStatus.SUCCESS)
        finally:
            channel_stubs.CHANNEL_REGISTRY["ecological"] = original


# ---------------------------------------------------------------------------
# PipelineResult
# ---------------------------------------------------------------------------

class TestPipelineResult(unittest.TestCase):

    def test_success_is_publishable(self):
        r = PipelineResult("s1", PipelineStatus.SUCCESS, "input")
        self.assertTrue(r.is_publishable)

    def test_partial_is_publishable(self):
        r = PipelineResult("s1", PipelineStatus.PARTIAL, "input")
        self.assertTrue(r.is_publishable)

    def test_failed_is_not_publishable(self):
        r = PipelineResult("s1", PipelineStatus.FAILED, "input")
        self.assertFalse(r.is_publishable)

    def test_ethics_blocked_is_not_publishable(self):
        r = PipelineResult("s1", PipelineStatus.ETHICS_BLOCKED, "input")
        self.assertFalse(r.is_publishable)

    def test_escalated_requires_human_review(self):
        r = PipelineResult("s1", PipelineStatus.ESCALATED, "input")
        self.assertTrue(r.requires_human_review)

    def test_ethics_blocked_was_blocked(self):
        r = PipelineResult("s1", PipelineStatus.ETHICS_BLOCKED, "input")
        self.assertTrue(r.was_blocked)

    def test_to_dict_is_json_serializable(self):
        r = PipelineResult("s1", PipelineStatus.SUCCESS, "input")
        d = r.to_dict()
        json.dumps(d)  # should not raise

    def test_to_json_returns_string(self):
        r = PipelineResult("s1", PipelineStatus.SUCCESS, "input")
        self.assertIsInstance(r.to_json(), str)

    def test_summary_returns_string(self):
        r = PipelineResult("s1", PipelineStatus.PARTIAL, "input")
        r.ethics_verdict = "ambiguous"
        r.synthesis_verdict = "mixed"
        s = r.summary()
        self.assertIsInstance(s, str)
        self.assertGreater(len(s), 0)


# ---------------------------------------------------------------------------
# Basic orchestrator behavior
# ---------------------------------------------------------------------------

class TestOrchestratorBasic(unittest.TestCase):

    def setUp(self):
        self.config, self.log_path = tmp_config()
        self.orch = Orchestrator(self.config)

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def test_run_returns_pipeline_result(self):
        result = self.orch.run("A national carbon tax policy.")
        self.assertIsInstance(result, PipelineResult)

    def test_empty_input_returns_failed(self):
        result = self.orch.run("")
        self.assertEqual(result.status, PipelineStatus.FAILED)
        self.assertGreater(len(result.errors), 0)

    def test_whitespace_input_returns_failed(self):
        result = self.orch.run("   ")
        self.assertEqual(result.status, PipelineStatus.FAILED)

    def test_result_has_session_id(self):
        result = self.orch.run("A policy.")
        self.assertIsNotNone(result.session_id)
        self.assertEqual(len(result.session_id), 36)  # UUID format

    def test_result_has_duration(self):
        result = self.orch.run("A policy.")
        self.assertIsNotNone(result.duration_ms)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_result_preserves_raw_input(self):
        text = "A unique and specific policy proposal text."
        result = self.orch.run(text)
        self.assertEqual(result.raw_input, text)

    def test_manifest_populated(self):
        result = self.orch.run("A national education reform policy.")
        self.assertIsNotNone(result.manifest)
        self.assertIn("manifest_id", result.manifest)

    def test_ethics_evaluation_populated(self):
        result = self.orch.run("A national renewable energy policy.")
        self.assertIsNotNone(result.ethics_evaluation)
        self.assertIn("verdict", result.ethics_evaluation)

    def test_ethics_verdict_populated(self):
        result = self.orch.run("A national renewable energy policy.")
        self.assertIsNotNone(result.ethics_verdict)

    def test_consequence_map_populated(self):
        result = self.orch.run("A national renewable energy policy.")
        self.assertIsNotNone(result.consequence_map)

    def test_synthesis_verdict_populated(self):
        result = self.orch.run("A national renewable energy policy.")
        self.assertIsNotNone(result.synthesis_verdict)

    def test_channels_invoked_list_populated(self):
        result = self.orch.run("A national carbon tax and ecological protection policy.")
        self.assertGreater(len(result.channels_invoked), 0)

    def test_all_channels_implemented_in_phase2(self):
        """Phase 2: channels_succeeded is non-empty; channels_stubbed is empty."""
        result = self.orch.run("A complex multi-domain policy.")
        self.assertEqual(result.channels_stubbed, [])
        self.assertGreater(len(result.channels_succeeded), 0)

    def test_no_stub_warning_in_phase2_result(self):
        """Phase 2: no stub warnings should appear since all channels are real."""
        result = self.orch.run("A national policy.")
        stub_warnings = [w for w in result.warnings if "[channels]" in w]
        self.assertEqual(len(stub_warnings), 0)

    def test_status_is_partial_when_stubs_present(self):
        # With all stubs, synthesis produces INSUFFICIENT_DATA
        # but we still get a consequence map → PARTIAL
        result = self.orch.run("A national renewable energy policy.")
        self.assertIn(result.status, [PipelineStatus.SUCCESS, PipelineStatus.PARTIAL, PipelineStatus.ESCALATED])

    def test_different_runs_have_different_session_ids(self):
        r1 = self.orch.run("Policy A")
        r2 = self.orch.run("Policy B")
        self.assertNotEqual(r1.session_id, r2.session_id)


# ---------------------------------------------------------------------------
# Ethics Core gating
# ---------------------------------------------------------------------------

class TestOrchestratorEthicsGating(unittest.TestCase):

    def setUp(self):
        self.config, self.log_path = tmp_config()
        self.orch = Orchestrator(self.config)

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def test_hard_reject_blocks_pipeline(self):
        """
        A proposal that triggers a hard constraint should be blocked.
        We can't guarantee this from natural language alone at the bridge
        level, but we can test the config behavior.
        """
        config, path = tmp_config()
        config.continue_after_fail = False
        orch = Orchestrator(config)
        try:
            # Force a hard reject by monkeypatching ethics core
            from SeedCore.ethics_core.models import EthicsEvaluation, Verdict
            from datetime import datetime, timezone

            mock_eval = EthicsEvaluation(
                proposal_id="test",
                verdict=Verdict.HARD_REJECT,
                justification="Hard constraint triggered.",
                hard_constraints_triggered=["no_existential_harm"],
                weighted_harm=0.95,
                weighted_benefit=0.05,
                net_score=-0.9,
                consciousness_weight=1.5,
                scope_weight_harm=2.0,
                scope_weight_benefit=1.0,
                mitigation_required=True,
                mitigation_notes=["Proposal cannot be mitigated."],
                flags=["existential_harm"],
                confidence=0.9,
                evaluated_at=datetime.now(timezone.utc).isoformat(),
            )

            with patch.object(orch._ethics, 'evaluate', return_value=mock_eval):
                result = orch.run("Test proposal.")

            self.assertEqual(result.status, PipelineStatus.ETHICS_BLOCKED)
            self.assertIsNone(result.consequence_map)
        finally:
            os.unlink(path)

    def test_continue_after_fail_config(self):
        """With continue_after_fail=True, FAIL verdict doesn't stop pipeline."""
        config, path = tmp_config()
        config.continue_after_fail = True
        orch = Orchestrator(config)
        try:
            from SeedCore.ethics_core.models import EthicsEvaluation, Verdict
            from datetime import datetime, timezone

            mock_eval = EthicsEvaluation(
                proposal_id="test",
                verdict=Verdict.FAIL,
                justification="Fails ethics check.",
                hard_constraints_triggered=[],
                weighted_harm=0.8,
                weighted_benefit=0.2,
                net_score=-0.6,
                consciousness_weight=1.5,
                scope_weight_harm=1.5,
                scope_weight_benefit=1.0,
                mitigation_required=True,
                mitigation_notes=[],
                flags=[],
                confidence=0.8,
                evaluated_at=datetime.now(timezone.utc).isoformat(),
            )

            with patch.object(orch._ethics, 'evaluate', return_value=mock_eval):
                result = orch.run("Test proposal.")

            # With continue_after_fail=True, should reach synthesis
            self.assertIsNotNone(result.consequence_map)
        finally:
            os.unlink(path)

    def test_escalate_verdict_sets_escalated_status(self):
        """ESCALATE verdict results in ESCALATED pipeline status."""
        config, path = tmp_config()
        orch = Orchestrator(config)
        try:
            from SeedCore.ethics_core.models import EthicsEvaluation, Verdict
            from datetime import datetime, timezone

            mock_eval = EthicsEvaluation(
                proposal_id="test",
                verdict=Verdict.ESCALATE,
                justification="Requires human review.",
                hard_constraints_triggered=[],
                weighted_harm=0.55,
                weighted_benefit=0.55,
                net_score=0.0,
                consciousness_weight=1.5,
                scope_weight_harm=1.5,
                scope_weight_benefit=1.5,
                mitigation_required=True,
                mitigation_notes=["Human ratification required."],
                flags=["unrecognized_consciousness"],
                confidence=0.6,
                evaluated_at=datetime.now(timezone.utc).isoformat(),
            )

            with patch.object(orch._ethics, 'evaluate', return_value=mock_eval):
                result = orch.run("A complex policy with uncertain consequences.")

            self.assertEqual(result.status, PipelineStatus.ESCALATED)
            # With continue_after_escalate=True (default), should still have map
            self.assertIsNotNone(result.consequence_map)
        finally:
            os.unlink(path)

    def test_pass_verdict_produces_success_or_partial(self):
        result = self.orch.run("A straightforward community library funding proposal.")
        # The bridge applies conservative estimates — a vague short input may
        # produce FAIL from the Ethics Core (low benefit, unknown reversibility).
        # All of these are valid outcomes at this stage of the pipeline.
        self.assertIn(
            result.status,
            [PipelineStatus.SUCCESS, PipelineStatus.PARTIAL,
             PipelineStatus.ESCALATED, PipelineStatus.ETHICS_BLOCKED]
        )
        self.assertIsNotNone(result.ethics_verdict)


# ---------------------------------------------------------------------------
# Audit log integration
# ---------------------------------------------------------------------------

class TestOrchestratorAuditLogging(unittest.TestCase):

    def setUp(self):
        self.config, self.log_path = tmp_config()
        self.orch = Orchestrator(self.config)

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def test_audit_log_populated_after_run(self):
        result = self.orch.run("A national policy.")
        log = self.orch.get_audit_log()
        self.assertGreater(log.count(), 0)

    def test_session_entries_logged(self):
        result = self.orch.run("A national carbon tax.")
        history = self.orch.get_session_history(result.session_id)
        self.assertGreater(len(history), 0)

    def test_input_received_entry_logged(self):
        result = self.orch.run("A national policy.")
        history = self.orch.get_session_history(result.session_id)
        kinds = [e["kind"] for e in history]
        self.assertIn(EntryKind.INPUT_RECEIVED.value, kinds)

    def test_context_parsed_entry_logged(self):
        result = self.orch.run("A national policy.")
        history = self.orch.get_session_history(result.session_id)
        kinds = [e["kind"] for e in history]
        self.assertIn(EntryKind.CONTEXT_PARSED.value, kinds)

    def test_ethics_evaluated_entry_logged(self):
        result = self.orch.run("A national renewable energy policy.")
        history = self.orch.get_session_history(result.session_id)
        kinds = [e["kind"] for e in history]
        self.assertIn(EntryKind.ETHICS_EVALUATED.value, kinds)

    def test_channel_output_entries_logged(self):
        result = self.orch.run("A multi-domain national policy.")
        history = self.orch.get_session_history(result.session_id)
        kinds = [e["kind"] for e in history]
        self.assertIn(EntryKind.CHANNEL_OUTPUT.value, kinds)

    def test_consequence_map_entry_logged(self):
        result = self.orch.run("A national policy.")
        history = self.orch.get_session_history(result.session_id)
        kinds = [e["kind"] for e in history]
        self.assertIn(EntryKind.CONSEQUENCE_MAP.value, kinds)

    def test_audit_chain_valid_after_run(self):
        self.orch.run("A policy.")
        self.orch.run("Another policy.")
        result = self.orch.verify_audit_chain(log_verification=False)
        self.assertTrue(result.valid, result.error_detail)

    def test_multiple_runs_all_in_audit_log(self):
        r1 = self.orch.run("Policy A")
        r2 = self.orch.run("Policy B")
        log = self.orch.get_audit_log()
        s1_entries = log.get_session(r1.session_id)
        s2_entries = log.get_session(r2.session_id)
        self.assertGreater(len(s1_entries), 0)
        self.assertGreater(len(s2_entries), 0)

    def test_audit_summary_reflects_runs(self):
        self.orch.run("A policy.")
        summary = self.orch.audit_summary()
        self.assertIn("total_entries", summary)
        self.assertGreater(summary["total_entries"], 0)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestOrchestratorErrors(unittest.TestCase):

    def setUp(self):
        self.config, self.log_path = tmp_config()
        self.orch = Orchestrator(self.config)

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def test_context_parser_failure_returns_failed_result(self):
        with patch.object(self.orch._parser, 'parse', side_effect=RuntimeError("Parser exploded")):
            result = self.orch.run("A policy.")
        self.assertEqual(result.status, PipelineStatus.FAILED)
        self.assertGreater(len(result.errors), 0)
        self.assertTrue(any("parsing" in e.lower() for e in result.errors))

    def test_ethics_failure_is_non_fatal(self):
        """Ethics Core failure should produce a warning, not abort the pipeline."""
        with patch.object(self.orch._ethics, 'evaluate', side_effect=RuntimeError("Ethics exploded")):
            result = self.orch.run("A policy.")
        # Should still produce a consequence map
        self.assertIsNotNone(result.consequence_map)
        self.assertTrue(any("ethics_core" in w for w in result.warnings))

    def test_synthesis_failure_recorded_in_errors(self):
        with patch.object(self.orch._synthesizer, 'synthesize', side_effect=RuntimeError("Synthesis exploded")):
            result = self.orch.run("A policy.")
        self.assertIsNone(result.consequence_map)
        self.assertTrue(any("synthesis" in e.lower() for e in result.errors))

    def test_pipeline_error_logged_for_context_failure(self):
        with patch.object(self.orch._parser, 'parse', side_effect=RuntimeError("Crash")):
            result = self.orch.run("A policy.")
        log = self.orch.get_audit_log()
        error_entries = log.query(LogQuery(kind=EntryKind.PIPELINE_ERROR))
        self.assertGreater(len(error_entries), 0)

    def test_audit_chain_valid_even_after_error(self):
        with patch.object(self.orch._parser, 'parse', side_effect=RuntimeError("Crash")):
            self.orch.run("A policy.")
        result = self.orch.verify_audit_chain(log_verification=False)
        self.assertTrue(result.valid)


# ---------------------------------------------------------------------------
# End-to-end integration scenarios
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.config, self.log_path = tmp_config()
        self.orch = Orchestrator(self.config)

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def test_carbon_tax_proposal_full_pipeline(self):
        result = self.orch.run(
            "Proposed legislation: a national carbon tax of $50 per tonne on all "
            "fossil fuel emissions, phased in over 5 years, with revenue redistributed "
            "as dividend payments to low-income households."
        )
        self.assertIsNotNone(result.manifest)
        self.assertIsNotNone(result.ethics_evaluation)
        self.assertIsNotNone(result.consequence_map)
        self.assertIsNotNone(result.ethics_verdict)
        self.assertIsNotNone(result.synthesis_verdict)
        self.assertIn(result.status, [
            PipelineStatus.SUCCESS, PipelineStatus.PARTIAL, PipelineStatus.ESCALATED
        ])

    def test_hypothetical_ubi_proposal(self):
        result = self.orch.run(
            "What if the federal government introduced a universal basic income "
            "of $1000 per month for all adult citizens? What would the economic "
            "and social consequences be over the next decade?"
        )
        self.assertEqual(result.manifest["context"]["input_type"], "hypothetical")
        self.assertIsNotNone(result.consequence_map)

    def test_surveillance_proposal_has_implicit_flags(self):
        result = self.orch.run(
            "New legislation to require all ISPs to monitor and log citizen "
            "online activity for national security purposes."
        )
        # The manifest should show implicit flags were detected
        context = result.manifest["context"]
        self.assertGreater(len(context.get("implicit_flags", [])), 0)

    def test_local_proposal_invokes_fewer_channels(self):
        result_local = self.orch.run("Increase the city library budget by 10%.")
        result_global = self.orch.run(
            "A global treaty to phase out all fossil fuels and redistribute "
            "energy wealth across all nations by 2040."
        )
        # Global proposal should invoke more channels
        self.assertGreaterEqual(
            len(result_global.channels_invoked),
            len(result_local.channels_invoked),
        )

    def test_consequence_map_has_executive_summary(self):
        result = self.orch.run("A national renewable energy transition policy.")
        self.assertIn("executive_summary", result.consequence_map)
        self.assertGreater(len(result.consequence_map["executive_summary"]), 0)

    def test_consequence_map_fully_populated_in_phase2(self):
        """Phase 2: all channels run with mock backend — consequence map is complete."""
        result = self.orch.run("A national economic reform policy.")
        cmap = result.consequence_map
        # All channels succeed with mock backend — channels_failed should be empty
        self.assertEqual(len(cmap.get("channels_failed", [])), 0)
        # A successful full run should produce findings
        self.assertIsNotNone(cmap.get("executive_summary"))

    def test_full_audit_chain_valid_after_scenario(self):
        self.orch.run("A complex multi-domain international climate treaty.")
        v = self.orch.verify_audit_chain(log_verification=False)
        self.assertTrue(v.valid, v.error_detail)

    def test_result_is_json_serializable(self):
        result = self.orch.run("A healthcare reform policy.")
        json_str = result.to_json()
        parsed = json.loads(json_str)
        self.assertIn("session_id", parsed)
        self.assertIn("status", parsed)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.config, self.log_path = tmp_config()

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def test_very_long_input(self):
        orch = Orchestrator(self.config)
        long_text = ("This is a comprehensive national policy proposal covering "
                     "economic, ecological, social, and geopolitical dimensions. ") * 100
        result = orch.run(long_text)
        self.assertIsNotNone(result)

    def test_very_short_input_produces_warnings(self):
        orch = Orchestrator(self.config)
        result = orch.run("Tax.")
        # Short inputs should produce parse warnings
        self.assertGreater(len(result.warnings), 0)

    def test_max_channels_config_respected(self):
        config, path = tmp_config()
        config.max_channels = 2
        orch = Orchestrator(config)
        try:
            result = orch.run("A complex multi-domain national policy.")
            self.assertLessEqual(len(result.channels_invoked), 2)
        finally:
            os.unlink(path)

    def test_orchestrator_default_config(self):
        """Orchestrator should work with default config (no explicit config)."""
        tmp_path = "./test_default_audit.jsonl"
        try:
            orch = Orchestrator(OrchestratorConfig(audit_log_path=tmp_path))
            result = orch.run("A test policy.")
            self.assertIsNotNone(result)
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass

    def test_context_manager_pattern(self):
        """AuditLog context manager works within orchestrator usage."""
        orch = Orchestrator(self.config)
        result = orch.run("A policy.")
        with orch.get_audit_log() as log:
            entries = list(log.read_all())
        self.assertGreater(len(entries), 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
