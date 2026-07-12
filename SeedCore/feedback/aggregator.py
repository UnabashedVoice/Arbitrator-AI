"""
aggregator.py — Feedback aggregation into FeedbackSummary.

The FeedbackAggregator is the synthesis layer of the Feedback System.
It receives a stream of validated FeedbackEntry objects and produces a
FeedbackSummary that represents the current state of human response
to a published consequence map.

Aggregation is incremental: each new submission updates the summary
rather than recomputing from scratch. The aggregator is stateful per
map_id — it holds an open FeedbackSummary for each active map.

KEY AGGREGATION DECISIONS:

Net sentiment is computed as:
    (sum of support trust weights) - (sum of challenge trust weights)
    divided by total trust weight
    → normalized to [-1.0, 1.0]

This means a domain expert's challenge counts more than five citizen
challenges if the domain expert has high trust in the relevant domain.
This is intentional: the goal is epistemic quality, not democratic vote.

Escalation pressure accumulates as:
    sum of trust weights from all ESCALATION_REQUEST submissions
At threshold 1.0, a single reviewer escalation is sufficient.
A group of citizens can also collectively cross the threshold if
their combined trust weight is sufficient.

Finding signals track per-finding support/challenge weight independently
of the map-level sentiment. A map can be net-positive in sentiment
while having one specific finding that is highly contested.
"""

from __future__ import annotations

from .models import (
    FeedbackEntry,
    FeedbackSummary,
    FeedbackStatus,
    FeedbackType,
    FindingSignal,
)


class FeedbackAggregator:
    """
    Aggregates validated feedback entries into per-map FeedbackSummary objects.

    Maintains one FeedbackSummary per map_id. Summaries are built
    incrementally as submissions arrive.

    Usage:
        agg = FeedbackAggregator()

        # Add validated entries
        agg.integrate(entry)

        # Get current summary
        summary = agg.get_summary(map_id)

        # Check if any map needs escalation
        for map_id, summary in agg.all_summaries().items():
            if summary.requires_escalation:
                trigger_human_review(map_id)
    """

    def __init__(self):
        self._summaries: dict[str, FeedbackSummary] = {}

    def integrate(self, entry: FeedbackEntry) -> FeedbackSummary:
        """
        Integrate a validated FeedbackEntry into the appropriate summary.

        Args:
            entry:  A validated FeedbackEntry (status should be VALIDATED
                    before calling this method).

        Returns:
            The updated FeedbackSummary for this entry's map_id.
        """
        summary = self._get_or_create(entry.map_id, entry.session_id)

        # Dispatch by type
        if entry.feedback_type == FeedbackType.FINDING_CHALLENGE:
            self._integrate_finding_signal(summary, entry, is_challenge=True)

        elif entry.feedback_type == FeedbackType.FINDING_SUPPORT:
            self._integrate_finding_signal(summary, entry, is_challenge=False)

        elif entry.feedback_type == FeedbackType.DATA_CORRECTION:
            summary.data_corrections.append(entry)
            # Also link to finding signal if targeting a specific finding
            if entry.target_finding_id:
                signal = self._get_or_create_signal(summary, entry.target_finding_id)
                signal.data_corrections.append(entry)

        elif entry.feedback_type == FeedbackType.ADVERSARIAL_CHALLENGE:
            summary.adversarial_challenges.append(entry)

        elif entry.feedback_type == FeedbackType.MITIGATION_SUGGESTION:
            summary.mitigation_suggestions.append(entry)

        elif entry.feedback_type == FeedbackType.GENERAL_COMMENT:
            summary.general_comments.append(entry)

        elif entry.feedback_type == FeedbackType.ESCALATION_REQUEST:
            summary.escalation_requests.append(entry)
            summary.escalation_pressure = round(
                summary.escalation_pressure + entry.trust_weight, 4
            )

        # Update counters and cross-cutting fields
        summary.total_submissions += 1
        role_key = entry.submitter.role.value
        summary.role_breakdown[role_key] = summary.role_breakdown.get(role_key, 0) + 1

        # Mark entry as integrated
        entry.status = FeedbackStatus.INTEGRATED

        # Recompute derived fields
        self._recompute_summary(summary)

        return summary

    def get_summary(self, map_id: str) -> FeedbackSummary | None:
        """Return the current FeedbackSummary for a map, or None."""
        return self._summaries.get(map_id)

    def all_summaries(self) -> dict[str, FeedbackSummary]:
        """Return all active FeedbackSummary objects."""
        return dict(self._summaries)

    def maps_requiring_escalation(self) -> list[str]:
        """Return map_ids where escalation_pressure >= threshold."""
        return [
            mid for mid, summary in self._summaries.items()
            if summary.requires_escalation
        ]

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _get_or_create(self, map_id: str, session_id: str) -> FeedbackSummary:
        if map_id not in self._summaries:
            self._summaries[map_id] = FeedbackSummary(
                map_id=map_id,
                session_id=session_id,
            )
        return self._summaries[map_id]

    def _get_or_create_signal(
        self, summary: FeedbackSummary, finding_id: str
    ) -> FindingSignal:
        if finding_id not in summary.finding_signals:
            summary.finding_signals[finding_id] = FindingSignal(
                finding_id=finding_id
            )
        return summary.finding_signals[finding_id]

    def _integrate_finding_signal(
        self,
        summary: FeedbackSummary,
        entry: FeedbackEntry,
        is_challenge: bool,
    ) -> None:
        signal = self._get_or_create_signal(summary, entry.target_finding_id)
        if is_challenge:
            signal.challenge_weight = round(
                signal.challenge_weight + entry.trust_weight, 4
            )
            signal.challenge_count += 1
            signal.challenges.append(entry)
        else:
            signal.support_weight = round(
                signal.support_weight + entry.trust_weight, 4
            )
            signal.support_count += 1
            signal.supports.append(entry)

    def _recompute_summary(self, summary: FeedbackSummary) -> None:
        """
        Recompute derived fields on the summary after an integration.

        Updates:
            - contested_findings
            - corroborated_findings
            - net_sentiment
        """
        summary.contested_findings = [
            fid for fid, sig in summary.finding_signals.items()
            if sig.is_contested
        ]
        summary.corroborated_findings = [
            fid for fid, sig in summary.finding_signals.items()
            if sig.is_corroborated
        ]

        # Net sentiment: (total_support - total_challenge) / total_weight
        total_support = sum(
            sig.support_weight for sig in summary.finding_signals.values()
        )
        total_challenge = sum(
            sig.challenge_weight for sig in summary.finding_signals.values()
        )
        total_weight = total_support + total_challenge

        if total_weight > 0:
            raw_sentiment = (total_support - total_challenge) / total_weight
            summary.net_sentiment = round(
                max(-1.0, min(1.0, raw_sentiment)), 4
            )
        else:
            # No finding-level signals — use general comment direction as proxy
            # (zero if no finding signals exist)
            summary.net_sentiment = 0.0
