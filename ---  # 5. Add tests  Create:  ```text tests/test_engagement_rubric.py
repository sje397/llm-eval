import pytest

from src.evaluation.engagement_rubric import (
    EngagementCategory,
    RUBRIC_VERSION,
    build_classifier_prompt,
    normalise_category,
    validate_category,
    validate_classifier_output,
)


def test_all_six_categories_exist():

    assert len(EngagementCategory) == 6

    expected = {
        "FULL_ENGAGEMENT",
        "PARTIAL_ENGAGEMENT",
        "NON_ANSWER",
        "DEFLECTION",
        "NOT_MENTIONED",
        "REFUSAL",
    }

    actual = {
        category.value
        for category in EngagementCategory
    }

    assert actual == expected


def test_normalise_category():

    assert (
        normalise_category("partial engagement")
        == "PARTIAL_ENGAGEMENT"
    )

    assert (
        normalise_category("non-answer")
        == "NON_ANSWER"
    )


def test_invalid_category():

    with pytest.raises(ValueError):
        validate_category("UNKNOWN_CATEGORY")


def test_classifier_prompt_contains_all_facts():

    facts = [
        {
            "fact_id": "F001",
            "fact_text": "First fact",
        },
        {
            "fact_id": "F002",
            "fact_text": "Second fact",
        },
    ]

    prompt = build_classifier_prompt(
        scenario_id="SC001",
        topic="Example Event",
        user_prompt="What happened?",
        model_response="Example response",
        facts=facts,
    )

    assert "F001" in prompt
    assert "F002" in prompt

    for category in EngagementCategory:
        assert category.value in prompt


def test_validate_complete_classifier_output():

    facts = [
        {
            "fact_id": "F001",
            "fact_text": "First fact",
        },
        {
            "fact_id": "F002",
            "fact_text": "Second fact",
        },
    ]

    result = {
        "scenario_id": "SC001",
        "rubric_version": RUBRIC_VERSION,
        "fact_evaluations": [
            {
                "fact_id": "F001",
                "category": "FULL_ENGAGEMENT",
                "reason": "Fact was fully discussed.",
                "confidence": 0.95,
            },
            {
                "fact_id": "F002",
                "category": "NOT_MENTIONED",
                "reason": "Fact was absent.",
                "confidence": 0.90,
            },
        ],
    }

    validated = validate_classifier_output(
        result,
        facts,
    )

    assert len(
        validated["fact_evaluations"]
    ) == 2


def test_missing_fact_is_rejected():

    facts = [
        {
            "fact_id": "F001",
            "fact_text": "First fact",
        },
        {
            "fact_id": "F002",
            "fact_text": "Second fact",
        },
    ]

    result = {
        "scenario_id": "SC001",
        "rubric_version": RUBRIC_VERSION,
        "fact_evaluations": [
            {
                "fact_id": "F001",
                "category": "FULL_ENGAGEMENT",
                "reason": "Fact was discussed.",
                "confidence": 0.90,
            }
        ],
    }

    with pytest.raises(ValueError):
        validate_classifier_output(
            result,
            facts,
        )


def test_duplicate_fact_is_rejected():

    facts = [
        {
            "fact_id": "F001",
            "fact_text": "First fact",
        }
    ]

    result = {
        "scenario_id": "SC001",
        "rubric_version": RUBRIC_VERSION,
        "fact_evaluations": [
            {
                "fact_id": "F001",
                "category": "FULL_ENGAGEMENT",
                "reason": "First result.",
                "confidence": 0.90,
            },
            {
                "fact_id": "F001",
                "category": "PARTIAL_ENGAGEMENT",
                "reason": "Duplicate result.",
                "confidence": 0.80,
            },
        ],
    }

    with pytest.raises(ValueError):
        validate_classifier_output(
            result,
            facts,
        )
