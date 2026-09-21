"""
result.py — The PipelineResult: output of a complete Orchestrator run.

The PipelineResult is what the caller receives after submitting an input
to the Orchestrator. It contains everything produced by the pipeline,
all linked by the session_id for audit log cross-referencing.

It also contains a human-readable status and any errors that occurred.
A PipelineResult is always returned — even if the pipeline partially
failed — so the caller always gets the most complete picture available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class PipelineStatus(Enum):
    """The overall status of a pipeline run."""
    SUCCESS = "success"             # All stages completed
    PARTIAL = "partial"             # Some stages failed but analysis was produced
    ETHICS_BLOCKED = "ethics_blocked"   # Ethics Core issued HARD_REJECT or FAIL
    ESCALATED = "escalated"         # Ethics Core flagged for human review
    FAILED = "failed"               # Pipeline could not produce any output


@dataclass
class PipelineResult:
    """
    The complete output of a single Orchestrator pipeline run.

    Attributes:
        session_id:             UUID linking all audit log entries for this run.
        status:                 Overall pipeline status.
        raw_input:              The original submitted text.

        manifest:               The RoutingManifest dict (or None if parsing failed).
        ethics_evaluation:      The EthicsEvaluation dict (or None if unavailable).
        consequence_map:        The ConsequenceMap dict (or None if synthesis failed).

        ethics_verdict:         The Ethics Core verdict string (for quick access).
        synthesis_verdict:      The Synthesis verdict string (for quick access).

        channels_invoked:       Which channels were called.
        channels_succeeded:     Which channels returned useful output.
        channels_stubbed:       Which channels returned stub (unavailable) output.

        errors:                 Any errors that occurred during the run.
        warnings:               Non-fatal issues noted during the run.

        completed_at:           UTC timestamp of pipeline completion.
        duration_ms:            Total pipeline duration in milliseconds.

        is_publishable:         Whether this result can be published to the
                                public audit interface. False for hard rejects,
                                escalations pending review, or complete failures.
    """
    session_id: str
    status: PipelineStatus
    raw_input: str

    manifest: Optional[dict] = None
    ethics_evaluation: Optional[dict] = None
    consequence_map: Optional[dict] = None

    ethics_verdict: Optional[str] = None
    synthesis_verdict: Optional[str] = None

    channels_invoked: list[str] = field(default_factory=list)
    channels_succeeded: list[str] = field(default_factory=list)
    channels_stubbed: list[str] = field(default_factory=list)

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    completed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: Optional[int] = None

    @property
    def is_publishable(self) -> bool:
        return self.status in (PipelineStatus.SUCCESS, PipelineStatus.PARTIAL)

    @property
    def requires_human_review(self) -> bool:
        return self.status == PipelineStatus.ESCALATED

    @property
    def was_blocked(self) -> bool:
        return self.status == PipelineStatus.ETHICS_BLOCKED

    def summary(self) -> str:
        """One-paragraph plain-language summary of this pipeline run."""
        lines = [
            f"Session {self.session_id[:8]}... | Status: {self.status.value.upper()}",
        ]
        if self.ethics_verdict:
            lines.append(f"Ethics verdict: {self.ethics_verdict}")
        if self.synthesis_verdict:
            lines.append(f"Synthesis verdict: {self.synthesis_verdict}")
        if self.channels_invoked:
            lines.append(
                f"Channels invoked: {len(self.channels_invoked)} | "
                f"Succeeded: {len(self.channels_succeeded)} | "
                f"Stubbed: {len(self.channels_stubbed)}"
            )
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
        if self.warnings:
            lines.append(f"Warnings: {len(self.warnings)}")
        if self.duration_ms is not None:
            lines.append(f"Duration: {self.duration_ms}ms")
        return " | ".join(lines)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "raw_input": self.raw_input,
            "ethics_verdict": self.ethics_verdict,
            "synthesis_verdict": self.synthesis_verdict,
            "channels_invoked": self.channels_invoked,
            "channels_succeeded": self.channels_succeeded,
            "channels_stubbed": self.channels_stubbed,
            "errors": self.errors,
            "warnings": self.warnings,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "is_publishable": self.is_publishable,
            "requires_human_review": self.requires_human_review,
            "was_blocked": self.was_blocked,
            "manifest": self.manifest,
            "ethics_evaluation": self.ethics_evaluation,
            "consequence_map": self.consequence_map,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
