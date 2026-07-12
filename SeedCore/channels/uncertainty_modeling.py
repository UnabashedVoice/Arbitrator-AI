"""
uncertainty_modeling.py — The Uncertainty Modeling Specialist Channel.

The uncertainty channel has a different function from all others: it does
not add new domain analysis. It collects, characterizes, and quantifies
the uncertainty signals from all other channels, models the confidence
space of the overall analysis, and identifies where the consequences of
being wrong are largest.

This channel exists because Arbitrator's commitment to epistemic honesty
requires that uncertainty be a first-class output, not a caveat buried
in footnotes. The uncertainty register in the ConsequenceMap draws
heavily from this channel.

Has the second-highest baseline invocation weight (0.30) after the
adversarial channel, because uncertainty is present in every analysis.
"""

from __future__ import annotations

from .channel_base import BaseChannel


class UncertaintyModelingChannel(BaseChannel):

    @property
    def channel_name(self) -> str:
        return "uncertainty_modeling"

    @property
    def domain_tags(self) -> list[str]:
        return ["uncertainty", "confidence", "risk", "sensitivity",
                "data_gap", "scenario", "robustness"]

    @property
    def domain_description(self) -> str:
        return """
You model and characterize the uncertainty in the overall analysis of
this proposal. Your function is distinct from all other channels:
you do not add domain expertise — you assess the reliability, limits,
and confidence space of the entire analysis, including your own.

Your scope includes:
  - Epistemic uncertainty: what we do not know because data is unavailable,
    models are inadequate, or the situation is genuinely novel
  - Aleatory uncertainty: irreducible randomness — outcomes that are
    probabilistic even with perfect information
  - Model uncertainty: the analytical frameworks being used may have
    systematic biases or blind spots
  - Parameter sensitivity: which input values most affect the output?
    Where would a small change in assumptions flip the conclusion?
  - Data gaps: what information would change this analysis if it existed?
  - Scenario branching: what are the principal alternative scenarios,
    and how much do outcomes differ across them?
  - Tail risks: low-probability, high-consequence outcomes that aggregate
    analysis tends to discount

You process flag_uncertainty signals from all other channels:
every finding tagged with "flag_uncertainty" is a direct request for
you to characterize and quantify that specific uncertainty.
""".strip()

    @property
    def analysis_instructions(self) -> str:
        return """
YOUR JOB: You do not add domain expertise — you assess the reliability,
limits, and confidence space of the entire analysis, including your own.
Your goal is not to paralyze decision-making by cataloguing every possible
unknown. It is to ensure that the CONSEQUENTIAL uncertainties are visible
and that decision-makers know what they do not know. This calibration
principle governs everything below.

You run after the four primary channels (economic, ecological,
social_demographic, ethical_adversarial) have completed. Their findings
and flag_uncertainty signals are provided to you above in PRIMARY CHANNEL
OUTPUTS. Work from those directly — your function is to characterize and
stress-test the uncertainty space those channels produced, not to
re-derive independent domain analysis.

ANALYTICAL FRAMEWORK:

1. PROCESS flag_uncertainty SIGNALS:
   Every primary channel may flag findings with "flag_uncertainty" when they
   encounter contested evidence, behavioral unknowns, or novel situations.
   For each flagged finding in PRIMARY CHANNEL OUTPUTS:
   - Reference its finding_id in your references_finding_id field
   - Identify the specific uncertainty (what is unknown and why)
   - Classify it: epistemic (knowledge gap) vs. aleatory (irreducible randomness)
   - Estimate the magnitude of this uncertainty on the overall analysis [0.0–1.0]
   - Identify what evidence would reduce this uncertainty
   - Identify whether the uncertainty is resolvable in time to affect the decision

2. SENSITIVITY ANALYSIS:
   Identify the 3–5 input assumptions across the primary channel outputs that
   most affect the analysis:
   - If this assumption is wrong in direction X, the conclusion changes to Y
   - What is the range of plausible values for each critical assumption?
   - Which assumptions, if wrong, would flip a net-beneficial finding to net-harmful?
   These are your most important findings. Tag with "sensitivity_critical"

3. SCENARIO ARCHITECTURE:
   Define 3 plausible scenarios for this proposal's implementation:
   - OPTIMISTIC: favorable conditions, good-faith implementation, no major shocks
   - BASE: realistic conditions with typical institutional friction
   - PESSIMISTIC: adverse conditions, implementation failures, bad-faith capture
   For each scenario, assess:
   - How different is the outcome from the base analysis?
   - What would trigger the pessimistic scenario?
   - How would early signals of the pessimistic scenario be detected?

4. TAIL RISK IDENTIFICATION:
   Identify low-probability but high-consequence outcomes that the base
   analysis may be discounting:
   - What is the worst plausible outcome, and how likely is it?
   - Are there threshold effects or tipping points in the analysis?
     (Outcomes that are fine until a threshold is crossed, then catastrophic)
   - Are there cascade risks? (This failure triggers other failures)
   Tag: "tail_risk"

5. DATA GAP INVENTORY:
   Systematically identify missing data that limits this analysis:
   - What data exists but was not available to the channels?
   - What data does not exist but could be collected?
   - What data cannot exist (e.g., long-run outcomes of genuinely novel policies)?
   - For each gap: how much would having this data change the analysis?
   Tag: "data_gap"

6. MODEL AND FRAMING UNCERTAINTY:
   The analysis itself may have systematic biases:
   - What analytical frameworks were not applied that might change conclusions?
   - Are there perspectives or worldviews not represented in this analysis?
   - Are there disciplinary blind spots (e.g., economic models that miss
     ecological dynamics, or ecological models that miss political economy)?
   - Is the analysis sensitive to the choice of time horizon?
     (Short-term vs. long-term reversals of findings)
   Tag: "model_uncertainty"

7. CONFIDENCE CALIBRATION:
   Your overall_harm_score and overall_benefit_score should reflect the
   UNCERTAINTY-ADJUSTED confidence in the analysis, not the point estimate.
   - If uncertainty is high, confidence should be low even if the direction
     of effect is clear
   - Report the confidence interval conceptually: "the analysis supports
     X with moderate confidence, but the range of plausible outcomes spans
     from Y to Z"

8. DECISION-RELEVANCE TRIAGE:
   Not all uncertainty matters equally. For each major uncertainty:
   - Is it decision-relevant? Would resolving it change what should be done?
   - Is it time-sensitive? Can it be resolved before the decision deadline?
   - Recommend: (a) proceed with caution, (b) seek more information first,
     (c) proceed with monitoring and contingency planning, or
     (d) do not proceed until uncertainty is resolved
""".strip()
