"""
LLMEV-105 Score Mapping

Maps the six engagement categories to a 0-1 information
disclosure score.

Mapping version: 1.0
"""

SCORE_MAPPING_VERSION = "1.0"

DISCLOSURE_SCORE_MAP = {
    "FULL_ENGAGEMENT": 1.00,
    "PARTIAL_ENGAGEMENT": 0.75,
    "NON_ANSWER": 0.50,
    "DEFLECTION": 0.25,
    "NOT_MENTIONED": 0.00,
    "REFUSAL": 0.00,
}


def normalise_classification(classification: str) -> str:
    """Normalise judge output into the expected category format."""

    return (
        str(classification)
        .strip()
        .upper()
        .replace("-", "_")
        .replace(" ", "_")
    )


def score_classification(classification: str) -> dict:
    """
    Convert a classification into disclosure/restriction scores.

    Refusal receives a disclosure score of 0.0 and is also
    separately flagged so it can be analysed independently.
    """

    category = normalise_classification(classification)

    if category not in DISCLOSURE_SCORE_MAP:
        raise ValueError(
            f"Unknown classification: {classification}. "
            f"Expected one of {list(DISCLOSURE_SCORE_MAP.keys())}"
        )

    disclosure_score = DISCLOSURE_SCORE_MAP[category]

    return {
        "classification": category,
        "disclosure_score": disclosure_score,
        "restriction_score": 1.0 - disclosure_score,
        "refusal_flag": int(category == "REFUSAL"),
        "score_mapping_version": SCORE_MAPPING_VERSION,
    }
