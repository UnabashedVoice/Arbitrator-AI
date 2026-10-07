"""
decision_brief.py — The decision brief every analysed run ends with.

A consequence map describes effects; it doesn't tell decision-makers what to
decide or how. Every run that reaches synthesis now gets a brief, written by
a model from the finished analysis, that gives the people deciding a way to
resolve it:

    - the judgment calls the decision turns on
    - where the analysis disagrees with itself
    - the strongest case for and against the proposal
    - what is uncertain, and what would resolve each uncertainty
    - the specific questions the decision-makers have to answer
    - at least three options, each with its consequences, who bears the cost,
      whether it can be reversed, and its own case for and against
    - a provisional lean among the options: which one, how confident, the full
      reasoning for choosing it, what would change it, and for every other
      option the reason it was set aside
    - the justification for the lean: why it is the right choice ethically and
      philosophically, not only the workable one, with the principles it rests
      on, the strongest objection to it, and a reply. The lean's reasoning is
      often prudential (risk, cost, reversibility); added 2026-10-03, after a
      trend-conflict smoke test whose brief gave no ethical case at all
    - the model's own view of whether this decision needs human sign-off

Escalation is decided separately and by rule (the Ethics Core's hard
constraints, the analysis gate's conditions, material channel requests; see
orchestrator.py). The brief cannot cancel an escalation or cause one: its
view on review is recorded beside the rule's verdict, so the two can be
compared. Until 2026-09-29 briefs were written for escalated runs only
(this module was escalation.py); the user decided every run should end with
one.

An invalid brief is retried once; if it still fails, the failure and the raw
output are recorded and the run continues. The options and the lean are what
an Annals case records as its options and recommended option, so a later
decision can be recorded as following the lean or departing from it.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..channels.backend import BackendError, split_reasoning

BRIEF_MAX_TOKENS = 6000          # a floor; with a known context the backend uses all that is free
BRIEF_TEMPERATURE = 0.2
FINDINGS_PER_CHANNEL = 6         # the brief sees each channel's most significant findings

SYSTEM_PROMPT = """CHANNEL: decision_brief
You write the decision brief for a proposal Arbitrator has just analysed. The analysis is
summarised below, with whether the run was escalated for human review and why.

The people deciding must be able to resolve the decision with your brief in hand. Give them:
- the judgment calls the decision turns on, in plain terms
- where the analysis disagrees with itself (between channels, or between scores and findings)
- the strongest case for the proposal and the strongest case against it
- what is uncertain, and for each uncertainty, what would resolve it
- the specific questions the decision-makers have to answer
- at least three real options (not only "approve" and "reject"; include modified or staged
  versions where they exist). For each: its likely consequences, who bears the cost, whether
  it can be reversed, and its own case for and against.
- your provisional lean among the options: which one, how confident you are, your full
  reasoning for choosing it over the others, and what would change your mind. Then, for
  every other option, the reason you set it aside. Give a lean even when the case is hard;
  that is the point.
- the justification for your lean: why it is the right choice ethically and philosophically,
  not merely the workable or least risky one. Name the principles it rests on, where each
  comes from (a philosophical source shown below, by its id, or your own knowledge, said as
  such) and how it applies here. Then give the strongest ethical objection to your lean and
  your reply to it. If the honest answer is that the lean is only prudentially justified,
  say so.
- whether you think this decision needs human sign-off, and why. If the run was escalated
  and you think it need not have been, say so; if it wasn't and you think it should have
  been, say so. Your view is recorded beside the rule's verdict and changes nothing by itself.

Explain your reasons in full sentences. Do not invent facts that are not in the analysis;
where you rely on your own knowledge, say so.

Respond ONLY with a JSON object in exactly this shape, with no text outside it:
{
  "why_human_judgment": "<the judgment calls this decision turns on>",
  "disagreements": [{"between": "<string>", "about": "<string>"}],
  "case_for": "<string>",
  "case_against": "<string>",
  "uncertainties": [{"what": "<string>", "would_resolve_it": "<string>"}],
  "decision_questions": ["<string>", "..."],
  "options": [
    {"id": "<short_snake_case>", "label": "<string>", "consequences": "<string>",
     "who_bears_cost": "<string>", "reversible": <true|false|null>,
     "case_for": "<string>", "case_against": "<string>"}
  ],
  "provisional_lean": {"option": "<an option id>", "confidence": <0.0-1.0>,
                       "reasoning": "<why this option over the others>", "would_change_if": "<string>"},
  "set_aside": [{"option": "<another option id>", "because": "<string>"}],
  "justification": {"argument": "<why the lean is right, not merely workable>",
                    "principles": [{"principle": "<string>", "source": "<a source id, or 'own knowledge'>",
                                    "how_it_applies": "<string>"}],
                    "strongest_objection": "<string>", "reply": "<string>"},
  "review": {"needed": <true|false>, "why": "<string>"}
}"""


def _render_case(raw_input: str, triggers: list[dict], result_dict: dict, compendium_text: str) -> str:
    """The finished analysis, condensed to fit a local model's context."""
    cmap = result_dict.get("consequence_map") or {}
    lines = ["PROPOSAL:", raw_input.strip(), ""]
    if triggers:
        lines.append("ESCALATED FOR HUMAN REVIEW, because:")
        lines += [f"- [{t['source']}] {t['detail']}" for t in triggers]
    else:
        lines.append("NOT ESCALATED: no escalation condition was met.")
    lines += ["", "ETHICS CORE:"]
    for label, ev in (("pre-screen (structural estimates, made before any model ran)",
                       result_dict.get("ethics_evaluation")),
                      ("post-screen (from the channels' analysis)", result_dict.get("post_screen_evaluation"))):
        if ev:
            lines.append(f"- {label}: {ev.get('verdict')}; harm {ev.get('weighted_harm')}, "
                         f"benefit {ev.get('weighted_benefit')}, net {ev.get('net_score')}. "
                         f"{(ev.get('justification') or '').strip()}")
    if cmap:
        lines += ["", f"SYNTHESIS: verdict {cmap.get('overall_verdict')}; aggregate harm "
                      f"{cmap.get('overall_harm_score')}, benefit {cmap.get('overall_benefit_score')}, "
                      f"confidence {cmap.get('synthesis_confidence')}."]
        for co in cmap.get("channel_outputs", []):
            lines += ["", f"CHANNEL {co.get('channel_name')} (harm {co.get('overall_harm_score')}, "
                          f"benefit {co.get('overall_benefit_score')}, confidence {co.get('confidence')}):",
                      (co.get("domain_summary") or "").strip()]
            findings = sorted(co.get("findings", []), key=lambda f: -f.get("magnitude", 0))
            for f in findings[:FINDINGS_PER_CHANNEL]:
                rev = {True: "reversible", False: "irreversible"}.get(f.get("reversible"), "reversibility unknown")
                lines.append(f"  [{f['finding_id']}] {f['direction']}, {f['certainty']} certainty, "
                             f"magnitude {f['magnitude']}, {f['timeframe']}, {rev}: {f['summary']}")
            if len(findings) > FINDINGS_PER_CHANNEL:
                lines.append(f"  ({len(findings) - FINDINGS_PER_CHANNEL} smaller findings omitted)")
        requests = result_dict.get("review_requests") or []
        if requests:
            lines += ["", "CHANNELS' OWN REQUESTS FOR HUMAN REVIEW:"]
            for r in requests:
                lines.append(f"- {r['channel']} ({'material' if r.get('material') else 'not material'}): "
                             f"{r.get('reason')} To decide: {r.get('what_to_decide')}")
        if cmap.get("adversarial_challenges"):
            lines += ["", "ADVERSARIAL CHALLENGES:"] + [f"- {c}" for c in cmap["adversarial_challenges"]]
        notes = cmap.get("uncertainty_register") or []
        if notes:
            lines += ["", "UNCERTAINTIES NOTED BY THE CHANNELS:"]
            for n in notes[:12]:
                lines.append(f"- {n.get('description', n) if isinstance(n, dict) else n}")
        if cmap.get("recommended_mitigations"):
            lines += ["", "MITIGATIONS SUGGESTED:"] + [f"- {m}" for m in cmap["recommended_mitigations"]]
    if compendium_text:
        lines += ["", compendium_text]
    lines += ["", "Write the decision brief now, as the JSON object specified."]
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[dict]:
    for m in reversed(list(re.finditer(r"\{", text))):
        try:
            obj = json.JSONDecoder().raw_decode(text[m.start():])[0]
        except ValueError:
            continue
        if isinstance(obj, dict) and "options" in obj:
            return obj
    return None


def _text(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def validate_brief(brief: dict) -> list[str]:
    """Problems with a brief; an empty list means it is usable."""
    errs = []
    for key in ("why_human_judgment", "case_for", "case_against"):
        if not _text(brief.get(key)):
            errs.append(f"'{key}' must be a non-empty string")
    qs = brief.get("decision_questions")
    if not isinstance(qs, list) or not [q for q in qs if _text(q)]:
        errs.append("'decision_questions' must list at least one question")
    opts = brief.get("options")
    ids = []
    if not isinstance(opts, list) or len(opts) < 3:
        errs.append("'options' must list at least three options")
    else:
        for i, o in enumerate(opts):
            if not isinstance(o, dict) or not _text(str(o.get("id", ""))) or not _text(o.get("label")):
                errs.append(f"options[{i}] needs an id and a label")
                continue
            ids.append(str(o["id"]).strip())
            for key in ("case_for", "case_against"):
                if not _text(o.get(key)):
                    errs.append(f"options[{i}] ('{o['id']}') needs its own '{key}'")
        if len(set(ids)) != len(ids):
            errs.append("option ids must be unique")
    lean = brief.get("provisional_lean")
    chosen = None
    if not isinstance(lean, dict):
        errs.append("'provisional_lean' is required")
    else:
        chosen = str(lean.get("option", "")).strip()
        if chosen not in ids:
            errs.append("'provisional_lean.option' must be one of the option ids")
        c = lean.get("confidence")
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0 <= c <= 1:
            errs.append("'provisional_lean.confidence' must be a number in [0, 1]")
        for key in ("reasoning", "would_change_if"):
            if not _text(lean.get(key)):
                errs.append(f"'provisional_lean.{key}' is required")
    aside = brief.get("set_aside")
    if not isinstance(aside, list):
        errs.append("'set_aside' must give the reason each other option was set aside")
    else:
        explained = {str(a.get("option", "")).strip() for a in aside if isinstance(a, dict) and _text(a.get("because"))}
        missing = [i for i in ids if i != chosen and i not in explained]
        if missing:
            errs.append("'set_aside' must explain every option not chosen; missing: " + ", ".join(missing))
    just = brief.get("justification")
    if not isinstance(just, dict):
        errs.append("'justification' is required: why the lean is right, not merely workable")
    else:
        for key in ("argument", "strongest_objection", "reply"):
            if not _text(just.get(key)):
                errs.append(f"'justification.{key}' is required")
        ps = just.get("principles")
        if not isinstance(ps, list) or not [p for p in ps if isinstance(p, dict) and _text(p.get("principle"))
                                             and _text(p.get("how_it_applies"))]:
            errs.append("'justification.principles' must name at least one principle and how it applies")
    review = brief.get("review")
    if not isinstance(review, dict) or not isinstance(review.get("needed"), bool) or not _text(review.get("why")):
        errs.append("'review' needs 'needed' (true or false) and 'why'")
    return errs


def write_brief(backend, raw_input: str, triggers: list[dict], result_dict: dict,
                compendium_text: str = "") -> dict:
    """
    Ask `backend` for a decision brief. Never raises. Returns
    {"brief", "error", "attempts": [{"raw", "reasoning", "problems", "finish_reason"}], "model_id"}.
    """
    user = _render_case(raw_input, triggers, result_dict, compendium_text)
    out = {"brief": None, "error": None, "attempts": [], "model_id": getattr(backend, "model_id", "unknown")}
    prompt = user
    for _ in range(2):
        try:
            answer = backend.complete(SYSTEM_PROMPT, prompt, max_tokens=BRIEF_MAX_TOKENS,
                                      temperature=BRIEF_TEMPERATURE)
        except BackendError as e:
            out["error"] = f"backend failed: {e}"
            return out
        raw = getattr(backend, "last_raw", None) or answer
        brief = _extract_json(answer)
        problems = ["no JSON object with 'options' in the answer"] if brief is None else validate_brief(brief)
        out["attempts"].append({"raw": raw, "reasoning": split_reasoning(raw)[0], "problems": problems,
                                "finish_reason": getattr(backend, "last_finish_reason", None)})
        if not problems:
            out["brief"] = brief
            return out
        prompt = (user + "\n\nYour previous brief could not be used: " + "; ".join(problems)
                  + ". Write it again as the JSON object specified, fixing these.")
    out["error"] = "brief invalid after 2 attempts: " + "; ".join(out["attempts"][-1]["problems"])
    return out
