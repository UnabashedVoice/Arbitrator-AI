"""
annals_link.py — Recording a recommendation in the Annals.

The Annals are a sibling project: an append-only record of what Arbitrator
recommended, what was decided, and what happened. Recording a run there
locks its findings as predictions *before* anyone knows how things turn
out, so the look-back years later has something specific to check.

Annals is found at $ARBITRATOR_ANNALS, or as a sibling folder (the
workspace layout: Claude/Arbitrator/Arbitrator-imported and Claude/Annals).
Nothing here is required to run Arbitrator; without --annals it isn't used.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent.parent


def _annals_root() -> Path:
    env = os.environ.get("ARBITRATOR_ANNALS")
    candidates = [Path(env)] if env else [_REPO.parent / "Annals", _REPO.parent.parent / "Annals"]
    for c in candidates:
        if (c / "annals" / "record.py").exists():
            return c
    raise RuntimeError("Annals not found: set ARBITRATOR_ANNALS to the Annals checkout")


def record_in_annals(result_dict: dict, arbitrator_version: str, people_file: Optional[str] = None,
                     question: Optional[str] = None, record_path: Optional[str] = None) -> dict:
    """Open an Annals case for this run. Returns the appended entry; raises on refusal."""
    root = _annals_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from annals import Annals
    from annals.cli import DEFAULT_RECORD
    from annals.intake import case_from_arbitrator
    from annals.provenance import git_version

    people = json.loads(Path(people_file).read_text(encoding="utf-8")) if people_file else {}
    body = case_from_arbitrator(
        result_dict, arbitrator_version=arbitrator_version, code_version=git_version(_REPO),
        question=question, decision_makers=people.get("decision_makers"), affected=people.get("affected"),
    )
    annals = Annals(record_path or os.environ.get("ANNALS_RECORD") or DEFAULT_RECORD)
    return annals.append("case_opened", body, body["recommender"])
