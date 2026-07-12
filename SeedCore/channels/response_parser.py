"""
response_parser.py — Converts model responses into validated ChannelOutput objects.

Every channel prompts the model to return a specific JSON schema.
This module is responsible for:
    1. Extracting JSON from the model response (handles markdown fences, preamble)
    2. Validating required fields are present
    3. Coercing values into the correct types (enum values, clamped floats)
    4. Constructing a fully typed ChannelOutput

If parsing fails at any step, the parser returns a FAILED ChannelOutput
with the error detail rather than raising — the pipeline handles failures
gracefully and the caller is never responsible for catching parse errors.

The JSON schema every channel must return is defined here and enforced
here. Channels build prompts that request this schema; this parser
validates that they got it.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..synthesis.channel_output import (
    ChannelOutput,
    ChannelStatus,
    Finding,
    ImpactCertainty,
    ImpactDirection,
    ImpactTimeframe,
    UncertaintyNote,
)


# ---------------------------------------------------------------------------
# Expected response schema (documented for prompt construction)
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA = """
{
  "domain_summary": "<string: 1-2 paragraph plain-language summary of analysis>",
  "overall_harm_score": <float 0.0-1.0>,
  "overall_benefit_score": <float 0.0-1.0>,
  "confidence": <float 0.0-1.0>,
  "findings": [
    {
      "finding_id": "<string: deterministic id in format '{channel_name}_{index:02d}', e.g. 'economic_00', 'ecological_03'>",
      "summary": "<string: one sentence>",
      "detail": "<string: 1-3 sentences of supporting detail>",
      "direction": "<'harm'|'benefit'|'neutral'|'mixed'>",
      "timeframe": "<'immediate'|'short_term'|'medium_term'|'long_term'|'generational'>",
      "certainty": "<'high'|'moderate'|'low'|'unknown'>",
      "magnitude": <float 0.0-1.0>,
      "affected_groups": ["<string>", ...],
      "reversible": <true|false|null>,
      "citations": ["<string>", ...],
      "tags": ["<string>", ...],
      "references_finding_id": ["<string: finding_id from another channel this finding responds to or builds on>", ...]
    }
  ],
  "uncertainty_notes": [
    {
      "description": "<string: what is uncertain>",
      "impact_on_analysis": "<string: how this affects findings>",
      "magnitude": <float 0.0-1.0>
    }
  ],
  "adversarial_challenges": ["<string>", ...]
}
"""


# ---------------------------------------------------------------------------
# Enum value maps (lenient parsing — accepts common variants)
# ---------------------------------------------------------------------------

_DIRECTION_MAP: dict[str, ImpactDirection] = {
    "harm": ImpactDirection.HARM,
    "harmful": ImpactDirection.HARM,
    "negative": ImpactDirection.HARM,
    "benefit": ImpactDirection.BENEFIT,
    "beneficial": ImpactDirection.BENEFIT,
    "positive": ImpactDirection.BENEFIT,
    "neutral": ImpactDirection.NEUTRAL,
    "mixed": ImpactDirection.MIXED,
    "both": ImpactDirection.MIXED,
}

_TIMEFRAME_MAP: dict[str, ImpactTimeframe] = {
    "immediate": ImpactTimeframe.IMMEDIATE,
    "short_term": ImpactTimeframe.SHORT_TERM,
    "short term": ImpactTimeframe.SHORT_TERM,
    "short-term": ImpactTimeframe.SHORT_TERM,
    "medium_term": ImpactTimeframe.MEDIUM_TERM,
    "medium term": ImpactTimeframe.MEDIUM_TERM,
    "medium-term": ImpactTimeframe.MEDIUM_TERM,
    "long_term": ImpactTimeframe.LONG_TERM,
    "long term": ImpactTimeframe.LONG_TERM,
    "long-term": ImpactTimeframe.LONG_TERM,
    "generational": ImpactTimeframe.GENERATIONAL,
    "intergenerational": ImpactTimeframe.GENERATIONAL,
}

_CERTAINTY_MAP: dict[str, ImpactCertainty] = {
    "high": ImpactCertainty.HIGH,
    "strong": ImpactCertainty.HIGH,
    "well-supported": ImpactCertainty.HIGH,
    "moderate": ImpactCertainty.MODERATE,
    "probable": ImpactCertainty.MODERATE,
    "low": ImpactCertainty.LOW,
    "speculative": ImpactCertainty.LOW,
    "uncertain": ImpactCertainty.LOW,
    "unknown": ImpactCertainty.UNKNOWN,
}


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> str:
    """
    Extract a JSON object from a string that may contain markdown fences,
    preamble text, or other noise.

    Tries in order:
    1. Direct parse (ideal case — pure JSON)
    2. Extract from ```json ... ``` fence
    3. Extract from ``` ... ``` fence
    4. Find the first { and last } and try parsing that substring
    """
    text = text.strip()

    # Try direct parse first
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # Try ```json fence
    fence_match = re.search(r'```json\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Try plain ``` fence
    fence_match = re.search(r'```\s*([\s\S]*?)\s*```', text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Try first { to last }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from response (length {len(text)})")


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

def _parse_float(value, default: float = 0.5, lo: float = 0.0, hi: float = 1.0) -> float:
    """Parse a float, clamp to [lo, hi], return default on failure."""
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def _parse_direction(value: str) -> ImpactDirection:
    return _DIRECTION_MAP.get(str(value).lower().strip(), ImpactDirection.NEUTRAL)


def _parse_timeframe(value: str) -> ImpactTimeframe:
    return _TIMEFRAME_MAP.get(str(value).lower().strip(), ImpactTimeframe.MEDIUM_TERM)


def _parse_certainty(value: str) -> ImpactCertainty:
    return _CERTAINTY_MAP.get(str(value).lower().strip(), ImpactCertainty.UNKNOWN)


def _parse_bool_or_none(value) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).lower()
    if s in ("true", "yes", "1"):
        return True
    if s in ("false", "no", "0"):
        return False
    return None


def _parse_str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


# ---------------------------------------------------------------------------
# Finding parser
# ---------------------------------------------------------------------------

def _parse_finding(raw: dict, channel_name: str, index: int) -> Optional[Finding]:
    """Parse one finding dict into a Finding. Returns None if critically malformed."""
    summary = str(raw.get("summary", "")).strip()
    if not summary:
        return None

    detail = str(raw.get("detail", summary))
    direction = _parse_direction(raw.get("direction", "neutral"))
    timeframe = _parse_timeframe(raw.get("timeframe", "medium_term"))
    certainty = _parse_certainty(raw.get("certainty", "unknown"))
    magnitude = _parse_float(raw.get("magnitude", 0.3))
    affected_groups = _parse_str_list(raw.get("affected_groups", []))
    reversible = _parse_bool_or_none(raw.get("reversible"))
    citations = _parse_str_list(raw.get("citations", []))
    references_finding_id = _parse_str_list(raw.get("references_finding_id", []))

    # Tags: always include the channel name as a tag
    tags = _parse_str_list(raw.get("tags", []))
    if channel_name not in tags:
        tags.insert(0, channel_name)

    # Use model-supplied finding_id if valid, otherwise generate deterministic fallback
    raw_fid = str(raw.get("finding_id", "")).strip()
    if raw_fid:
        finding_id = raw_fid
    else:
        finding_id = f"{channel_name}_{index:02d}"

    try:
        return Finding(
            finding_id=finding_id,
            summary=summary,
            detail=detail,
            direction=direction,
            timeframe=timeframe,
            certainty=certainty,
            magnitude=magnitude,
            affected_groups=affected_groups,
            reversible=reversible,
            citations=citations,
            tags=tags,
            references_finding_id=references_finding_id,
        )
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# UncertaintyNote parser
# ---------------------------------------------------------------------------

def _parse_uncertainty_note(raw: dict) -> Optional[UncertaintyNote]:
    """Parse one uncertainty note dict. Returns None if critically malformed."""
    description = str(raw.get("description", "")).strip()
    if not description:
        return None
    impact = str(raw.get("impact_on_analysis", "Impact on analysis not specified."))
    magnitude = _parse_float(raw.get("magnitude", 0.5))
    try:
        return UncertaintyNote(
            description=description,
            impact_on_analysis=impact,
            magnitude=magnitude,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_channel_response(
    raw_response: str,
    channel_name: str,
    model_id: str = "unknown",
    processing_time_ms: Optional[int] = None,
) -> ChannelOutput:
    """
    Parse a raw model response string into a validated ChannelOutput.

    Always returns a ChannelOutput — never raises. Failures produce a
    FAILED status output with the error in error_message.

    Args:
        raw_response:       The raw string from the model backend.
        channel_name:       Which channel this response is for.
        model_id:           Backend identifier for audit logging.
        processing_time_ms: How long the backend call took.

    Returns:
        ChannelOutput with status SUCCESS or FAILED.
    """

    # --- Extract JSON ---
    try:
        json_str = _extract_json(raw_response)
        data = json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        return ChannelOutput(
            channel_name=channel_name,
            status=ChannelStatus.FAILED,
            error_message=f"JSON extraction failed: {e}. Response length: {len(raw_response)}.",
            model_id=model_id,
            processing_time_ms=processing_time_ms,
        )

    if not isinstance(data, dict):
        return ChannelOutput(
            channel_name=channel_name,
            status=ChannelStatus.FAILED,
            error_message=f"Expected JSON object, got {type(data).__name__}.",
            model_id=model_id,
            processing_time_ms=processing_time_ms,
        )

    # --- Parse fields ---
    domain_summary = str(data.get("domain_summary", "")).strip()
    if not domain_summary:
        domain_summary = f"[{channel_name}] No summary provided."

    overall_harm = data.get("overall_harm_score")
    overall_benefit = data.get("overall_benefit_score")
    confidence = data.get("confidence")

    harm_score = _parse_float(overall_harm, default=0.3) if overall_harm is not None else None
    benefit_score = _parse_float(overall_benefit, default=0.3) if overall_benefit is not None else None
    confidence_score = _parse_float(confidence, default=0.5) if confidence is not None else None

    # --- Parse findings ---
    raw_findings = data.get("findings", [])
    findings = []
    if isinstance(raw_findings, list):
        for index, raw in enumerate(raw_findings):
            if isinstance(raw, dict):
                f = _parse_finding(raw, channel_name, index)
                if f is not None:
                    findings.append(f)

    # --- Parse uncertainty notes ---
    raw_notes = data.get("uncertainty_notes", [])
    uncertainty_notes = []
    if isinstance(raw_notes, list):
        for raw in raw_notes:
            if isinstance(raw, dict):
                note = _parse_uncertainty_note(raw)
                if note is not None:
                    uncertainty_notes.append(note)

    # --- Parse adversarial challenges ---
    raw_challenges = data.get("adversarial_challenges", [])
    adversarial_challenges = _parse_str_list(raw_challenges)

    return ChannelOutput(
        channel_name=channel_name,
        status=ChannelStatus.SUCCESS,
        findings=findings,
        uncertainty_notes=uncertainty_notes,
        overall_harm_score=harm_score,
        overall_benefit_score=benefit_score,
        confidence=confidence_score,
        domain_summary=domain_summary,
        adversarial_challenges=adversarial_challenges,
        model_id=model_id,
        processing_time_ms=processing_time_ms,
    )
