"""
parser.py — The Arbitrator Context Parser.

The Context Parser is the entry point for all analysis requests. It takes
raw natural language input and produces:

    1. A ParsedContext — structured metadata about what the input is,
       who it affects, at what scale, over what time horizon, and what
       flags the parser detected.

    2. A RoutingManifest — a record of which model channels are relevant
       to this input, with the relevance score and matched signals for
       each channel. This manifest drives channel invocation and is
       published in the public audit log.

Architecture:
    - Pure Python, no external NLP dependencies
    - Fully deterministic: the same input always produces the same output
    - Fully auditable: every routing decision includes the signals that
      drove it and a human-readable rationale
    - Stateless: no memory between calls

Usage:
    from context_parser.parser import ContextParser

    parser = ContextParser()
    manifest = parser.parse("What would happen if we banned all fossil fuels by 2030?")

    for route in manifest.routes:
        print(route.channel.value, route.invoked, route.relevance_score)
"""

from __future__ import annotations

import json
import re

from .extractors import (
    detect_controversy,
    detect_urgency,
    extract_affected_populations,
    extract_explicit_assumptions,
    extract_implicit_flags,
    extract_input_type,
    extract_key_entities,
    extract_scale,
    extract_time_horizon,
)
from .lexicons import (
    CHANNEL_BASELINE_SCORES,
    CHANNEL_LEXICONS,
    INVOCATION_THRESHOLD,
)
from .models import (
    Channel,
    ChannelRoute,
    ParsedContext,
    RoutingManifest,
)


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """
    Normalize input text for consistent signal matching.

    - Lowercase
    - Collapse whitespace
    - Remove punctuation that could interfere with phrase matching
      (but preserve hyphens, which appear in signal phrases)
    """
    text = text.lower()
    text = re.sub(r'[^\w\s\-]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# Channel scoring
# ---------------------------------------------------------------------------

def _score_channel(normalized_text: str, channel: Channel) -> tuple[float, list[str]]:
    """
    Score a single channel against the normalized input text.

    Returns:
        (score, matched_signals)

    Score is the sum of weights of matched signals, normalized by a
    soft ceiling that prevents any single channel from dominating purely
    because it has a large lexicon. The result is clamped to [0.0, 1.0].

    The soft ceiling is: sum of the top-N signal weights where N = 5.
    This means a channel can score 1.0 if it matches its 5 strongest signals.

    Baseline scores are applied AFTER normalization and are additive.
    This ensures channels like ETHICAL_ADVERSARIAL and UNCERTAINTY_MODELING
    reliably meet the invocation threshold even without strong lexicon matches.
    """
    lexicon = CHANNEL_LEXICONS[channel]
    baseline = CHANNEL_BASELINE_SCORES.get(channel, 0.0)

    matched_signals = []
    raw_score = 0.0

    for signal in lexicon:
        if signal.phrase in normalized_text:
            matched_signals.append(signal.phrase)
            raw_score += signal.weight

    # Soft ceiling: top-5 signals from this lexicon define score of 1.0
    top5_weight = sum(
        sorted([s.weight for s in lexicon], reverse=True)[:5]
    ) or 1.0

    # Normalize lexicon score then add baseline on top
    normalized_score = min(1.0, (raw_score / top5_weight) + baseline)
    return round(normalized_score, 4), matched_signals


def _build_rationale(
    channel: Channel,
    score: float,
    matched_signals: list[str],
    invoked: bool,
) -> str:
    """
    Produce a human-readable rationale for the routing decision.
    """
    channel_name = channel.value.replace("_", " ").title()

    if not invoked:
        if not matched_signals:
            return (
                f"{channel_name} channel not invoked: no domain signals detected in input "
                f"(relevance score: {score:.2f})."
            )
        else:
            return (
                f"{channel_name} channel not invoked: relevance score {score:.2f} "
                f"is below the invocation threshold. "
                f"Weak signals detected: {', '.join(matched_signals[:3])}."
            )

    if score >= 0.7:
        strength = "strong"
    elif score >= 0.4:
        strength = "moderate"
    else:
        strength = "low but sufficient"

    signals_str = ', '.join(f'"{s}"' for s in matched_signals[:5])
    if len(matched_signals) > 5:
        signals_str += f" (+{len(matched_signals) - 5} more)"

    return (
        f"{channel_name} channel invoked ({strength} relevance, score: {score:.2f}). "
        f"Key signals: {signals_str}."
    )


# ---------------------------------------------------------------------------
# Parser confidence
# ---------------------------------------------------------------------------

def _compute_parser_confidence(
    context: ParsedContext,
    invoked_count: int,
) -> tuple[float, list[str]]:
    """
    Estimate how confident the parser is in its own output.

    Confidence is reduced when:
    - The input is very short (less context to work with)
    - No channels were invoked (input may be too vague)
    - Input type is GENERAL_QUERY (couldn't classify it)
    - Parse warnings were generated

    Returns (confidence, warnings).
    """
    from .models import InputType

    warnings = []
    confidence = 1.0

    word_count = len(context.raw_input.split())
    if word_count < 10:
        confidence -= 0.3
        warnings.append(
            f"Input is very short ({word_count} words). "
            "Routing decisions may be unreliable. More context will improve accuracy."
        )
    elif word_count < 25:
        confidence -= 0.15
        warnings.append(
            f"Input is brief ({word_count} words). "
            "Consider providing more detail for higher-confidence routing."
        )

    if invoked_count == 0:
        confidence -= 0.4
        warnings.append(
            "No channels were invoked. The input may be too vague or abstract "
            "to route to any specialist domain."
        )
    elif invoked_count == 1:
        confidence -= 0.1
        warnings.append(
            "Only one channel was invoked. This may indicate the input is "
            "too narrow or that key domain signals are absent from the text."
        )

    if context.input_type == InputType.GENERAL_QUERY:
        confidence -= 0.15
        warnings.append(
            "Input type could not be classified beyond 'general query'. "
            "Explicit framing (e.g., 'proposed policy', 'legislation') improves routing."
        )

    confidence = max(0.1, round(confidence, 4))
    return confidence, warnings


# ---------------------------------------------------------------------------
# Main parser class
# ---------------------------------------------------------------------------

class ContextParser:
    """
    The Arbitrator Context Parser.

    Transforms natural language input into a RoutingManifest — a structured
    record of what the input is about, who it affects, and which model channels
    should be invoked to analyze it.

    The parser is stateless and deterministic. It uses no external libraries.
    All routing decisions are auditable through the RoutingManifest.

    Attributes:
        routing_version: Version string passed into every RoutingManifest.
    """

    ROUTING_VERSION = "0.1.0"

    def parse(self, raw_input: str) -> RoutingManifest:
        """
        Parse a natural language input and produce a RoutingManifest.

        Args:
            raw_input: The raw text submitted by the user. May be a question,
                       a proposal description, a policy brief, or anything else.

        Returns:
            A RoutingManifest containing the parsed context and routing decisions
            for every available channel.

        Raises:
            ValueError: If raw_input is empty or whitespace-only.
        """
        if not raw_input or not raw_input.strip():
            raise ValueError("Input must not be empty.")

        normalized = _normalize(raw_input)

        # --- Metadata extraction ---
        input_type = extract_input_type(normalized)
        scale = extract_scale(normalized)
        time_horizon = extract_time_horizon(normalized)
        affected_populations = extract_affected_populations(normalized)
        key_entities = extract_key_entities(raw_input)   # Use raw for entity extraction
        urgency = detect_urgency(normalized)
        controversy = detect_controversy(normalized)
        explicit_assumptions = extract_explicit_assumptions(raw_input)
        implicit_flags = extract_implicit_flags(normalized)

        # Domains mentioned: the channels with high relevance are the domains
        # (populated after routing below)

        # --- Channel scoring and routing ---
        routes: list[ChannelRoute] = []

        for channel in Channel:
            score, matched_signals = _score_channel(normalized, channel)
            invoked = score >= INVOCATION_THRESHOLD
            rationale = _build_rationale(channel, score, matched_signals, invoked)
            routes.append(ChannelRoute(
                channel=channel,
                invoked=invoked,
                relevance_score=score,
                signals=matched_signals,
                rationale=rationale,
            ))

        invoked_count = sum(1 for r in routes if r.invoked)

        # Domains mentioned = names of invoked channels
        domains_mentioned = [
            r.channel.value.replace("_", " ")
            for r in routes
            if r.invoked
        ]

        # --- Build ParsedContext ---
        context = ParsedContext(
            raw_input=raw_input,
            normalized_input=normalized,
            input_type=input_type,
            scale=scale,
            time_horizon=time_horizon,
            affected_populations=affected_populations,
            domains_mentioned=domains_mentioned,
            explicit_assumptions=explicit_assumptions,
            implicit_flags=implicit_flags,
            key_entities=key_entities,
            urgency_detected=urgency,
            controversy_signals=controversy,
            parser_confidence=1.0,   # Updated below
            parse_warnings=[],       # Updated below
        )

        # --- Compute parser confidence and warnings ---
        confidence, warnings = _compute_parser_confidence(context, invoked_count)
        context.parser_confidence = confidence
        context.parse_warnings = warnings

        return RoutingManifest(
            context=context,
            routes=routes,
            routing_version=self.ROUTING_VERSION,
        )

    def parse_and_serialize(self, raw_input: str) -> str:
        """
        Parse input and return the RoutingManifest as a JSON string.
        Suitable for audit logging and downstream consumers.
        """
        manifest = self.parse(raw_input)
        return json.dumps(manifest.to_dict(), indent=2)
