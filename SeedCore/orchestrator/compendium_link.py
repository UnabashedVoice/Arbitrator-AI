"""
compendium_link.py — Consulting the Compendium during a run.

The Compendium is a sibling project: a philosophy corpus that extends the
tradition's "person" and "society" to artificial agents and digital
ecosystems, by grounding rather than substitution. It is found at
$COMPENDIUM_ROOT, or as a folder named Compendium beside this checkout or
any of its parents (the workspace layout: Claude/Arbitrator/Arbitrator and
Claude/Compendium).

A consultation is one model call: the model reads the Compendium's index
and names the entries (at most three, possibly none) that the proposal's
concepts turn on. The Compendium's own text for those entries, each with
its strongest counter-position, is shown to the channels that declare
uses_compendium (the ethical adversary). No model paraphrase of the corpus
reaches a channel. Nothing here is needed to run Arbitrator; without
--compendium it isn't used, and a failed consultation leaves the run as it
would have been, with the failure recorded.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()


def load_compendium():
    """Import the Compendium's access module and load the built corpus."""
    import os
    env = os.environ.get("COMPENDIUM_ROOT")
    candidates = [Path(env)] if env else [p / "Compendium" for p in _HERE.parents]
    for c in candidates:
        if (c / "compendium_access.py").exists():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            import compendium_access
            return compendium_access.Compendium(c / "dist" / "compendium.jsonl")
    raise FileNotFoundError("Compendium not found: set COMPENDIUM_ROOT to the Compendium folder")


def consult(proposal: str, backend, max_entries: int = 3, budget_chars: int = 6000) -> tuple[dict, str]:
    """
    Run one consultation with `backend`. Returns (record, disclosed text).

    The record carries the Compendium version, the entries chosen and why,
    ids the model named that don't exist, the raw selection output, and
    `identity`: the line the Annals write as the recommender's
    compendium_version. Never raises.
    """
    try:
        comp = load_compendium()
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        return {"version": "unavailable", "error": err,
                "identity": f"not consulted (Compendium unavailable: {err})"}, ""

    def complete(system: str, user: str) -> str:
        # Room for a reasoning model's thinking before the short JSON answer.
        return backend.complete(system, user, max_tokens=3000, temperature=0.2)

    c = comp.consult(proposal, complete, max_entries=max_entries, budget_chars=budget_chars)
    record = c.to_dict()
    record["identity"] = c.identity()
    record["model_id"] = getattr(backend, "model_id", "unknown")
    record["stale_build"] = comp.stale
    return record, c.text
