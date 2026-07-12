"""
extractors.py — Metadata extraction functions for the Arbitrator Context Parser.

These functions analyze normalized text to extract structured metadata:
scale, time horizon, affected populations, key entities, urgency signals,
controversy signals, explicit assumptions, and implicit flags.

All extraction is rule-based and pattern-matching — no external NLP libraries.
Every rule is explicit and auditable.
"""

from __future__ import annotations

import re

from .models import InputScale, InputType, TimeHorizon


# ---------------------------------------------------------------------------
# Scale extraction
# ---------------------------------------------------------------------------

_SCALE_SIGNALS: list[tuple[InputScale, list[str]]] = [
    (InputScale.GLOBAL, [
        "global", "worldwide", "planet", "planetary", "earth", "all nations",
        "international community", "world", "civilizat", "humanity",
        "united nations", "every country",
    ]),
    (InputScale.INTERNATIONAL, [
        "international", "multinational", "cross-border", "bilateral", "multilateral",
        "foreign", "treaty", "alliance", "nato", "trade agreement", "diplomatic",
        "between countries", "between nations",
    ]),
    (InputScale.NATIONAL, [
        "national", "federal", "country", "nation", "nationwide", "countrywide",
        "congress", "parliament", "senate", "president", "prime minister",
        "throughout the country", "across the nation",
    ]),
    (InputScale.REGIONAL, [
        "state", "province", "region", "regional", "county", "territory",
        "district", "zone", "area",
    ]),
    (InputScale.LOCAL, [
        "city", "town", "municipal", "local", "neighborhood", "community",
        "borough", "village", "ward", "council",
    ]),
]


def extract_scale(text: str) -> InputScale:
    """
    Determine the primary geographic/institutional scale of the input.
    Returns the most specific (broadest) scale detected.
    Scale priority: GLOBAL > INTERNATIONAL > NATIONAL > REGIONAL > LOCAL
    """
    for scale, signals in _SCALE_SIGNALS:
        for signal in signals:
            if signal in text:
                return scale
    return InputScale.NATIONAL   # Default: assume national if unclear


# ---------------------------------------------------------------------------
# Time horizon extraction
# ---------------------------------------------------------------------------

_HORIZON_SIGNALS: list[tuple[TimeHorizon, list[str]]] = [
    (TimeHorizon.GENERATIONAL, [
        "generation", "future generation", "intergenerational", "century",
        "centuries", "long-term", "long term", "50 year", "100 year",
        "our children", "grandchildren", "legacy",
    ]),
    (TimeHorizon.LONG_TERM, [
        "decade", "decades", "10 year", "20 year", "30 year", "long-term",
        "long term", "sustained", "permanent", "lasting",
    ]),
    (TimeHorizon.MEDIUM_TERM, [
        "year", "years", "annual", "5 year", "3 year", "medium term",
        "medium-term", "several years", "coming years",
    ]),
    (TimeHorizon.SHORT_TERM, [
        "month", "months", "quarter", "next year", "short-term", "short term",
        "near-term", "near term",
    ]),
    (TimeHorizon.IMMEDIATE, [
        "immediately", "immediate", "now", "today", "this week", "emergency",
        "urgent", "crisis", "right away", "at once",
    ]),
]


def extract_time_horizon(text: str) -> TimeHorizon:
    """
    Determine the primary time horizon implied by the input.
    Returns the longest horizon detected (most conservative for analysis depth).
    """
    for horizon, signals in _HORIZON_SIGNALS:
        for signal in signals:
            if signal in text:
                return horizon
    return TimeHorizon.UNKNOWN


# ---------------------------------------------------------------------------
# Input type classification
# ---------------------------------------------------------------------------

_INPUT_TYPE_SIGNALS: list[tuple[InputType, list[str]]] = [
    # HYPOTHETICAL must be first — "what if" framing overrides domain classification
    (InputType.HYPOTHETICAL, [
        "what if", "what would happen if", "suppose", "imagine",
        "hypothetically", "scenario:", "consider a world where",
        "let's say", "if we were to",
    ]),
    (InputType.MILITARY_ACTION, [
        "military", "troops", "deploy", "strike", "bomb", "war", "invasion",
        "armed force", "drone", "missile", "combat",
    ]),
    (InputType.TREATY_OR_AGREEMENT, [
        "treaty", "agreement", "accord", "pact", "convention", "protocol",
        "ratif", "sign", "negotiate",
    ]),
    (InputType.LEGISLATIVE_PROPOSAL, [
        "bill", "legislation", "act", "law", "statute", "amendment",
        "repeal", "enact", "pass a", "introduce a",
    ]),
    (InputType.EXECUTIVE_ACTION, [
        "executive order", "presidential directive", "prime minister order",
        "proclamation", "decree",
    ]),
    (InputType.INFRASTRUCTURE_PROJECT, [
        "build", "construct", "infrastructure", "pipeline", "road", "bridge",
        "dam", "power plant", "grid", "network", "facility",
    ]),
    (InputType.ENVIRONMENTAL_ACTION, [
        "protect the environment", "conservation", "ban plastic", "carbon tax",
        "emissions limit", "clean energy", "reforestation", "rewilding",
        "environmental regulation",
    ]),
    (InputType.ECONOMIC_INTERVENTION, [
        "tax cut", "tax increase", "stimulus", "bailout", "interest rate",
        "monetary policy", "fiscal policy", "austerity", "spending cut",
        "universal basic income",
    ]),
    (InputType.SOCIAL_PROGRAM, [
        "social program", "welfare", "universal healthcare", "free education",
        "public housing", "food assistance", "child benefit", "pension reform",
    ]),
    (InputType.REGULATORY_CHANGE, [
        "regulate", "deregulate", "remove regulation", "new regulation",
        "oversight", "compliance", "standard", "rule change",
    ]),
    (InputType.POLICY_PROPOSAL, [
        "policy", "propose", "proposal", "plan", "program", "initiative",
        "implement", "introduce", "reform",
    ]),
]


def extract_input_type(text: str) -> InputType:
    """Classify the type of action being proposed."""
    for input_type, signals in _INPUT_TYPE_SIGNALS:
        for signal in signals:
            if signal in text:
                return input_type
    return InputType.GENERAL_QUERY


# ---------------------------------------------------------------------------
# Affected populations
# ---------------------------------------------------------------------------

_POPULATION_SIGNALS: list[tuple[str, list[str]]] = [
    ("children and youth", ["child", "children", "youth", "student", "minor", "teenager", "school"]),
    ("elderly", ["elderly", "senior", "aging", "retirement", "pensioner", "older adult"]),
    ("low-income populations", ["low income", "poverty", "poor", "disadvantaged", "destitute", "homeless"]),
    ("workers and labor", ["worker", "employee", "labor", "union", "workforce", "gig worker"]),
    ("women", ["women", "woman", "female", "maternal", "mother"]),
    ("racial and ethnic minorities", ["racial minority", "ethnic minority", "people of color", "black", "hispanic", "latino", "asian", "indigenous", "native"]),
    ("LGBTQ+ communities", ["lgbtq", "gay", "lesbian", "transgender", "queer", "bisexual", "nonbinary"]),
    ("people with disabilities", ["disability", "disabled", "handicap", "accessibility"]),
    ("immigrants and refugees", ["immigrant", "refugee", "asylum", "migrant", "undocumented"]),
    ("rural communities", ["rural", "countryside", "farming community", "small town"]),
    ("urban populations", ["urban", "city dweller", "metropolitan"]),
    ("veterans", ["veteran", "former soldier", "military service"]),
    ("indigenous peoples", ["indigenous", "tribal", "native", "first nation", "aboriginal"]),
    ("future generations", ["future generation", "our children", "grandchildren", "unborn"]),
    ("small businesses", ["small business", "entrepreneur", "startup", "self-employed"]),
    ("large corporations", ["corporation", "big business", "multinational", "conglomerate"]),
    ("farmers and agricultural workers", ["farmer", "agricultural worker", "rancher", "farmworker"]),
    ("animals and wildlife", ["animal", "wildlife", "species", "ecosystem", "fauna"]),
]


def extract_affected_populations(text: str) -> list[str]:
    """Extract a list of population groups mentioned or implied in the text."""
    found = []
    for label, signals in _POPULATION_SIGNALS:
        for signal in signals:
            if signal in text:
                found.append(label)
                break
    return found


# ---------------------------------------------------------------------------
# Key entity extraction (lightweight named entity recognition)
# ---------------------------------------------------------------------------

# Patterns for detecting likely named entities
# We keep this simple: capitalized multi-word sequences likely to be names/orgs/places
_ENTITY_PATTERN = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b')
_ACRONYM_PATTERN = re.compile(r'\b[A-Z]{2,6}\b')

# Known entities to always check for (case-insensitive)
_KNOWN_ENTITIES: list[str] = [
    "United States", "European Union", "United Nations", "World Bank",
    "IMF", "WHO", "NATO", "WTO", "IPCC", "EPA", "FDA",
    "China", "Russia", "India", "Brazil", "Germany", "France",
    "United Kingdom", "Canada", "Australia", "Japan",
    "Amazon", "Microsoft", "Google", "Meta", "Apple",
    "Wall Street", "Federal Reserve", "Congress", "Senate",
    "Supreme Court", "White House", "Pentagon",
]


def extract_key_entities(raw_text: str) -> list[str]:
    """
    Extract likely named entities from the original (non-normalized) text.
    Returns a deduplicated list.
    """
    found = set()

    # Check known entities
    for entity in _KNOWN_ENTITIES:
        if entity.lower() in raw_text.lower():
            found.add(entity)

    # Pattern match capitalized sequences (likely proper nouns)
    for match in _ENTITY_PATTERN.finditer(raw_text):
        candidate = match.group()
        # Exclude common false positives
        if candidate not in {"The Policy", "This Plan", "Our Goal"}:
            found.add(candidate)

    # Acronyms
    for match in _ACRONYM_PATTERN.finditer(raw_text):
        candidate = match.group()
        if len(candidate) >= 2:
            found.add(candidate)

    return sorted(found)


# ---------------------------------------------------------------------------
# Urgency and controversy detection
# ---------------------------------------------------------------------------

_URGENCY_SIGNALS = [
    "emergency", "urgent", "crisis", "immediate", "now", "right away",
    "must act", "time-sensitive", "no time", "imminent", "critical",
    "before it's too late", "running out of time", "deadline",
]

_CONTROVERSY_SIGNALS = [
    "controversial", "debate", "contested", "divided", "polarizing",
    "political", "partisan", "oppose", "protest", "resistance",
    "unpopular", "radical", "extreme", "far right", "far left",
    "both sides", "disagreement", "conflict", "backlash",
]


def detect_urgency(text: str) -> bool:
    """Return True if urgency language is detected."""
    return any(signal in text for signal in _URGENCY_SIGNALS)


def detect_controversy(text: str) -> bool:
    """Return True if political controversy signals are detected."""
    return any(signal in text for signal in _CONTROVERSY_SIGNALS)


# ---------------------------------------------------------------------------
# Explicit assumption detection
# ---------------------------------------------------------------------------

_ASSUMPTION_PATTERNS = [
    re.compile(r'\bassumption[s]?\b[^.]*\.', re.IGNORECASE),
    re.compile(r'\bwe assume\b[^.]*\.', re.IGNORECASE),
    re.compile(r'\bassuming that\b[^.]*\.', re.IGNORECASE),
    re.compile(r'\bgiven that\b[^.]*\.', re.IGNORECASE),
    re.compile(r'\bif we assume\b[^.]*\.', re.IGNORECASE),
    re.compile(r'\bprovided that\b[^.]*\.', re.IGNORECASE),
    re.compile(r'\bunder the assumption\b[^.]*\.', re.IGNORECASE),
]


def extract_explicit_assumptions(raw_text: str) -> list[str]:
    """Extract sentences that explicitly state assumptions."""
    found = []
    for pattern in _ASSUMPTION_PATTERNS:
        for match in pattern.finditer(raw_text):
            candidate = match.group().strip()
            if candidate not in found:
                found.append(candidate)
    return found


# ---------------------------------------------------------------------------
# Implicit flag detection
# ---------------------------------------------------------------------------

_IMPLICIT_FLAG_RULES: list[tuple[str, list[str]]] = [
    (
        "Proposal may disproportionately affect vulnerable populations without "
        "explicitly addressing equity.",
        ["cut", "reduce", "eliminate", "remove", "defund", "privatize"],
    ),
    (
        "Action appears to concentrate power or resources in a single entity.",
        ["monopoly", "nationalize", "consolidate", "centralize", "sole control", "single authority"],
    ),
    (
        "Proposal involves surveillance or restriction of civil liberties.",
        ["monitor", "track", "surveil", "restrict movement", "curfew", "ban assembly",
         "limit speech", "censor", "data collection", "facial recognition"],
    ),
    (
        "Action may have irreversible ecological consequences not explicitly addressed.",
        ["clear", "drain", "fill", "pave", "mine", "drill", "dam", "reroute"],
    ),
    (
        "Proposal involves use of force or coercion not explicitly justified.",
        ["force", "compel", "coerce", "mandatory", "required by law", "punish",
         "arrest", "detain", "remove"],
    ),
    (
        "Economic benefits appear concentrated while costs are broadly distributed.",
        ["tax break for", "subsidy for", "benefit for", "profit for", "reward for"],
    ),
    (
        "Proposal may undermine existing institutional checks and balances.",
        ["bypass", "circumvent", "override", "ignore", "dissolve", "abolish",
         "dismantle", "defund the"],
    ),
]


def extract_implicit_flags(text: str) -> list[str]:
    """
    Detect implicit concerns the submitter may not have explicitly raised.
    These are surfaced as flags in the parsed context.
    """
    found = []
    for flag_text, signals in _IMPLICIT_FLAG_RULES:
        for signal in signals:
            if signal in text:
                found.append(flag_text)
                break
    return found
