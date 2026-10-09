# Diagrams

Two diagrams that the report embeds, both generated from a committed script rather than
drawn by hand.

| File | Ticket | Script |
|---|---|---|
| `architecture.png` / `.svg` | LLMEV-145 | `scripts/diagram_architecture.py` |
| `data-model.png` / `.svg` | LLMEV-144 | `scripts/diagram_data_model.py` |

Regenerate both (default output directory is this one):

```bash
python scripts/diagram_architecture.py
python scripts/diagram_data_model.py
```

Neither script needs the network or a model. Both verify their own inputs on every run
and refuse to draw an unverified claim, so a stale source file fails loudly instead of
silently producing a wrong picture.

## Why the SVG files are committed here

`docs/visualisation/figures/` tracks only the PNGs and leaves each figure script's SVG
companion uncommitted. This directory keeps both. The difference is deliberate: those
nineteen charts are generated from data files and are read as data, so the PNG is the
artefact. These two are line art that the report prints and that a reader zooms into,
where the vector form is the better master and the PNG is the copy that gets embedded.

Both scripts write their SVG **byte-reproducibly**, which is the precondition for
committing one. Two things in matplotlib's output had to be dealt with first: it stamps
the generation time into the SVG's `dc:date`, and it derives clip-path ids from object
addresses, so an untouched SVG differs on every run. `savefig(..., metadata={"Date":
None})` removes the first; `stabilise_svg()` rewrites the second to a fixed name in order
of first appearance and then asserts that no `url(#...)` reference was left dangling. Run
either script twice and the two SVGs are byte-identical - checked, not assumed. The PNGs
were already stable.

## LLMEV-144 — evaluation data model

Derived from the artefacts, not from prose. The script reads the DDL out of
`data/index.sqlite3` and executes every join it asserts against the real files before
drawing anything.

The shipped schema is a single table, four columns, and no foreign key anywhere:

```sql
CREATE TABLE IF NOT EXISTS "articles" (
    topic_id    TEXT NOT NULL,
    topic       TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    facts_json  TEXT NOT NULL
);
```

The ground-truth layer is therefore one table with the facts denormalised into
`facts_json` as a JSON array - 60 rows, 7,883 facts, 92-382 per article. There is no fact
table, and `topic_id` holds no declared constraint tying it to `scenarios.json`; the join
is implicit and was checked as sets (60/60 matched). Four boxes in the diagram are tagged
*derived*: they come from the LLMEV-107 export (Romit's PR #29, still open), and
`data/processed/` does not yet exist on `main`.

## LLMEV-145 — pipeline architecture

Source of truth is the code plus `docs/module-design.md`: the script parses the module
list out of that document and checks that every module file it names exists on disk
before drawing.

**The six-or-seven question resolves cleanly.** `module-design.md` says the pipeline is
"composed of six independent, composable modules" and then numbers *seven* entries;
`tender-deliverables-hours-timeline.md` quotes six. `src/pipeline/` holds eight files.
`index.ts` is the orchestrator and `types.ts` is interfaces with no runtime code, so
neither is a module, which leaves exactly six. The document's numbering counts the shared
types as entry 1, and that numbering is the only inconsistent thing about it. The diagram
draws six.

A second, smaller divergence is worth knowing: that document numbers `LLM Client` (2)
before `Translator` (3), while its own data-flow block and orchestrator line translate
the scenario *before* querying the four model slots. The diagram follows the execution
order, because that is what the pipeline does.

Modules are composable through the interfaces in `types.ts`, so each stage can be
replaced without touching the others; the design doc names five extension points. The
whole chain runs with no model loaded under `MOCK_MODE=true`, which returns a distinct
canned response per slot.
