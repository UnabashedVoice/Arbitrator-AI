"""
test_escalation.py — Canonical finding ids, raw model output, channel escalation
requests, the analysis gate (rule B), and the decision brief written for every run.

Uses the mock backend and small fakes; no model is called.
"""

import copy
import dataclasses
import json
import os
import tempfile
import unittest

from Arbitrator.SeedCore.channels.backend import MockBackend
from Arbitrator.SeedCore.channels.economic import EconomicChannel
from Arbitrator.SeedCore.channels.response_parser import parse_channel_response
from Arbitrator.SeedCore.ethics_core.models import Verdict
from Arbitrator.SeedCore.orchestrator.channel_stubs import get_channel
from Arbitrator.SeedCore.orchestrator.decision_brief import validate_brief, write_brief
from Arbitrator.SeedCore.orchestrator.orchestrator import Orchestrator, OrchestratorConfig

SEAWALL = ("A coastal city proposes a 10% tax on short-term rental income to fund construction of a "
           "seawall protecting its low-lying neighbourhoods over the next twenty years.")

BRIEF = {
    "why_human_judgment": "The trade-off is between present renters and future flood victims.",
    "disagreements": [{"between": "economic and ethical_adversarial", "about": "incidence of the tax"}],
    "case_for": "Protects low-lying neighbourhoods.", "case_against": "Burden falls on a narrow group.",
    "uncertainties": [{"what": "rental demand elasticity", "would_resolve_it": "a pilot year"}],
    "decision_questions": ["Is a narrow tax base acceptable for a city-wide benefit?"],
    "options": [
        {"id": "adopt", "label": "Adopt as proposed", "consequences": "Funds the wall.",
         "who_bears_cost": "rental hosts", "reversible": True,
         "case_for": "Simple and quick.", "case_against": "A narrow group pays for a city-wide good."},
        {"id": "broaden", "label": "Broaden the tax base", "consequences": "Spreads the cost.",
         "who_bears_cost": "all property owners", "reversible": True,
         "case_for": "Those who benefit pay.", "case_against": "Needs a wider political mandate."},
        {"id": "defer", "label": "Defer for a flood-risk study", "consequences": "Delay.",
         "who_bears_cost": "residents at risk meanwhile", "reversible": True,
         "case_for": "Better evidence.", "case_against": "Leaves people exposed meanwhile."}],
    "provisional_lean": {"option": "broaden", "confidence": 0.55,
                         "reasoning": "The benefit is city-wide, so the cost should be too.",
                         "would_change_if": "hosts are few and wealthy"},
    "set_aside": [{"option": "adopt", "because": "It puts a city-wide cost on a narrow group."},
                  {"option": "defer", "because": "The risk is already well known."}],
    "review": {"needed": False, "why": "An ordinary fiscal choice for the council."},
}


class FakeBackend:
    model_id = "fake/model"

    def __init__(self, answers, raw_prefix=""):
        self.answers = list(answers)
        self.raw_prefix = raw_prefix
        self.last_raw = ""
        self.calls = 0

    def complete(self, system_prompt, user_prompt, max_tokens=4000, temperature=0.2):
        self.calls += 1
        answer = self.answers.pop(0)
        self.last_raw = self.raw_prefix + answer
        return answer


def _mock():
    backend = get_channel("ethical_adversarial")._backend
    if not isinstance(backend, MockBackend):
        raise unittest.SkipTest("channels are not on the mock backend here")
    return backend


class TestFindingIds(unittest.TestCase):

    def test_ids_are_assigned_not_taken_from_the_model(self):
        raw = json.dumps({"domain_summary": "s", "findings": [
            {"finding_id": "economic_00", "summary": "a", "references_finding_id": ["economic_00", "ghost_01"]},
            {"summary": ""},  # dropped: no summary
            {"finding_id": "uncertainty_modeling_01", "summary": "b"}]})
        out = parse_channel_response(raw, "uncertainty_modeling", known_ids={"economic_00"})
        self.assertEqual([f.finding_id for f in out.findings],
                         ["uncertainty_modeling_00", "uncertainty_modeling_01"])
        self.assertEqual(out.findings[0].model_finding_id, "economic_00")
        self.assertIsNone(out.findings[1].model_finding_id)  # it matched
        self.assertEqual(out.findings[0].references_finding_id, ["economic_00"])
        self.assertEqual(out.findings[0].unresolved_references, ["ghost_01"])

    def test_escalation_request_is_parsed(self):
        raw = json.dumps({"domain_summary": "s", "findings": [],
                          "escalation_request": {"requested": True, "reason": "consent",
                                                 "what_to_decide": "do they agree?"}})
        self.assertEqual(parse_channel_response(raw, "economic").escalation_request,
                         {"requested": True, "reason": "consent", "what_to_decide": "do they agree?"})
        raw = json.dumps({"domain_summary": "s", "findings": [],
                          "escalation_request": {"requested": False, "reason": "", "what_to_decide": ""}})
        self.assertIsNone(parse_channel_response(raw, "economic").escalation_request)


class TestRawOutput(unittest.TestCase):

    def test_channel_keeps_raw_output_and_reasoning(self):
        answer = json.dumps({"domain_summary": "s", "findings": [{"summary": "a"}]})
        backend = FakeBackend([answer], raw_prefix="<think>weighing the tax</think>\n")
        out = EconomicChannel(backend=backend).analyze(SEAWALL, {})
        self.assertEqual(out.reasoning, "weighing the tax")
        self.assertTrue(out.raw_response.startswith("<think>"))
        self.assertIn("reasoning", out.to_dict())


class TestBrief(unittest.TestCase):

    def test_valid_brief(self):
        self.assertEqual(validate_brief(BRIEF), [])

    def test_brief_must_give_reasons_for_every_option(self):
        bad = copy.deepcopy(BRIEF)
        del bad["options"][2]["case_against"]
        bad["set_aside"] = bad["set_aside"][:1]
        del bad["provisional_lean"]["reasoning"]
        problems = " ".join(validate_brief(bad))
        self.assertIn("('defer') needs its own 'case_against'", problems)
        self.assertIn("missing: defer", problems)
        self.assertIn("provisional_lean.reasoning", problems)

    def test_brief_needs_a_view_on_review(self):
        bad = copy.deepcopy(BRIEF)
        bad["review"] = {"why": "unsure"}
        self.assertIn("'review' needs", " ".join(validate_brief(bad)))

    def test_brief_needs_three_options_and_a_real_lean(self):
        bad = copy.deepcopy(BRIEF)
        bad["options"] = bad["options"][:2]
        bad["provisional_lean"]["option"] = "nowhere"
        problems = " ".join(validate_brief(bad))
        self.assertIn("at least three options", problems)
        self.assertIn("one of the option ids", problems)

    def test_invalid_brief_is_retried_once(self):
        backend = FakeBackend(["no json here", json.dumps(BRIEF)])
        out = write_brief(backend, SEAWALL, [{"source": "t", "detail": "d"}], {"consequence_map": {}})
        self.assertEqual(out["brief"]["provisional_lean"]["option"], "broaden")
        self.assertEqual(len(out["attempts"]), 2)
        self.assertTrue(out["attempts"][0]["problems"])

    def test_brief_failure_is_recorded(self):
        backend = FakeBackend(["nope", "still nope"])
        out = write_brief(backend, SEAWALL, [{"source": "t", "detail": "d"}], {"consequence_map": {}})
        self.assertIsNone(out["brief"])
        self.assertIn("invalid after 2 attempts", out["error"])
        self.assertEqual([a["raw"] for a in out["attempts"]], ["nope", "still nope"])


class TestAnalysisTriggers(unittest.TestCase):

    @staticmethod
    def _out(name, harm, findings=()):
        from Arbitrator.SeedCore.synthesis.channel_output import (
            ChannelOutput, ChannelStatus, Finding, ImpactCertainty, ImpactDirection, ImpactTimeframe)
        fs = [Finding(summary=s, detail=s, direction=ImpactDirection.HARM, timeframe=ImpactTimeframe.SHORT_TERM,
                      certainty=ImpactCertainty.MODERATE, magnitude=m, reversible=rev, finding_id=f"{name}_{i:02d}")
              for i, (s, m, rev) in enumerate(findings)]
        return ChannelOutput(channel_name=name, status=ChannelStatus.SUCCESS, findings=fs, overall_harm_score=harm)

    @staticmethod
    def _cmap(harm, confidence):
        class M:
            overall_harm_score = harm
            synthesis_confidence = confidence
        return M()

    def test_quiet_analysis_triggers_nothing(self):
        from Arbitrator.SeedCore.orchestrator.orchestrator import analysis_triggers
        outs = [self._out("economic", 0.2, [("minor", 0.2, True)]), self._out("geopolitical", 0.15)]
        self.assertEqual(analysis_triggers(self._cmap(0.2, 0.6), outs), [])

    def test_each_condition_names_itself(self):
        from Arbitrator.SeedCore.orchestrator.orchestrator import analysis_triggers
        outs = [self._out("economic", 0.8, [("permanent loss", 0.6, False)]), self._out("geopolitical", 0.2)]
        sources = [t["source"] for t in analysis_triggers(self._cmap(0.55, 0.4), outs)]
        self.assertEqual(sources, ["analysis:irreversible_harm", "analysis:channel_disagreement",
                                   "analysis:high_harm_low_confidence"])

    def test_irreversible_harm_counts_only_from_empirical_channels(self):
        from Arbitrator.SeedCore.orchestrator.orchestrator import analysis_triggers
        outs = [self._out("ethical_adversarial", 0.3, [("lock-in", 0.7, False)]),
                self._out("uncertainty_modeling", 0.3, [("tail risk", 0.9, False)])]
        self.assertEqual(analysis_triggers(self._cmap(0.3, 0.6), outs), [])


class TestAnswerBudget(unittest.TestCase):

    def test_budget_fills_the_context(self):
        from Arbitrator.SeedCore.channels.backend import LMStudioBackend
        from unittest.mock import patch
        b = LMStudioBackend("gpt-oss-20b", context_length=16384)
        self.assertEqual(b._answer_budget(6000, 4000), 16384 - (2000 + 300) - 256)
        self.assertEqual(b._answer_budget(60000, 4000), 512)  # prompt nearly fills it: a small floor
        target = "Arbitrator.SeedCore.channels.backend.probe_loaded_context"
        with patch(target, return_value=0):  # LM Studio can't say: the requested budget stands
            self.assertEqual(LMStudioBackend("gpt-oss-20b")._answer_budget(6000, 4000), 4000)
        with patch(target, return_value=131072) as probe:  # asked once, then the whole free window
            auto = LMStudioBackend("gpt-oss-20b")
            self.assertEqual(auto._answer_budget(6000, 4000), 131072 - (2000 + 300) - 256)
            auto._answer_budget(6000, 4000)
            self.assertEqual(probe.call_count, 1)


class TestAnalysisGate(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.mock = _mock()

    def tearDown(self):
        self.mock.reset()

    def _run(self, gate, text=SEAWALL, **cfg):
        orch = Orchestrator(OrchestratorConfig(audit_log_path=os.path.join(self.dir, f"{gate}.jsonl"),
                                               ethics_gate=gate, **cfg))
        return orch, orch.run(text).to_dict()

    def test_prescreen_gate_still_blocks_a_structural_fail(self):
        _, r = self._run("prescreen")
        self.assertEqual(r["status"], "ethics_blocked")

    def test_analysis_gate_treats_a_structural_fail_as_advisory(self):
        _, r = self._run("analysis")
        self.assertNotEqual(r["status"], "ethics_blocked")
        self.assertEqual(r["prescreen_verdict"], "fail")
        self.assertEqual(r["post_screen_evaluation"]["stage"], "post_screen")
        self.assertEqual(r["ethics_verdict"], r["post_screen_evaluation"]["verdict"])
        self.assertTrue(any("advisory" in w for w in r["warnings"]))

    def test_analysis_gate_still_blocks_a_hard_constraint(self):
        orch = Orchestrator(OrchestratorConfig(audit_log_path=os.path.join(self.dir, "hard.jsonl"),
                                               ethics_gate="analysis"))
        real = orch._ethics.evaluate
        orch._ethics.evaluate = lambda p: dataclasses.replace(
            real(p), verdict=Verdict.HARD_REJECT, hard_constraints_triggered=["test constraint"])
        r = orch.run(SEAWALL).to_dict()
        self.assertEqual(r["status"], "ethics_blocked")
        self.assertTrue(any("test constraint" in w for w in r["warnings"]))

    def test_channel_request_escalates_and_gets_a_brief(self):
        self.mock.add_response("economic", {
            "domain_summary": "s", "overall_harm_score": 0.65, "overall_benefit_score": 0.5, "confidence": 0.7,
            "findings": [{"summary": "Hosts pay.", "direction": "harm", "certainty": "moderate",
                          "magnitude": 0.3, "timeframe": "short_term"}],
            "uncertainty_notes": [], "adversarial_challenges": [],
            "escalation_request": {"requested": True, "reason": "who should pay is a value choice",
                                   "what_to_decide": "is a narrow tax base fair?"}})
        self.mock.add_response("decision_brief", BRIEF)
        _, r = self._run("analysis")
        self.assertEqual(r["status"], "escalated")
        self.assertIn("channel:economic", [t["source"] for t in r["escalation"]["triggers"]])
        self.assertEqual(r["brief"]["brief"]["provisional_lean"]["option"], "broaden")
        with open(os.path.join(self.dir, "analysis.jsonl"), encoding="utf-8") as f:
            kinds = [json.loads(line)["kind"] for line in f]
        self.assertIn("escalation", kinds)
        self.assertIn("decision_brief", kinds)

    def test_unescalated_run_still_gets_a_brief(self):
        self.mock.add_response("decision_brief", BRIEF)
        _, r = self._run("analysis")
        self.assertIsNone(r["escalation"])
        self.assertEqual(r["brief"]["brief"]["review"]["needed"], False)

    def test_request_below_material_harm_does_not_escalate(self):
        self.mock.add_response("economic", {
            "domain_summary": "s", "overall_harm_score": 0.5, "findings": [], "uncertainty_notes": [],
            "adversarial_challenges": [],
            "escalation_request": {"requested": True, "reason": "r", "what_to_decide": "w"}})
        _, r = self._run("analysis")
        self.assertFalse(r["review_requests"][0]["material"])

    def test_immaterial_request_is_recorded_but_does_not_escalate(self):
        self.mock.add_response("economic", {
            "domain_summary": "s", "overall_harm_score": 0.1, "overall_benefit_score": 0.4, "confidence": 0.8,
            "findings": [{"summary": "Slightly shorter meetings.", "direction": "harm", "certainty": "moderate",
                          "magnitude": 0.1, "timeframe": "short_term", "reversible": True}],
            "uncertainty_notes": [], "adversarial_challenges": [],
            "escalation_request": {"requested": True, "reason": "stakeholders' preferences",
                                   "what_to_decide": "whether to change it"}})
        _, r = self._run("analysis")
        self.assertEqual(r["review_requests"][0]["channel"], "economic")
        self.assertFalse(r["review_requests"][0]["material"])
        self.assertNotIn("channel:economic",
                         [t["source"] for t in (r["escalation"] or {}).get("triggers", [])])

    def test_brief_can_be_turned_off(self):
        self.mock.add_response("economic", {
            "domain_summary": "s", "overall_harm_score": 0.7, "findings": [], "uncertainty_notes": [],
            "adversarial_challenges": [],
            "escalation_request": {"requested": True, "reason": "r", "what_to_decide": "w"}})
        _, r = self._run("analysis", decision_brief=False)
        self.assertEqual(r["status"], "escalated")
        self.assertIsNone(r["brief"])

    def test_bad_gate_name_is_refused(self):
        with self.assertRaises(ValueError):
            OrchestratorConfig(ethics_gate="none")


if __name__ == "__main__":
    unittest.main()
