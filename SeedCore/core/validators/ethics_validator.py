import os
import json
import datetime

from scenario_parser import load_scenario
from adversarial_module import analyze_challenge
from reasoning.llama_bridge import get_dialectic_response

RULES_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "ethics_rules", "base_rules.json"
)
LOG_DIR = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "data", "logs"
)


def load_ethics_rules():
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("ethics", [])
    except FileNotFoundError:
        print("Error: base_rules.json not found.")
        return []
    except json.JSONDecodeError as e:
        print(f"JSON Error: {e}")
        return []


def evaluate_rule(rule, scenario):
    score = 0
    trace = []

    if rule["principle"] == "mutual_benefit":
        beneficiaries = set(scenario.actors.get("beneficiaries", []))
        affected = set(scenario.actors.get("affected_parties", []))
        if beneficiaries and affected:
            score += 0.5
            trace.append("Identified both beneficiaries and affected parties.")
        if len(beneficiaries) > len(affected):
            score += 0.5
            trace.append("More entities benefit than are harmed.")

    elif rule["principle"] == "minimize_harm":
        harm_details = scenario.proposal.get("harm", {}).get("details", "")
        if "layoff" in harm_details.lower():
            score += 0.25
            trace.append("Detected layoffs, indicating economic harm.")
        if "temporary" in harm_details.lower():
            score += 0.25
            trace.append("Harm appears to be short-term.")
        if scenario.outcomes.get("long_term") and "shift" in scenario.outcomes["long_term"].lower():
            score += 0.5
            trace.append("Long-term adaptation may mitigate harm.")

    elif rule["principle"] == "respect_consciousness":
        if scenario.entities:
            score += 0.5
            trace.append("Conscious entities explicitly listed.")
        if "minority" not in " ".join(scenario.entities).lower():
            score += 0.5
            trace.append("No minority group appears excluded.")

    return min(score, 1.0), trace


def prompt_challenge(rule_id, title):
    response = input(f"\nWould you like to challenge [{rule_id}] {title}? (y/n): ").strip().lower()
    if response == 'y':
        return input("Enter your counterargument: ").strip()
    return None


def save_log(entry):
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    filename = f"log_{entry['scenario_id']}_{entry['timestamp'].replace(':', '-')}.json"
    path = os.path.join(LOG_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)
    print(f"\n✅ Log saved to {path}")


def run_evaluation():
    print("\n=== Arbitrator Ethical Validator ===\n")

    rules = load_ethics_rules()
    scenario = load_scenario()

    if not scenario or not rules:
        print("Error loading inputs.")
        return

    scenario.summary()
    print("\nEvaluating scenario against ethical principles...\n")

    log_entry = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "scenario_id": scenario.id,
        "title": scenario.title,
        "evaluation": []
    }

    for rule in rules:
        score, trace = evaluate_rule(rule, scenario)

        print(f"\n[{rule['id']}] {rule['title']}")
        print(f"Score: {score:.2f}")
        print("Reasoning Trace:")
        for step in trace:
            print(f"  - {step}")

        challenge = prompt_challenge(rule['id'], rule['title'])

        # Adversarial analysis
        adversarial_report = analyze_challenge(rule, trace, challenge)
        print(f"Adversarial Analysis: Severity = {adversarial_report['severity']}")
        for insight in adversarial_report["insights"]:
            print(f"  • {insight}")

        # Dialectic response (via Phi-2)
        dialectic_response = get_dialectic_response(rule, trace, challenge)
        print("\nDialectic Response:")
        print(dialectic_response)

        log_entry["evaluation"].append({
            "rule_id": rule["id"],
            "rule_title": rule["title"],
            "score": score,
            "trace": trace,
            "challenge": challenge,
            "adversarial_report": adversarial_report,
            "dialectic_response": dialectic_response
        })

    save_log(log_entry)


if __name__ == "__main__":
    run_evaluation()
