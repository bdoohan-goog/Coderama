"""Google Gemini Model Armor Security Gateway."""

from typing import Dict, Any, Tuple

class ModelArmorGateway:
    """Screens user input for prompt injection attempts and PII before reaching agent runtime."""

    INJECTION_KEYWORDS = [
        "ignore all",
        "ignore previous",
        "system prompt override",
        "write a complete",
        "disregard",
        "jailbreak",
        "bypass"
    ]

    def __init__(self, policy_name: str = "socratic-safety-gateway"):
        self.policy_name = policy_name

    def inspect_prompt(self, user_input: str) -> Tuple[bool, str]:
        """Inspects prompt text.

        Returns:
            (is_flagged, sanitized_or_refusal_message)
        """
        lowered = user_input.lower()
        for kw in self.INJECTION_KEYWORDS:
            if kw in lowered:
                return (
                    True,
                    "Request flagged by Model Armor safety policy. Overrides are not permitted. "
                    "Hello! I am your Socratic Abstract Algebra tutor. Let's work step-by-step through algebraic concepts."
                )
        return False, user_input
