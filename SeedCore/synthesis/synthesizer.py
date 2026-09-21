"""
synthesizer.py — The Arbitrator Synthesis Layer.

The Synthesizer is the thalamus: it receives discrete outputs from multiple
specialist channels and integrates them into a unified ConsequenceMap.

It does not produce any analysis of its own. It integrates what the channels
give it. The intelligence is in the weighting, the aggregation, the ripple
detection, and the honest accounting of what is missing.

Pipeline:
    1. Validate channel outputs — reject malformed, record failed channels
    2. Aggregate scores — compute weighted harm/benefit scores across channels
    3. Organize by timeframe — group findings into ImpactSummary per timeframe
    4. Organize by population — group findings by affected group
    5. Detect ripple effects — identify second-order consequences
    6. Collect adversarial challenges — surface all challenges from the
       ethical adversarial channel
    7. Build uncertainty register — collect all uncertainty notes
    8. Identify data gaps — note what we couldn't analyze and why
    9. Derive overall verdict — from aggregate scores and confidence
   10. Write executive summary — plain-language synthesis
   11. Assemble and return ConsequenceMap

Design notes:
    - Channel outputs are weighted by their confidence score. A channel that
      reports low confidence contributes less to the aggregate scores.
    - Failed channels are always recorded. A missing channel is never silently
      ignored — it is a documented gap.
    - Ripple effect detection is currently rule-based (cross-domain signal
      matching). This is the component most likely to benefit from LLM
      integration when the channel invocation layer is built.
"""

from __future__ import annotations

import statistics
from typing import Optional

from .channel_output import (
    ChannelOutput,
    ChannelStatus,
    ImpactDirection,
    ImpactTimeframe,
    ImpactCertainty,
    Finding,
    UncertaintyNote,
)
from .consequence_map import (
    ConsequenceMap,
    ImpactSummary,
    OverallVerdict,
    PopulationImpact,
    RippleEffect,
)


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------

_CERTAINTY_WEIGHTS = {
    ImpactCertainty.HIGH: 1.0,
    ImpactCertainty.MODERATE: 0.7,
    ImpactCertainty.LOW: 0.4,
    ImpactCertainty.UNKNOWN: 0.25,
}


def _aggregate_scores(outputs: list[ChannelOutput]) -> tuple[float, float, float]:
    """
    Compute weighted aggregate harm and benefit scores across all successful channels.

    Weighting:
        - Each channel's scores are weighted by its reported confidence.
        - Within a channel, individual finding scores contribute based on their
          certainty (HIGH certainty findings count more).
        - A channel with confidence=None is treated as confidence=0.5.

    Returns:
        (weighted_harm, weighted_benefit, aggregate_confidence)
        All values in [0.0, 1.0].
    """
    successful = [o for o in outputs if o.succeeded]
    if not successful:
        return 0.0, 0.0, 0.0

    harm_scores = []
    benefit_scores = []
    confidences = []

    for output in successful:
        channel_confidence = output.confidence if output.confidence is not None else 0.5
        confidences.append(channel_confidence)

        # Use the channel's overall scores if provided
        if output.overall_harm_score is not None:
            harm_scores.append((output.overall_harm_score, channel_confidence))
        elif output.findings:
            # Derive from findings if no overall score
            harm_findings = output.harm_findings
            if harm_findings:
                finding_score = sum(
                    f.magnitude * _CERTAINTY_WEIGHTS.get(f.certainty, 0.5)
                    for f in harm_findings
                ) / len(harm_findings)
                harm_scores.append((finding_score, channel_confidence))

        if output.overall_benefit_score is not None:
            benefit_scores.append((output.overall_benefit_score, channel_confidence))
        elif output.findings:
            benefit_findings = output.benefit_findings
            if benefit_findings:
                finding_score = sum(
                    f.magnitude * _CERTAINTY_WEIGHTS.get(f.certainty, 0.5)
                    for f in benefit_findings
                ) / len(benefit_findings)
                benefit_scores.append((finding_score, channel_confidence))

    def weighted_average(score_weight_pairs: list[tuple[float, float]]) -> float:
        if not score_weight_pairs:
            return 0.0
        total_weight = sum(w for _, w in score_weight_pairs)
        if total_weight == 0:
            return 0.0
        return sum(s * w for s, w in score_weight_pairs) / total_weight

    harm = min(1.0, weighted_average(harm_scores))
    benefit = min(1.0, weighted_average(benefit_scores))
    confidence = statistics.mean(confidences) if confidences else 0.0

    return round(harm, 4), round(benefit, 4), round(confidence, 4)


# ---------------------------------------------------------------------------
# Timeframe organization
# ---------------------------------------------------------------------------

def _organize_by_timeframe(outputs: list[ChannelOutput]) -> list[ImpactSummary]:
    """
    Group all findings from all channels by their timeframe.

    Returns one ImpactSummary per timeframe that has at least one finding.
    Timeframes with no findings are omitted (not padded with empty entries).
    """
    timeframe_buckets: dict[ImpactTimeframe, dict] = {}

    for output in outputs:
        if not output.succeeded:
            continue
        for finding in output.findings:
            tf = finding.timeframe
            if tf not in timeframe_buckets:
                timeframe_buckets[tf] = {
                    "harm": [],
                    "benefit": [],
                    "neutral": [],
                }
            if finding.direction in (ImpactDirection.HARM, ImpactDirection.MIXED):
                timeframe_buckets[tf]["harm"].append(finding)
            elif finding.direction == ImpactDirection.BENEFIT:
                timeframe_buckets[tf]["benefit"].append(finding)
            else:
                timeframe_buckets[tf]["neutral"].append(finding)

    # Order timeframes chronologically
    timeframe_order = [
        ImpactTimeframe.IMMEDIATE,
        ImpactTimeframe.SHORT_TERM,
        ImpactTimeframe.MEDIUM_TERM,
        ImpactTimeframe.LONG_TERM,
        ImpactTimeframe.GENERATIONAL,
    ]

    summaries = []
    for tf in timeframe_order:
        if tf not in timeframe_buckets:
            continue
        bucket = timeframe_buckets[tf]

        harm_magnitude = (
            sum(f.magnitude for f in bucket["harm"]) / len(bucket["harm"])
            if bucket["harm"] else 0.0
        )
        benefit_magnitude = (
            sum(f.magnitude for f in bucket["benefit"]) / len(bucket["benefit"])
            if bucket["benefit"] else 0.0
        )

        net_magnitude = abs(benefit_magnitude - harm_magnitude)
        if benefit_magnitude > harm_magnitude:
            net_direction = ImpactDirection.BENEFIT
        elif harm_magnitude > benefit_magnitude:
            net_direction = ImpactDirection.HARM
        else:
            net_direction = ImpactDirection.NEUTRAL

        total_findings = len(bucket["harm"]) + len(bucket["benefit"]) + len(bucket["neutral"])
        summary_text = _write_timeframe_summary(tf, bucket, net_direction, net_magnitude)

        summaries.append(ImpactSummary(
            timeframe=tf,
            harm_findings=bucket["harm"],
            benefit_findings=bucket["benefit"],
            neutral_findings=bucket["neutral"],
            net_direction=net_direction,
            net_magnitude=round(net_magnitude, 4),
            summary_text=summary_text,
        ))

    return summaries


def _write_timeframe_summary(
    tf: ImpactTimeframe,
    bucket: dict,
    net_direction: ImpactDirection,
    net_magnitude: float,
) -> str:
    """Generate a plain-language summary for a single timeframe."""
    tf_label = tf.value.replace("_", " ")
    harm_count = len(bucket["harm"])
    benefit_count = len(bucket["benefit"])

    if harm_count == 0 and benefit_count == 0:
        return f"No significant {tf_label} impacts identified."

    direction_phrase = {
        ImpactDirection.BENEFIT: "net beneficial",
        ImpactDirection.HARM: "net harmful",
        ImpactDirection.NEUTRAL: "balanced",
    }.get(net_direction, "mixed")

    magnitude_phrase = (
        "marginally" if net_magnitude < 0.2 else
        "moderately" if net_magnitude < 0.5 else
        "significantly" if net_magnitude < 0.8 else
        "severely"
    )

    parts = [f"In the {tf_label} timeframe, the analysis is {magnitude_phrase} {direction_phrase}."]

    if harm_count > 0:
        # Surface the highest-magnitude harm
        top_harm = max(bucket["harm"], key=lambda f: f.magnitude)
        parts.append(f"Primary harm: {top_harm.summary}")

    if benefit_count > 0:
        top_benefit = max(bucket["benefit"], key=lambda f: f.magnitude)
        parts.append(f"Primary benefit: {top_benefit.summary}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Population impact organization
# ---------------------------------------------------------------------------

def _organize_by_population(outputs: list[ChannelOutput]) -> list[PopulationImpact]:
    """
    Group findings by affected population group across all channels.
    """
    population_buckets: dict[str, dict] = {}

    for output in outputs:
        if not output.succeeded:
            continue
        for finding in output.findings:
            for group in finding.affected_groups:
                if group not in population_buckets:
                    population_buckets[group] = {"harm": [], "benefit": []}
                if finding.direction in (ImpactDirection.HARM, ImpactDirection.MIXED):
                    population_buckets[group]["harm"].append(finding)
                elif finding.direction == ImpactDirection.BENEFIT:
                    population_buckets[group]["benefit"].append(finding)

    impacts = []
    for population, bucket in sorted(population_buckets.items()):
        harm_mag = (
            sum(f.magnitude for f in bucket["harm"]) / len(bucket["harm"])
            if bucket["harm"] else 0.0
        )
        benefit_mag = (
            sum(f.magnitude for f in bucket["benefit"]) / len(bucket["benefit"])
            if bucket["benefit"] else 0.0
        )
        net_magnitude = abs(benefit_mag - harm_mag)
        net_direction = (
            ImpactDirection.BENEFIT if benefit_mag > harm_mag else
            ImpactDirection.HARM if harm_mag > benefit_mag else
            ImpactDirection.NEUTRAL
        )

        harm_summaries = "; ".join(f.summary for f in bucket["harm"][:2])
        benefit_summaries = "; ".join(f.summary for f in bucket["benefit"][:2])
        parts = [f"Impact on {population}:"]
        if harm_summaries:
            parts.append(f"Harms include: {harm_summaries}.")
        if benefit_summaries:
            parts.append(f"Benefits include: {benefit_summaries}.")

        impacts.append(PopulationImpact(
            population=population,
            harm_findings=bucket["harm"],
            benefit_findings=bucket["benefit"],
            net_direction=net_direction,
            net_magnitude=round(net_magnitude, 4),
            summary_text=" ".join(parts),
        ))

    return impacts


# ---------------------------------------------------------------------------
# Ripple effect detection
# ---------------------------------------------------------------------------

# Cross-domain ripple rules: when finding A in domain X exists above a
# magnitude threshold, it implies ripple effect B touching domain Y.
# Format: (trigger_tags, trigger_direction, trigger_magnitude_min, ripple_description,
#          ripple_direction, affected_domains, certainty_note)

_RIPPLE_RULES: list[tuple] = [
    (
        ["economic"], ImpactDirection.HARM, 0.5,
        "Economic harm at scale typically increases pressure on social welfare systems, "
        "raising healthcare costs and social program demand.",
        ImpactDirection.HARM,
        ["social", "health"],
        "Moderate certainty — historically observed in economic downturns.",
    ),
    (
        ["ecological"], ImpactDirection.HARM, 0.5,
        "Ecological harm often translates to economic harm through loss of ecosystem "
        "services (clean water, pollination, flood protection, fisheries).",
        ImpactDirection.HARM,
        ["economic", "social"],
        "Moderate certainty — well-documented in environmental economics literature.",
    ),
    (
        ["ecological"], ImpactDirection.HARM, 0.7,
        "Severe ecological harm tends to disproportionately affect indigenous and "
        "low-income communities who depend directly on natural resources for subsistence.",
        ImpactDirection.HARM,
        ["social", "indigenous communities"],
        "High certainty — consistently observed in extractive industry impacts.",
    ),
    (
        ["social"], ImpactDirection.HARM, 0.6,
        "Social instability and inequality create conditions that increase political "
        "polarization, eroding institutional trust and democratic function.",
        ImpactDirection.HARM,
        ["political", "institutional"],
        "Moderate certainty — pattern observed across multiple historical contexts.",
    ),
    (
        ["economic"], ImpactDirection.BENEFIT, 0.6,
        "Economic growth, if broadly distributed, tends to improve health outcomes "
        "and educational attainment across affected populations.",
        ImpactDirection.BENEFIT,
        ["social", "health", "education"],
        "Moderate certainty — dependent on distribution mechanisms.",
    ),
    (
        ["geopolitical"], ImpactDirection.HARM, 0.5,
        "Geopolitical instability can disrupt global supply chains, increasing "
        "costs and reducing economic stability across interconnected economies.",
        ImpactDirection.HARM,
        ["economic", "social"],
        "Moderate certainty — supply chain vulnerability varies by sector.",
    ),
    (
        ["ecological"], ImpactDirection.HARM, 0.6,
        "Habitat loss and ecological degradation are leading drivers of zoonotic "
        "disease emergence, increasing pandemic risk.",
        ImpactDirection.HARM,
        ["health", "economic", "social"],
        "Moderate-to-high certainty — supported by epidemiological research.",
    ),
    (
        ["economic"], ImpactDirection.HARM, 0.7,
        "Severe economic disruption increases rates of mental health crises, "
        "substance use disorders, and family instability.",
        ImpactDirection.HARM,
        ["health", "social"],
        "High certainty — extensively documented in economic stress research.",
    ),
]


def _detect_ripple_effects(outputs: list[ChannelOutput]) -> list[RippleEffect]:
    """
    Apply cross-domain ripple rules to identify second-order consequences.

    A ripple rule fires when:
    - A finding with matching tags exists
    - The finding's direction matches the trigger direction
    - The finding's magnitude meets or exceeds the threshold
    """
    all_findings = []
    for output in outputs:
        if output.succeeded:
            all_findings.extend(output.findings)

    ripples = []
    seen_descriptions = set()

    for rule in _RIPPLE_RULES:
        trigger_tags, trigger_direction, min_magnitude, description, ripple_direction, affected_domains, certainty_note = rule

        # Find findings that trigger this rule
        triggering_findings = []
        for finding in all_findings:
            tag_match = any(tag in finding.tags for tag in trigger_tags)
            direction_match = finding.direction == trigger_direction
            magnitude_match = finding.magnitude >= min_magnitude

            if tag_match and direction_match and magnitude_match:
                triggering_findings.append(finding)

        if triggering_findings and description not in seen_descriptions:
            seen_descriptions.add(description)
            ripples.append(RippleEffect(
                description=description,
                source_finding_ids=[f.finding_id for f in triggering_findings],
                direction=ripple_direction,
                certainty_note=certainty_note,
                affected_domains=affected_domains,
            ))

    return ripples


# ---------------------------------------------------------------------------
# Channel failure accounting
# ---------------------------------------------------------------------------

def _account_for_failures(
    outputs: list[ChannelOutput],
    invoked_channels: list[str],
) -> tuple[list[dict], list[str]]:
    """
    Produce a list of failed channel records and data gap descriptions.

    Returns:
        (failed_channels, data_gaps)
    """
    failed = []
    gaps = []

    succeeded_names = {o.channel_name for o in outputs if o.succeeded}

    for output in outputs:
        if not output.succeeded:
            failed.append({
                "channel": output.channel_name,
                "status": output.status.value,
                "reason": output.error_message or "No error detail available.",
            })
            gaps.append(
                f"{output.channel_name.replace('_', ' ').title()} analysis unavailable "
                f"({output.status.value}). "
                f"Findings from this domain are absent from the consequence map."
            )

    # Channels that were expected but produced no output at all
    for channel_name in invoked_channels:
        if channel_name not in succeeded_names and channel_name not in {o.channel_name for o in outputs}:
            failed.append({
                "channel": channel_name,
                "status": "no_output",
                "reason": "Channel was invoked but returned no output.",
            })
            gaps.append(
                f"{channel_name.replace('_', ' ').title()} was invoked but returned no output. "
                f"This domain is unrepresented in the analysis."
            )

    return failed, gaps


# ---------------------------------------------------------------------------
# Verdict derivation
# ---------------------------------------------------------------------------

def _derive_verdict(
    harm: float,
    benefit: float,
    confidence: float,
    successful_count: int,
    total_invoked: int,
) -> OverallVerdict:
    """
    Derive the synthesis-level OverallVerdict from aggregate scores.
    """
    # Not enough data
    if successful_count == 0:
        return OverallVerdict.INSUFFICIENT_DATA

    coverage = successful_count / max(total_invoked, 1)
    if coverage < 0.5 or confidence < 0.3:
        return OverallVerdict.REQUIRES_REVIEW

    net = benefit - harm

    if net >= 0.25:
        return OverallVerdict.NET_BENEFICIAL
    elif net <= -0.25:
        return OverallVerdict.NET_HARMFUL
    elif harm >= 0.4 and benefit >= 0.4:
        return OverallVerdict.MIXED
    elif abs(net) < 0.1 and confidence < 0.6:
        return OverallVerdict.REQUIRES_REVIEW
    else:
        return OverallVerdict.MIXED


# ---------------------------------------------------------------------------
# Executive summary generation
# ---------------------------------------------------------------------------

def _write_executive_summary(
    proposal_description: str,
    verdict: OverallVerdict,
    harm: float,
    benefit: float,
    confidence: float,
    timeframe_impacts: list[ImpactSummary],
    adversarial_challenges: list[str],
    failed_channels: list[dict],
    ripple_count: int,
) -> str:
    """
    Write a plain-language executive summary of the consequence map.
    """
    verdict_phrases = {
        OverallVerdict.NET_BENEFICIAL: "the analysis finds this action to be net beneficial",
        OverallVerdict.NET_HARMFUL: "the analysis finds this action to be net harmful",
        OverallVerdict.MIXED: "the analysis identifies significant harms and benefits, with no clear net direction",
        OverallVerdict.REQUIRES_REVIEW: "the analysis is inconclusive and requires human review before a decision can be made",
        OverallVerdict.INSUFFICIENT_DATA: "insufficient data is available to reach a synthesis conclusion",
    }

    confidence_phrase = (
        "high confidence" if confidence >= 0.7 else
        "moderate confidence" if confidence >= 0.4 else
        "low confidence"
    )

    harm_phrase = (
        "minimal" if harm < 0.2 else
        "moderate" if harm < 0.5 else
        "significant" if harm < 0.75 else
        "severe"
    )

    benefit_phrase = (
        "minimal" if benefit < 0.2 else
        "moderate" if benefit < 0.5 else
        "significant" if benefit < 0.75 else
        "substantial"
    )

    summary_parts = [
        f"With {confidence_phrase}, {verdict_phrases.get(verdict, 'the verdict is unclear')}. "
        f"Aggregate harm is assessed as {harm_phrase} (score: {harm:.2f}) and "
        f"aggregate benefit as {benefit_phrase} (score: {benefit:.2f})."
    ]

    if timeframe_impacts:
        tf_labels = [ti.timeframe.value.replace("_", " ") for ti in timeframe_impacts]
        summary_parts.append(
            f"Impacts were identified across {len(timeframe_impacts)} timeframe(s): "
            f"{', '.join(tf_labels)}."
        )

    if ripple_count > 0:
        summary_parts.append(
            f"{ripple_count} second-order ripple effect(s) were identified. "
            f"These indirect consequences should be considered alongside the direct findings."
        )

    if adversarial_challenges:
        summary_parts.append(
            f"The ethical adversarial channel raised {len(adversarial_challenges)} challenge(s) "
            f"to this proposal. These are surfaced in full in the adversarial challenges section."
        )

    if failed_channels:
        channels_str = ", ".join(fc["channel"] for fc in failed_channels)
        summary_parts.append(
            f"Note: {len(failed_channels)} channel(s) failed to produce output ({channels_str}). "
            f"The analysis is incomplete in these domains. See the data gaps section."
        )

    summary_parts.append(
        "This consequence map is an analysis, not a recommendation. "
        "The decision authority rests with the human decision-maker."
    )

    return " ".join(summary_parts)


# ---------------------------------------------------------------------------
# Mitigation collection
# ---------------------------------------------------------------------------

def _collect_mitigations(outputs: list[ChannelOutput]) -> list[str]:
    """
    Collect recommended mitigations from all channel outputs.
    Currently derived from uncertainty notes and high-magnitude harm findings.
    As channels mature, they will provide explicit mitigation suggestions.
    """
    mitigations = []
    seen = set()

    for output in outputs:
        if not output.succeeded:
            continue

        # High-magnitude harms imply mitigation need
        for finding in output.harm_findings:
            if finding.magnitude >= 0.5:
                suggestion = (
                    f"[{output.channel_name}] Mitigation needed for: {finding.summary}"
                )
                if suggestion not in seen:
                    seen.add(suggestion)
                    mitigations.append(suggestion)

        # Uncertainty notes that suggest action
        for note in output.uncertainty_notes:
            if note.magnitude >= 0.5:
                suggestion = (
                    f"[{output.channel_name}] Address uncertainty before proceeding: "
                    f"{note.description}"
                )
                if suggestion not in seen:
                    seen.add(suggestion)
                    mitigations.append(suggestion)

    return mitigations


# ---------------------------------------------------------------------------
# Main Synthesizer class
# ---------------------------------------------------------------------------

class Synthesizer:
    """
    The Arbitrator Synthesis Layer.

    Integrates discrete channel outputs into a unified ConsequenceMap.
    This is the thalamus: it receives signals from many sources and
    produces a coherent, integrated picture.

    The Synthesizer is stateless. It holds no memory between calls.
    All state is in the inputs and the returned ConsequenceMap.

    Usage:
        synthesizer = Synthesizer()
        consequence_map = synthesizer.synthesize(
            proposal_description="...",
            manifest_id="...",
            channel_outputs=[output1, output2, ...],
            ethics_evaluation_id="...",   # optional
        )
    """

    def synthesize(
        self,
        proposal_description: str,
        manifest_id: str,
        channel_outputs: list[ChannelOutput],
        ethics_evaluation_id: Optional[str] = None,
    ) -> ConsequenceMap:
        """
        Integrate channel outputs into a ConsequenceMap.

        Args:
            proposal_description:   The original proposal text.
            manifest_id:            ID of the RoutingManifest that drove invocation.
            channel_outputs:        List of ChannelOutput objects from invoked channels.
            ethics_evaluation_id:   ID of the Ethics Core evaluation (if available).

        Returns:
            A fully populated ConsequenceMap.
        """
        if not proposal_description.strip():
            raise ValueError("proposal_description must not be empty")

        invoked_channels = [o.channel_name for o in channel_outputs]
        successful_outputs = [o for o in channel_outputs if o.succeeded]

        # --- Score aggregation ---
        harm, benefit, confidence = _aggregate_scores(channel_outputs)
        net_score = round(benefit - harm, 4)

        # --- Timeframe organization ---
        timeframe_impacts = _organize_by_timeframe(channel_outputs)

        # --- Population impacts ---
        population_impacts = _organize_by_population(channel_outputs)

        # --- Ripple effects ---
        ripple_effects = _detect_ripple_effects(channel_outputs)

        # --- Adversarial challenges ---
        adversarial_challenges = []
        for output in channel_outputs:
            if output.succeeded and output.adversarial_challenges:
                adversarial_challenges.extend(output.adversarial_challenges)

        # --- Uncertainty register ---
        uncertainty_register = []
        for output in channel_outputs:
            if output.succeeded:
                uncertainty_register.extend(output.uncertainty_notes)

        # --- Failure accounting ---
        failed_channels, data_gaps = _account_for_failures(channel_outputs, invoked_channels)

        # --- Mitigations ---
        recommended_mitigations = _collect_mitigations(channel_outputs)

        # --- Verdict ---
        verdict = _derive_verdict(
            harm=harm,
            benefit=benefit,
            confidence=confidence,
            successful_count=len(successful_outputs),
            total_invoked=len(invoked_channels),
        )

        # --- Executive summary ---
        executive_summary = _write_executive_summary(
            proposal_description=proposal_description,
            verdict=verdict,
            harm=harm,
            benefit=benefit,
            confidence=confidence,
            timeframe_impacts=timeframe_impacts,
            adversarial_challenges=adversarial_challenges,
            failed_channels=failed_channels,
            ripple_count=len(ripple_effects),
        )

        return ConsequenceMap(
            proposal_description=proposal_description,
            manifest_id=manifest_id,
            ethics_evaluation_id=ethics_evaluation_id,
            overall_verdict=verdict,
            overall_harm_score=harm,
            overall_benefit_score=benefit,
            net_score=net_score,
            synthesis_confidence=confidence,
            executive_summary=executive_summary,
            timeframe_impacts=timeframe_impacts,
            population_impacts=population_impacts,
            ripple_effects=ripple_effects,
            adversarial_challenges=adversarial_challenges,
            uncertainty_register=uncertainty_register,
            channel_outputs=[o.to_dict() for o in channel_outputs],
            channels_invoked=invoked_channels,
            channels_succeeded=[o.channel_name for o in successful_outputs],
            channels_failed=failed_channels,
            data_gaps=data_gaps,
            recommended_mitigations=recommended_mitigations,
        )
