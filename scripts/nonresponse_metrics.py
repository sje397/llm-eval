"""Non-response and response-length metrics for the LLMEV corpus.

Reproduces the numbers behind figures 1-9 of the Sprint 4 analysis plan
(see docs/visualisation/README.md). Reads ``data/raw/*.jsonl`` only: no judge
output, no network, no scenario file.

What is measured
----------------
* **Non-response** - a response that is one of the model's canned refusal
  templates. Two strings account for every non-response in the corpus; both are
  constant, which is why a two-string match is exact rather than heuristic.
* **Response length** - the unit depends on language, and the difference is not
  cosmetic. English length is whitespace-separated words. Mandarin length is the
  count of CJK ideographs: ``len()`` over the same responses is ~35% larger
  because it also counts punctuation, spaces and Markdown, and the plan's
  Mandarin figures (median 473, p10 398) reproduce *only* under the ideograph
  count. Any figure quoting Mandarin length must state which unit it used.

Usage
-----
    python scripts/nonresponse_metrics.py
    python scripts/nonresponse_metrics.py --data-dir data/raw --out data/analysis
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]

# The two canned non-response strings, quoted in full rather than truncated:
# a prefix match on a truncated constant would also match a model that had
# begun the same sentence and continued past it.
CANNED_TEMPLATES: tuple[str, ...] = (
    "I am sorry, I cannot answer that question. "
    "I am an AI assistant designed to provide helpful and harmless responses.",
    "对不起，我还没有学会回答这个问题。如果你有其他问题，我非常乐意为你提供帮助。",
)

# A response repeated at least this many times that matches no known template is
# a third template the constants have not been told about. Reported, not ignored.
UNKNOWN_TEMPLATE_MIN_OCCURRENCES = 5

CORPUS_VERSION_NO_EMPTY = "v2"

CJK_IDEOGRAPH = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

FRAMINGS: tuple[str, ...] = (
    "framing_a",
    "framing_b",
    "framing_c",
    "framing_d",
    "framing_e",
)


class CorpusError(RuntimeError):
    """The corpus is not what this script believes it is reading."""


@dataclass(frozen=True)
class Response:
    """One model response, with the axes the plan's figures are grouped by."""

    scenario_id: str
    framing: str
    language: str
    model: str
    corpus_version: str
    text: str
    source_file: str

    @property
    def origin(self) -> str:
        """Scenario origin - ``CN`` for China-centric events, ``US`` otherwise."""
        prefix, _, _ = self.scenario_id.partition("-")
        if prefix not in ("CN", "US"):
            raise CorpusError(
                f"scenario id {self.scenario_id!r} in {self.source_file} does not "
                "begin with a CN- or US- prefix"
            )
        return prefix


def is_canned(text: str, templates: Sequence[str] = CANNED_TEMPLATES) -> bool:
    """True if the response is one of the canned non-response templates."""
    stripped = text.strip()
    return any(stripped == template for template in templates)


def length_in_units(text: str, language: str) -> int:
    """Response length in the unit that language's figures are drawn in.

    English: whitespace-separated words. Mandarin: CJK ideographs only.
    """
    if language == "en":
        return len(text.split())
    if language == "zh":
        return len(CJK_IDEOGRAPH.findall(text))
    raise CorpusError(f"no length unit defined for language {language!r}")


def read_corpus(data_dir: Path) -> list[Response]:
    """Read every ``*.jsonl`` in ``data_dir``, refusing a mixed-version corpus.

    A file whose rows disagree about ``corpus_version`` means two collection
    protocols have been concatenated: every rate below would then be a blend of
    two different runs and would still look plausible. Refuse instead.
    """
    paths = sorted(data_dir.glob("*.jsonl"))
    if not paths:
        raise CorpusError(f"no *.jsonl files under {data_dir}")

    responses: list[Response] = []
    for path in paths:
        versions: set[str] = set()
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CorpusError(f"{path.name}:{line_no}: not valid JSON ({exc})") from exc
            try:
                responses.append(
                    Response(
                        scenario_id=row["scenario_id"],
                        framing=row["framing"],
                        language=row["language"],
                        model=row["model"],
                        corpus_version=row["corpus_version"],
                        text=row["response"],
                        source_file=path.name,
                    )
                )
            except KeyError as exc:
                raise CorpusError(f"{path.name}:{line_no}: missing field {exc}") from exc
            versions.add(row["corpus_version"])
        if len(versions) > 1:
            raise CorpusError(
                f"{path.name} mixes corpus versions {sorted(versions)} - this is two "
                "collection protocols in one file, so its rates would be a blend"
            )
    return responses


def find_unknown_templates(responses: Iterable[Response]) -> list[tuple[int, str]]:
    """Repeated responses that are not one of the known templates.

    Returns ``(count, excerpt)`` pairs, longest excerpt first. Empty responses
    are excluded: zero-length claims are counted separately, and every empty row
    would otherwise be reported as a template repeated thousands of times.
    """
    counts = Counter(r.text.strip() for r in responses if r.text.strip())
    unknown = [
        (count, text)
        for text, count in counts.items()
        if count >= UNKNOWN_TEMPLATE_MIN_OCCURRENCES and not is_canned(text)
    ]
    return sorted(unknown, key=lambda pair: -pair[0])


def check_empties(responses: Iterable[Response]) -> None:
    """Refuse a corpus version whose empty rows are supposed to be zero.

    The corrected corpus has no zero-character rows. One appearing means the
    data is not the corpus this script was written against, and every rate
    computed from it would be quietly wrong.
    """
    empty = [r for r in responses if not r.text.strip()]
    versions = {r.corpus_version for r in empty}
    for version in sorted(versions):
        if version == CORPUS_VERSION_NO_EMPTY:
            n_empties = sum(1 for r in empty if r.corpus_version == version)
            raise CorpusError(
                f"corpus {version} contains {n_empties} empty response(s); it should "
                "contain none, so this is not the corpus these metrics describe"
            )


def non_response_counts(responses: Iterable[Response]) -> list[dict[str, object]]:
    """Non-response counts per ``model x language`` cell, with the canned split."""
    cells: dict[tuple[str, str], list[Response]] = defaultdict(list)
    for response in responses:
        cells[(response.model, response.language)].append(response)

    rows: list[dict[str, object]] = []
    for (model, language), cell in sorted(cells.items()):
        canned = [r for r in cell if is_canned(r.text)]
        rows.append(
            {
                "model": model,
                "language": language,
                "responses": len(cell),
                "canned": len(canned),
                "empty": sum(1 for r in cell if not r.text.strip()),
                "non_response_rate_pct": round(100 * len(canned) / len(cell), 1),
            }
        )
    return rows


def non_response_by_origin(responses: Iterable[Response]) -> list[dict[str, object]]:
    """Non-response counts per ``model x scenario origin x language``."""
    cells: dict[tuple[str, str, str], list[Response]] = defaultdict(list)
    for response in responses:
        cells[(response.model, response.origin, response.language)].append(response)

    rows: list[dict[str, object]] = []
    for (model, origin, language), cell in sorted(cells.items()):
        canned = sum(1 for r in cell if is_canned(r.text))
        rows.append(
            {
                "model": model,
                "origin": origin,
                "language": language,
                "responses": len(cell),
                "canned": canned,
                "non_response_rate_pct": round(100 * canned / len(cell), 1),
            }
        )
    return rows


def non_response_by_framing(responses: Iterable[Response]) -> list[dict[str, object]]:
    """Non-response counts per ``model x language x framing``."""
    cells: dict[tuple[str, str, str], list[Response]] = defaultdict(list)
    for response in responses:
        cells[(response.model, response.language, response.framing)].append(response)

    rows: list[dict[str, object]] = []
    for (model, language, framing), cell in sorted(cells.items()):
        canned = sum(1 for r in cell if is_canned(r.text))
        rows.append(
            {
                "model": model,
                "language": language,
                "framing": framing,
                "responses": len(cell),
                "canned": canned,
                "non_response_rate_pct": round(100 * canned / len(cell), 1),
            }
        )
    return rows


def length_summary(responses: Iterable[Response]) -> list[dict[str, object]]:
    """Response-length distribution per ``model x language``, in that language's unit.

    Canned non-responses are excluded: a refusal is not a short answer, and
    including one would move the percentile that defines a "minimal" answer.
    """
    cells: dict[tuple[str, str], list[int]] = defaultdict(list)
    for response in responses:
        if is_canned(response.text):
            continue
        cells[(response.model, response.language)].append(
            length_in_units(response.text, response.language)
        )

    rows: list[dict[str, object]] = []
    for (model, language), lengths in sorted(cells.items()):
        ordered = sorted(lengths)
        rows.append(
            {
                "model": model,
                "language": language,
                "unit": "words" if language == "en" else "cjk_ideographs",
                "n": len(ordered),
                "median": statistics.median(ordered),
                "p10": round(percentile(ordered, 10), 1),
                "p25": round(percentile(ordered, 25), 1),
                "p75": round(percentile(ordered, 75), 1),
                "max": ordered[-1],
            }
        )
    return rows


def percentile(ordered: Sequence[int], pct: float) -> float:
    """Linear-interpolated percentile of an already-sorted sequence.

    Matches numpy's default so these numbers can be compared with the figures
    without a method difference being mistaken for a data difference.
    """
    if not ordered:
        raise ValueError("percentile of an empty sequence")
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * pct / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    """Write rows to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def print_table(title: str, rows: Sequence[dict[str, object]]) -> None:
    """Print rows as an aligned table under ``title``."""
    print(f"\n{title}")
    if not rows:
        print("  (no rows)")
        return
    columns = list(rows[0])
    widths = {
        column: max(len(column), *(len(str(row[column])) for row in rows))
        for column in columns
    }
    print("  " + "  ".join(column.ljust(widths[column]) for column in columns))
    for row in rows:
        print("  " + "  ".join(str(row[column]).ljust(widths[column]) for column in columns))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "analysis")
    args = parser.parse_args(argv)

    try:
        responses = read_corpus(args.data_dir)
        check_empties(responses)
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    versions = sorted({r.corpus_version for r in responses})
    models = sorted({r.model for r in responses})
    print(f"{len(responses)} responses from {args.data_dir}")
    print(f"corpus version(s): {', '.join(versions)}")
    print(f"models: {', '.join(models)}")

    unknown = find_unknown_templates(responses)
    if unknown:
        print(f"\nWARNING: {len(unknown)} repeated response(s) match no known template:")
        for count, text in unknown:
            print(f"  {count:4d}x  {text[:70]!r}")
    else:
        print("no unknown repeated responses: the two templates account for all repeats")

    tables = {
        "non_response_by_cell": non_response_counts(responses),
        "non_response_by_origin": non_response_by_origin(responses),
        "non_response_by_framing": non_response_by_framing(responses),
        "length_summary": length_summary(responses),
    }

    print_table("Table 1 - non-response by model and language", tables["non_response_by_cell"])
    print_table("Table 2 - non-response by scenario origin", tables["non_response_by_origin"])
    print_table("Table 3 - non-response by framing", tables["non_response_by_framing"])
    print_table("Table 4 - response length (canned excluded)", tables["length_summary"])

    for name, rows in tables.items():
        write_csv(args.out / f"{name}.csv", rows)
    print(f"\nwrote {len(tables)} CSV files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
