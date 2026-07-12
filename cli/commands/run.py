"""
commands/run.py — The 'arbitrator run' command.

Submits a proposal to the full pipeline and displays the consequence map.

Usage:
    arbitrator run "Proposed 10% tariff on imported solar panels."
    arbitrator run --verbose "A national carbon tax of $50 per tonne..."
    arbitrator run --no-color --output result.json "..."
    arbitrator run --ethics-only "..."
    echo "proposal text" | arbitrator run -
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# Ensure package root is findable regardless of invocation method
import os
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Arbitrator.cli.config_manager import ConfigManager
from Arbitrator.cli import display


def run_command(
    proposal: str,
    config: ConfigManager,
    verbose: bool = False,
    ethics_only: bool = False,
    output_file: Optional[str] = None,
    json_output: bool = False,
) -> int:
    """
    Execute the analysis pipeline for a proposal.

    Returns exit code: 0 = success/partial/escalated, 1 = ethics blocked, 2 = failure
    """
    # Read from stdin if proposal is "-"
    if proposal.strip() == "-":
        display.status("Reading proposal from stdin...")
        proposal = sys.stdin.read().strip()

    if not proposal.strip():
        display.error("Proposal text is empty.")
        return 2

    display.status(
        f"Analyzing: {proposal[:80]}{'...' if len(proposal) > 80 else ''}"
    )

    # Build orchestrator
    from Arbitrator.SeedCore.orchestrator.orchestrator import (
        Orchestrator, OrchestratorConfig
    )

    cfg = OrchestratorConfig(
        audit_log_path=config.get("audit_log_path"),
        node_id=config.get("node_id"),
        continue_after_fail=config.get("continue_after_fail"),
        continue_after_escalate=config.get("continue_after_escalate"),
        arbitrator_version=config.get("arbitrator_version"),
    )

    try:
        orch = Orchestrator(cfg)
    except Exception as e:
        display.error(f"Failed to initialize pipeline: {e}")
        return 2

    # Show backend info
    from Arbitrator.SeedCore.channels.backend import get_default_backend
    backend = get_default_backend()
    display.status(f"Backend: {backend.model_id}")

    # Run pipeline
    display.status("Running analysis pipeline...")
    try:
        result = orch.run(proposal)
    except Exception as e:
        display.error(f"Pipeline error: {e}")
        return 2

    result_dict = result.to_dict()

    # Ethics-only mode
    if ethics_only:
        ee = result_dict.get("ethics_evaluation")
        if ee:
            print(display.render_ethics_evaluation(ee))
        else:
            display.warn("Ethics evaluation not available in result.")
        return _exit_code(result_dict)

    # JSON output
    if json_output:
        output = json.dumps(result_dict, indent=2)
        if output_file:
            Path(output_file).write_text(output, encoding="utf-8")
            display.success(f"Result written to {output_file}")
        else:
            print(output)
        return _exit_code(result_dict)

    # Render terminal output
    rendered = display.render_pipeline_result(result_dict, verbose=verbose)

    if verbose and result_dict.get("ethics_evaluation"):
        rendered += "\n" + display.render_ethics_evaluation(
            result_dict["ethics_evaluation"]
        )

    if output_file:
        Path(output_file).write_text(rendered, encoding="utf-8")
        display.success(f"Result written to {output_file}")
        status_str = result_dict.get("status", "unknown")
        ev = result_dict.get("ethics_verdict", "")
        sv = result_dict.get("synthesis_verdict", "")
        display.info(f"Status: {status_str}  Ethics: {ev}  Synthesis: {sv}")
    else:
        pager = config.get("pager") and verbose
        display.print_output(rendered, pager=pager)

    return _exit_code(result_dict)


def _exit_code(result_dict: dict) -> int:
    status = result_dict.get("status", "failed")
    if status in ("success", "partial", "escalated"):
        return 0
    if status == "ethics_blocked":
        return 1
    return 2
