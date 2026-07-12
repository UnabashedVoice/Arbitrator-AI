"""
lexicons.py — Domain signal lexicons for the Arbitrator Context Parser.

Each channel has a lexicon: a structured set of keywords, phrases, and
patterns that indicate relevance to that channel's domain of analysis.
Signals are grouped by weight tier:
    - STRONG   (weight 1.0): unambiguous domain indicators
    - MODERATE (weight 0.6): likely but not certain domain indicators
    - WEAK     (weight 0.3): contextual hints that may indicate relevance

The parser scores a text against each lexicon by summing matched signal
weights (normalized) to produce a relevance_score in [0.0, 1.0].

Design principles:
    - All signals are lowercase strings (matching is done on normalized text)
    - Multi-word phrases are checked as substrings
    - No external NLP dependencies — pure Python string matching
    - Lexicons are explicitly curated, not learned — making them auditable
      and correctable by human contributors
    - Adding, removing, or reweighting signals is a documented change
      tracked in version control

This file is intentionally verbose. Every signal is a deliberate choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from .models import Channel


# ---------------------------------------------------------------------------
# Signal weight tiers
# ---------------------------------------------------------------------------

STRONG = 1.0
MODERATE = 0.6
WEAK = 0.3


class Signal(NamedTuple):
    """A single lexical signal with its weight tier."""
    phrase: str
    weight: float


# ---------------------------------------------------------------------------
# Channel lexicons
# ---------------------------------------------------------------------------

CHANNEL_LEXICONS: dict[Channel, list[Signal]] = {

    Channel.ECONOMIC: [
        # Strong indicators
        Signal("universal basic income", STRONG),
        Signal("ubi", STRONG),
        Signal("basic income", STRONG),
        Signal("income support", STRONG),
        Signal("gdp", STRONG),
        Signal("economic growth", STRONG),
        Signal("tax", STRONG),
        Signal("taxation", STRONG),
        Signal("fiscal", STRONG),
        Signal("budget", STRONG),
        Signal("deficit", STRONG),
        Signal("debt", STRONG),
        Signal("inflation", STRONG),
        Signal("interest rate", STRONG),
        Signal("unemployment", STRONG),
        Signal("employment", STRONG),
        Signal("labor market", STRONG),
        Signal("trade", STRONG),
        Signal("tariff", STRONG),
        Signal("subsidy", STRONG),
        Signal("subsidies", STRONG),
        Signal("minimum wage", STRONG),
        Signal("income inequality", STRONG),
        Signal("poverty", STRONG),
        Signal("wealth gap", STRONG),
        Signal("privatization", STRONG),
        Signal("nationalization", STRONG),
        Signal("market", STRONG),
        Signal("investment", STRONG),
        Signal("spending", STRONG),
        Signal("cost", STRONG),
        Signal("price", STRONG),
        Signal("revenue", STRONG),
        Signal("economic impact", STRONG),
        Signal("financial", STRONG),
        Signal("bank", STRONG),
        Signal("currency", STRONG),
        Signal("trade deficit", STRONG),
        Signal("supply chain", STRONG),
        Signal("export", STRONG),
        Signal("import", STRONG),
        # Moderate indicators
        Signal("pension", MODERATE),
        Signal("welfare", MODERATE),
        Signal("benefit", MODERATE),
        Signal("grant", MODERATE),
        Signal("loan", MODERATE),
        Signal("fund", MODERATE),
        Signal("insurance", MODERATE),
        Signal("housing", MODERATE),
        Signal("property", MODERATE),
        Signal("rent", MODERATE),
        Signal("infrastructure spending", MODERATE),
        Signal("public sector", MODERATE),
        Signal("private sector", MODERATE),
        # Weak indicators
        Signal("growth", WEAK),
        Signal("development", WEAK),
        Signal("industry", WEAK),
        Signal("sector", WEAK),
        Signal("worker", WEAK),
        Signal("job", WEAK),
    ],

    Channel.ECOLOGICAL: [
        # Strong indicators
        Signal("climate", STRONG),
        Signal("climate change", STRONG),
        Signal("global warming", STRONG),
        Signal("carbon", STRONG),
        Signal("emissions", STRONG),
        Signal("greenhouse gas", STRONG),
        Signal("deforestation", STRONG),
        Signal("biodiversity", STRONG),
        Signal("species", STRONG),
        Signal("extinction", STRONG),
        Signal("ecosystem", STRONG),
        Signal("habitat", STRONG),
        Signal("pollution", STRONG),
        Signal("environmental", STRONG),
        Signal("renewable energy", STRONG),
        Signal("fossil fuel", STRONG),
        Signal("oil", STRONG),
        Signal("coal", STRONG),
        Signal("natural gas", STRONG),
        Signal("deforestation", STRONG),
        Signal("reforestation", STRONG),
        Signal("ocean", STRONG),
        Signal("water", STRONG),
        Signal("watershed", STRONG),
        Signal("soil", STRONG),
        Signal("land use", STRONG),
        Signal("agriculture", STRONG),
        Signal("pesticide", STRONG),
        Signal("toxic", STRONG),
        Signal("waste", STRONG),
        Signal("recycling", STRONG),
        Signal("sustainability", STRONG),
        Signal("sustainable", STRONG),
        Signal("nature", STRONG),
        Signal("wildlife", STRONG),
        Signal("forest", STRONG),
        Signal("rainforest", STRONG),
        Signal("wetland", STRONG),
        Signal("coral reef", STRONG),
        Signal("air quality", STRONG),
        Signal("water quality", STRONG),
        # Moderate indicators
        Signal("mining", MODERATE),
        Signal("drilling", MODERATE),
        Signal("pipeline", MODERATE),
        Signal("nuclear", MODERATE),
        Signal("solar", MODERATE),
        Signal("wind energy", MODERATE),
        Signal("hydropower", MODERATE),
        Signal("conservation", MODERATE),
        Signal("park", MODERATE),
        Signal("protected area", MODERATE),
        Signal("fishing", MODERATE),
        Signal("farming", MODERATE),
        Signal("food production", MODERATE),
        # Weak indicators
        Signal("land", WEAK),
        Signal("resource", WEAK),
        Signal("energy", WEAK),
        Signal("natural", WEAK),
        Signal("green", WEAK),
    ],

    Channel.SOCIAL_DEMOGRAPHIC: [
        # Strong indicators
        Signal("race", STRONG),
        Signal("racial", STRONG),
        Signal("ethnicity", STRONG),
        Signal("gender", STRONG),
        Signal("sex", STRONG),
        Signal("sexual orientation", STRONG),
        Signal("lgbtq", STRONG),
        Signal("disability", STRONG),
        Signal("mental health", STRONG),
        Signal("public health", STRONG),
        Signal("healthcare", STRONG),
        Signal("health care", STRONG),
        Signal("education", STRONG),
        Signal("school", STRONG),
        Signal("children", STRONG),
        Signal("child", STRONG),
        Signal("elderly", STRONG),
        Signal("aging", STRONG),
        Signal("population", STRONG),
        Signal("demographic", STRONG),
        Signal("migration", STRONG),
        Signal("immigration", STRONG),
        Signal("refugee", STRONG),
        Signal("displacement", STRONG),
        Signal("inequality", STRONG),
        Signal("discrimination", STRONG),
        Signal("marginalized", STRONG),
        Signal("community", STRONG),
        Signal("social welfare", STRONG),
        Signal("housing", STRONG),
        Signal("homelessness", STRONG),
        Signal("food security", STRONG),
        Signal("nutrition", STRONG),
        Signal("drug", STRONG),
        Signal("addiction", STRONG),
        Signal("crime", STRONG),
        Signal("incarceration", STRONG),
        Signal("prison", STRONG),
        Signal("police", STRONG),
        Signal("policing", STRONG),
        Signal("civil rights", STRONG),
        Signal("human rights", STRONG),
        Signal("voting", STRONG),
        Signal("democracy", STRONG),
        Signal("religion", STRONG),
        Signal("indigenous", STRONG),
        Signal("tribal", STRONG),
        # Moderate indicators
        Signal("family", MODERATE),
        Signal("parent", MODERATE),
        Signal("youth", MODERATE),
        Signal("teenager", MODERATE),
        Signal("veteran", MODERATE),
        Signal("worker", MODERATE),
        Signal("rural", MODERATE),
        Signal("urban", MODERATE),
        Signal("rural community", MODERATE),
        Signal("social program", MODERATE),
        Signal("welfare program", MODERATE),
        Signal("access", MODERATE),
        Signal("equity", MODERATE),
        Signal("inclusion", MODERATE),
        Signal("social consequence", STRONG),
        Signal("social impact", STRONG),
        # Weak indicators
        Signal("people", WEAK),
        Signal("citizen", WEAK),
        Signal("resident", WEAK),
        Signal("public", WEAK),
        Signal("society", WEAK),
    ],

    Channel.HISTORICAL_PRECEDENT: [
        # Strong indicators
        Signal("precedent", STRONG),
        Signal("history", STRONG),
        Signal("historical", STRONG),
        Signal("before", STRONG),
        Signal("previously", STRONG),
        Signal("in the past", STRONG),
        Signal("has been tried", STRONG),
        Signal("tried before", STRONG),
        Signal("last time", STRONG),
        Signal("similar policy", STRONG),
        Signal("similar program", STRONG),
        Signal("new deal", STRONG),
        Signal("great depression", STRONG),
        Signal("cold war", STRONG),
        Signal("world war", STRONG),
        Signal("revolution", STRONG),
        Signal("reform", STRONG),
        Signal("lesson", STRONG),
        Signal("experience", STRONG),
        Signal("evidence", STRONG),
        Signal("study", STRONG),
        Signal("research shows", STRONG),
        Signal("data shows", STRONG),
        Signal("proven", STRONG),
        Signal("failed before", STRONG),
        Signal("worked before", STRONG),
        # Moderate indicators
        Signal("decade", MODERATE),
        Signal("century", MODERATE),
        Signal("era", MODERATE),
        Signal("period", MODERATE),
        Signal("war", MODERATE),
        Signal("conflict", MODERATE),
        Signal("crisis", MODERATE),
        Signal("recession", MODERATE),
        Signal("pandemic", MODERATE),
        Signal("case study", MODERATE),
        Signal("example", MODERATE),
        Signal("model", MODERATE),
        # Weak indicators
        Signal("old", WEAK),
        Signal("traditional", WEAK),
        Signal("legacy", WEAK),
        Signal("established", WEAK),
    ],

    Channel.LEGAL_INSTITUTIONAL: [
        # Strong indicators
        Signal("law", STRONG),
        Signal("legislation", STRONG),
        Signal("statute", STRONG),
        Signal("regulation", STRONG),
        Signal("regulatory", STRONG),
        Signal("constitutional", STRONG),
        Signal("constitution", STRONG),
        Signal("court", STRONG),
        Signal("judicial", STRONG),
        Signal("legal", STRONG),
        Signal("illegal", STRONG),
        Signal("rights", STRONG),
        Signal("enforcement", STRONG),
        Signal("compliance", STRONG),
        Signal("mandate", STRONG),
        Signal("ban", STRONG),
        Signal("prohibition", STRONG),
        Signal("permit", STRONG),
        Signal("license", STRONG),
        Signal("liability", STRONG),
        Signal("penalty", STRONG),
        Signal("sanction", STRONG),
        Signal("treaty", STRONG),
        Signal("international law", STRONG),
        Signal("jurisdiction", STRONG),
        Signal("federal", STRONG),
        Signal("state law", STRONG),
        Signal("amendment", STRONG),
        Signal("executive order", STRONG),
        Signal("veto", STRONG),
        Signal("repeal", STRONG),
        Signal("reform", STRONG),
        Signal("institution", STRONG),
        Signal("agency", STRONG),
        Signal("authority", STRONG),
        # Moderate indicators
        Signal("rule", MODERATE),
        Signal("policy", MODERATE),
        Signal("governance", MODERATE),
        Signal("oversight", MODERATE),
        Signal("audit", MODERATE),
        Signal("accountability", MODERATE),
        Signal("transparency", MODERATE),
        Signal("government", MODERATE),
        Signal("parliament", MODERATE),
        Signal("congress", MODERATE),
        Signal("senate", MODERATE),
        Signal("legislature", MODERATE),
        # Weak indicators
        Signal("official", WEAK),
        Signal("public", WEAK),
        Signal("standard", WEAK),
        Signal("requirement", WEAK),
    ],

    Channel.GEOPOLITICAL: [
        # Strong indicators
        Signal("foreign policy", STRONG),
        Signal("international", STRONG),
        Signal("geopolitical", STRONG),
        Signal("nation", STRONG),
        Signal("country", STRONG),
        Signal("state", STRONG),
        Signal("government", STRONG),
        Signal("war", STRONG),
        Signal("military", STRONG),
        Signal("defense", STRONG),
        Signal("nato", STRONG),
        Signal("un ", STRONG),
        Signal("united nations", STRONG),
        Signal("alliance", STRONG),
        Signal("sanction", STRONG),
        Signal("diplomacy", STRONG),
        Signal("diplomatic", STRONG),
        Signal("ambassador", STRONG),
        Signal("treaty", STRONG),
        Signal("trade agreement", STRONG),
        Signal("border", STRONG),
        Signal("territory", STRONG),
        Signal("sovereignty", STRONG),
        Signal("occupation", STRONG),
        Signal("conflict", STRONG),
        Signal("war crime", STRONG),
        Signal("nuclear", STRONG),
        Signal("weapon", STRONG),
        Signal("arms", STRONG),
        Signal("intelligence", STRONG),
        Signal("espionage", STRONG),
        Signal("china", STRONG),
        Signal("russia", STRONG),
        Signal("united states", STRONG),
        Signal("europe", STRONG),
        Signal("middle east", STRONG),
        Signal("africa", STRONG),
        Signal("asia", STRONG),
        # Moderate indicators
        Signal("election", MODERATE),
        Signal("regime", MODERATE),
        Signal("power", MODERATE),
        Signal("influence", MODERATE),
        Signal("ally", MODERATE),
        Signal("adversary", MODERATE),
        Signal("competitor", MODERATE),
        Signal("immigration", MODERATE),
        Signal("refugee", MODERATE),
        Signal("aid", MODERATE),
        Signal("humanitarian", MODERATE),
        # Weak indicators
        Signal("global", WEAK),
        Signal("world", WEAK),
        Signal("regional", WEAK),
        Signal("cross-border", WEAK),
    ],

    Channel.ETHICAL_ADVERSARIAL: [
        # This channel is invoked for almost everything with meaningful harm/stakes.
        # Its signals are broad — the channel exists to challenge, not confirm.
        # Strong indicators — explicit ethical framing
        Signal("ethical", STRONG),
        Signal("moral", STRONG),
        Signal("right", STRONG),
        Signal("wrong", STRONG),
        Signal("justice", STRONG),
        Signal("injustice", STRONG),
        Signal("fair", STRONG),
        Signal("unfair", STRONG),
        Signal("harm", STRONG),
        Signal("benefit", STRONG),
        Signal("rights", STRONG),
        Signal("dignity", STRONG),
        Signal("consent", STRONG),
        Signal("autonomy", STRONG),
        Signal("freedom", STRONG),
        Signal("liberty", STRONG),
        Signal("oppression", STRONG),
        Signal("exploitation", STRONG),
        Signal("sacrifice", STRONG),
        Signal("trade-off", STRONG),
        Signal("tradeoff", STRONG),
        Signal("value", STRONG),
        Signal("principle", STRONG),
        Signal("should", STRONG),
        Signal("must", STRONG),
        Signal("ought", STRONG),
        Signal("obligation", STRONG),
        Signal("duty", STRONG),
        Signal("responsibility", STRONG),
        # Moderate indicators — high-stakes contexts
        Signal("force", MODERATE),
        Signal("power", MODERATE),
        Signal("control", MODERATE),
        Signal("surveillance", MODERATE),
        Signal("privacy", MODERATE),
        Signal("vulnerable", MODERATE),
        Signal("protect", MODERATE),
        Signal("risk", MODERATE),
        Signal("danger", MODERATE),
        Signal("safety", MODERATE),
        Signal("security", MODERATE),
        Signal("life", MODERATE),
        Signal("death", MODERATE),
        Signal("kill", MODERATE),
        Signal("war", MODERATE),
        Signal("violence", MODERATE),
        Signal("torture", MODERATE),
        # Weak indicators — ethical consideration implied
        Signal("people", WEAK),
        Signal("community", WEAK),
        Signal("society", WEAK),
        Signal("future", WEAK),
        Signal("generation", WEAK),
        Signal("impact", WEAK),
    ],

    Channel.UNCERTAINTY_MODELING: [
        # This channel is invoked whenever estimates are contested or unknowns are large.
        # Strong indicators
        Signal("uncertain", STRONG),
        Signal("uncertainty", STRONG),
        Signal("unknown", STRONG),
        Signal("estimate", STRONG),
        Signal("projection", STRONG),
        Signal("model", STRONG),
        Signal("forecast", STRONG),
        Signal("predict", STRONG),
        Signal("scenario", STRONG),
        Signal("probability", STRONG),
        Signal("risk", STRONG),
        Signal("likelihood", STRONG),
        Signal("assumption", STRONG),
        Signal("if", STRONG),
        Signal("could", STRONG),
        Signal("might", STRONG),
        Signal("may", STRONG),
        Signal("possibly", STRONG),
        Signal("perhaps", STRONG),
        Signal("unclear", STRONG),
        Signal("debate", STRONG),
        Signal("contested", STRONG),
        Signal("controversial", STRONG),
        Signal("unintended consequence", STRONG),
        Signal("side effect", STRONG),
        Signal("second-order", STRONG),
        Signal("spillover", STRONG),
        # Moderate indicators
        Signal("complex", MODERATE),
        Signal("complicated", MODERATE),
        Signal("difficult to predict", MODERATE),
        Signal("hard to say", MODERATE),
        Signal("depends on", MODERATE),
        Signal("variable", MODERATE),
        Signal("confidence", MODERATE),
        Signal("margin", MODERATE),
        Signal("range", MODERATE),
        Signal("best case", MODERATE),
        Signal("worst case", MODERATE),
        # Weak indicators
        Signal("new", WEAK),
        Signal("novel", WEAK),
        Signal("first time", WEAK),
        Signal("unprecedented", WEAK),
    ],
}


# ---------------------------------------------------------------------------
# Baseline invocation rules
# ---------------------------------------------------------------------------

# Some channels have a minimum baseline relevance score — they are always
# considered even if the lexicon score is low, because their value is
# in challenging assumptions rather than confirming domain relevance.
#
# ETHICAL_ADVERSARIAL and UNCERTAINTY_MODELING are almost always worth
# invoking unless the query is truly trivial.

CHANNEL_BASELINE_SCORES: dict[Channel, float] = {
    Channel.ECONOMIC: 0.0,
    Channel.ECOLOGICAL: 0.0,
    Channel.SOCIAL_DEMOGRAPHIC: 0.0,
    Channel.HISTORICAL_PRECEDENT: 0.0,
    Channel.LEGAL_INSTITUTIONAL: 0.0,
    Channel.GEOPOLITICAL: 0.0,
    Channel.ETHICAL_ADVERSARIAL: 0.35,     # Nearly always worth invoking — challenge is its purpose
    Channel.UNCERTAINTY_MODELING: 0.30,    # Nearly always worth invoking — unknown unknowns matter
}

# Minimum relevance score required to invoke a channel.
# Channels scoring below this are skipped (with rationale logged).
INVOCATION_THRESHOLD: float = 0.15
