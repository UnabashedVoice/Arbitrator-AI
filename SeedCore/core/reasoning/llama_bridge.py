import requests

LLAMA_API_URL = "http://127.0.0.1:5000/v1/completions"
MAX_TOKENS = 300
TEMPERATURE = 0.7

def format_dialectic_prompt(rule_title, rule_description, arbitrator_trace, user_challenge):
    trace_text = "\n".join(f"- {t}" for t in arbitrator_trace)
    challenge_text = user_challenge.strip() if user_challenge else "None provided."

    prompt = f"""
The following is an ethical deliberation on the rule: "{rule_title}"

Rule Description:
{rule_description}

Arbitrator's Reasoning:
{trace_text}

User Challenge:
{challenge_text}

Respond as if you are an ethical dialectician reviewing the challenge. Do you agree or disagree with the challenge? Why? Is Arbitrator's reasoning sufficient, or should it be revised? Provide your reasoning in 3-5 sentences using logical and philosophical clarity.
"""
    return prompt.strip()

def get_dialectic_response(rule, trace, challenge):
    prompt = format_dialectic_prompt(
        rule_title=rule["title"],
        rule_description=rule["description"],
        arbitrator_trace=trace,
        user_challenge=challenge
    )

    try:
        response = requests.post(LLAMA_API_URL, json={
            "prompt": prompt,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE
        })

        if response.status_code == 200:
            return response.json()['choices'][0]['text'].strip()
        else:
            return f"[ERROR] API returned status code {response.status_code}: {response.text}"

    except Exception as e:
        return f"[ERROR] Dialectic request failed: {e}"
