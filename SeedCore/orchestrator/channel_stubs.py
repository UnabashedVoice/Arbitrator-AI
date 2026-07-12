"""
channel_stubs.py — Channel registry and invocation layer.

This module owns the CHANNEL_REGISTRY — the single source of truth for
which channel implementations are active. It is the interface between
the Orchestrator and the channel implementations.

CHANNEL-AWARE MODEL SELECTION:

Each channel is now instantiated with the best available backend for its
specific analytical requirements, rather than a single shared backend.
The ModelSelector scores all available backends against each channel's
declared requirements and returns the best match.

This means:
    - ethical_adversarial and uncertainty_modeling (highest reasoning
      demand) receive the strongest available model.
    - economic and social_demographic (strongest structured output demand)
      receive models most reliable for schema-constrained JSON.
    - historical_precedent and legal_institutional (highest context
      demand) receive models with the largest effective context windows.
    - All channels degrade gracefully: if the best model for a channel
      is unavailable, the next-best available is used.

To inspect what will be selected before running:
    from SeedCore.orchestrator.channel_stubs import explain_model_selections
    explain_model_selections()

Channel architecture:
    Primary four  — economic, ecological, social_demographic, ethical_adversarial
                    Produce grounded analysis and emit cross-domain signals
                    (flag_legal, flag_historical, flag_geopolitical, flag_uncertainty)

    Secondary four — historical_precedent, legal_institutional, geopolitical,
                     uncertainty_modeling
                     Process the flag_* signals from the primary four.
"""

from __future__ import annotations

from typing import Callable

from ..synthesis.channel_output import ChannelOutput, ChannelStatus
from ..channels.model_registry import get_model_selector, ModelSelector
from ..channels.economic import EconomicChannel
from ..channels.ecological import EcologicalChannel
from ..channels.social_demographic import SocialDemographicChannel
from ..channels.ethical_adversarial import EthicalAdversarialChannel
from ..channels.historical_precedent import HistoricalPrecedentChannel
from ..channels.legal_institutional import LegalInstitutionalChannel
from ..channels.geopolitical import GeopoliticalChannel
from ..channels.uncertainty_modeling import UncertaintyModelingChannel


# ---------------------------------------------------------------------------
# Channel callable type
# ---------------------------------------------------------------------------

ChannelCallable = Callable[[str, dict], ChannelOutput]


# ---------------------------------------------------------------------------
# Stub factory (preserved for extensions and test overrides)
# ---------------------------------------------------------------------------

def _make_stub(channel_name: str) -> ChannelCallable:
    """
    Create a stub callable for a channel that has not been implemented.
    Used for any future channels beyond the current eight, and for
    test overrides.
    """
    def stub(raw_input: str, context_dict: dict) -> ChannelOutput:
        return ChannelOutput(
            channel_name=channel_name,
            status=ChannelStatus.UNAVAILABLE,
            error_message=(
                f"Channel '{channel_name}' is not yet implemented. "
                f"This is a planned analysis domain. "
                f"The consequence map is incomplete for this domain."
            ),
            model_id="stub-v0.1",
        )
    stub.__name__ = f"stub_{channel_name}"
    return stub


# ---------------------------------------------------------------------------
# Channel registry with per-channel model selection
# ---------------------------------------------------------------------------

def _build_registry(
    selector: ModelSelector | None = None,
) -> dict[str, ChannelCallable]:
    """
    Instantiate all eight channels, each with the best available backend
    for its analytical requirements.

    Args:
        selector:   ModelSelector to use. If None, creates one via
                    get_model_selector() which auto-discovers available
                    backends (Anthropic → Ollama → Mock).

    Returns:
        Dict of channel_name → ChannelCallable.
    """
    if selector is None:
        selector = get_model_selector()

    return {
        # Primary four — grounded analysis + cross-domain signals
        "economic":             EconomicChannel(
            backend=selector.for_channel("economic")
        ),
        "ecological":           EcologicalChannel(
            backend=selector.for_channel("ecological")
        ),
        "social_demographic":   SocialDemographicChannel(
            backend=selector.for_channel("social_demographic")
        ),
        "ethical_adversarial":  EthicalAdversarialChannel(
            backend=selector.for_channel("ethical_adversarial")
        ),
        # Secondary four — process flag_* signals
        "historical_precedent": HistoricalPrecedentChannel(
            backend=selector.for_channel("historical_precedent")
        ),
        "legal_institutional":  LegalInstitutionalChannel(
            backend=selector.for_channel("legal_institutional")
        ),
        "geopolitical":         GeopoliticalChannel(
            backend=selector.for_channel("geopolitical")
        ),
        "uncertainty_modeling": UncertaintyModelingChannel(
            backend=selector.for_channel("uncertainty_modeling")
        ),
    }


CHANNEL_REGISTRY: dict[str, ChannelCallable] = _build_registry()


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------

def invoke_channel(
    channel_name: str,
    raw_input: str,
    context_dict: dict,
) -> ChannelOutput:
    """
    Invoke a primary channel by name. Always returns a ChannelOutput, never raises.

    Used for the four primary channels (economic, ecological, social_demographic)
    which run without access to other channels' outputs.

    Args:
        channel_name:   The channel to invoke (e.g., "economic").
        raw_input:      The original proposal text.
        context_dict:   The ParsedContext serialized to dict.

    Returns:
        ChannelOutput with status SUCCESS, FAILED, or UNAVAILABLE.
    """
    if channel_name not in CHANNEL_REGISTRY:
        return ChannelOutput(
            channel_name=channel_name,
            status=ChannelStatus.FAILED,
            error_message=f"No channel registered for '{channel_name}'.",
            model_id="unknown",
        )

    try:
        return CHANNEL_REGISTRY[channel_name](raw_input, context_dict)
    except Exception as e:
        return ChannelOutput(
            channel_name=channel_name,
            status=ChannelStatus.FAILED,
            error_message=(
                f"Channel '{channel_name}' raised an unhandled exception: "
                f"{type(e).__name__}: {e}"
            ),
            model_id="unknown",
        )


def invoke_channel_with_primary_outputs(
    channel_name: str,
    raw_input: str,
    context_dict: dict,
    primary_outputs: list[ChannelOutput],
) -> ChannelOutput:
    """
    Invoke a secondary channel with primary channel outputs injected.

    Used for secondary channels (ethical_adversarial, historical_precedent,
    legal_institutional, geopolitical, uncertainty_modeling) which run after
    the primary channels and process their flag_* signals.

    The primary_outputs are serialized into the user prompt so the secondary
    channel can reference specific finding_ids and respond to flagged findings.

    Args:
        channel_name:       The channel to invoke.
        raw_input:          The original proposal text.
        context_dict:       The ParsedContext serialized to dict.
        primary_outputs:    ChannelOutputs from the three primary channels.

    Returns:
        ChannelOutput with status SUCCESS, FAILED, or UNAVAILABLE.
    """
    if channel_name not in CHANNEL_REGISTRY:
        return ChannelOutput(
            channel_name=channel_name,
            status=ChannelStatus.FAILED,
            error_message=f"No channel registered for '{channel_name}'.",
            model_id="unknown",
        )

    channel = CHANNEL_REGISTRY[channel_name]

    # Stubs don't have analyze_with_primary_outputs — fall back to regular invoke
    if is_stub(channel_name):
        return channel(raw_input, context_dict)

    try:
        return channel.analyze_with_primary_outputs(
            raw_input, context_dict, primary_outputs
        )
    except Exception as e:
        return ChannelOutput(
            channel_name=channel_name,
            status=ChannelStatus.FAILED,
            error_message=(
                f"Channel '{channel_name}' raised an unhandled exception: "
                f"{type(e).__name__}: {e}"
            ),
            model_id="unknown",
        )


# ---------------------------------------------------------------------------
# Registry inspection
# ---------------------------------------------------------------------------

def is_stub(channel_name: str) -> bool:
    """Return True if the channel is a stub (not a real implementation)."""
    fn = CHANNEL_REGISTRY.get(channel_name)
    return fn is not None and getattr(fn, '__name__', '').startswith('stub_')


def implemented_channels() -> list[str]:
    """Return channel names that have real (non-stub) implementations."""
    return [name for name in CHANNEL_REGISTRY if not is_stub(name)]


def stub_channels() -> list[str]:
    """Return channel names that are currently stubs."""
    return [name for name in CHANNEL_REGISTRY if is_stub(name)]


def get_channel(channel_name: str):
    """Return the channel object for a given name, or None if not registered."""
    return CHANNEL_REGISTRY.get(channel_name)


def explain_model_selections(
    selector: ModelSelector | None = None,
) -> dict[str, list[tuple[float, str]]]:
    """
    Return per-channel model rankings for all available backends.

    Useful for operators to understand what the system will use and why.

    Returns:
        Dict of channel_name → [(score, model_id), ...] sorted best-first.

    Example output:
        {
          "ethical_adversarial": [
            (0.9245, "anthropic/claude-opus-4-6"),
            (0.8810, "anthropic/claude-sonnet-4-6"),
            (0.7312, "ollama/deepseek-r1:70b"),
            (0.0000, "mock/deterministic-v1"),
          ],
          ...
        }
    """
    if selector is None:
        selector = get_model_selector()
    return {
        channel: selector.explain(channel)
        for channel in [
            "economic", "ecological", "social_demographic",
            "ethical_adversarial", "historical_precedent",
            "legal_institutional", "geopolitical", "uncertainty_modeling",
        ]
    }
