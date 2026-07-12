"""
config_manager.py — Configuration management for the Arbitrator CLI.

Reads and writes global_config.yaml in the Arbitrator root directory.
Provides typed access to all configuration values with sensible defaults.

Config file location is resolved relative to this file's parent directory,
which is the Arbitrator package root. This means config is co-located
with the codebase regardless of where the CLI is invoked from.

All writes are atomic (write to .tmp, rename).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

# Config file lives in Arbitrator/ (one level up from cli/)
_CONFIG_PATH = Path(__file__).parent.parent / "global_config.yaml"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    # Paths
    "audit_log_path":       "./arbitrator_audit.jsonl",
    "feedback_ledger_path": "./arbitrator_trust_ledger.json",
    "output_dir":           "./arbitrator_output",

    # Node identity
    "node_id":              "local",

    # Pipeline behaviour
    "continue_after_fail":      False,
    "continue_after_escalate":  True,
    "max_channels":             None,

    # Display
    "color":                True,
    "verbose":              False,
    "pager":                True,

    # Backend
    "backend":              "auto",   # auto | anthropic | ollama | mock
    "ollama_model":         "mistral",
    "ollama_url":           "http://localhost:11434",
    "anthropic_model":      "claude-sonnet-4-20250514",

    # Version
    "arbitrator_version":   "0.1.0",
}


# ---------------------------------------------------------------------------
# Minimal YAML parser/writer (stdlib only — no pyyaml dependency)
# ---------------------------------------------------------------------------

def _parse_yaml(text: str) -> dict:
    """
    Parse a simple flat YAML file into a dict.

    Supports only key: value pairs at the top level.
    Values: strings, booleans, integers, floats, null.
    Does not support nested structures, lists, or multi-line values.
    This is sufficient for global_config.yaml.
    """
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()

        # Strip inline comments
        if " #" in raw_value:
            raw_value = raw_value[:raw_value.index(" #")].strip()

        # Strip quotes
        if (raw_value.startswith('"') and raw_value.endswith('"')) or \
           (raw_value.startswith("'") and raw_value.endswith("'")):
            raw_value = raw_value[1:-1]
            result[key] = raw_value
            continue

        # Type coercion
        if raw_value.lower() == "true":
            result[key] = True
        elif raw_value.lower() == "false":
            result[key] = False
        elif raw_value.lower() in ("null", "none", "~", ""):
            result[key] = None
        else:
            try:
                result[key] = int(raw_value)
            except ValueError:
                try:
                    result[key] = float(raw_value)
                except ValueError:
                    result[key] = raw_value

    return result


def _write_yaml(data: dict) -> str:
    """Serialize a flat dict to simple YAML text."""
    lines = [
        "# Arbitrator global configuration",
        "# Edit this file or use: arbitrator config set <key> <value>",
        "",
    ]
    for key, value in sorted(data.items()):
        if value is None:
            lines.append(f"{key}: null")
        elif isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        elif isinstance(value, str):
            # Quote strings that contain special characters
            if any(c in value for c in [':', '#', "'", '"', '\n']):
                escaped = value.replace('"', '\\"')
                lines.append(f'{key}: "{escaped}"')
            else:
                lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """
    Thread-safe configuration manager for the Arbitrator CLI.

    Merges file config with DEFAULTS. File values take precedence.
    Missing keys fall back to defaults.

    Usage:
        config = ConfigManager()
        path = config.get("audit_log_path")
        config.set("color", False)
        config.save()
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._path = config_path or _CONFIG_PATH
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        """Load from file, merging with defaults."""
        file_data: dict = {}
        if self._path.exists():
            try:
                text = self._path.read_text(encoding="utf-8")
                file_data = _parse_yaml(text)
            except (OSError, ValueError):
                file_data = {}
        self._data = {**DEFAULTS, **file_data}

    def get(self, key: str, default: Any = None) -> Any:
        """Return a config value. Falls back to DEFAULTS then to default."""
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        """Set a config value in memory. Call save() to persist."""
        self._data[key] = value

    def save(self) -> None:
        """Persist current config to global_config.yaml atomically."""
        tmp = self._path.with_suffix(".yaml.tmp")
        try:
            tmp.write_text(_write_yaml(self._data), encoding="utf-8")
            tmp.replace(self._path)
        except OSError as e:
            raise RuntimeError(f"Could not save config to {self._path}: {e}") from e

    def init(self) -> None:
        """Write default config if none exists."""
        if not self._path.exists():
            self._data = dict(DEFAULTS)
            self.save()

    def all(self) -> dict:
        """Return all current config values."""
        return dict(self._data)

    def reset(self) -> None:
        """Reset all values to defaults and save."""
        self._data = dict(DEFAULTS)
        self.save()
