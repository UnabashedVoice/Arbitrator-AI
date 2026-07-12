"""
commands/models.py — The 'arbitrator models' command family.

Subcommands:
    arbitrator models list      — List all registered model profiles
    arbitrator models available — Show which backends are currently reachable
    arbitrator models explain   — Show per-channel model rankings
    arbitrator models register  — Register a custom model profile from JSON

This command surface makes model selection transparent and auditable.
Before running an analysis, operators can inspect exactly which model
will be used for each channel and why.
"""

from __future__ import annotations

import json
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import Optional
from Arbitrator.cli.config_manager import ConfigManager
from Arbitrator.cli import display


def models_list(config: ConfigManager, json_output: bool = False) -> int:
    """List all registered model profiles."""
    from Arbitrator.SeedCore.channels.model_registry import get_model_registry

    registry = get_model_registry()
    profiles = sorted(registry.all_profiles(), key=lambda p: (p.provider, p.model_id))

    if json_output:
        data = []
        for p in profiles:
            data.append({
                "model_id":             p.model_id,
                "provider":             p.provider,
                "display_name":         p.display_name,
                "reasoning_depth":      p.reasoning_depth,
                "structured_output":    p.structured_output,
                "context_capacity":     p.context_capacity,
                "instruction_following": p.instruction_following,
                "speed_tier":           p.speed_tier,
                "context_window_tokens": p.context_window_tokens,
            })
        print(json.dumps(data, indent=2))
        return 0

    print(display.section("REGISTERED MODEL PROFILES"))
    print(display.dim(f"  {len(profiles)} profiles registered\n"))

    current_provider = None
    for p in profiles:
        if p.provider != current_provider:
            current_provider = p.provider
            print(f"\n  {display.bold(p.provider.upper())}")

        print(
            f"    {display.cyan(p.model_id)}\n"
            f"      {display.dim(p.display_name)}"
            f"  {display.dim('[' + p.speed_tier + ']')}"
            f"  {display.dim(str(p.context_window_tokens // 1000) + 'K ctx')}"
        )
        print(
            f"      reasoning   {_dim_bar(p.reasoning_depth)}"
            f"  structured {_dim_bar(p.structured_output)}"
            f"  context    {_dim_bar(p.context_capacity)}"
            f"  instr      {_dim_bar(p.instruction_following)}"
        )
        if p.notes:
            print(f"      {display.dim(p.notes[:90])}")

    print()
    return 0


def models_available(config: ConfigManager, json_output: bool = False) -> int:
    """Show which backends are currently reachable."""
    from Arbitrator.SeedCore.channels.model_registry import _discover_candidates

    display.status("Probing backend availability...")
    candidates = _discover_candidates()

    if json_output:
        data = []
        for b in candidates:
            available = b.is_available()
            data.append({
                "model_id":  b.model_id,
                "available": available,
            })
        print(json.dumps(data, indent=2))
        return 0

    print(display.section("BACKEND AVAILABILITY"))
    print()

    any_real = False
    for b in candidates:
        available = b.is_available()
        if available and b.model_id != "mock/deterministic-v1":
            any_real = True
        status_str = display.green("✓  available") if available else display.red("✗  unavailable")
        print(f"  {status_str}  {b.model_id}")

    print()
    if not any_real:
        display.warn(
            "No real backends available. All channels will use the mock backend."
        )
        display.info(
            "Set ANTHROPIC_API_KEY or start Ollama to enable real model inference."
        )
    return 0


def models_explain(
    config: ConfigManager,
    channel: Optional[str] = None,
    json_output: bool = False,
) -> int:
    """Show per-channel model rankings."""
    from Arbitrator.SeedCore.channels.model_registry import get_model_selector
    from Arbitrator.SeedCore.orchestrator.channel_stubs import explain_model_selections

    display.status("Computing model rankings...")
    selector = get_model_selector()

    CHANNELS = [
        "economic", "ecological", "social_demographic",
        "ethical_adversarial", "historical_precedent",
        "legal_institutional", "geopolitical", "uncertainty_modeling",
    ]

    target_channels = [channel] if channel else CHANNELS

    if json_output:
        result = {}
        for ch in target_channels:
            result[ch] = [
                {"score": s, "model_id": mid}
                for s, mid in selector.explain(ch)
            ]
        print(json.dumps(result, indent=2))
        return 0

    print(display.section("CHANNEL MODEL RANKINGS"))
    print(display.dim("  Shows available backends ranked by fit for each channel.\n"))

    from Arbitrator.SeedCore.channels.model_registry import CHANNEL_REQUIREMENTS

    for ch in target_channels:
        req = CHANNEL_REQUIREMENTS.get(ch)
        ranked = selector.explain(ch)

        print(f"\n  {display.bold(ch.replace('_', ' ').upper())}")
        if req and req.notes:
            print(f"  {display.dim(req.notes[:80])}")

        if not ranked:
            print(f"  {display.dim('  No available backends.')}")
            continue

        for i, (score, mid) in enumerate(ranked):
            marker = display.green("→") if i == 0 else display.dim(" ")
            bar = _score_bar_inline(score)
            model_str = display.bold(mid) if i == 0 else display.dim(mid)
            print(f"    {marker} {bar}  {model_str}")

    print()
    print(display.dim(
        "  '→' marks the backend that will be used for each channel.\n"
        "  Scores are weighted composites of reasoning, JSON reliability,\n"
        "  context capacity, instruction following, and domain knowledge."
    ))
    print()
    return 0


def models_register(
    config: ConfigManager,
    profile_file: str,
) -> int:
    """Register a custom model profile from a JSON file."""
    from pathlib import Path
    from Arbitrator.SeedCore.channels.model_registry import get_model_registry, ModelProfile

    try:
        text = Path(profile_file).read_text(encoding="utf-8")
        data = json.loads(text)
    except FileNotFoundError:
        display.error(f"File not found: {profile_file}")
        return 2
    except json.JSONDecodeError as e:
        display.error(f"Invalid JSON in {profile_file}: {e}")
        return 2

    # Handle single profile or list
    if isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        display.error("Profile file must be a JSON object or array of objects.")
        return 2

    registry = get_model_registry()
    registered = []
    errors = []

    for item in data:
        try:
            profile = ModelProfile(
                model_id=item["model_id"],
                provider=item.get("provider", "custom"),
                display_name=item.get("display_name", item["model_id"]),
                reasoning_depth=float(item.get("reasoning_depth", 0.6)),
                structured_output=float(item.get("structured_output", 0.65)),
                context_capacity=float(item.get("context_capacity", 0.6)),
                instruction_following=float(item.get("instruction_following", 0.65)),
                domain_knowledge=item.get("domain_knowledge", {}),
                speed_tier=item.get("speed_tier", "standard"),
                context_window_tokens=int(item.get("context_window_tokens", 8192)),
                notes=item.get("notes", ""),
            )
            registry.register(profile)
            registered.append(profile.model_id)
        except (KeyError, ValueError, TypeError) as e:
            errors.append(f"{item.get('model_id', '?')}: {e}")

    for mid in registered:
        display.success(f"Registered: {mid}")
    for err in errors:
        display.error(f"Failed: {err}")

    if registered:
        display.info(
            "Custom profiles are registered in memory for this session. "
            "Restart will reload only built-in profiles."
        )

    return 0 if not errors else 1


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _dim_bar(value: float, width: int = 8) -> str:
    filled = round(value * width)
    bar = "█" * filled + "░" * (width - filled)
    return display.dim(bar + f" {value:.2f}")


def _score_bar_inline(value: float, width: int = 12) -> str:
    filled = round(value * width)
    bar = "█" * filled + "░" * (width - filled)
    color = display.green if value >= 0.80 else display.yellow if value >= 0.60 else display.dim
    return color(bar) + display.dim(f" {value:.4f}")
