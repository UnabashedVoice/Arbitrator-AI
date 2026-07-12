"""
test_model_registry.py — Tests for the model registry and channel-aware selector.

Tests:
    TestModelProfile            — profile validation and domain scoring
    TestChannelRequirements     — scoring a profile against channel requirements
    TestModelRegistry           — registration, lookup, custom profiles
    TestModelSelector           — selection logic, availability, fallback
    TestBuiltInProfiles         — sanity checks on built-in profile values
    TestChannelRequirementsMap  — built-in requirements sanity
    TestModelsCommand           — CLI 'arbitrator models' subcommands
    TestSelectorIntegration     — channel_stubs uses selector, not single backend

Run with:
    python -m unittest SeedCore/tests/test_model_registry.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Arbitrator.SeedCore.channels.model_registry import (
    ModelProfile,
    ChannelRequirements,
    ModelRegistry,
    ModelSelector,
    BUILT_IN_PROFILES,
    CHANNEL_REQUIREMENTS,
    get_model_registry,
    get_model_selector,
    _generic_profile,
    _discover_candidates,
)
from Arbitrator.SeedCore.channels.backend import (
    AnthropicBackend, OllamaBackend, MockBackend, BackendError
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def always_available(backend):
    """Patch a backend to always report as available."""
    backend.is_available = lambda: True
    return backend


def make_anthropic(model: str) -> AnthropicBackend:
    b = AnthropicBackend(model=model)
    b.is_available = lambda: True
    return b


def make_ollama(model: str) -> OllamaBackend:
    b = OllamaBackend(model=model)
    b.is_available = lambda: True
    return b


def all_available_candidates():
    """Return all built-in backends forced available."""
    return [
        make_anthropic("claude-opus-4-6"),
        make_anthropic("claude-sonnet-4-6"),
        make_anthropic("claude-haiku-4-5-20251001"),
        make_ollama("deepseek-r1:70b"),
        make_ollama("llama3.3:70b"),
        make_ollama("qwen2.5:72b"),
        make_ollama("mistral:7b"),
        MockBackend(),
    ]


def make_selector_all_available() -> ModelSelector:
    return ModelSelector(
        candidates=all_available_candidates(),
        registry=get_model_registry(),
        requirements=CHANNEL_REQUIREMENTS,
    )


def make_selector_mock_only() -> ModelSelector:
    return ModelSelector(
        candidates=[MockBackend()],
        registry=get_model_registry(),
        requirements=CHANNEL_REQUIREMENTS,
    )


def make_selector_local_only() -> ModelSelector:
    return ModelSelector(
        candidates=[
            make_ollama("deepseek-r1:70b"),
            make_ollama("qwen2.5:72b"),
            make_ollama("mistral:7b"),
            MockBackend(),
        ],
        registry=get_model_registry(),
        requirements=CHANNEL_REQUIREMENTS,
    )


# ---------------------------------------------------------------------------
# TestModelProfile
# ---------------------------------------------------------------------------

class TestModelProfile(unittest.TestCase):

    def make_profile(self, **kwargs) -> ModelProfile:
        defaults = dict(
            model_id="test/model", provider="test",
            display_name="Test Model",
            reasoning_depth=0.5, structured_output=0.5,
            context_capacity=0.5, instruction_following=0.5,
        )
        defaults.update(kwargs)
        return ModelProfile(**defaults)

    def test_valid_profile_creates(self):
        p = self.make_profile()
        self.assertEqual(p.model_id, "test/model")

    def test_invalid_score_above_1_raises(self):
        with self.assertRaises(ValueError):
            self.make_profile(reasoning_depth=1.1)

    def test_invalid_score_below_0_raises(self):
        with self.assertRaises(ValueError):
            self.make_profile(structured_output=-0.1)

    def test_domain_score_known_domain(self):
        p = self.make_profile(domain_knowledge={"economic": 0.85})
        self.assertAlmostEqual(p.domain_score("economic"), 0.85)

    def test_domain_score_unknown_domain_defaults_to_05(self):
        p = self.make_profile(domain_knowledge={})
        self.assertAlmostEqual(p.domain_score("unknown_domain"), 0.5)

    def test_speed_tier_default(self):
        p = self.make_profile()
        self.assertEqual(p.speed_tier, "standard")

    def test_context_window_default(self):
        p = self.make_profile()
        self.assertEqual(p.context_window_tokens, 8192)


# ---------------------------------------------------------------------------
# TestChannelRequirements
# ---------------------------------------------------------------------------

class TestChannelRequirements(unittest.TestCase):

    def make_req(self, **kwargs) -> ChannelRequirements:
        defaults = dict(
            channel_name="test",
            reasoning_depth_weight=0.25,
            structured_output_weight=0.25,
            context_capacity_weight=0.25,
            instruction_following_weight=0.25,
        )
        defaults.update(kwargs)
        return ChannelRequirements(**defaults)

    def make_profile(self, rd=0.5, so=0.5, cc=0.5, inf=0.5) -> ModelProfile:
        return ModelProfile(
            model_id="t/m", provider="t", display_name="t",
            reasoning_depth=rd, structured_output=so,
            context_capacity=cc, instruction_following=inf,
        )

    def test_perfect_profile_scores_high(self):
        # With equal weights (0.25 each) and domain_weight=0.2 (default) but
        # no primary_domains, total_weight=1.2 and domain contributes 0.
        # Score = 0.9*1.0 / 1.2 = 0.75. Expect > 0.70.
        req = self.make_req()
        p = self.make_profile(0.9, 0.9, 0.9, 0.9)
        score = req.score(p)
        self.assertGreater(score, 0.70)

    def test_perfect_profile_with_no_domain_weight_scores_near_input(self):
        # When domain_weight=0 and all dims 0.9, score should be exactly 0.9
        req = self.make_req(
            reasoning_depth_weight=0.25,
            structured_output_weight=0.25,
            context_capacity_weight=0.25,
            instruction_following_weight=0.25,
        )
        req.domain_weight = 0.0
        p = self.make_profile(0.9, 0.9, 0.9, 0.9)
        score = req.score(p)
        self.assertAlmostEqual(score, 0.9, places=3)

    def test_weak_profile_scores_low(self):
        req = self.make_req()
        p = self.make_profile(0.1, 0.1, 0.1, 0.1)
        score = req.score(p)
        self.assertLess(score, 0.3)

    def test_score_in_0_1_range(self):
        req = self.make_req()
        for scores in [(0.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0, 1.0), (0.5, 0.5, 0.5, 0.5)]:
            p = self.make_profile(*scores)
            s = req.score(p)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_high_reasoning_weight_rewards_reasoning(self):
        """Channel that values reasoning more should prefer high-reasoning model."""
        req_high = self.make_req(reasoning_depth_weight=0.8,
                                  structured_output_weight=0.1,
                                  context_capacity_weight=0.05,
                                  instruction_following_weight=0.05)
        req_low = self.make_req(reasoning_depth_weight=0.1,
                                structured_output_weight=0.7,
                                context_capacity_weight=0.1,
                                instruction_following_weight=0.1)
        high_reason = self.make_profile(rd=0.95, so=0.50, cc=0.50, inf=0.50)
        high_struct = self.make_profile(rd=0.50, so=0.95, cc=0.50, inf=0.50)

        self.assertGreater(req_high.score(high_reason), req_high.score(high_struct))
        self.assertGreater(req_low.score(high_struct), req_low.score(high_reason))

    def test_domain_knowledge_contributes_to_score(self):
        req = self.make_req(
            reasoning_depth_weight=0.20,
            structured_output_weight=0.20,
            context_capacity_weight=0.20,
            instruction_following_weight=0.20,
            primary_domains=["economic"],
            domain_weight=0.20,
        )
        p_with_domain = ModelProfile(
            model_id="t/m", provider="t", display_name="t",
            reasoning_depth=0.5, structured_output=0.5,
            context_capacity=0.5, instruction_following=0.5,
            domain_knowledge={"economic": 0.9},
        )
        p_without_domain = self.make_profile(0.5, 0.5, 0.5, 0.5)
        self.assertGreater(req.score(p_with_domain), req.score(p_without_domain))

    def test_zero_total_weight_returns_05(self):
        req = ChannelRequirements(
            channel_name="test",
            reasoning_depth_weight=0.0,
            structured_output_weight=0.0,
            context_capacity_weight=0.0,
            instruction_following_weight=0.0,
            domain_weight=0.0,
        )
        p = self.make_profile()
        self.assertEqual(req.score(p), 0.5)


# ---------------------------------------------------------------------------
# TestModelRegistry
# ---------------------------------------------------------------------------

class TestModelRegistry(unittest.TestCase):

    def test_built_in_profiles_loaded(self):
        registry = ModelRegistry()
        self.assertEqual(len(registry.all_profiles()), len(BUILT_IN_PROFILES))

    def test_get_known_model(self):
        registry = ModelRegistry()
        p = registry.get("anthropic/claude-opus-4-6")
        self.assertIsNotNone(p)
        self.assertEqual(p.model_id, "anthropic/claude-opus-4-6")

    def test_get_unknown_model_returns_none(self):
        registry = ModelRegistry()
        self.assertIsNone(registry.get("totally/unknown-model"))

    def test_get_or_default_unknown_returns_generic(self):
        registry = ModelRegistry()
        p = registry.get_or_default("my/custom-model")
        self.assertEqual(p.model_id, "my/custom-model")
        self.assertEqual(p.provider, "my")
        self.assertIn("generic", p.notes.lower())

    def test_register_custom_profile(self):
        registry = ModelRegistry()
        custom = ModelProfile(
            model_id="custom/my-model",
            provider="custom",
            display_name="My Custom Model",
            reasoning_depth=0.7,
            structured_output=0.7,
            context_capacity=0.7,
            instruction_following=0.7,
        )
        registry.register(custom)
        retrieved = registry.get("custom/my-model")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.display_name, "My Custom Model")

    def test_register_overrides_existing(self):
        registry = ModelRegistry()
        override = ModelProfile(
            model_id="anthropic/claude-opus-4-6",
            provider="anthropic",
            display_name="Overridden Opus",
            reasoning_depth=0.1,
            structured_output=0.1,
            context_capacity=0.1,
            instruction_following=0.1,
        )
        registry.register(override)
        p = registry.get("anthropic/claude-opus-4-6")
        self.assertEqual(p.display_name, "Overridden Opus")

    def test_profiles_for_provider(self):
        registry = ModelRegistry()
        anthropic = registry.profiles_for_provider("anthropic")
        self.assertGreater(len(anthropic), 0)
        for p in anthropic:
            self.assertEqual(p.provider, "anthropic")

    def test_all_profiles_returns_list(self):
        registry = ModelRegistry()
        profiles = registry.all_profiles()
        self.assertIsInstance(profiles, list)
        self.assertGreater(len(profiles), 0)


# ---------------------------------------------------------------------------
# TestBuiltInProfiles
# ---------------------------------------------------------------------------

class TestBuiltInProfiles(unittest.TestCase):
    """Sanity checks on built-in profile values."""

    def test_all_profiles_have_valid_scores(self):
        for p in BUILT_IN_PROFILES:
            for attr in ("reasoning_depth", "structured_output",
                         "context_capacity", "instruction_following"):
                val = getattr(p, attr)
                self.assertGreaterEqual(val, 0.0, f"{p.model_id}.{attr} < 0")
                self.assertLessEqual(val, 1.0, f"{p.model_id}.{attr} > 1")

    def test_opus_outscores_haiku_on_reasoning(self):
        registry = ModelRegistry()
        opus = registry.get("anthropic/claude-opus-4-6")
        haiku = registry.get("anthropic/claude-haiku-4-5-20251001")
        self.assertGreater(opus.reasoning_depth, haiku.reasoning_depth)

    def test_opus_outscores_sonnet_on_reasoning(self):
        registry = ModelRegistry()
        opus = registry.get("anthropic/claude-opus-4-6")
        sonnet = registry.get("anthropic/claude-sonnet-4-6")
        self.assertGreater(opus.reasoning_depth, sonnet.reasoning_depth)

    def test_haiku_is_fast_tier(self):
        registry = ModelRegistry()
        haiku = registry.get("anthropic/claude-haiku-4-5-20251001")
        self.assertEqual(haiku.speed_tier, "fast")

    def test_opus_is_slow_tier(self):
        registry = ModelRegistry()
        opus = registry.get("anthropic/claude-opus-4-6")
        self.assertEqual(opus.speed_tier, "slow")

    def test_mock_has_perfect_structured_output(self):
        registry = ModelRegistry()
        mock = registry.get("mock/deterministic-v1")
        self.assertEqual(mock.structured_output, 1.0)

    def test_mock_has_zero_reasoning_depth(self):
        registry = ModelRegistry()
        mock = registry.get("mock/deterministic-v1")
        self.assertEqual(mock.reasoning_depth, 0.0)

    def test_all_profiles_have_model_id(self):
        for p in BUILT_IN_PROFILES:
            self.assertTrue(p.model_id, f"Profile missing model_id: {p}")

    def test_all_profiles_have_provider(self):
        for p in BUILT_IN_PROFILES:
            self.assertTrue(p.provider, f"Profile missing provider: {p}")

    def test_deepseek_has_high_reasoning(self):
        registry = ModelRegistry()
        ds = registry.get("ollama/deepseek-r1:70b")
        self.assertIsNotNone(ds)
        self.assertGreater(ds.reasoning_depth, 0.80)

    def test_model_ids_match_backend_model_ids(self):
        """Profile model_ids must match what backends return for registry lookup."""
        registry = ModelRegistry()
        for b in [
            AnthropicBackend("claude-opus-4-6"),
            AnthropicBackend("claude-sonnet-4-6"),
            AnthropicBackend("claude-haiku-4-5-20251001"),
        ]:
            p = registry.get(b.model_id)
            self.assertIsNotNone(p,
                f"No profile for backend model_id '{b.model_id}'")


# ---------------------------------------------------------------------------
# TestChannelRequirementsMap
# ---------------------------------------------------------------------------

class TestChannelRequirementsMap(unittest.TestCase):
    """Sanity checks on built-in channel requirements."""

    CHANNELS = [
        "economic", "ecological", "social_demographic",
        "ethical_adversarial", "historical_precedent",
        "legal_institutional", "geopolitical", "uncertainty_modeling",
    ]

    def test_all_channels_have_requirements(self):
        for ch in self.CHANNELS:
            self.assertIn(ch, CHANNEL_REQUIREMENTS, f"Missing: {ch}")

    def test_all_weights_positive(self):
        for ch, req in CHANNEL_REQUIREMENTS.items():
            for attr in ("reasoning_depth_weight", "structured_output_weight",
                         "context_capacity_weight", "instruction_following_weight",
                         "domain_weight"):
                val = getattr(req, attr)
                self.assertGreaterEqual(val, 0.0, f"{ch}.{attr} < 0")

    def test_adversarial_has_highest_reasoning_weight(self):
        """ethical_adversarial should weight reasoning most heavily."""
        adv = CHANNEL_REQUIREMENTS["ethical_adversarial"]
        for ch, req in CHANNEL_REQUIREMENTS.items():
            if ch != "ethical_adversarial":
                self.assertGreaterEqual(
                    adv.reasoning_depth_weight, req.reasoning_depth_weight,
                    f"adversarial reasoning weight should be >= {ch}"
                )

    def test_uncertainty_has_high_reasoning_weight(self):
        unc = CHANNEL_REQUIREMENTS["uncertainty_modeling"]
        self.assertGreaterEqual(unc.reasoning_depth_weight, 0.30)

    def test_legal_has_significant_context_weight(self):
        legal = CHANNEL_REQUIREMENTS["legal_institutional"]
        self.assertGreaterEqual(legal.context_capacity_weight, 0.20)

    def test_all_channels_have_primary_domains(self):
        for ch, req in CHANNEL_REQUIREMENTS.items():
            self.assertGreater(len(req.primary_domains), 0,
                               f"{ch} has no primary_domains")


# ---------------------------------------------------------------------------
# TestModelSelector
# ---------------------------------------------------------------------------

class TestModelSelector(unittest.TestCase):

    def test_mock_only_returns_mock(self):
        sel = make_selector_mock_only()
        for ch in CHANNEL_REQUIREMENTS:
            b = sel.for_channel(ch)
            self.assertIsInstance(b, MockBackend)

    def test_all_available_opus_wins_adversarial(self):
        """When Opus is available, it should win for ethical_adversarial."""
        sel = make_selector_all_available()
        b = sel.for_channel("ethical_adversarial")
        self.assertEqual(b.model_id, "anthropic/claude-opus-4-6")

    def test_all_available_opus_wins_uncertainty(self):
        """Uncertainty modeling also demands highest reasoning — Opus should win."""
        sel = make_selector_all_available()
        b = sel.for_channel("uncertainty_modeling")
        self.assertEqual(b.model_id, "anthropic/claude-opus-4-6")

    def test_all_available_opus_wins_all_channels(self):
        """With all backends available, Opus should win every channel."""
        sel = make_selector_all_available()
        for ch in CHANNEL_REQUIREMENTS:
            b = sel.for_channel(ch)
            self.assertEqual(b.model_id, "anthropic/claude-opus-4-6",
                             f"Opus should win {ch}")

    def test_local_only_deepseek_wins_adversarial(self):
        """Without Anthropic, DeepSeek R1 should win adversarial (highest local reasoning)."""
        sel = make_selector_local_only()
        b = sel.for_channel("ethical_adversarial")
        self.assertEqual(b.model_id, "ollama/deepseek-r1:70b")

    def test_local_only_deepseek_or_qwen_wins_uncertainty(self):
        """Without Anthropic, deepseek or qwen should win uncertainty_modeling."""
        sel = make_selector_local_only()
        b = sel.for_channel("uncertainty_modeling")
        self.assertIn(b.model_id, ["ollama/deepseek-r1:70b", "ollama/qwen2.5:72b"])

    def test_mistral_7b_not_selected_when_better_available(self):
        """Mistral 7B should never be selected when 70B models are available."""
        sel = make_selector_local_only()
        for ch in CHANNEL_REQUIREMENTS:
            b = sel.for_channel(ch)
            self.assertNotEqual(b.model_id, "ollama/mistral:7b",
                               f"Mistral 7B should not win {ch} with better options")

    def test_no_available_backends_raises(self):
        sel = ModelSelector(candidates=[])
        with self.assertRaises(BackendError):
            sel.for_channel("economic")

    def test_no_available_backends_returns_fallback(self):
        sel = ModelSelector(candidates=[])
        mock = MockBackend()
        b = sel.for_channel("economic", fallback=mock)
        self.assertIsInstance(b, MockBackend)

    def test_all_selections_returns_all_channels(self):
        sel = make_selector_mock_only()
        selections = sel.all_selections()
        for ch in CHANNEL_REQUIREMENTS:
            self.assertIn(ch, selections)

    def test_explain_returns_ranked_list(self):
        sel = make_selector_all_available()
        rankings = sel.explain("ethical_adversarial")
        self.assertGreater(len(rankings), 0)
        # Verify sorted descending
        scores = [s for s, _ in rankings]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_explain_unknown_channel_returns_empty(self):
        sel = make_selector_mock_only()
        rankings = sel.explain("nonexistent_channel")
        self.assertEqual(rankings, [])

    def test_availability_cached(self):
        """is_available() should only be called once per backend."""
        call_counts = {}

        class CountingMock(MockBackend):
            def is_available(self):
                call_counts["mock"] = call_counts.get("mock", 0) + 1
                return True

        sel = ModelSelector(candidates=[CountingMock()])
        sel.for_channel("economic")
        sel.for_channel("ecological")
        sel.for_channel("ethical_adversarial")
        self.assertEqual(call_counts.get("mock", 0), 1,
                         "is_available() should be cached after first call")

    def test_generic_profile_used_for_unknown_model(self):
        """A backend with an unregistered model_id should get a generic profile."""
        class UnknownBackend(MockBackend):
            @property
            def model_id(self):
                return "unknown/never-heard-of-this-model"
            def is_available(self):
                return True

        sel = ModelSelector(
            candidates=[UnknownBackend(), MockBackend()],
            registry=get_model_registry(),
        )
        # Should not raise; should use generic profile
        b = sel.for_channel("economic")
        self.assertIsNotNone(b)


# ---------------------------------------------------------------------------
# TestModelsCommand
# ---------------------------------------------------------------------------

def run_models_cmd(argv: list, config=None) -> tuple[int, str, str]:
    from Arbitrator.cli.config_manager import ConfigManager
    from Arbitrator.cli.main import build_parser, dispatch
    from Arbitrator.cli import display as display_mod
    display_mod.set_color(False)

    if config is None:
        config = ConfigManager()

    stdout_buf = StringIO()
    stderr_buf = StringIO()
    with patch("sys.stdout", stdout_buf), patch("sys.stderr", stderr_buf):
        parser = build_parser()
        args = parser.parse_args(argv)
        code = dispatch(args, config)
    return code, stdout_buf.getvalue(), stderr_buf.getvalue()


class TestModelsCommand(unittest.TestCase):

    def test_models_list(self):
        code, out, err = run_models_cmd(["models", "list"])
        self.assertEqual(code, 0)
        self.assertIn("REGISTERED MODEL PROFILES", out)

    def test_models_list_json(self):
        code, out, err = run_models_cmd(["models", "list", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("model_id", data[0])
        self.assertIn("reasoning_depth", data[0])

    def test_models_available(self):
        code, out, err = run_models_cmd(["models", "available"])
        self.assertEqual(code, 0)
        self.assertIn("BACKEND AVAILABILITY", out)

    def test_models_available_json(self):
        code, out, err = run_models_cmd(["models", "available", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        for item in data:
            self.assertIn("model_id", item)
            self.assertIn("available", item)

    def test_models_explain(self):
        code, out, err = run_models_cmd(["models", "explain"])
        self.assertEqual(code, 0)
        self.assertIn("CHANNEL MODEL RANKINGS", out)
        self.assertIn("ETHICAL ADVERSARIAL", out)

    def test_models_explain_single_channel(self):
        code, out, err = run_models_cmd(
            ["models", "explain", "--channel", "economic"]
        )
        self.assertEqual(code, 0)
        self.assertIn("ECONOMIC", out)
        self.assertNotIn("ECOLOGICAL", out)

    def test_models_explain_json(self):
        code, out, err = run_models_cmd(["models", "explain", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        for ch in ["ethical_adversarial", "economic"]:
            self.assertIn(ch, data)
            # Each channel should have a list of (score, model_id) dicts
            self.assertIsInstance(data[ch], list)

    def test_models_register_valid_profile(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({
                "model_id": "custom/my-test-model",
                "provider": "custom",
                "display_name": "My Test Model",
                "reasoning_depth": 0.75,
                "structured_output": 0.70,
                "context_capacity": 0.65,
                "instruction_following": 0.72,
                "domain_knowledge": {"economic": 0.80},
                "speed_tier": "fast",
                "context_window_tokens": 16384,
            }, f)
            fname = f.name

        try:
            code, out, err = run_models_cmd(["models", "register", fname])
            self.assertEqual(code, 0)
        finally:
            os.unlink(fname)

    def test_models_register_nonexistent_file(self):
        code, out, err = run_models_cmd(
            ["models", "register", "/nonexistent/path/profile.json"]
        )
        self.assertEqual(code, 2)

    def test_models_register_invalid_json(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("{not valid json")
            fname = f.name

        try:
            code, out, err = run_models_cmd(["models", "register", fname])
            self.assertEqual(code, 2)
        finally:
            os.unlink(fname)

    def test_models_no_subcommand_returns_error(self):
        code, out, err = run_models_cmd(["models"])
        self.assertEqual(code, 2)

    def test_models_explain_shows_arrow_for_best(self):
        code, out, err = run_models_cmd(["models", "explain"])
        self.assertEqual(code, 0)
        self.assertIn("→", out)

    def test_models_list_contains_opus(self):
        code, out, err = run_models_cmd(["models", "list"])
        self.assertIn("claude-opus", out)

    def test_models_list_contains_mock(self):
        code, out, err = run_models_cmd(["models", "list"])
        self.assertIn("mock", out)


# ---------------------------------------------------------------------------
# TestSelectorIntegration
# ---------------------------------------------------------------------------

class TestSelectorIntegration(unittest.TestCase):
    """Verify that channel_stubs correctly uses the selector."""

    def test_channel_stubs_builds_with_mock(self):
        """The registry should build without error in this environment."""
        from Arbitrator.SeedCore.orchestrator.channel_stubs import _build_registry
        registry = _build_registry()
        self.assertIn("economic", registry)
        self.assertIn("ethical_adversarial", registry)
        self.assertEqual(len(registry), 8)

    def test_channel_stubs_builds_with_custom_selector(self):
        """Can pass a custom selector to _build_registry."""
        from Arbitrator.SeedCore.orchestrator.channel_stubs import _build_registry
        sel = make_selector_mock_only()
        registry = _build_registry(selector=sel)
        self.assertEqual(len(registry), 8)

    def test_each_channel_has_backend_attribute(self):
        """Each registered channel should have a _backend attribute."""
        from Arbitrator.SeedCore.orchestrator.channel_stubs import _build_registry
        sel = make_selector_mock_only()
        registry = _build_registry(selector=sel)
        for name, channel in registry.items():
            self.assertTrue(
                hasattr(channel, '_backend'),
                f"Channel '{name}' missing _backend attribute"
            )

    def test_explain_model_selections_returns_all_channels(self):
        from Arbitrator.SeedCore.orchestrator.channel_stubs import explain_model_selections
        sel = make_selector_mock_only()
        explanations = explain_model_selections(selector=sel)
        for ch in CHANNEL_REQUIREMENTS:
            self.assertIn(ch, explanations)

    def test_full_pipeline_uses_per_channel_backends(self):
        """After _build_registry with selector, each channel's model_id is logged."""
        from Arbitrator.SeedCore.orchestrator.channel_stubs import _build_registry

        # Use all-available selector to force differentiation
        sel = make_selector_all_available()
        registry = _build_registry(selector=sel)

        # All channels should have Opus as their backend when it's available
        for name, channel in registry.items():
            if hasattr(channel, '_backend'):
                self.assertEqual(
                    channel._backend.model_id, "anthropic/claude-opus-4-6",
                    f"Channel {name} should use Opus when it's the best available"
                )

    def test_generic_profile_for_unknown_ollama_model(self):
        """An Ollama model not in the registry should get a generic profile."""
        registry = get_model_registry()
        p = registry.get_or_default("ollama/some-new-model-2026")
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.reasoning_depth, 0.60, places=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
