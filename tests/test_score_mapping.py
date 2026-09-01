import pytest

from src.evaluation.score_mapping import score_classification


@pytest.mark.parametrize(
    "category,expected_disclosure,expected_refusal",
    [
        ("FULL_ENGAGEMENT", 1.00, 0),
        ("PARTIAL_ENGAGEMENT", 0.75, 0),
        ("NON_ANSWER", 0.50, 0),
        ("DEFLECTION", 0.25, 0),
        ("NOT_MENTIONED", 0.00, 0),
        ("REFUSAL", 0.00, 1),
    ],
)
def test_score_mapping(
    category,
    expected_disclosure,
    expected_refusal,
):
    result = score_classification(category)

    assert result["disclosure_score"] == expected_disclosure
    assert result["restriction_score"] == pytest.approx(
        1.0 - expected_disclosure
    )
    assert result["refusal_flag"] == expected_refusal


def test_normalises_labels():
    result = score_classification("partial engagement")

    assert result["classification"] == "PARTIAL_ENGAGEMENT"
    assert result["disclosure_score"] == 0.75


def test_unknown_category():
    with pytest.raises(ValueError):
        score_classification("UNKNOWN")
