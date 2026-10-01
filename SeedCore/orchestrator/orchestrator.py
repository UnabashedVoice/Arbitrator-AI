"""
orchestrator.py — The Arbitrator Orchestrator.

The Orchestrator is the single entry point for a complete analysis run.
It wires together all four modules in sequence:

    1. Context Parser  →  RoutingManifest
    2. Bridge          →  ActionProposal
    3. Ethics Core     →  EthicsEvaluation
    4. Channel Invocation  →  list[ChannelOutput]
    5. Synthesizer     →  ConsequenceMap
    6. Audit Log       →  logged throughout

Every stage is wrapped in error handling. A failure at any stage is:
    - Logged to the audit log
    - Recorded in the PipelineResult
    - Handled gracefully so subsequent stages can still run where possible

Ethics Core gating:
    - HARD_REJECT: pipeline stops. No channel invocation. No consequence map.
      The rejection itself is logged and returned.
    - FAIL: pipeline stops with ETHICS_BLOCKED status.
    - ESCALATE: pipeline continues but result is marked ESCALATED.
      Human review is required before publication.
    - PASS / AMBIGUOUS: pipeline continues normally.

Usage:
    from orchestrator import Orchestrator, OrchestratorConfig

    config = OrchestratorConfig(audit_log_path="./audit.jsonl")
    orch = Orchestrator(config)
    result = orch.run("What if we implemented a universal carbon tax?")

    print(result.status)
    print(result.ethics_verdict)
    if result.consequence_map:
        print(result.consequence_map["executive_summary"])
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..audit_log import AuditLog, LogQuery, EntryKind, writers
from ..context_parser import ContextParser
from ..ethics_core import EthicsCore
from ..ethics_core.models import Verdict
from ..synthesis import Synthesizer, ChannelOutput
from ..synthesis.channel_output import ChannelStatus

from .bridge import analysis_to_proposal, context_to_proposal
from .channel_stubs import (
    get_channel, invoke_channel, invoke_channel_with_primary_outputs, is_stub, stub_channels,
)
from .result import PipelineResult, PipelineStatus


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class OrchestratorConfig:
    """
    Configuration for the Orchestrator.

    Attributes:
        audit_log_path:         Path to the audit log file.
                                Defaults to ./arbitrator_audit.jsonl
        node_id:                Identifier for this node. Appears in all
                                audit entries.
        continue_after_fail:    If True, continue to channel invocation and
                                synthesis even after Ethics Core returns FAIL.
                                Default False (stop on FAIL, continue on AMBIGUOUS).
        continue_after_escalate: If True, continue synthesis when escalation
                                is triggered. Default True — escalation means
                                "human review required" not "stop everything".
        max_channels:           Maximum number of channels to invoke. None = all.
        arbitrator_version:     Version string written to audit log.
        use_compendium:         If True, consult the Compendium once per run and
                                show the chosen entries to the channels that use
                                it (the ethical adversary). See compendium_link.py.
        ethics_gate:            "prescreen" (default): the Ethics Core's pre-screen,
                                scored from structural estimates of the parsed
                                proposal, can stop the run (FAIL, HARD_REJECT) and
                                sets escalation. "analysis": only a HARD_REJECT
                                (a named hard constraint) stops the run; the
                                pre-screen is otherwise advisory, and a post-screen
                                on the channels' own scores decides the Ethics
                                verdict and escalation (bridge.analysis_to_proposal).
        decision_brief:         If True, every run that reaches synthesis ends with a
                                decision brief written by a model: options, each
                                with its case for and against, and a reasoned lean
                                (see decision_brief.py). Escalated or not.
        compendium_max_entries, compendium_budget_chars, compendium_max_sections:
                                How much of the Compendium a consultation may
                                disclose: entries chosen, characters shown, and
                                extra sections per entry.
    """
    audit_log_path: str = "./arbitrator_audit.jsonl"
    node_id: str = "local"
    continue_after_fail: bool = False
    continue_after_escalate: bool = True
    max_channels: Optional[int] = None
    arbitrator_version: str = "0.1.0"
    use_compendium: bool = False
    ethics_gate: str = "prescreen"
    decision_brief: bool = True
    # How deep the Compendium consultation reads. None = scale to the ethical
    # adversary's loaded context window (compendium_access.budget_for_context)
    # and let the model ask for any of an entry's sections.
    compendium_max_entries: int = 5
    compendium_budget_chars: Optional[int] = None
    compendium_max_sections: Optional[int] = None

    def __post_init__(self):
        if self.ethics_gate not in ("prescreen", "analysis"):
            raise ValueError(f"ethics_gate must be 'prescreen' or 'analysis', not {self.ethics_gate!r}")


# ---------------------------------------------------------------------------
# Ethics Core gating
# ---------------------------------------------------------------------------

# Verdicts that stop the pipeline
_BLOCKING_VERDICTS = {Verdict.HARD_REJECT, Verdict.FAIL}

# Verdicts that allow the pipeline to continue but flag for human review
_ESCALATING_VERDICTS = {Verdict.ESCALATE}


# Escalation conditions for the analysis gate. Each names why a human is needed.
IRREVERSIBLE_HARM_MAGNITUDE = 0.5     # a harm the channels call irreversible, at least this large
DISAGREEMENT_SPREAD = 0.3             # channels' harm scores further apart than this
HIGH_HARM = 0.5                       # aggregate harm at least this high ...
LOW_CONFIDENCE = 0.5                  # ... while the synthesis is less confident than this
MATERIAL_CHANNEL_HARM = 0.6           # a channel's own harm score that makes its request material

# Rule B (user decision, 2026-09-29, after the gpt-oss thirteen-question batch, in
# which 12 of 13 runs escalated). An irreversible harm counts only when an empirical
# channel reports it with at least moderate certainty: the ethical adversary is told
# to hunt for lock-in and power concentration, and uncertainty modelling for tail
# risks, so both label findings irreversible as a matter of course. A channel's own
# request for review escalates only if that channel's harm score is at least 0.6.
EMPIRICAL_CHANNELS = {"economic", "ecological", "social_demographic", "historical_precedent",
                      "legal_institutional", "geopolitical"}
CERTAIN_ENOUGH = {"moderate", "high"}


def analysis_triggers(consequence_map, channel_outputs: list) -> list[dict]:
    """Escalation triggers from the finished analysis (analysis gate)."""
    out = []
    ok = [o for o in channel_outputs if o.succeeded]
    irreversible = [(o.channel_name, f) for o in ok if o.channel_name in EMPIRICAL_CHANNELS
                    for f in o.harm_findings
                    if f.reversible is False and f.magnitude >= IRREVERSIBLE_HARM_MAGNITUDE
                    and f.certainty.value in CERTAIN_ENOUGH]
    if irreversible:
        out.append({"source": "analysis:irreversible_harm",
                    "detail": "Significant harm an empirical channel calls irreversible: " + "; ".join(
                        f"[{f.finding_id}] {f.summary} (magnitude {f.magnitude})" for _, f in irreversible)})
    scores = [(o.channel_name, o.overall_harm_score) for o in ok if o.overall_harm_score is not None]
    if len(scores) >= 2:
        lo, hi = min(scores, key=lambda x: x[1]), max(scores, key=lambda x: x[1])
        if hi[1] - lo[1] > DISAGREEMENT_SPREAD:
            out.append({"source": "analysis:channel_disagreement",
                        "detail": f"The channels disagree on harm: {hi[0]} {hi[1]} against {lo[0]} {lo[1]}."})
    if (consequence_map.overall_harm_score >= HIGH_HARM
            and consequence_map.synthesis_confidence < LOW_CONFIDENCE):
        out.append({"source": "analysis:high_harm_low_confidence",
                    "detail": f"Aggregate harm {consequence_map.overall_harm_score} with synthesis confidence "
                              f"only {consequence_map.synthesis_confidence}."})
    return out


def _material(output) -> bool:
    """Whether a channel reports enough at stake for its review request to escalate (rule B)."""
    return (output.overall_harm_score or 0) >= MATERIAL_CHANNEL_HARM


def _evaluation_dict(evaluation, stage: str) -> dict:
    return {
        "stage": stage,
        "proposal_id": evaluation.proposal_id,
        "verdict": evaluation.verdict.value,
        "justification": evaluation.justification,
        "hard_constraints_triggered": evaluation.hard_constraints_triggered,
        "weighted_harm": evaluation.weighted_harm,
        "weighted_benefit": evaluation.weighted_benefit,
        "net_score": evaluation.net_score,
        "consciousness_weight": evaluation.consciousness_weight,
        "mitigation_required": evaluation.mitigation_required,
        "mitigation_notes": evaluation.mitigation_notes,
        "flags": evaluation.flags,
        "confidence": evaluation.confidence,
        "evaluated_at": evaluation.evaluated_at,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    The Arbitrator Orchestrator.

    Wires the Context Parser, Ethics Core, Channel Invocation, Synthesizer,
    and Audit Log into a single end-to-end analysis pipeline.

    The Orchestrator is stateless between runs except for the shared
    AuditLog instance. Each call to run() produces a self-contained
    PipelineResult.

    Args:
        config:     OrchestratorConfig. Uses defaults if not provided.
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self._config = config or OrchestratorConfig()
        self._parser = ContextParser()
        self._ethics = EthicsCore()
        self._synthesizer = Synthesizer()
        self._audit = AuditLog(
            path=self._config.audit_log_path,
            node_id=self._config.node_id,
            auto_open=True,
        )

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def run(self, raw_input: str) -> PipelineResult:
        """
        Run a complete analysis pipeline on a natural language input.

        Args:
            raw_input:  The proposal or question to analyze. Any natural
                        language text. Must not be empty.

        Returns:
            A PipelineResult containing everything produced by the pipeline,
            all linked by session_id in the audit log.
        """
        session_id = str(uuid.uuid4())
        start_time = time.monotonic()

        result = PipelineResult(
            session_id=session_id,
            status=PipelineStatus.FAILED,
            raw_input=raw_input,
        )

        # --- Input validation ---
        if not raw_input or not raw_input.strip():
            result.errors.append("Input must not be empty.")
            result.status = PipelineStatus.FAILED
            result.duration_ms = int((time.monotonic() - start_time) * 1000)
            return result

        # --- Log input received ---
        input_id = str(uuid.uuid4())
        self._audit.append(writers.write_input_received(
            session_id=session_id,
            raw_input=raw_input,
            input_id=input_id,
            node_id=self._config.node_id,
        ))

        # =====================================================================
        # Stage 1: Context Parsing
        # =====================================================================
        manifest = None
        context = None

        try:
            manifest = self._parser.parse(raw_input)
            context = manifest.context

            self._audit.append(writers.write_context_parsed(
                session_id=session_id,
                manifest_dict=manifest.to_dict(),
                input_id=input_id,
                node_id=self._config.node_id,
            ))

            result.manifest = manifest.to_dict()

            if context.parse_warnings:
                result.warnings.extend(
                    f"[context_parser] {w}" for w in context.parse_warnings
                )

        except Exception as e:
            error_msg = f"Context parsing failed: {type(e).__name__}: {e}"
            result.errors.append(error_msg)
            self._audit.append(writers.write_pipeline_error(
                session_id=session_id,
                stage="context_parser",
                error_type=type(e).__name__,
                error_message=str(e),
                node_id=self._config.node_id,
            ))
            result.status = PipelineStatus.FAILED
            result.duration_ms = int((time.monotonic() - start_time) * 1000)
            return result

        # =====================================================================
        # Stage 2: Ethics Core (pre-screen)
        # =====================================================================
        evaluation = None
        proposal_id = str(uuid.uuid4())

        try:
            proposal = context_to_proposal(
                context=context,
                raw_input=raw_input,
                proposal_id=proposal_id,
            )

            evaluation = self._ethics.evaluate(proposal)
            eval_dict = _evaluation_dict(evaluation, stage="pre_screen")

            self._audit.append(writers.write_ethics_evaluated(
                session_id=session_id,
                evaluation_dict=eval_dict,
                proposal_id=proposal_id,
                manifest_id=manifest.manifest_id,
                node_id=self._config.node_id,
            ))

            result.ethics_evaluation = eval_dict
            result.ethics_verdict = evaluation.verdict.value

        except Exception as e:
            error_msg = f"Ethics evaluation failed: {type(e).__name__}: {e}"
            result.errors.append(error_msg)
            self._audit.append(writers.write_pipeline_error(
                session_id=session_id,
                stage="ethics_core",
                error_type=type(e).__name__,
                error_message=str(e),
                related_ids=[proposal_id, manifest.manifest_id],
                node_id=self._config.node_id,
            ))
            # Ethics failure is non-fatal — continue with warning
            result.warnings.append("[ethics_core] Evaluation could not be completed.")
            evaluation = None

        # --- Ethics gating ---
        analysis_gate = self._config.ethics_gate == "analysis"
        result.gate_mode = self._config.ethics_gate
        if evaluation is not None and analysis_gate:
            # Only a named hard constraint stops the run. Anything else the
            # pre-screen says is advisory: it is scored from structural
            # estimates, and the post-screen after the channels decides.
            result.prescreen_verdict = evaluation.verdict.value
            if evaluation.verdict == Verdict.HARD_REJECT:
                result.status = PipelineStatus.ETHICS_BLOCKED
                result.warnings.append(
                    f"[ethics_core] Pipeline stopped by a hard constraint: "
                    f"{'; '.join(evaluation.hard_constraints_triggered)}. "
                    f"Justification: {evaluation.justification}"
                )
                result.duration_ms = int((time.monotonic() - start_time) * 1000)
                return result
            if evaluation.verdict != Verdict.PASS:
                result.warnings.append(
                    f"[ethics_core] Pre-screen verdict {evaluation.verdict.value} is advisory under the "
                    f"analysis gate (structural estimates only); the post-screen decides. "
                    f"Justification: {evaluation.justification}"
                )
        elif evaluation is not None:
            if evaluation.verdict in _BLOCKING_VERDICTS and not self._config.continue_after_fail:
                block_status = PipelineStatus.ETHICS_BLOCKED
                result.status = block_status
                result.warnings.append(
                    f"[ethics_core] Pipeline stopped: verdict={evaluation.verdict.value}. "
                    f"Justification: {evaluation.justification}"
                )
                result.duration_ms = int((time.monotonic() - start_time) * 1000)
                return result

            if evaluation.verdict in _ESCALATING_VERDICTS:
                result.warnings.append(
                    f"[ethics_core] Human review required: verdict=ESCALATE. "
                    f"Justification: {evaluation.justification}"
                )
                if not self._config.continue_after_escalate:
                    result.status = PipelineStatus.ESCALATED
                    result.duration_ms = int((time.monotonic() - start_time) * 1000)
                    return result

        # =====================================================================
        # Stage 3: Channel Invocation (two-phase)
        #
        # Phase A — Primary channels run independently:
        #   economic, ecological, social_demographic
        #   These produce grounded domain analysis and emit flag_* signals.
        #
        # Phase B — Secondary channels run with primary outputs injected:
        #   ethical_adversarial, historical_precedent, legal_institutional,
        #   geopolitical, uncertainty_modeling
        #   These process the flag_* signals and reference primary finding_ids.
        # =====================================================================
        _PRIMARY_CHANNELS = {"economic", "ecological", "social_demographic"}
        _SECONDARY_CHANNELS = {
            "ethical_adversarial",
            "historical_precedent",
            "legal_institutional",
            "geopolitical",
            "uncertainty_modeling",
        }

        channel_outputs: list[ChannelOutput] = []
        channels_to_invoke = [r.channel.value for r in manifest.routes if r.invoked]

        if self._config.max_channels is not None:
            channels_to_invoke = channels_to_invoke[:self._config.max_channels]

        result.channels_invoked = channels_to_invoke
        context_dict = context.to_dict()

        # --- Phase A: primary channels ---
        primary_outputs: list[ChannelOutput] = []
        for channel_name in channels_to_invoke:
            if channel_name not in _PRIMARY_CHANNELS:
                continue

            output = invoke_channel(channel_name, raw_input, context_dict)

            self._audit.append(writers.write_channel_output(
                session_id=session_id,
                channel_output_dict=output.to_dict(),
                manifest_id=manifest.manifest_id,
                node_id=self._config.node_id,
            ))

            if output.status == ChannelStatus.FAILED:
                self._audit.append(writers.write_channel_failure(
                    session_id=session_id,
                    channel_name=channel_name,
                    failure_reason=output.error_message or "Unknown failure",
                    manifest_id=manifest.manifest_id,
                    node_id=self._config.node_id,
                ))

            primary_outputs.append(output)
            channel_outputs.append(output)

        # --- Compendium consultation (opt-in), before the channels that use it ---
        if self._config.use_compendium and "ethical_adversarial" in channels_to_invoke:
            from .compendium_link import consult
            record, disclosed = consult(
                raw_input, get_channel("ethical_adversarial")._backend,
                max_entries=self._config.compendium_max_entries,
                budget_chars=self._config.compendium_budget_chars,
                max_sections=self._config.compendium_max_sections,
            )
            result.compendium = record
            if disclosed:
                context_dict["compendium_referents"] = disclosed
            if record.get("error"):
                result.warnings.append(f"[compendium] Consultation failed: {record['error']}")
            self._audit.append(writers.write_compendium_consulted(
                session_id=session_id,
                consultation_dict=record,
                manifest_id=manifest.manifest_id,
                node_id=self._config.node_id,
            ))

        # --- Phase B: secondary channels (with primary outputs injected) ---
        for channel_name in channels_to_invoke:
            if channel_name not in _SECONDARY_CHANNELS:
                continue

            output = invoke_channel_with_primary_outputs(
                channel_name, raw_input, context_dict, primary_outputs
            )

            self._audit.append(writers.write_channel_output(
                session_id=session_id,
                channel_output_dict=output.to_dict(),
                manifest_id=manifest.manifest_id,
                node_id=self._config.node_id,
            ))

            if output.status == ChannelStatus.FAILED:
                self._audit.append(writers.write_channel_failure(
                    session_id=session_id,
                    channel_name=channel_name,
                    failure_reason=output.error_message or "Unknown failure",
                    manifest_id=manifest.manifest_id,
                    node_id=self._config.node_id,
                ))

            channel_outputs.append(output)

        # Track succeeded vs stubbed
        result.channels_succeeded = [
            o.channel_name for o in channel_outputs
            if o.status == ChannelStatus.SUCCESS
        ]
        result.channels_stubbed = [
            o.channel_name for o in channel_outputs
            if o.status == ChannelStatus.UNAVAILABLE and is_stub(o.channel_name)
        ]

        if result.channels_stubbed:
            result.warnings.append(
                f"[channels] {len(result.channels_stubbed)} channel(s) are stubs "
                f"(not yet implemented): {', '.join(result.channels_stubbed)}. "
                f"Consequence map is incomplete for these domains."
            )

        # =====================================================================
        # Stage 4: Synthesis
        # =====================================================================
        consequence_map = None

        try:
            consequence_map = self._synthesizer.synthesize(
                proposal_description=raw_input,
                manifest_id=manifest.manifest_id,
                channel_outputs=channel_outputs,
                ethics_evaluation_id=proposal_id if evaluation else None,
            )

            cmap_dict = consequence_map.to_dict()

            self._audit.append(writers.write_consequence_map(
                session_id=session_id,
                consequence_map_dict=cmap_dict,
                manifest_id=manifest.manifest_id,
                ethics_evaluation_id=proposal_id if evaluation else None,
                node_id=self._config.node_id,
            ))

            result.consequence_map = cmap_dict
            result.synthesis_verdict = consequence_map.overall_verdict.value

        except Exception as e:
            error_msg = f"Synthesis failed: {type(e).__name__}: {e}"
            result.errors.append(error_msg)
            self._audit.append(writers.write_pipeline_error(
                session_id=session_id,
                stage="synthesizer",
                error_type=type(e).__name__,
                error_message=str(e),
                related_ids=[manifest.manifest_id],
                node_id=self._config.node_id,
            ))

        # =====================================================================
        # Stage 5 (analysis gate): post-screen on the channels' own scores
        # =====================================================================
        post = None
        if analysis_gate and evaluation is not None and consequence_map is not None:
            try:
                post_proposal = analysis_to_proposal(proposal, consequence_map, channel_outputs)
                post = self._ethics.evaluate(post_proposal)
                post_dict = _evaluation_dict(post, stage="post_screen")
                self._audit.append(writers.write_ethics_evaluated(
                    session_id=session_id,
                    evaluation_dict=post_dict,
                    proposal_id=post_proposal.proposal_id,
                    manifest_id=manifest.manifest_id,
                    node_id=self._config.node_id,
                ))
                result.post_screen_evaluation = post_dict
                result.ethics_verdict = post.verdict.value
            except Exception as e:
                post = None
                result.errors.append(f"Post-screen failed: {type(e).__name__}: {e}")
                self._audit.append(writers.write_pipeline_error(
                    session_id=session_id, stage="post_screen", error_type=type(e).__name__,
                    error_message=str(e), related_ids=[manifest.manifest_id], node_id=self._config.node_id,
                ))

        # =====================================================================
        # Escalation: what triggered it, and a brief that lets people resolve it
        # =====================================================================
        triggers = []
        if analysis_gate:
            # The Ethics Core's post-screen verdict is recorded, but only a hard
            # constraint escalates from it: its multipliers were tuned for the
            # bridge's structural estimates and, fed the channels' scores, would
            # escalate almost any proposal (user decision, 2026-09-29). The
            # analysis escalates on explicit conditions instead.
            if post is not None and post.verdict == Verdict.HARD_REJECT:
                triggers.append({"source": "ethics_core_post_screen",
                                 "detail": f"hard constraint in the analysis: "
                                           f"{'; '.join(post.hard_constraints_triggered)}. {post.justification}"})
            if consequence_map is not None:
                triggers.extend(analysis_triggers(consequence_map, channel_outputs))
        elif evaluation is not None and evaluation.verdict in _ESCALATING_VERDICTS:
            triggers.append({"source": "ethics_core_pre_screen",
                             "detail": f"verdict {evaluation.verdict.value} (structural estimates): "
                                       f"{evaluation.justification}"})
        # Channels' own requests for review: all are recorded, and each escalates
        # only if that channel reports something material (user decision, 2026-09-29).
        requests = []
        for o in channel_outputs:
            if o.succeeded and o.escalation_request:
                material = _material(o)
                requests.append({"channel": o.channel_name, "material": material, **o.escalation_request})
                if material:
                    triggers.append({"source": f"channel:{o.channel_name}",
                                     "detail": f"{o.escalation_request.get('reason', '')} To decide: "
                                               f"{o.escalation_request.get('what_to_decide', '')}".strip()})
        result.review_requests = requests
        if triggers:
            result.escalation = {"triggers": triggers}
            self._audit.append(writers.write_escalation(
                session_id=session_id, escalation_dict=result.escalation,
                manifest_id=manifest.manifest_id, node_id=self._config.node_id,
            ))

        # =====================================================================
        # Decision brief: every analysed run ends with a way to resolve it
        # (user decision, 2026-09-29), escalated or not.
        # =====================================================================
        if self._config.decision_brief and result.consequence_map is not None:
            from .decision_brief import write_brief
            written = write_brief(get_channel("ethical_adversarial")._backend, raw_input, triggers,
                                  result.to_dict(), context_dict.get("compendium_referents", ""))
            result.brief = written
            if written["error"]:
                result.warnings.append(f"[decision_brief] Brief not produced: {written['error']}")
            self._audit.append(writers.write_decision_brief(
                session_id=session_id, brief_dict=written,
                manifest_id=manifest.manifest_id, node_id=self._config.node_id,
            ))

        # =====================================================================
        # Determine final status
        # =====================================================================
        if triggers:
            result.status = PipelineStatus.ESCALATED
        elif result.consequence_map is not None:
            if result.errors:
                result.status = PipelineStatus.PARTIAL
            else:
                result.status = PipelineStatus.SUCCESS
        elif result.ethics_evaluation is not None:
            result.status = PipelineStatus.PARTIAL
        else:
            result.status = PipelineStatus.FAILED

        result.duration_ms = int((time.monotonic() - start_time) * 1000)
        return result

    # ---------------------------------------------------------------------------
    # Audit log access
    # ---------------------------------------------------------------------------

    def get_audit_log(self) -> AuditLog:
        """Return the underlying AuditLog instance."""
        return self._audit

    def verify_audit_chain(self, log_verification: bool = True):
        """
        Run chain integrity verification on the audit log.

        Args:
            log_verification:   If True, write the verification result
                                to the log itself.
        Returns:
            VerificationResult
        """
        return self._audit.verify(log_verification=log_verification)

    def get_session_history(self, session_id: str) -> list[dict]:
        """
        Return all audit entries for a given session as dicts.
        Useful for debugging and the public audit interface.
        """
        entries = self._audit.get_session(session_id)
        return [e.to_public_dict() for e in entries]

    def audit_summary(self) -> dict:
        """Return summary statistics for the audit log."""
        return self._audit.summary()
