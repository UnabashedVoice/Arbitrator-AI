"""
backend.py — Pluggable model backend interface for Arbitrator channels.

Every channel sends a prompt to a model and receives a response.
The backend abstraction decouples channels from the specific model they
use, enabling:
    - Local model deployment (Ollama, llama.cpp, etc.)
    - Anthropic API (cloud or on-prem)
    - OpenAI-compatible endpoints
    - Testing with deterministic mock backends

All backends implement the same interface: given a system prompt and a
user prompt, return a string response.

The channel layer never calls an API directly — it calls backend.complete().
Swapping the backend is a one-line config change.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class ModelBackend(ABC):
    """
    Abstract base class for all model backends.

    Subclasses must implement complete() and may optionally implement
    is_available() for health checking.
    """

    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.2,
    ) -> str:
        """
        Send a prompt to the model and return the response text.

        Args:
            system_prompt:  The system/instruction prompt.
            user_prompt:    The user/content prompt.
            max_tokens:     Maximum tokens to generate.
            temperature:    Sampling temperature. Lower = more deterministic.
                            Channels use low temperature for consistency.

        Returns:
            The model's response as a string.

        Raises:
            BackendError:   If the model call fails for any reason.
        """

    def is_available(self) -> bool:
        """Return True if this backend is currently reachable. Default True."""
        return True

    @property
    def model_id(self) -> str:
        """A string identifying this backend and model for audit logging."""
        return "unknown"


# ---------------------------------------------------------------------------
# Anthropic API backend
# ---------------------------------------------------------------------------

class AnthropicBackend(ModelBackend):
    """
    Backend that calls the Anthropic Messages API.

    Requires the ANTHROPIC_API_KEY environment variable, or an explicit
    api_key argument.

    Usage:
        backend = AnthropicBackend()
        response = backend.complete("You are an analyst.", "Analyze this policy.")
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        timeout: int = 60,
    ):
        self._model = model
        self._timeout = timeout
        self._api_key = api_key  # If None, uses ANTHROPIC_API_KEY env var

    @property
    def model_id(self) -> str:
        return f"anthropic/{self._model}"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.2,
    ) -> str:
        import urllib.request
        import os

        api_key = self._api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise BackendError("ANTHROPIC_API_KEY not set and no api_key provided.")

        payload = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["content"][0]["text"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise BackendError(f"Anthropic API error {e.code}: {body[:500]}") from e
        except Exception as e:
            raise BackendError(f"Anthropic backend failed: {type(e).__name__}: {e}") from e

    def is_available(self) -> bool:
        import os
        return bool(self._api_key or os.environ.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------------
# Ollama backend (local models)
# ---------------------------------------------------------------------------

class OllamaBackend(ModelBackend):
    """
    Backend that calls a local Ollama server.

    Ollama runs models locally (Mistral, LLaMA, Qwen, etc.) with an
    OpenAI-compatible API. Default URL: http://localhost:11434

    Usage:
        backend = OllamaBackend(model="mistral")
        response = backend.complete("You are an analyst.", "Analyze this policy.")
    """

    def __init__(
        self,
        model: str = "mistral",
        base_url: str = "http://localhost:11434",
        timeout: int = 120,
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def model_id(self) -> str:
        return f"ollama/{self._model}"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.2,
    ) -> str:
        import urllib.request

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["message"]["content"]
        except Exception as e:
            raise BackendError(f"Ollama backend failed: {type(e).__name__}: {e}") from e

    def is_available(self) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(
                f"{self._base_url}/api/tags", timeout=3
            ) as resp:
                return resp.status == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Mock backend (deterministic, for testing and development)
# ---------------------------------------------------------------------------

@dataclass
class MockResponse:
    """A canned response for a specific channel in the mock backend."""
    channel_name: str
    response_json: dict

    def to_json_string(self) -> str:
        return json.dumps(self.response_json)


class MockBackend(ModelBackend):
    """
    Deterministic mock backend for testing and offline development.

    Returns pre-configured JSON responses keyed by channel name.
    The channel name is extracted from the system prompt.

    If no mock response is configured for a channel, returns a minimal
    valid response with low-confidence findings.

    Usage:
        backend = MockBackend()
        # Optionally add custom responses:
        backend.add_response("economic", {...})
    """

    def __init__(self):
        self._responses: dict[str, dict] = {}
        self._call_log: list[dict] = []

    @property
    def model_id(self) -> str:
        return "mock/deterministic-v1"

    def add_response(self, channel_name: str, response_dict: dict) -> None:
        """Register a mock response for a specific channel."""
        self._responses[channel_name] = response_dict

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.2,
    ) -> str:
        # Extract channel name from system prompt (convention: first line contains it)
        channel_name = "unknown"
        for line in system_prompt.splitlines():
            if "CHANNEL:" in line:
                channel_name = line.split("CHANNEL:")[-1].strip().lower()
                break

        self._call_log.append({
            "channel": channel_name,
            "user_prompt_length": len(user_prompt),
        })

        if channel_name in self._responses:
            return json.dumps(self._responses[channel_name])

        # Default: minimal valid response
        return json.dumps(_default_mock_response(channel_name))

    @property
    def call_log(self) -> list[dict]:
        """Returns the log of all calls made to this backend."""
        return list(self._call_log)

    def reset(self) -> None:
        """Clear call log and registered responses."""
        self._responses.clear()
        self._call_log.clear()


def _default_mock_response(channel_name: str) -> dict:
    """Produce a minimal valid mock response for a channel."""
    return {
        "domain_summary": (
            f"[Mock {channel_name} analysis] This is a placeholder response from the "
            f"mock backend. In production, a real model would analyze the proposal and "
            f"return grounded findings."
        ),
        "overall_harm_score": 0.3,
        "overall_benefit_score": 0.5,
        "confidence": 0.4,
        "findings": [
            {
                "summary": f"Mock finding from {channel_name} channel.",
                "detail": "This is a mock finding produced by the test backend.",
                "direction": "neutral",
                "timeframe": "medium_term",
                "certainty": "low",
                "magnitude": 0.3,
                "affected_groups": [],
                "reversible": None,
                "citations": [],
                "tags": [channel_name],
            }
        ],
        "uncertainty_notes": [
            {
                "description": "Mock backend — no real analysis performed.",
                "impact_on_analysis": "All findings should be treated as placeholders.",
                "magnitude": 0.9,
            }
        ],
        "adversarial_challenges": [],
    }


# ---------------------------------------------------------------------------
# Backend registry and selection
# ---------------------------------------------------------------------------

def get_default_backend() -> ModelBackend:
    """
    Return the best available backend, in priority order:
    1. AnthropicBackend (if ANTHROPIC_API_KEY is set)
    2. OllamaBackend (if localhost:11434 is reachable)
    3. MockBackend (always available, for development)
    """
    anthropic = AnthropicBackend()
    if anthropic.is_available():
        return anthropic

    ollama = OllamaBackend()
    if ollama.is_available():
        return ollama

    return MockBackend()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class BackendError(Exception):
    """Raised when a model backend fails to produce a response."""
    pass
