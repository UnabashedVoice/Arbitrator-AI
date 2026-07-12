"""
commands/config.py — The 'arbitrator config' command family.

Subcommands:
    arbitrator config show          — Display current configuration
    arbitrator config set <k> <v>   — Set a configuration value
    arbitrator config init          — Write default config if none exists
    arbitrator config reset         — Reset all values to defaults

Config is stored in global_config.yaml in the Arbitrator package root.
"""

from __future__ import annotations

from typing import Optional

from ..config_manager import ConfigManager, DEFAULTS
from .. import display


def config_show(config: ConfigManager) -> int:
    """Display all current configuration values."""
    print(display.section("CONFIGURATION"))
    print(display.dim(f"  Config file: {config._path}"))
    print()

    all_vals = config.all()
    max_key = max(len(k) for k in all_vals) + 2

    for key, value in sorted(all_vals.items()):
        default = DEFAULTS.get(key)
        is_default = (value == default)
        val_str = display.dim(str(value)) if is_default else display.bold(str(value))
        default_marker = "" if is_default else display.dim(f"  (default: {default})")
        print(f"  {key.ljust(max_key)} {val_str}{default_marker}")

    print()
    print(display.dim("  Values shown in bold differ from defaults."))
    print(display.dim("  Use 'arbitrator config set <key> <value>' to change a value."))
    return 0


def config_set(config: ConfigManager, key: str, value: str) -> int:
    """Set a configuration value."""
    if key not in DEFAULTS:
        display.warn(f"Unknown key '{key}'. Adding anyway.")

    # Type coerce based on current/default type
    default = DEFAULTS.get(key)
    coerced = _coerce(value, type(default) if default is not None else str)

    config.set(key, coerced)
    try:
        config.save()
        display.success(f"Set {key} = {coerced!r}")
        return 0
    except RuntimeError as e:
        display.error(str(e))
        return 2


def config_init(config: ConfigManager) -> int:
    """Write default config file if none exists."""
    if config._path.exists():
        display.info(f"Config already exists: {config._path}")
        display.info("Use 'arbitrator config reset' to restore defaults.")
        return 0
    try:
        config.init()
        display.success(f"Config written to {config._path}")
        return 0
    except RuntimeError as e:
        display.error(str(e))
        return 2


def config_reset(config: ConfigManager) -> int:
    """Reset all configuration values to defaults."""
    try:
        config.reset()
        display.success(f"Config reset to defaults at {config._path}")
        return 0
    except RuntimeError as e:
        display.error(str(e))
        return 2


def _coerce(value: str, target_type: type):
    """Coerce a string value to the target type."""
    if target_type is bool:
        return value.lower() in ("true", "1", "yes", "on")
    if target_type is int:
        try:
            return int(value)
        except ValueError:
            return value
    if target_type is float:
        try:
            return float(value)
        except ValueError:
            return value
    if value.lower() in ("null", "none", ""):
        return None
    return value
