"""
model_registry.py — Model capability profiles and channel-aware backend selection.

Arbitrator does not treat all models as interchangeable. Each channel has
distinct requirements, and different models have distinct strengths. The
registry encodes this relationship so the system can select the most
capable available model for each channel's task.

CAPABILITY DIMENSIONS:

    reasoning_depth     [0.0–1.0]
        Ability to reason through complex, multi-step problems with
        incomplete information. Required highly for: ethical_adversarial,
        uncertainty_modeling. Required moderately for: historical_precedent,
        geopolitical.

    structured_output   [0.0–1.0]
        Reliability of well-formed JSON output matching a schema.
        All channels require this — the parser is lenient, but the higher
        this score, the fewer parse failures and retry cycles.

    context_capacity    [0.0–1.0]
        Effective handling of long inputs and generation of long outputs.
        Required for: geopolitical (many actors), legal_institutional
        (statute references), historical_precedent (case detail).

    domain_knowledge    dict[str, float]
        Estimated domain-specific knowledge depth per channel tag domain.
        This is prior knowledge, not retrieval — models trained on large
        corpora of legal, ecological, or economic text perform better in
        those domains.

    instruction_following [0.0–1.0]
        Ability to follow complex, multi-part instructions without
        hallucinating structure or ignoring constraints.
        All channels depend on this; adversarial and uncertainty rely on it most.

    speed_tier          "fast" | "standard" | "slow"
        Relative inference speed. Not used in correctness ranking, but
        surfaced for operator decision-making and logged per invocation.

CHANNEL REQUIREMENTS:

Each channel declares minimum acceptable scores per dimension and a
ranked list of preferred domain knowledge areas. The selector uses these
to score available models and return the best match.

SELECTING A BACKEND:

    selector = ModelSelector()
    backend = selector.for_channel("ethical_adversarial")

The selector:
    1. Queries all registered backends for availability
    2. Scores each available backend against the channel's requirements
    3. Returns the highest-scoring available backend
    4. Falls back through the availability chain to MockBackend

MODEL PROFILE REGISTRATION:

Built-in profiles cover known Anthropic and common Ollama models.
Operators can register custom profiles for local models:

    registry = get_model_registry()
    registry.register(ModelProfile(
        model_id="ollama/llama3.1:70b",
        provider="ollama",
        ...
    ))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .backend import (
    ModelBackend,
    AnthropicBackend,
    OllamaBackend,
    MockBackend,
    BackendError,
)


# ---------------------------------------------------------------------------
# ModelProfile
# ---------------------------------------------------------------------------

@dataclass
class ModelProfile:
    """
    Capability profile for a specific model.

    All scores are in [0.0, 1.0]. They represent relative capability
    compared to the best available model in that dimension, not absolute
    benchmarks.

    Attributes:
        model_id:               Canonical ID, e.g. "anthropic/claude-opus-4-6"
        provider:               "anthropic" | "ollama" | "mock" | "custom"
        display_name:           Human-readable name for logs and display.
        reasoning_depth:        Multi-step reasoning and inference quality.
        structured_output:      JSON schema compliance and parse reliability.
        context_capacity:       Effective long-context handling.
        instruction_following:  Complex multi-part instruction adherence.
        domain_knowledge:       Per-domain estimated knowledge depth.
        speed_tier:             Relative speed class.
        context_window_tokens:  Maximum context window in tokens.
        notes:                  Optional operator notes.
    """
    model_id: str
    provider: str
    display_name: str
    reasoning_depth: float
    structured_output: float
    context_capacity: float
    instruction_following: float
    domain_knowledge: dict[str, float] = field(default_factory=dict)
    speed_tier: str = "standard"          # "fast" | "standard" | "slow"
    context_window_tokens: int = 8192
    notes: str = ""

    def domain_score(self, domain: str) -> float:
        """Return domain knowledge score, defaulting to 0.5 for unknown domains."""
        return self.domain_knowledge.get(domain, 0.5)

    def __post_init__(self):
        for attr in ("reasoning_depth", "structured_output",
                     "context_capacity", "instruction_following"):
            val = getattr(self, attr)
            if not (0.0 <= val <= 1.0):
                raise ValueError(
                    f"ModelProfile.{attr} must be in [0.0, 1.0], got {val}"
                )


# ---------------------------------------------------------------------------
# ChannelRequirements
# ---------------------------------------------------------------------------

@dataclass
class ChannelRequirements:
    """
    The model capability requirements for a specific channel.

    Attributes:
        channel_name:               The channel this applies to.
        reasoning_depth_weight:     Importance of reasoning depth [0–1].
        structured_output_weight:   Importance of JSON reliability [0–1].
        context_capacity_weight:    Importance of context handling [0–1].
        instruction_following_weight: Importance of instruction adherence [0–1].
        primary_domains:            Ordered list of domain knowledge areas
                                    this channel benefits from most.
        domain_weight:              Collective weight for domain knowledge [0–1].
        notes:                      Why these weights were chosen.
    """
    channel_name: str
    reasoning_depth_weight: float
    structured_output_weight: float
    context_capacity_weight: float
    instruction_following_weight: float
    primary_domains: list[str] = field(default_factory=list)
    domain_weight: float = 0.2
    notes: str = ""

    def score(self, profile: ModelProfile) -> float:
        """
        Score a model profile against this channel's requirements.

        Returns a float in [0.0, 1.0] representing overall fit.
        Weights are normalized to sum to 1.0 before scoring.
        """
        total_weight = (
            self.reasoning_depth_weight
            + self.structured_output_weight
            + self.context_capacity_weight
            + self.instruction_following_weight
            + self.domain_weight
        )
        if total_weight == 0:
            return 0.5

        # Capability dimensions
        score = (
            self.reasoning_depth_weight * profile.reasoning_depth
            + self.structured_output_weight * profile.structured_output
            + self.context_capacity_weight * profile.context_capacity
            + self.instruction_following_weight * profile.instruction_following
        )

        # Domain knowledge: average over primary domains
        if self.primary_domains:
            domain_avg = sum(
                profile.domain_score(d) for d in self.primary_domains
            ) / len(self.primary_domains)
            score += self.domain_weight * domain_avg

        return round(score / total_weight, 4)


# ---------------------------------------------------------------------------
# Built-in channel requirements
# ---------------------------------------------------------------------------
#
# Design rationale for each channel's weights:
#
# economic:
#   Requires precise structured output (distributional scorecards, numbers).
#   Moderate reasoning — the logic chain is long but mostly linear.
#   Benefits from economics domain knowledge.
#
# ecological:
#   Domain knowledge is paramount — carbon accounting, biodiversity, IPCC.
#   Structured output matters for the irreversibility flag.
#   Moderate reasoning for ecosystem service valuation chains.
#
# social_demographic:
#   Heavy instruction_following — must disaggregate, never aggregate-only.
#   Domain knowledge spans health, equity, civil_liberties.
#   Moderate reasoning.
#
# ethical_adversarial:
#   Reasoning depth is the dominant requirement — must identify non-obvious
#   failure modes, simulate adversarial actors, surface capture risks.
#   High instruction_following — must run all seven named analyses.
#   Less domain-specific than the others.
#
# historical_precedent:
#   Domain knowledge + context capacity — needs broad recall of specific
#   cases with accurate detail. Can't hallucinate precedents.
#   Moderate reasoning, high structured output for case naming requirement.
#
# legal_institutional:
#   Context capacity — statutes, regulations, constitutional provisions.
#   Domain knowledge in law and governance.
#   High structured output for the implementation feasibility map.
#
# geopolitical:
#   Context capacity — many actors, many relationships.
#   Reasoning for multi-actor game-theoretic inference.
#   Domain knowledge in international relations.
#
# uncertainty_modeling:
#   Highest reasoning depth — synthesizes outputs from all other channels
#   and models reliability of the entire analysis.
#   Must reason about what it doesn't know.
#   High instruction_following — must run sensitivity analysis, scenarios.

CHANNEL_REQUIREMENTS: dict[str, ChannelRequirements] = {
    "economic": ChannelRequirements(
        channel_name="economic",
        reasoning_depth_weight=0.20,
        structured_output_weight=0.30,
        context_capacity_weight=0.15,
        instruction_following_weight=0.20,
        primary_domains=["economic", "fiscal", "labor"],
        domain_weight=0.15,
        notes="Precision and structured output matter most. "
              "Economic analysis requires reliable numbers and scorecard structure.",
    ),
    "ecological": ChannelRequirements(
        channel_name="ecological",
        reasoning_depth_weight=0.20,
        structured_output_weight=0.25,
        context_capacity_weight=0.15,
        instruction_following_weight=0.20,
        primary_domains=["ecological", "biodiversity", "climate"],
        domain_weight=0.20,
        notes="Domain knowledge is critical — IPCC findings, biodiversity "
              "metrics, carbon accounting. Hallucinated ecology is dangerous.",
    ),
    "social_demographic": ChannelRequirements(
        channel_name="social_demographic",
        reasoning_depth_weight=0.20,
        structured_output_weight=0.25,
        context_capacity_weight=0.15,
        instruction_following_weight=0.25,
        primary_domains=["social", "demographic", "health", "equity"],
        domain_weight=0.15,
        notes="Instruction following is critical — disaggregation requirement "
              "must be enforced. Domain spans health, equity, civil liberties.",
    ),
    "ethical_adversarial": ChannelRequirements(
        channel_name="ethical_adversarial",
        reasoning_depth_weight=0.35,
        structured_output_weight=0.20,
        context_capacity_weight=0.10,
        instruction_following_weight=0.25,
        primary_domains=["adversarial", "ethics"],
        domain_weight=0.10,
        notes="Reasoning depth is the dominant requirement. Must surface "
              "non-obvious failure modes and simulate adversarial actors. "
              "Best model available should run this channel.",
    ),
    "historical_precedent": ChannelRequirements(
        channel_name="historical_precedent",
        reasoning_depth_weight=0.20,
        structured_output_weight=0.25,
        context_capacity_weight=0.25,
        instruction_following_weight=0.15,
        primary_domains=["historical", "comparative"],
        domain_weight=0.15,
        notes="Context capacity and domain knowledge matter — must recall "
              "specific named cases accurately. Hallucinated precedents are "
              "worse than acknowledged ignorance.",
    ),
    "legal_institutional": ChannelRequirements(
        channel_name="legal_institutional",
        reasoning_depth_weight=0.20,
        structured_output_weight=0.25,
        context_capacity_weight=0.25,
        instruction_following_weight=0.15,
        primary_domains=["legal", "institutional", "constitutional", "governance"],
        domain_weight=0.15,
        notes="Context capacity for statute and regulatory references. "
              "Legal domain knowledge critical. Implementation feasibility "
              "analysis requires long structured output.",
    ),
    "geopolitical": ChannelRequirements(
        channel_name="geopolitical",
        reasoning_depth_weight=0.25,
        structured_output_weight=0.20,
        context_capacity_weight=0.25,
        instruction_following_weight=0.15,
        primary_domains=["geopolitical", "international", "trade", "security"],
        domain_weight=0.15,
        notes="Context capacity for multi-actor analysis. Reasoning for "
              "game-theoretic inference over alliance and adversary responses.",
    ),
    "uncertainty_modeling": ChannelRequirements(
        channel_name="uncertainty_modeling",
        reasoning_depth_weight=0.35,
        structured_output_weight=0.20,
        context_capacity_weight=0.20,
        instruction_following_weight=0.20,
        primary_domains=["uncertainty", "risk"],
        domain_weight=0.05,
        notes="Highest reasoning depth. Must synthesize all other channels "
              "and reason about what the entire analysis does not know. "
              "Best model available should run this alongside adversarial.",
    ),
}


# ---------------------------------------------------------------------------
# Built-in model profiles
# ---------------------------------------------------------------------------
#
# Domain knowledge scores are estimates based on:
# - Training data characteristics (public information)
# - Observed benchmark performance in domain-specific tasks
# - Qualitative assessment from adversarial testing
#
# These are priors, not ground truth. Operators should adjust via
# custom registration if they observe different behaviour.

BUILT_IN_PROFILES: list[ModelProfile] = [

    # ── Anthropic ────────────────────────────────────────────────────────────

    ModelProfile(
        model_id="anthropic/claude-opus-4-6",
        provider="anthropic",
        display_name="Claude Opus 4.6",
        reasoning_depth=0.97,
        structured_output=0.95,
        context_capacity=0.95,
        instruction_following=0.97,
        domain_knowledge={
            "economic": 0.90, "ecological": 0.88, "social": 0.90,
            "demographic": 0.88, "adversarial": 0.95, "ethics": 0.95,
            "historical": 0.90, "legal": 0.90, "institutional": 0.88,
            "geopolitical": 0.90, "international": 0.88, "uncertainty": 0.92,
            "risk": 0.90, "climate": 0.88, "biodiversity": 0.82,
        },
        speed_tier="slow",
        context_window_tokens=200000,
        notes="Highest reasoning depth. Best for adversarial and uncertainty "
              "channels. Use when correctness outweighs cost.",
    ),

    ModelProfile(
        model_id="anthropic/claude-sonnet-4-6",
        provider="anthropic",
        display_name="Claude Sonnet 4.6",
        reasoning_depth=0.90,
        structured_output=0.93,
        context_capacity=0.92,
        instruction_following=0.93,
        domain_knowledge={
            "economic": 0.87, "ecological": 0.85, "social": 0.87,
            "demographic": 0.85, "adversarial": 0.88, "ethics": 0.90,
            "historical": 0.87, "legal": 0.87, "institutional": 0.85,
            "geopolitical": 0.87, "international": 0.85, "uncertainty": 0.88,
            "risk": 0.87, "climate": 0.85, "biodiversity": 0.80,
        },
        speed_tier="standard",
        context_window_tokens=200000,
        notes="Strong across all dimensions. Best default for most channels. "
              "Good balance of capability and throughput.",
    ),

    ModelProfile(
        model_id="anthropic/claude-haiku-4-5-20251001",
        provider="anthropic",
        display_name="Claude Haiku 4.5",
        reasoning_depth=0.75,
        structured_output=0.88,
        context_capacity=0.85,
        instruction_following=0.85,
        domain_knowledge={
            "economic": 0.75, "ecological": 0.72, "social": 0.75,
            "demographic": 0.72, "adversarial": 0.70, "ethics": 0.75,
            "historical": 0.73, "legal": 0.75, "institutional": 0.72,
            "geopolitical": 0.73, "international": 0.72, "uncertainty": 0.73,
            "risk": 0.73, "climate": 0.70, "biodiversity": 0.68,
        },
        speed_tier="fast",
        context_window_tokens=200000,
        notes="Fast and cost-efficient. Adequate for less reasoning-intensive "
              "channels (economic structured output, legal references). "
              "Not recommended for adversarial or uncertainty.",
    ),

    # ── Ollama / open weights ────────────────────────────────────────────────
    # Scores are conservative estimates. Performance varies significantly
    # by quantization level and hardware. Operators should adjust if needed.

    ModelProfile(
        model_id="ollama/llama3.3:70b",
        provider="ollama",
        display_name="LLaMA 3.3 70B (Ollama)",
        reasoning_depth=0.82,
        structured_output=0.78,
        context_capacity=0.75,
        instruction_following=0.80,
        domain_knowledge={
            "economic": 0.78, "ecological": 0.72, "social": 0.78,
            "demographic": 0.75, "adversarial": 0.76, "ethics": 0.78,
            "historical": 0.78, "legal": 0.75, "institutional": 0.72,
            "geopolitical": 0.78, "international": 0.75, "uncertainty": 0.76,
            "risk": 0.75, "climate": 0.70, "biodiversity": 0.65,
        },
        speed_tier="standard",
        context_window_tokens=128000,
        notes="Strong open-weight model. Best local option for most channels. "
              "Structured output less reliable than Anthropic — more retries expected.",
    ),

    ModelProfile(
        model_id="ollama/qwen2.5:72b",
        provider="ollama",
        display_name="Qwen 2.5 72B (Ollama)",
        reasoning_depth=0.83,
        structured_output=0.82,
        context_capacity=0.80,
        instruction_following=0.82,
        domain_knowledge={
            "economic": 0.80, "ecological": 0.72, "social": 0.78,
            "demographic": 0.75, "adversarial": 0.78, "ethics": 0.80,
            "historical": 0.78, "legal": 0.78, "institutional": 0.75,
            "geopolitical": 0.80, "international": 0.80, "uncertainty": 0.78,
            "risk": 0.77, "climate": 0.70, "biodiversity": 0.65,
        },
        speed_tier="standard",
        context_window_tokens=128000,
        notes="Strong multilingual and structured output. Good for geopolitical "
              "and legal channels. Better JSON compliance than LLaMA.",
    ),

    ModelProfile(
        model_id="ollama/mistral:7b",
        provider="ollama",
        display_name="Mistral 7B (Ollama)",
        reasoning_depth=0.62,
        structured_output=0.68,
        context_capacity=0.55,
        instruction_following=0.65,
        domain_knowledge={
            "economic": 0.62, "ecological": 0.55, "social": 0.62,
            "demographic": 0.58, "adversarial": 0.55, "ethics": 0.60,
            "historical": 0.60, "legal": 0.60, "institutional": 0.58,
            "geopolitical": 0.62, "international": 0.60, "uncertainty": 0.58,
            "risk": 0.58, "climate": 0.55, "biodiversity": 0.50,
        },
        speed_tier="fast",
        context_window_tokens=32768,
        notes="Lightweight and fast. Adequate for simple channels when hardware "
              "is constrained. Not recommended for adversarial, uncertainty, "
              "or legal channels without operator testing.",
    ),

    ModelProfile(
        model_id="ollama/mistral-nemo:12b",
        provider="ollama",
        display_name="Mistral Nemo 12B (Ollama)",
        reasoning_depth=0.70,
        structured_output=0.72,
        context_capacity=0.65,
        instruction_following=0.70,
        domain_knowledge={
            "economic": 0.68, "ecological": 0.60, "social": 0.68,
            "demographic": 0.62, "adversarial": 0.62, "ethics": 0.65,
            "historical": 0.65, "legal": 0.65, "institutional": 0.62,
            "geopolitical": 0.67, "international": 0.65, "uncertainty": 0.63,
            "risk": 0.63, "climate": 0.58, "biodiversity": 0.53,
        },
        speed_tier="fast",
        context_window_tokens=128000,
        notes="Good balance of speed and capability for a local 12B model. "
              "128K context is an advantage for legal and historical channels.",
    ),

    ModelProfile(
        model_id="ollama/deepseek-r1:70b",
        provider="ollama",
        display_name="DeepSeek R1 70B (Ollama)",
        reasoning_depth=0.88,
        structured_output=0.76,
        context_capacity=0.75,
        instruction_following=0.80,
        domain_knowledge={
            "economic": 0.82, "ecological": 0.70, "social": 0.78,
            "demographic": 0.72, "adversarial": 0.85, "ethics": 0.82,
            "historical": 0.78, "legal": 0.78, "institutional": 0.72,
            "geopolitical": 0.78, "international": 0.78, "uncertainty": 0.84,
            "risk": 0.82, "climate": 0.68, "biodiversity": 0.62,
        },
        speed_tier="slow",
        context_window_tokens=128000,
        notes="Strong reasoning model. Chain-of-thought architecture makes it "
              "well-suited for adversarial and uncertainty channels. "
              "JSON reliability lower than Anthropic — retry budget recommended.",
    ),

    ModelProfile(
        model_id="ollama/gemma3:27b",
        provider="ollama",
        display_name="Gemma 3 27B (Ollama)",
        reasoning_depth=0.76,
        structured_output=0.75,
        context_capacity=0.70,
        instruction_following=0.74,
        domain_knowledge={
            "economic": 0.73, "ecological": 0.70, "social": 0.75,
            "demographic": 0.72, "adversarial": 0.70, "ethics": 0.74,
            "historical": 0.72, "legal": 0.72, "institutional": 0.68,
            "geopolitical": 0.73, "international": 0.72, "uncertainty": 0.71,
            "risk": 0.70, "climate": 0.68, "biodiversity": 0.65,
        },
        speed_tier="standard",
        context_window_tokens=128000,
        notes="Well-rounded local model. Decent across all domains. "
              "Better for channels with moderate requirements.",
    ),

    # ── Mock ─────────────────────────────────────────────────────────────────

    ModelProfile(
        model_id="mock/deterministic-v1",
        provider="mock",
        display_name="Mock Backend (Development)",
        reasoning_depth=0.0,
        structured_output=1.0,   # Always valid JSON
        context_capacity=1.0,
        instruction_following=1.0,
        domain_knowledge={},     # 0.5 default for all domains
        speed_tier="fast",
        context_window_tokens=9999999,
        notes="Deterministic test backend. Never use in production.",
    ),
]


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------

class ModelRegistry:
    """
    Registry of known model capability profiles.

    Maintains the built-in profile set and allows operator registration
    of custom profiles for local or fine-tuned models.

    The registry does not manage backend instances — it manages profiles.
    The ModelSelector uses profiles to decide which backend to use.
    """

    def __init__(self):
        self._profiles: dict[str, ModelProfile] = {}
        for profile in BUILT_IN_PROFILES:
            self._profiles[profile.model_id] = profile

    def register(self, profile: ModelProfile) -> None:
        """Register a custom model profile, overriding any existing entry."""
        self._profiles[profile.model_id] = profile

    def get(self, model_id: str) -> Optional[ModelProfile]:
        """Return the profile for a model_id, or None."""
        return self._profiles.get(model_id)

    def get_or_default(self, model_id: str) -> ModelProfile:
        """Return the profile for a model_id, or a generic medium profile."""
        return self._profiles.get(model_id) or _generic_profile(model_id)

    def all_profiles(self) -> list[ModelProfile]:
        return list(self._profiles.values())

    def profiles_for_provider(self, provider: str) -> list[ModelProfile]:
        return [p for p in self._profiles.values() if p.provider == provider]


def _generic_profile(model_id: str) -> ModelProfile:
    """Fallback profile for unregistered models. Conservative mid-range scores."""
    provider = model_id.split("/")[0] if "/" in model_id else "unknown"
    return ModelProfile(
        model_id=model_id,
        provider=provider,
        display_name=model_id,
        reasoning_depth=0.60,
        structured_output=0.65,
        context_capacity=0.60,
        instruction_following=0.65,
        speed_tier="standard",
        notes="Auto-generated generic profile. Register a custom profile "
              "for accurate channel-to-model matching.",
    )


# ---------------------------------------------------------------------------
# ModelSelector
# ---------------------------------------------------------------------------

class ModelSelector:
    """
    Selects the best available backend for each channel.

    The selector is initialized with a list of candidate backends (in
    fallback priority order). For each channel, it scores all available
    backends against the channel's requirements and returns the best match.

    If no backends are available (all fail is_available()), raises
    BackendError. In practice the MockBackend is always last in the
    fallback list, so this should never happen in normal operation.

    Usage:
        selector = ModelSelector(candidates=[
            AnthropicBackend(model="claude-opus-4-6"),
            AnthropicBackend(model="claude-sonnet-4-6"),
            OllamaBackend(model="llama3.3:70b"),
            MockBackend(),
        ])

        # Get best backend for a channel
        backend = selector.for_channel("ethical_adversarial")

        # Get best backend for a channel with fallback
        backend = selector.for_channel("economic", fallback=MockBackend())
    """

    def __init__(
        self,
        candidates: Optional[list[ModelBackend]] = None,
        registry: Optional[ModelRegistry] = None,
        requirements: Optional[dict[str, ChannelRequirements]] = None,
    ):
        """
        Args:
            candidates:     Ordered list of backends to consider.
                            If None, auto-discovers: Anthropic → Ollama → Mock.
            registry:       Model capability registry. Uses global registry if None.
            requirements:   Channel requirements. Uses CHANNEL_REQUIREMENTS if None.
        """
        self._registry = registry or get_model_registry()
        self._requirements = requirements or CHANNEL_REQUIREMENTS

        if candidates is None:
            self._candidates = _discover_candidates()
        else:
            self._candidates = candidates

        # Cache availability checks — is_available() may be slow (network call)
        self._available: dict[str, bool] = {}

    def for_channel(
        self,
        channel_name: str,
        fallback: Optional[ModelBackend] = None,
    ) -> ModelBackend:
        """
        Return the best available backend for the given channel.

        Args:
            channel_name:   The channel to select for.
            fallback:       Backend to use if no candidates are available.
                            If None and no candidates are available, raises BackendError.

        Returns:
            The highest-scoring available backend for this channel.
        """
        requirements = self._requirements.get(channel_name)
        available = self._available_candidates()

        if not available:
            if fallback is not None:
                return fallback
            raise BackendError(
                f"No backends available for channel '{channel_name}'. "
                "Check ANTHROPIC_API_KEY or Ollama connectivity."
            )

        if requirements is None:
            # Unknown channel — return best all-around available backend
            return self._best_allround(available)

        # Score all available backends and return the highest
        scored = []
        for backend in available:
            profile = self._registry.get_or_default(backend.model_id)
            score = requirements.score(profile)
            scored.append((score, backend))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def all_selections(self) -> dict[str, str]:
        """
        Return a dict of channel_name → model_id for all known channels.
        Useful for logging what the system will use before running.
        """
        result = {}
        for channel_name in self._requirements:
            try:
                backend = self.for_channel(channel_name)
                result[channel_name] = backend.model_id
            except BackendError:
                result[channel_name] = "unavailable"
        return result

    def explain(self, channel_name: str) -> list[tuple[float, str]]:
        """
        Return ranked list of (score, model_id) for all available backends
        for a given channel. Useful for diagnostics and display.
        """
        requirements = self._requirements.get(channel_name)
        if requirements is None:
            return []

        available = self._available_candidates()
        scored = []
        for backend in available:
            profile = self._registry.get_or_default(backend.model_id)
            score = requirements.score(profile)
            scored.append((round(score, 4), backend.model_id))

        scored.sort(reverse=True)
        return scored

    def _available_candidates(self) -> list[ModelBackend]:
        """Return candidates that pass is_available(), using cached results."""
        available = []
        for backend in self._candidates:
            mid = backend.model_id
            if mid not in self._available:
                self._available[mid] = backend.is_available()
            if self._available[mid]:
                available.append(backend)
        return available

    def _best_allround(self, available: list[ModelBackend]) -> ModelBackend:
        """For channels with no registered requirements, return the best overall model."""
        scored = []
        for backend in available:
            profile = self._registry.get_or_default(backend.model_id)
            # Simple average of all dimensions
            score = (
                profile.reasoning_depth
                + profile.structured_output
                + profile.context_capacity
                + profile.instruction_following
            ) / 4
            scored.append((score, backend))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

def _discover_candidates() -> list[ModelBackend]:
    """
    Build the list of candidate backends by probing what's available.

    Order matters: the selector picks the *best scoring* from this list,
    but if two models score identically, earlier in the list wins.
    Within each provider, order from most capable to least capable so
    ties break toward stronger models.
    """
    candidates = []

    # Anthropic: probe key availability first (no network call for key check)
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        candidates += [
            AnthropicBackend(model="claude-opus-4-6"),
            AnthropicBackend(model="claude-sonnet-4-6"),
            AnthropicBackend(model="claude-haiku-4-5-20251001"),
        ]

    # Ollama: probe server availability once, then add all model candidates
    # We probe /api/tags to get what's actually pulled, not just registered
    ollama_models = _probe_ollama_models()
    if ollama_models is not None:
        # ollama_models is a list of pulled model names
        # Map to our registered profiles — only add backends for models
        # we have profiles for (or all, if operators prefer discovery)
        registered_ollama = {
            "llama3.3:70b":      "ollama/llama3.3:70b",
            "qwen2.5:72b":       "ollama/qwen2.5:72b",
            "mistral:7b":        "ollama/mistral:7b",
            "mistral-nemo:12b":  "ollama/mistral-nemo:12b",
            "deepseek-r1:70b":   "ollama/deepseek-r1:70b",
            "gemma3:27b":        "ollama/gemma3:27b",
        }
        for pulled_name in ollama_models:
            # Match prefix (Ollama names can include digest suffixes)
            for known_short, model_id in registered_ollama.items():
                if pulled_name.startswith(known_short.split(":")[0]):
                    candidates.append(OllamaBackend(model=pulled_name))
                    break
            else:
                # Unknown model — add anyway with generic profile
                if pulled_name:
                    candidates.append(OllamaBackend(model=pulled_name))

    # MockBackend: always available as final fallback
    candidates.append(MockBackend())

    return candidates


def _probe_ollama_models(
    base_url: str = "http://localhost:11434",
    timeout: int = 3,
) -> Optional[list[str]]:
    """
    Probe Ollama for available models.
    Returns list of model names if reachable, None if not.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(
            f"{base_url}/api/tags", timeout=timeout
        ) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Global registry singleton
# ---------------------------------------------------------------------------

_REGISTRY: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """Return the global ModelRegistry singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ModelRegistry()
    return _REGISTRY


def get_model_selector(
    candidates: Optional[list[ModelBackend]] = None,
) -> ModelSelector:
    """
    Return a ModelSelector configured with the global registry.

    Args:
        candidates: Override backend candidates. If None, auto-discovers.
    """
    return ModelSelector(
        candidates=candidates,
        registry=get_model_registry(),
        requirements=CHANNEL_REQUIREMENTS,
    )
