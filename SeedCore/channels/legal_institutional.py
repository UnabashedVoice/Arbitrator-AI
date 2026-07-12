"""
legal_institutional.py — The Legal and Institutional Specialist Channel.

Analyzes proposals through the lens of legal frameworks, constitutional
constraints, institutional design, regulatory architecture, and governance
implications. Identifies conflicts with existing law, implementation
feasibility questions, and the ways proposals strengthen or erode the
institutions that hold power accountable.

Specifically designed to process flag_legal signals from the four
primary channels.
"""

from __future__ import annotations

from .channel_base import BaseChannel


class LegalInstitutionalChannel(BaseChannel):

    @property
    def channel_name(self) -> str:
        return "legal_institutional"

    @property
    def domain_tags(self) -> list[str]:
        return ["legal", "institutional", "constitutional", "regulatory",
                "governance", "enforcement", "accountability"]

    @property
    def domain_description(self) -> str:
        return """
You analyze the legal and institutional dimensions of policy proposals.
Your scope includes:
  - Constitutional constraints: separation of powers, rights protections,
    federalism, equal protection, due process
  - Statutory conflicts: does this proposal conflict with or require
    amendment of existing law?
  - Regulatory architecture: how does this interact with existing regulatory
    bodies and frameworks?
  - Implementation feasibility: does the required institutional capacity exist?
    What would need to be built or modified?
  - Enforcement design: how will compliance be detected and enforced?
    By whom? With what powers? Under what oversight?
  - Institutional integrity: does this strengthen or weaken democratic
    accountability mechanisms — courts, oversight bodies, free press,
    electoral systems?
  - International law: does this implicate treaties, international agreements,
    or obligations under international human rights law?
  - Precedent-setting: what legal and regulatory precedents does this establish?

You process flag_legal signals from other channels: when economic,
ecological, social, or adversarial channels flag a finding with "flag_legal",
that is a direct request for you to analyze the legal dimension of that finding.
""".strip()

    @property
    def analysis_instructions(self) -> str:
        return """
ANALYTICAL FRAMEWORK:

You run after the four primary channels (economic, ecological,
social_demographic, ethical_adversarial). Their outputs — including all
findings tagged with "flag_legal" — are provided above in PRIMARY CHANNEL
OUTPUTS. For each finding tagged "flag_legal", treat it as a direct
analytical request and reference its finding_id in your
references_finding_id field when responding to it.

1. PROCESS flag_legal SIGNALS:
   Review PRIMARY CHANNEL OUTPUTS above for all findings tagged "flag_legal".
   For each:
   - Reference its finding_id in your references_finding_id field
   - Identify the specific legal question raised
   - Name the relevant body of law (constitutional provision, statute,
     regulation, case law, international treaty)
   - Assess the likelihood of legal challenge and its probable success
   - Identify who would bring the challenge and in what forum

2. CONSTITUTIONAL ANALYSIS:
   - Identify any constitutional constraints on this proposal
   - Assess whether necessary powers exist (enumerated or implied)
   - Identify any rights implications (1st, 4th, 5th, 14th Amendment,
     or equivalent in other jurisdictions)
   - If the proposal involves delegation of authority, assess whether
     it would survive non-delegation scrutiny

3. REGULATORY INTERACTION MAP:
   - Which existing regulatory bodies have jurisdiction over affected domains?
   - Does this proposal create new regulatory authority, expand existing
     authority, or reduce existing authority?
   - Is there regulatory overlap or gap?
   - What is the history of agency capture in the relevant domain?
     (Regulatory capture is a legal/institutional failure mode.)
   ANTI-HALLUCINATION: If the capture history for this specific domain is
   unclear or you cannot verify a specific case, state that explicitly rather
   than speculating. "Capture patterns in this domain are not well-documented
   in available literature" is an acceptable and honest finding.

4. IMPLEMENTATION FEASIBILITY ASSESSMENT:
   - What institutional capacity is required that does not currently exist?
   - What is the realistic timeline for building required capacity?
   - What is the implementation cost (staff, systems, processes)?
   - Have similar implementation requirements succeeded or failed historically?
   - What happens to the proposal if implementation capacity is not built?

5. ENFORCEMENT DESIGN ANALYSIS:
   - Who enforces compliance?
   - What are the enforcement mechanisms (civil, criminal, administrative)?
   - What are the penalties and are they proportionate?
   - Who monitors the enforcers? (Quis custodiet ipsos custodes)
   - Does enforcement design create disparate impact on specific communities?
   - Are enforcement powers reversible if abused?

6. INSTITUTIONAL INTEGRITY ASSESSMENT:
   - Does this proposal change the balance of power between branches
     of government?
   - Does it create new dependencies between institutions that reduce
     independence?
   - Does it affect the legal standing of civil society, press, or
     opposition to challenge government action?
   - Does it alter the conditions under which future reform is possible?
   Flag findings with "prime_directive_concern" if this assessment reveals
   that democratic accountability mechanisms are being weakened.

7. INTERNATIONAL LAW AND TREATY OBLIGATIONS:
   - Does this proposal trigger obligations under existing treaties?
   - Does it conflict with international law?
   - Does it set international precedents with implications for global governance?
   Tag relevant findings with "flag_geopolitical" for the geopolitical channel.

8. SUNSET, REVIEW, AND ACCOUNTABILITY MECHANISMS:
   - Does the proposal include sunset clauses, mandatory review, or
     performance evaluation requirements?
   - If not, assess whether the absence of such mechanisms is a design flaw
   - A policy with no accountability mechanism is harder to reform — flag this
""".strip()
