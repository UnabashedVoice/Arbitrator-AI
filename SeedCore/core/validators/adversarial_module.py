import re

def analyze_challenge(rule, reasoning_trace, user_challenge):
    report = {
        "rule_id": rule["id"],
        "rule_title": rule["title"],
        "challenge": user_challenge,
        "contradiction_detected": False,
        "severity": "none",
        "insights": []
    }

    if not user_challenge:
        report["insights"].append("No challenge submitted.")
        return report

    lc_challenge = user_challenge.lower()

    # Heuristic 1: Look for violation keywords
    for signal in rule.get("violation_signals", []):
        if signal.lower() in lc_challenge:
            report["contradiction_detected"] = True
            report["severity"] = "moderate"
            report["insights"].append(f"Challenge mentions potential ethical violation: '{signal}'")

    # Heuristic 2: Challenge highlights unaddressed party
    if re.search(r"\b(excluded|ignored|overlooked|neglected)\b", lc_challenge):
        report["contradiction_detected"] = True
        report["severity"] = "high"
        report["insights"].append("Challenge suggests entities were ethically overlooked.")

    # Heuristic 3: No overlap between trace and challenge
    if not any(term.lower() in lc_challenge for term in " ".join(reasoning_trace).split()):
        report["insights"].append("Challenge uses novel framing not covered in Arbitrator's reasoning.")

    if report["contradiction_detected"] and report["severity"] == "none":
        report["severity"] = "low"

    if not report["contradiction_detected"]:
        report["insights"].append("No clear contradiction detected, but review is advised.")

    return report
