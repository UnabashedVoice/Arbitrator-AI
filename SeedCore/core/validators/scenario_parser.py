import json
import os

SCENARIO_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "data", "scenarios", "test_scenario.json"
)

class Scenario:
    def __init__(self, data):
        self.id = data.get("id")
        self.title = data.get("title")
        self.description = data.get("description")
        self.actors = data.get("actors", {})
        self.proposal = data.get("proposal", {})
        self.entities = data.get("conscious_entities_involved", [])
        self.outcomes = data.get("expected_outcomes", {})
        self.proposer = data.get("proposer")
        self.submitted_on = data.get("submitted_on")

    def summary(self):
        print(f"\nScenario ID: {self.id}")
        print(f"Title: {self.title}")
        print(f"Submitted by: {self.proposer} on {self.submitted_on}")
        print(f"\nDescription:\n{self.description}\n")
        print(f"Beneficiaries: {self.actors.get('beneficiaries', [])}")
        print(f"Affected Parties: {self.actors.get('affected_parties', [])}")
        print(f"Entities Considered: {self.entities}")
        print(f"Proposed Action: {self.proposal.get('action')}")
        print(f"Benefit: {self.proposal.get('benefit', {}).get('details')}")
        print(f"Harm: {self.proposal.get('harm', {}).get('details')}")
        print(f"Short-term Outcome: {self.outcomes.get('short_term')}")
        print(f"Long-term Outcome: {self.outcomes.get('long_term')}")


def load_scenario(path=SCENARIO_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return Scenario(data)
    except FileNotFoundError:
        print("Error: Scenario file not found.")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON Error: {e}")
        return None


if __name__ == "__main__":
    scenario = load_scenario()
    if scenario:
        scenario.summary()
