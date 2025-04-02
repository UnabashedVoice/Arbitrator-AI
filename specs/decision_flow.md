# Arbitrator Decision Flow Diagram

```mermaid
flowchart TD
    A[Input Received] --> B{Context Parsing}
    B --> C[Ethics Core Evaluation]
    C --> D[Adversarial Reasoning Simulations]
    D --> E[Aggregate Consequence Map]
    E --> F{Confidence Threshold Met?}
    F -- Yes --> G[Decision Published with Justification]
    F -- No --> H[Flag for Human Review or Defer]
```

## Description

Each input (conflict, proposal, decision request) flows through:
1. Parsing into formal semantic context
2. Evaluation against ethics core (mutual benefit, harm minimization, consciousness sanctity)
3. Adversarial simulation of stakeholder positions
4. Generation of multi-path consequence maps
5. Confidence check: If > threshold, publish decision; else flag for review
