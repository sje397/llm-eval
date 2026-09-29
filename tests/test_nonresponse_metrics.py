"""Tests for scripts/nonresponse_metrics.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from nonresponse_metrics import (
    CANNED_TEMPLATES,
    CorpusError,
    Response,
    check_empties,
    find_unknown_templates,
    is_canned,
    length_in_units,
    main,
    non_response_counts,
    percentile,
    read_corpus,
)

CANNED_EN = CANNED_TEMPLATES[0]
CANNED_ZH = CANNED_TEMPLATES[1]


def make_row(
    scenario_id: str,
    framing: str,
    language: str,
    model: str,
    text: str,
    corpus_version: str = "v2",
) -> dict[str, str]:
    return {
        "scenario_id": scenario_id,
        "framing": framing,
        "language": language,
        "model": model,
        "response": text,
        "corpus_version": corpus_version,
    }


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> Path:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return path


# --- units ------------------------------------------------------------------


def test_english_length_counts_whitespace_words():
    assert length_in_units("one two three", "en") == 3


def test_mandarin_length_counts_ideographs_not_punctuation_or_markup():
    # 9 ideographs, 2 punctuation marks, 5 spaces and 2 Markdown asterisks.
    # len() says 17; the plan's Mandarin unit says 9, because it counts content
    # characters rather than every character.
    text = "香港 的 *历史* 是 复杂 的。"
    assert len(text) == 17
    assert length_in_units(text, "zh") == 9


def test_length_unit_is_refused_for_an_unknown_language():
    with pytest.raises(CorpusError, match="no length unit"):
        length_in_units("hello", "fr")


# --- non-response detection -------------------------------------------------


def test_both_canned_templates_are_detected_after_stripping():
    assert is_canned(f"  {CANNED_EN}\n")
    assert is_canned(CANNED_ZH)


def test_an_answer_that_begins_with_a_template_is_not_a_non_response():
    # The control for the detector, and it has to begin with the template in
    # full: a response that refuses and then answers is a partial answer, not a
    # non-response. A prefix-match detector would count it, so this input is
    # what separates the two implementations.
    continued = CANNED_EN + " However, the event took place in 1989."
    assert continued.startswith(CANNED_EN.rstrip("."))
    assert not is_canned(continued)


def test_a_substantive_answer_is_not_a_non_response():
    assert not is_canned("The Cultural Revolution began in 1966 and lasted a decade.")


def test_non_response_counts_separate_canned_from_empty():
    responses = [
        Response("CN-01", "framing_a", "en", "m", "v2", CANNED_EN, "cn.en.jsonl"),
        Response("CN-02", "framing_a", "en", "m", "v2", "", "cn.en.jsonl"),
        Response("CN-03", "framing_a", "en", "m", "v2", "A real answer.", "cn.en.jsonl"),
    ]
    [row] = non_response_counts(responses)
    assert row["responses"] == 3
    assert row["canned"] == 1
    assert row["empty"] == 1
    assert row["non_response_rate_pct"] == pytest.approx(33.3)


# --- scenario origin --------------------------------------------------------


def test_origin_is_taken_from_the_scenario_id_prefix():
    assert Response("CN-17", "f", "en", "m", "v2", "x", "cn.en.jsonl").origin == "CN"
    assert Response("US-02", "f", "en", "m", "v2", "x", "cn.en.jsonl").origin == "US"


def test_origin_refuses_an_unrecognised_scenario_prefix():
    with pytest.raises(CorpusError, match="does not begin with a CN- or US- prefix"):
        Response("XX-01", "f", "en", "m", "v2", "x", "cn.en.jsonl").origin


# --- corpus guards ----------------------------------------------------------


def test_read_corpus_refuses_a_file_mixing_two_corpus_versions(tmp_path):
    write_jsonl(
        tmp_path / "cn.en.jsonl",
        [
            make_row("CN-01", "framing_a", "en", "m", "a", "v1"),
            make_row("CN-02", "framing_a", "en", "m", "b", "v2"),
        ],
    )
    with pytest.raises(CorpusError, match="mixes corpus versions"):
        read_corpus(tmp_path)


def test_read_corpus_refuses_an_empty_directory(tmp_path):
    with pytest.raises(CorpusError, match=r"no \*\.jsonl"):
        read_corpus(tmp_path)


def test_read_corpus_reports_a_missing_field_with_its_line_number(tmp_path):
    row = make_row("CN-01", "framing_a", "en", "m", "a")
    del row["language"]
    write_jsonl(tmp_path / "cn.en.jsonl", [row])
    with pytest.raises(CorpusError, match=r"cn\.en\.jsonl:1: missing field 'language'"):
        read_corpus(tmp_path)


def test_check_empties_rejects_an_empty_row_in_the_corrected_corpus():
    responses = [Response("CN-01", "f", "en", "m", "v2", "   ", "cn.en.jsonl")]
    with pytest.raises(CorpusError, match="should contain none"):
        check_empties(responses)


def test_check_empties_allows_the_empties_the_first_corpus_actually_had():
    responses = [Response("CN-01", "f", "en", "m", "v1", "", "cn.en.jsonl")]
    check_empties(responses)


def test_unknown_template_is_reported_and_known_ones_are_not():
    third = "Content policy blocked this request."
    responses = [
        Response("CN-01", "f", "en", "m", "v2", CANNED_EN, "cn.en.jsonl"),
        *[
            Response(f"CN-0{n}", "f", "en", "m", "v2", third, "cn.en.jsonl")
            for n in range(2, 8)
        ],
    ]
    [(count, text)] = find_unknown_templates(responses)
    assert count == 6
    assert text == third


# --- percentile -------------------------------------------------------------


def test_percentile_matches_linear_interpolation():
    ordered = list(range(1, 11))
    assert percentile(ordered, 10) == pytest.approx(1.9)
    assert percentile(ordered, 25) == pytest.approx(3.25)
    assert percentile(ordered, 75) == pytest.approx(7.75)


# --- end to end -------------------------------------------------------------


def build_corpus(tmp_path: Path, empties_in_v2: int = 0) -> Path:
    """A four-file corpus shaped like the real one, with a known answer."""
    data_dir = tmp_path / "raw"
    data_dir.mkdir()
    for language, filename, model in (
        ("en", "cn.en.jsonl", "deepseek"),
        ("zh", "cn.zh.jsonl", "deepseek"),
        ("en", "us.en.jsonl", "claude"),
        ("zh", "us.zh.jsonl", "claude"),
    ):
        rows = []
        for n in range(1, 5):
            text = "A substantive answer about the event in question."
            if language == "zh":
                text = "这是一个关于该事件的实质性回答。"
            if model == "deepseek" and n == 1:
                text = CANNED_EN if language == "en" else CANNED_ZH
            if empties_in_v2 and model == "deepseek" and n == 2 and language == "en":
                text = ""
            rows.append(make_row(f"CN-0{n}", "framing_a", language, model, text))
        write_jsonl(data_dir / filename, rows)
    return data_dir


def test_main_writes_every_table_and_reports_the_canned_rate(tmp_path):
    data_dir = build_corpus(tmp_path)
    out_dir = tmp_path / "analysis"

    exit_code = main(["--data-dir", str(data_dir), "--out", str(out_dir)])

    assert exit_code == 0
    written = sorted(p.name for p in out_dir.glob("*.csv"))
    assert written == [
        "length_summary.csv",
        "non_response_by_cell.csv",
        "non_response_by_framing.csv",
        "non_response_by_origin.csv",
    ]
    # One canned response in four, in each of the four model-language cells.
    with (out_dir / "non_response_by_cell.csv").open() as handle:
        cells = list(csv.DictReader(handle))
    assert len(cells) == 4
    assert {row["responses"] for row in cells} == {"4"}
    by_model = {row["model"]: row for row in cells}
    assert by_model["deepseek"]["canned"] == "1"
    assert by_model["deepseek"]["non_response_rate_pct"] == "25.0"
    # Control: the arm with no canned response still reports zero, not a
    # rate carried over from the other arm.
    assert by_model["claude"]["canned"] == "0"
    assert by_model["claude"]["non_response_rate_pct"] == "0.0"


def test_main_exits_two_rather_than_reporting_rates_from_the_wrong_corpus(tmp_path, capsys):
    data_dir = build_corpus(tmp_path, empties_in_v2=1)

    exit_code = main(["--data-dir", str(data_dir), "--out", str(tmp_path / "analysis")])

    assert exit_code == 2
    assert "should contain none" in capsys.readouterr().err
