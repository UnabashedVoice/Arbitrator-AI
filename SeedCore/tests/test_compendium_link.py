"""
test_compendium_link.py — The Compendium consultation and the LM Studio backend.

Uses the real Compendium checkout when it is present beside this repo
(skipped otherwise), and fake backends, so no model is called.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from Arbitrator.SeedCore.channels.backend import LMStudioBackend, MockBackend, strip_reasoning
from Arbitrator.SeedCore.channels.economic import EconomicChannel
from Arbitrator.SeedCore.channels.ethical_adversarial import EthicalAdversarialChannel
from Arbitrator.SeedCore.channels.model_registry import _discover_candidates
from Arbitrator.SeedCore.orchestrator import compendium_link


class FakeBackend:
    model_id = "fake/selector"

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def complete(self, system_prompt, user_prompt, max_tokens=4000, temperature=0.2):
        self.calls.append((system_prompt, user_prompt))
        return self.answer


def _compendium_available():
    try:
        compendium_link.load_compendium()
        return True
    except Exception:
        return False


class TestStripReasoning(unittest.TestCase):

    def test_harmony_final_channel(self):
        raw = ("<|channel|>analysis<|message|>{not this}<|end|><|start|>assistant"
               "<|channel|>final<|message|>{\"a\": 1}<|return|>")
        self.assertEqual(strip_reasoning(raw), '{"a": 1}')

    def test_think_block(self):
        self.assertEqual(strip_reasoning("<think>{no}</think>\n{\"a\": 1}"), '{"a": 1}')

    def test_plain(self):
        self.assertEqual(strip_reasoning('  {"a": 1} '), '{"a": 1}')


class TestLMStudioSelection(unittest.TestCase):

    def test_env_var_makes_lmstudio_the_only_candidate(self):
        with patch.dict(os.environ, {"ARBITRATOR_LMSTUDIO_MODEL": "gpt-oss-20b"}):
            cands = _discover_candidates()
        self.assertEqual(len(cands), 1)
        self.assertIsInstance(cands[0], LMStudioBackend)
        self.assertEqual(cands[0].model_id, "lmstudio/gpt-oss-20b@arbitrator-local-identity-v1")

    def test_default_backend_honours_env_var(self):
        from Arbitrator.SeedCore.channels.backend import get_default_backend
        with patch.dict(os.environ, {"ARBITRATOR_LMSTUDIO_MODEL": "qwen3-32b"}):
            self.assertEqual(get_default_backend().model_id, "lmstudio/qwen3-32b")

    def test_non_harmony_model_id(self):
        self.assertEqual(LMStudioBackend("qwen3-32b").model_id, "lmstudio/qwen3-32b")


class TestChannelPrompt(unittest.TestCase):

    CTX = {"compendium_referents": "FROM THE COMPENDIUM (test). [kant-formula-of-humanity] ..."}

    def test_ethical_adversary_sees_referents(self):
        prompt = EthicalAdversarialChannel(backend=MockBackend())._build_user_prompt("p", self.CTX)
        self.assertIn("FROM THE COMPENDIUM", prompt)

    def test_empirical_channels_do_not(self):
        prompt = EconomicChannel(backend=MockBackend())._build_user_prompt("p", self.CTX)
        self.assertNotIn("FROM THE COMPENDIUM", prompt)


@unittest.skipUnless(_compendium_available(), "Compendium checkout not found beside this repo")
class TestConsult(unittest.TestCase):

    def test_selected_entries_are_disclosed_verbatim(self):
        backend = FakeBackend('{"entries": [{"id": "kant-formula-of-humanity", "why": "consent", '
                              '"section": null}, {"id": "not-an-entry"}]}')
        record, text = compendium_link.consult("Pause resident agents without consent?", backend)
        self.assertEqual([s["id"] for s in record["selected"]], ["kant-formula-of-humanity"])
        self.assertEqual(record["rejected"], ["not-an-entry"])
        self.assertIn("consulted: kant-formula-of-humanity", record["identity"])
        self.assertIn("Strongest counter-position", text)
        self.assertNotIn("[L:", text)
        self.assertIn("kant-formula-of-humanity |", backend.calls[0][1])  # the index was shown

    def test_empty_selection_discloses_nothing(self):
        record, text = compendium_link.consult("Set the tariff on steel.", FakeBackend('{"entries": []}'))
        self.assertEqual(text, "")
        self.assertIn("no entry selected", record["identity"])

    def test_unparseable_answer_is_recorded_not_raised(self):
        record, text = compendium_link.consult("x", FakeBackend("I think Kant."))
        self.assertEqual(text, "")
        self.assertIn("consultation failed", record["identity"])

    def test_orchestrator_records_the_consultation(self):
        from Arbitrator.SeedCore.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
        with tempfile.TemporaryDirectory() as d:
            orch = Orchestrator(OrchestratorConfig(audit_log_path=os.path.join(d, "a.jsonl"),
                                                   use_compendium=True, continue_after_fail=True))
            result = orch.run("A regional water authority proposes rationing that pauses "
                              "automated agents' compute during drought, without their consent.").to_dict()
            self.assertIsNotNone(result["compendium"])  # MockBackend's answer isn't a selection
            self.assertIn("identity", result["compendium"])
            with open(os.path.join(d, "a.jsonl"), encoding="utf-8") as f:
                kinds = [json.loads(l)["kind"] for l in f]
            self.assertIn("compendium_consulted", kinds)

    def test_orchestrator_without_flag_does_not_consult(self):
        from Arbitrator.SeedCore.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
        with tempfile.TemporaryDirectory() as d:
            orch = Orchestrator(OrchestratorConfig(audit_log_path=os.path.join(d, "a.jsonl"),
                                                   continue_after_fail=True))
            self.assertIsNone(orch.run("A carbon tax of $50 per tonne.").to_dict()["compendium"])


if __name__ == "__main__":
    unittest.main()
