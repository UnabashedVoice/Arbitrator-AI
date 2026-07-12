"""
writers.py — Typed entry constructors for the Arbitrator Audit Log.

These functions create correctly-typed AuditEntry instances from the
outputs of each pipeline stage. They are the interface between the
pipeline and the audit log — callers don't construct AuditEntry directly.

Every pipeline stage has a corresponding writer function here.
Using these functions (rather than constructing AuditEntry manually)
ensures that:
    - Payloads are consistently structured
    - Required fields are always populated
    - Entry kinds match their payloads
    - Related IDs are correctly linked

All writer functions return an AuditEntry that is ready to be passed
to AuditLog.append().
"""

from __future__ import annotations

from typing import Any, Optional

from .models import AuditEntry, EntryKind


# ---------------------------------------------------------------------------
# Pipeline stage writers
# ---------------------------------------------------------------------------

def write_input_received(
    session_id: str,
    raw_input: str,
    input_id: str,
    source: str = "user",
    node_id: str = "local",
) -> AuditEntry:
    """
    Log the raw input received from a user or external source.

    This is always the first entry in an analysis session.
    """
    return AuditEntry(
        kind=EntryKind.INPUT_RECEIVED,
        session_id=session_id,
        node_id=node_id,
        related_ids=[input_id],
        payload={
            "input_id": input_id,
            "raw_input": raw_input,
            "source": source,
            "character_count": len(raw_input),
            "word_count": len(raw_input.split()),
        },
    )


def write_context_parsed(
    session_id: str,
    manifest_dict: dict,
    input_id: str,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log the RoutingManifest produced by the Context Parser.

    Args:
        manifest_dict:  The dict from RoutingManifest.to_dict().
        input_id:       The input_id this parse was derived from.
    """
    return AuditEntry(
        kind=EntryKind.CONTEXT_PARSED,
        session_id=session_id,
        node_id=node_id,
        related_ids=[input_id, manifest_dict.get("manifest_id", "")],
        payload=manifest_dict,
    )


def write_ethics_evaluated(
    session_id: str,
    evaluation_dict: dict,
    proposal_id: str,
    manifest_id: str,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log an EthicsEvaluation from the Ethics Core.

    Args:
        evaluation_dict:  The dict from EthicsEvaluation.to_dict(), extended
                          with proposal metadata.
        proposal_id:      The proposal_id this evaluation covers.
        manifest_id:      The manifest_id that drove this evaluation.
    """
    return AuditEntry(
        kind=EntryKind.ETHICS_EVALUATED,
        session_id=session_id,
        node_id=node_id,
        related_ids=[proposal_id, manifest_id],
        payload=evaluation_dict,
    )


def write_channel_output(
    session_id: str,
    channel_output_dict: dict,
    manifest_id: str,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log the output of a single specialist channel.

    Each channel invocation produces its own audit entry. This means
    the complete raw output of every channel is in the public record,
    not just the synthesis.

    Args:
        channel_output_dict:  The dict from ChannelOutput.to_dict().
        manifest_id:          The manifest_id that triggered this invocation.
    """
    return AuditEntry(
        kind=EntryKind.CHANNEL_OUTPUT,
        session_id=session_id,
        node_id=node_id,
        related_ids=[
            manifest_id,
            channel_output_dict.get("output_id", ""),
        ],
        payload=channel_output_dict,
    )


def write_consequence_map(
    session_id: str,
    consequence_map_dict: dict,
    manifest_id: str,
    ethics_evaluation_id: Optional[str] = None,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log the ConsequenceMap produced by the Synthesizer.

    This is the primary output of the analysis pipeline and the record
    most likely to be read by public audit reviewers.

    Args:
        consequence_map_dict:   The dict from ConsequenceMap.to_dict().
        manifest_id:            The manifest_id that drove this synthesis.
        ethics_evaluation_id:   The ethics evaluation ID, if available.
    """
    related = [manifest_id, consequence_map_dict.get("map_id", "")]
    if ethics_evaluation_id:
        related.append(ethics_evaluation_id)

    return AuditEntry(
        kind=EntryKind.CONSEQUENCE_MAP,
        session_id=session_id,
        node_id=node_id,
        related_ids=related,
        payload=consequence_map_dict,
    )


def write_feedback_received(
    session_id: str,
    feedback_dict: dict,
    related_map_id: str,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log a feedback submission against a published consequence map.

    Args:
        feedback_dict:      The structured feedback payload.
        related_map_id:     The map_id the feedback refers to.
    """
    return AuditEntry(
        kind=EntryKind.FEEDBACK_RECEIVED,
        session_id=session_id,
        node_id=node_id,
        related_ids=[related_map_id, feedback_dict.get("id", "")],
        payload=feedback_dict,
    )


def write_human_review(
    session_id: str,
    reviewer_id: str,
    decision: str,
    rationale: str,
    related_map_id: str,
    related_ethics_id: Optional[str] = None,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log a human review decision.

    Human review is triggered when the Synthesizer or Ethics Core
    flags an analysis as requiring human ratification before publication.

    Args:
        reviewer_id:        Identifier of the reviewing human (may be anonymized).
        decision:           One of: "approve", "reject", "defer", "amend"
        rationale:          Human-readable explanation of the decision.
        related_map_id:     The consequence map under review.
        related_ethics_id:  The ethics evaluation under review, if applicable.
    """
    valid_decisions = {"approve", "reject", "defer", "amend"}
    if decision not in valid_decisions:
        raise ValueError(f"decision must be one of {valid_decisions}, got {decision!r}")

    related = [related_map_id]
    if related_ethics_id:
        related.append(related_ethics_id)

    return AuditEntry(
        kind=EntryKind.HUMAN_REVIEW,
        session_id=session_id,
        node_id=node_id,
        related_ids=related,
        payload={
            "reviewer_id": reviewer_id,
            "decision": decision,
            "rationale": rationale,
            "related_map_id": related_map_id,
            "related_ethics_id": related_ethics_id,
        },
    )


# ---------------------------------------------------------------------------
# System event writers
# ---------------------------------------------------------------------------

def write_log_opened(
    session_id: str,
    log_path: str,
    arbitrator_version: str = "0.1.0",
    node_id: str = "local",
) -> AuditEntry:
    """Log that a new audit log file was opened (first entry in any log file)."""
    return AuditEntry(
        kind=EntryKind.LOG_OPENED,
        session_id=session_id,
        node_id=node_id,
        payload={
            "log_path": log_path,
            "arbitrator_version": arbitrator_version,
            "note": "Audit log initialized. All subsequent entries are hash-chained from this point.",
        },
    )


def write_verification_result(
    session_id: str,
    verification_dict: dict,
    node_id: str = "local",
) -> AuditEntry:
    """Log the result of a chain integrity verification run."""
    kind = (
        EntryKind.LOG_VERIFIED
        if verification_dict.get("valid", False)
        else EntryKind.VERIFICATION_FAILED
    )
    return AuditEntry(
        kind=kind,
        session_id=session_id,
        node_id=node_id,
        payload=verification_dict,
    )


def write_pipeline_error(
    session_id: str,
    stage: str,
    error_type: str,
    error_message: str,
    related_ids: Optional[list[str]] = None,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log an error that occurred during pipeline processing.

    Errors are logged rather than silently swallowed. The audit record
    shows not only what succeeded but what failed and why.
    """
    return AuditEntry(
        kind=EntryKind.PIPELINE_ERROR,
        session_id=session_id,
        node_id=node_id,
        related_ids=related_ids or [],
        payload={
            "stage": stage,
            "error_type": error_type,
            "error_message": error_message,
        },
    )


def write_channel_failure(
    session_id: str,
    channel_name: str,
    failure_reason: str,
    manifest_id: str,
    node_id: str = "local",
) -> AuditEntry:
    """Log a specific channel invocation failure."""
    return AuditEntry(
        kind=EntryKind.CHANNEL_FAILURE,
        session_id=session_id,
        node_id=node_id,
        related_ids=[manifest_id],
        payload={
            "channel_name": channel_name,
            "failure_reason": failure_reason,
            "manifest_id": manifest_id,
        },
    )
