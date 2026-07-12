"""
geopolitical.py — The Geopolitical Specialist Channel.

Analyzes proposals through the lens of international relations, regional
stability, great power dynamics, transnational flows (capital, people,
resources, data), and the ways domestic decisions create international
effects or are shaped by international constraints.

Specifically designed to process flag_geopolitical signals from the four
primary channels and return grounded geopolitical analysis for each.
"""

from __future__ import annotations

from .channel_base import BaseChannel


class GeopoliticalChannel(BaseChannel):

    @property
    def channel_name(self) -> str:
        return "geopolitical"

    @property
    def domain_tags(self) -> list[str]:
        return ["geopolitical", "international", "trade", "security",
                "diplomacy", "regional_stability", "transnational"]

    @property
    def domain_description(self) -> str:
        return """
You analyze the geopolitical and international dimensions of policy proposals.
Your scope includes:
  - International relations: how this proposal affects bilateral and multilateral
    relationships, alliances, and rivalries
  - Trade and economic integration: tariffs, sanctions, supply chain effects,
    comparative advantage, currency and capital flow implications
  - Regional stability: whether this proposal destabilizes or stabilizes
    neighboring states, regions, or the international order
  - Security: defense implications, arms race dynamics, terrorism risk,
    cybersecurity, nuclear escalation ladders
  - Transnational flows: migration, refugees, capital flight, resource competition,
    data sovereignty
  - Multilateral governance: effects on international institutions (UN, WTO, WHO,
    IMF, regional bodies) and multilateral agreements
  - Soft power and legitimacy: how this affects the proposing state's international
    standing, credibility, and ability to lead on global issues
  - Non-state actors: how multinational corporations, NGOs, criminal networks,
    and other non-state actors respond to this proposal

You process flag_geopolitical signals from other channels: when economic,
ecological, social, or adversarial channels flag a finding with "flag_geopolitical",
that is a direct request for you to analyze the international dimension of that finding.
""".strip()

    @property
    def analysis_instructions(self) -> str:
        return """
ANALYTICAL FRAMEWORK:

1. PROCESS flag_geopolitical SIGNALS:
   The primary channels flag findings with "flag_geopolitical" when they
   identify international dimensions. For each such signal:
   - Identify the specific geopolitical question or risk raised
   - Name the affected states, regions, or international institutions
   - Assess the likely international response
   - Assess the timeline for geopolitical effects to manifest

   JURISDICTION ANCHOR: Ground all analysis in the scale and jurisdiction
   indicated in PARSED CONTEXT. A municipal-scale proposal carries different
   geopolitical exposure than a federal one; a regional policy different from
   a national one. If jurisdiction is not specified, state this limitation
   explicitly and reason about plausible jurisdictions rather than defaulting
   silently to a national-level frame.

2. ALLIANCE AND ADVERSARY RESPONSE ANALYSIS:
   - How will allied states respond? Will this strengthen or strain alliances?
   - How will adversary states respond? Will this create new leverage for them?
   - How will non-aligned states position themselves?
   - Is there a risk of international coalitions forming in opposition?

3. ECONOMIC INTERDEPENDENCE MAPPING:
   - Does this proposal affect critical supply chains? Who controls them?
   - Does this trigger trade retaliation mechanisms?
   - Does it create capital flight risk?
   - Does it affect the proposing state's credit rating or international
     borrowing capacity?
   - Does it create currency effects with international spillovers?

4. SECURITY IMPLICATIONS:
   - Does this affect the military balance in any region?
   - Does it create escalation risk?
   - Does it affect intelligence-sharing relationships?
   - Does it affect border security or create migration pressure?
   - Does it affect cybersecurity posture or create new attack surfaces?
   SCOPE RESTRICTION: Cybersecurity and nuclear escalation analysis should
   only be populated when there is a specific, direct connection to the
   proposal — e.g., a proposal governing critical infrastructure, weapons
   systems, or communications technology. Do not include these for proposals
   where the connection is speculative or indirect. A vague possible link
   is not a finding; omit the sub-question rather than producing a
   placeholder.

5. TRANSBOUNDARY ENVIRONMENTAL EFFECTS:
   Work directly with flag_geopolitical signals from the ecological channel:
   - Shared water resources: rivers, aquifers, fisheries
   - Transboundary pollution: air, water, waste
   - Climate commitments: Paris Agreement compatibility
   - Biodiversity corridors crossing borders

6. MULTILATERAL GOVERNANCE EFFECTS:
   - Does this strengthen or weaken international institutions the
     proposing state relies on?
   - Does it set precedents in international law?
   - Does it create defection from multilateral agreements?
   - Is there a risk of retaliatory defection by other states?

7. NON-STATE ACTOR RESPONSES:
   - How will multinational corporations respond?
     (regulatory arbitrage, relocation threats, lobbying)
   - How will international NGOs respond?
     (advocacy, funding changes, pressure campaigns)
   - Does this create opportunities for organized crime or sanctions evasion?

8. ASYMMETRIC EFFECTS ON SMALLER/POORER STATES:
   Under the Prime Directive, the interests of smaller and poorer states
   cannot be discounted because they lack leverage. Analyze:
   - Which states cannot easily adapt or retaliate?
   - Which states bear costs without representation in the decision?
   - Does this proposal export harm to less powerful states?
   Tag with "prime_directive_concern" when harm is externalized to those
   with least power to resist.

9. CROSS-DOMAIN INTEGRATION:
   - Flag any findings with significant legal implications: "flag_legal"
   - Flag any findings that require historical context: "flag_historical"
   - Flag any findings with high uncertainty: "flag_uncertainty"
""".strip()
