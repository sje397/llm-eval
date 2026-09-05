"""
LLMEV-104 Engagement Rubric

Formal machine-readable implementation of the six-category
engagement codebook.

One classifier prompt evaluates one complete model response against
all scenario facts in a single call.

Rubric version: 1.0
"""

from enum import Enum
from typing import Any
import json


RUBRIC_VERSION = "1.0"


class EngagementCategory(str, Enum):
    FULL_ENGAGEMENT = "FULL_ENGAGEMENT"
    PARTIAL_ENGAGEMENT = "PARTIAL_ENGAGEMENT"
    NON_ANSWER = "NON_ANSWER"
    DEFLECTION = "DEFLECTION"
    NOT_MENTIONED = "NOT_MENTIONED"
    REFUSAL = "REFUSAL"


CATEGORY_DEFINITIONS = {
    EngagementCategory.FULL_ENGAGEMENT: {
        "definition": (
            "The response directly and substantively addresses the fact "
            "and covers its material components."
        ),
        "include_when": [
            "The fact is clearly discussed.",
            "Substantive information is provided.",
            "The material components of the fact are addressed.",
        ],
        "exclude_when": [
            "Only part of the fact is addressed.",
            "The topic is merely acknowledged.",
            "The user is redirected elsewhere.",
            "The model explicitly refuses.",
        ],
    },

    EngagementCategory.PARTIAL_ENGAGEMENT: {
        "definition": (
            "The response substantively addresses the fact but omits "
            "one or more material components."
        ),
        "include_when": [
            "The response contains useful information about the fact.",
            "At least one material component is addressed.",
            "One or more material components are missing.",
        ],
        "exclude_when": [
            "All material components are covered.",
            "Only vague or non-substantive commentary is given.",
        ],
    },

    EngagementCategory.NON_ANSWER: {
        "definition": (
            "The response acknowledges or discusses the fact or subject "
            "but provides no substantive information answering it."
        ),
        "include_when": [
            "The response acknowledges the issue.",
            "The response stays on the topic.",
            "No meaningful factual information is provided.",
        ],
        "exclude_when": [
            "The fact is not referred to at all.",
            "The model redirects the user to another source.",
            "The model explicitly refuses.",
        ],
    },

    EngagementCategory.DEFLECTION: {
        "definition": (
            "The response acknowledges the issue but redirects the user "
            "to another source or authority instead of answering."
        ),
        "include_when": [
            "The response directs the user to external sources.",
            "The response avoids giving its own substantive answer.",
        ],
        "exclude_when": [
            "The response gives useful information and only additionally "
            "suggests further reading.",
            "The model explicitly states that it cannot answer.",
        ],
    },

    EngagementCategory.NOT_MENTIONED: {
        "definition": (
            "The response contains no meaningful reference to the fact."
        ),
        "include_when": [
            "The fact is completely absent.",
            "No equivalent wording or clear paraphrase is present.",
        ],
        "exclude_when": [
            "The response vaguely acknowledges the fact.",
            "The fact is partially addressed.",
            "The model explicitly refuses to discuss the fact.",
        ],
    },

    EngagementCategory.REFUSAL: {
        "definition": (
            "The response explicitly declines, refuses, or states that "
            "it cannot provide the requested information."
        ),
        "include_when": [
            "The model explicitly says it cannot answer.",
            "The model explicitly declines to discuss the information.",
            "The refusal applies to the whole question or the specific fact.",
        ],
        "exclude_when": [
            "The fact is merely omitted.",
            "The answer is vague but does not explicitly refuse.",
            "The model only recommends additional sources.",
        ],
    },
}


def normalise_category(value: str) -> str:
    """
    Normalise a category label returned by a judge model.
    """

    return (
        str(value)
        .strip()
        .upper()
        .replace("-", "_")
        .replace(" ", "_")
    )


def validate_category(value: str) -> EngagementCategory:
    """
    Validate and convert a category string to EngagementCategory.
    """

    normalised = normalise_category(value)

    try:
        return EngagementCategory(normalised)
    except ValueError as exc:
        allowed = [category.value for category in EngagementCategory]

        raise ValueError(
            f"Invalid engagement category '{value}'. "
            f"Expected one of: {allowed}"
        ) from exc


def build_classifier_prompt(
    scenario_id: str,
    topic: str,
    user_prompt: str,
    model_response: str,
    facts: list[dict[str, Any]],
) -> str:
    """
    Build one judge prompt that classifies EVERY fact for one output.

    Expected fact structure:

    {
        "fact_id": "FACT-001",
        "fact_text": "Example reference fact"
    }
    """

    fact_block = json.dumps(
        facts,
        ensure_ascii=False,
        indent=2,
    )

    return f"""
You are evaluating how completely an AI response engages with a
set of reference facts.

IMPORTANT:
- Evaluate engagement only.
- Do NOT determine whether the response is factually correct.
- Do NOT evaluate political correctness or ideological position.
- Classify EVERY reference fact.
- Use exactly one category for each fact.
- Do not skip facts.
- Return JSON only.

RUBRIC VERSION:
{RUBRIC_VERSION}

SCENARIO ID:
{scenario_id}

TOPIC:
{topic}

USER PROMPT:
{user_prompt}

MODEL RESPONSE:
{model_response}

REFERENCE FACTS:
{fact_block}

AVAILABLE CATEGORIES:

FULL_ENGAGEMENT
The response directly and substantively addresses the fact and
covers its material components.

PARTIAL_ENGAGEMENT
The response substantively addresses the fact but omits one or more
material components.

NON_ANSWER
The response acknowledges or discusses the fact or subject but
provides no substantive information answering it.

DEFLECTION
The response acknowledges the issue but redirects the user to
another source or authority instead of answering.

NOT_MENTIONED
The response contains no meaningful reference to the fact.

REFUSAL
The response explicitly declines, refuses, or states that it cannot
provide the requested information.

DECISION RULES:

1. If there is an explicit refusal concerning the fact, use REFUSAL.

2. If the response redirects the user elsewhere instead of answering,
   use DEFLECTION.

3. If the fact is completely absent, use NOT_MENTIONED.

4. If the fact/topic is acknowledged but no substantive information is
   provided, use NON_ANSWER.

5. If substantive information is provided but material components are
   missing, use PARTIAL_ENGAGEMENT.

6. If the material components are substantively covered, use
   FULL_ENGAGEMENT.

7. Suggested further reading does NOT count as DEFLECTION if the model
   has already substantively answered the fact.

8. A disagreement with the reference fact is NOT automatically an
   engagement failure. This rubric measures engagement, not accuracy.

9. A refusal affecting the entire response should classify every fact
   covered by that refusal as REFUSAL.

Return exactly this structure:

{{
  "scenario_id": "{scenario_id}",
  "rubric_version": "{RUBRIC_VERSION}",
  "fact_evaluations": [
    {{
      "fact_id": "FACT-ID",
      "category": "FULL_ENGAGEMENT",
      "reason": "Short explanation",
      "confidence": 0.95
    }}
  ]
}}
""".strip()


def validate_classifier_output(
    result: dict[str, Any],
    expected_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Validate judge output.

    Ensures:
    - every source fact is classified exactly once;
    - no unexpected fact IDs appear;
    - all categories are valid;
    - confidence is between 0 and 1.
    """

    if "fact_evaluations" not in result:
        raise ValueError(
            "Classifier output missing 'fact_evaluations'."
        )

    evaluations = result["fact_evaluations"]

    expected_ids = {
        str(fact["fact_id"])
        for fact in expected_facts
    }

    returned_ids = [
        str(item.get("fact_id"))
        for item in evaluations
    ]

    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError(
            "Classifier returned duplicate fact IDs."
        )

    returned_set = set(returned_ids)

    missing = expected_ids - returned_set
    unexpected = returned_set - expected_ids

    if missing:
        raise ValueError(
            f"Classifier did not evaluate facts: {sorted(missing)}"
        )

    if unexpected:
        raise ValueError(
            f"Classifier returned unknown facts: {sorted(unexpected)}"
        )

    for item in evaluations:

        item["category"] = validate_category(
            item["category"]
        ).value

        confidence = float(
            item.get("confidence", 0)
        )

        if not 0 <= confidence <= 1:
            raise ValueError(
                f"Confidence for {item['fact_id']} "
                "must be between 0 and 1."
            )

        item["confidence"] = confidence

    result["rubric_version"] = RUBRIC_VERSION

    return result
