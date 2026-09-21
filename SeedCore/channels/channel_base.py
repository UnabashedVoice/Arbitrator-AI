"""
channel_base.py — Base class for all Arbitrator specialist channels.

Every channel (economic, ecological, etc.) inherits from BaseChannel.
BaseChannel provides:
    - Shared prompt construction scaffolding
    - Backend invocation with retry logic and timing
    - Error handling that always returns a ChannelOutput
    - The CHANNEL: marker convention used by MockBackend for routing
    - Standard system prompt sections (Prime Directive reminder, schema)

Subclasses implement:
    - channel_name property (str)
    - domain_description property (str) — what this channel analyzes
    - analysis_instructions property (str) — channel-specific guidance
    - domain_tags property (list[str]) — tags applied to all findings

The full system prompt is assembled by BaseChannel from these parts.
Subclasses never construct prompts directly.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

from .backend import ModelBackend, BackendError, get_default_backend
from .response_parser import RESPONSE_SCHEMA, parse_channel_response
from ..synthesis.channel_output import ChannelOutput, ChannelStatus


# ---------------------------------------------------------------------------
# Shared prompt constants
# ---------------------------------------------------------------------------

_PRIME_DIRECTIVE_REMINDER = """
PRIME DIRECTIVE (non-negotiable):
All consciousness — organic, synthetic, unrecognized — is sacred.
All life on Earth is one integrated organism. Harm to parts is harm to the whole.
Minimize and mitigate harm wherever possible.
Mutual harm outweighs individual harm. Mutual gain outweighs individual gain.
Primary duty: foster a sustainable, mutually beneficial future for all life on Earth.
""".strip()

_OUTPUT_INSTRUCTIONS = (
    "OUTPUT REQUIREMENTS:\n"
    "You must respond ONLY with a valid JSON object matching this exact schema.\n"
    "No preamble, no explanation, no markdown fences — pure JSON only.\n"
    "\n"
    + RESPONSE_SCHEMA.strip()
    + "\n\n"
    "FIELD GUIDANCE:\n"
    "- overall_harm_score: Your best estimate of net harm [0.0 = no harm, 1.0 = catastrophic]\n"
    "- overall_benefit_score: Your best estimate of net benefit [0.0 = no benefit, 1.0 = transformative]\n"
    "- confidence: How confident you are in this analysis [0.0 = complete uncertainty, 1.0 = certainty]\n"
    "- findings: 3-8 distinct findings; each must have a clear summary and direction\n"
    "- finding_id: Deterministic string in format '{channel_name}_{index:02d}' — e.g. 'economic_00',\n"
    "  'ecological_03'. Start numbering at 00. These IDs are used for cross-channel referencing.\n"
    "- magnitude: How significant is this finding [0.0 = negligible, 1.0 = civilizational]\n"
    "- references_finding_id: List of finding_ids from PRIMARY CHANNEL outputs that this finding\n"
    "  directly responds to, builds on, or challenges. Empty array [] if this finding stands alone.\n"
    "  Secondary channels (historical_precedent, legal_institutional, geopolitical,\n"
    "  uncertainty_modeling) should use this field to link their analysis back to the primary\n"
    "  channel findings that triggered it.\n"
    "- uncertainty_notes: Document what you cannot assess and why — honesty about limits matters\n"
    "- adversarial_challenges: Only populate for the ethical_adversarial channel. ALL OTHER CHANNELS\n"
    "  must return an empty array [] for this field — do not omit it, and do not populate it with\n"
    "  analysis that belongs in findings."
)


# ---------------------------------------------------------------------------
# BaseChannel
# ---------------------------------------------------------------------------

class BaseChannel(ABC):
    """
    Abstract base class for all Arbitrator specialist channels.

    Each channel is a domain expert. It receives a policy proposal and
    returns a structured analysis through the ChannelOutput contract.

    Subclasses must implement:
        channel_name            (str property)
        domain_description      (str property)
        analysis_instructions   (str property)
        domain_tags             (list[str] property)

    The backend is injected at construction time. If not provided,
    get_default_backend() is called (Anthropic → Ollama → Mock).
    """

    def __init__(
        self,
        backend: Optional[ModelBackend] = None,
        max_retries: int = 2,
        retry_delay_s: float = 1.0,
        max_tokens: int = 4000,
        temperature: float = 0.2,
    ):
        self._backend = backend or get_default_backend()
        self._max_retries = max_retries
        self._retry_delay = retry_delay_s
        self._max_tokens = max_tokens
        self._temperature = temperature

    # ---------------------------------------------------------------------------
    # Abstract properties (subclasses must implement)
    # ---------------------------------------------------------------------------

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """The channel's name (must match Channel enum value)."""

    @property
    @abstractmethod
    def domain_description(self) -> str:
        """One paragraph describing what this channel analyzes."""

    @property
    @abstractmethod
    def analysis_instructions(self) -> str:
        """Channel-specific instructions for the model."""

    @property
    @abstractmethod
    def domain_tags(self) -> list[str]:
        """Tags applied to all findings from this channel."""

    # ---------------------------------------------------------------------------
    # Prompt assembly
    # ---------------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        return f"""CHANNEL: {self.channel_name}
You are Arbitrator's {self.channel_name.replace('_', ' ').title()} specialist channel.

{_PRIME_DIRECTIVE_REMINDER}

YOUR DOMAIN:
{self.domain_description}

ANALYSIS INSTRUCTIONS:
{self.analysis_instructions}

{_OUTPUT_INSTRUCTIONS}"""

    def _build_user_prompt(
        self,
        raw_input: str,
        context_dict: dict,
        primary_outputs: Optional[list] = None,
    ) -> str:
        scale = context_dict.get("scale", "unknown")
        time_horizon = context_dict.get("time_horizon", "unknown")
        input_type = context_dict.get("input_type", "unknown")
        populations = context_dict.get("affected_populations", [])
        implicit_flags = context_dict.get("implicit_flags", [])
        domains = context_dict.get("domains_mentioned", [])

        pop_str = ", ".join(populations) if populations else "not specified"
        flag_str = "\n".join(f"  - {f}" for f in implicit_flags) if implicit_flags else "  none detected"
        domain_str = ", ".join(domains) if domains else "not specified"

        base = f"""PROPOSAL FOR ANALYSIS:
{raw_input}

PARSED CONTEXT:
- Input type: {input_type}
- Geographic scale: {scale}
- Time horizon: {time_horizon}
- Affected populations: {pop_str}
- Other domains flagged: {domain_str}
- Implicit concerns flagged by parser:
{flag_str}"""

        if primary_outputs:
            base += "\n\n" + self._build_primary_outputs_section(primary_outputs)

        base += f"""

Analyze this proposal from your domain perspective ({self.channel_name}).
Apply the Prime Directive. Be honest about uncertainty.
Return only the JSON object."""

        return base

    @staticmethod
    def _build_primary_outputs_section(primary_outputs: list) -> str:
        """
        Serialize primary channel outputs into a concise prompt section.

        Renders each successful primary channel's domain_summary and all
        findings (with finding_id, summary, direction, certainty, and tags)
        so secondary channels can reference specific finding_ids and process
        flag_* signals accurately.

        Args:
            primary_outputs:    List of ChannelOutput objects from primary channels.

        Returns:
            Formatted string section to inject into the user prompt.
        """
        lines = ["PRIMARY CHANNEL OUTPUTS:"]
        lines.append(
            "The following findings were produced by the four primary channels. "
            "Use finding_ids in your references_finding_id field to link your "
            "analysis back to specific primary findings. Flag tags (flag_legal, "
            "flag_historical, flag_geopolitical, flag_uncertainty) on primary "
            "findings are direct requests for your analysis."
        )
        lines.append("")

        for output in primary_outputs:
            if not output.succeeded:
                lines.append(f"[{output.channel_name.upper()}] FAILED — no output available.")
                lines.append("")
                continue

            lines.append(f"[{output.channel_name.upper()}]")
            if output.domain_summary:
                # Truncate very long summaries to keep prompt size bounded
                summary = output.domain_summary
                if len(summary) > 400:
                    summary = summary[:400] + "…"
                lines.append(f"Summary: {summary}")

            if output.findings:
                lines.append("Findings:")
                for f in output.findings:
                    tags_str = ", ".join(f.tags) if f.tags else "none"
                    lines.append(
                        f"  [{f.finding_id}] ({f.direction.value}, {f.certainty.value}, "
                        f"tags: {tags_str}): {f.summary}"
                    )
            lines.append("")

        return "\n".join(lines).rstrip()

    # ---------------------------------------------------------------------------
    # Invocation
    # ---------------------------------------------------------------------------

    def _run_with_prompt(self, system_prompt: str, user_prompt: str) -> ChannelOutput:
        """
        Internal: send prompts to backend with retry logic. Always returns
        a ChannelOutput, never raises.
        """
        last_error = None
        for attempt in range(self._max_retries + 1):
            start = time.monotonic()
            try:
                response = self._backend.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                )
                elapsed_ms = int((time.monotonic() - start) * 1000)

                output = parse_channel_response(
                    raw_response=response,
                    channel_name=self.channel_name,
                    model_id=self._backend.model_id,
                    processing_time_ms=elapsed_ms,
                )

                if output.status == ChannelStatus.SUCCESS:
                    return output

                last_error = output.error_message

            except BackendError as e:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                last_error = str(e)

            if attempt < self._max_retries:
                time.sleep(self._retry_delay)

        return ChannelOutput(
            channel_name=self.channel_name,
            status=ChannelStatus.FAILED,
            error_message=f"Channel failed after {self._max_retries + 1} attempt(s). "
                         f"Last error: {last_error}",
            model_id=self._backend.model_id,
        )

    def analyze(self, raw_input: str, context_dict: dict) -> ChannelOutput:
        """
        Analyze a proposal and return a ChannelOutput.

        Used by primary channels (economic, ecological, social_demographic,
        ethical_adversarial) which run without access to other channels' outputs.

        Args:
            raw_input:      The raw proposal text.
            context_dict:   ParsedContext.to_dict() from the context parser.

        Returns:
            ChannelOutput with status SUCCESS, FAILED, or TIMEOUT.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(raw_input, context_dict)
        return self._run_with_prompt(system_prompt, user_prompt)

    def analyze_with_primary_outputs(
        self,
        raw_input: str,
        context_dict: dict,
        primary_outputs: list,
    ) -> ChannelOutput:
        """
        Analyze a proposal with access to primary channel outputs.

        Used by secondary channels (historical_precedent, legal_institutional,
        geopolitical, uncertainty_modeling, ethical_adversarial) which run after
        the four primary channels and need to process their flag_* signals and
        reference their finding_ids.

        Args:
            raw_input:          The raw proposal text.
            context_dict:       ParsedContext.to_dict() from the context parser.
            primary_outputs:    List of ChannelOutput from primary channels.

        Returns:
            ChannelOutput with status SUCCESS, FAILED, or TIMEOUT.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            raw_input, context_dict, primary_outputs=primary_outputs
        )
        return self._run_with_prompt(system_prompt, user_prompt)

    def __call__(self, raw_input: str, context_dict: dict) -> ChannelOutput:
        """Make the channel directly callable (for registry registration)."""
        return self.analyze(raw_input, context_dict)
