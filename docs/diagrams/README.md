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

Neither script needs the network or a model. Both check their inputs on every run and
refuse to draw when a check fails, so a stale source file fails loudly rather than
silently producing a wrong picture.

Being exact about the reach of that, because "verifies its inputs" is easy to read as
"verifies everything in the picture": the architecture script checks three things - that
`module-design.md` numbers as many entries as it has headings, that every module file it
names exists in `src/pipeline/`, and that the order it draws matches the document's own
data-flow block. The data-model script executes every join it asserts against the real
files. Figures quoted into the panels from elsewhere - the article counts, the model
behind the endpoint - are attributed to their source rather than re-derived here, and
should be read as quoted rather than as checked.

Neither script needs the network or a model. Both verify their own inputs on every run
and refuse to draw an unverified claim, so a stale source file fails loudly instead of
silently producing a wrong picture.

**These are not redrawings of an existing diagram.** LLMEV-96 ("Recreate Data Flow
Architecture") is marked Done as of 2026-08-20, so before drawing anything we checked
whether it had already produced one. It carries no description, attachment, comment or
issue link, so it names no artefact; `git ls-files` for image assets returns, besides
these four files, only the nineteen visualisation figures and the web assets; and the
tender draft describes the six modules in prose and contains no diagram. Nothing is
being duplicated. If LLMEV-96's output exists somewhere outside this repository, it is
not here, and this note is the record of that.

One thing about LLMEV-96 is worth noting for whoever revisits this: it is a subtask of
LLMEV-92, "Tender — Read & Review Tender Document", so it most likely reconstructed the
architecture the *tender* describes as part of reviewing that document, whereas this
diagram documents the pipeline as built from the code. The ticket states nothing at all,
so treat that as an inference from its title and parentage, not as a fact. The practical
point holds either way: it names no artefact, and no diagram of the built pipeline
existed in this repository before these two.

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
is implicit and was checked as sets (60/60 matched). Three boxes are tagged *derived*, which is the whole of the fourth data
layer: they come from the LLMEV-107 export (Romit's PR #29, still open), and
`data/processed/` does not yet exist on `main`. The caption counts them from the drawing
rather than restating the number, because those two disagreed once (this README said four,
the caption said three, and three were drawn).

## LLMEV-145 — pipeline architecture

Source of truth is the code plus `docs/module-design.md`: the script parses the module
list out of that document and checks that every module file it names exists on disk
before drawing.

**The six-or-seven question resolves cleanly - but by derivation, not by any sentence the
document contains.** `module-design.md` says the pipeline is "composed of six independent,
composable modules" and then numbers *seven* entries, and it never reconciles the two. The
team's tender draft (`tender-deliverables-hours-timeline.md`, a working draft held out of
the published repository; see `.gitignore`) quotes six.
`src/pipeline/` holds eight files.
`index.ts` is the orchestrator and `types.ts` is interfaces with no runtime code, so
neither is a module, which leaves exactly six - the count the prose supports, arrived at
from the code rather than read off the page. The document's numbering counts the shared
types as entry 1, and that numbering is the only inconsistent thing about it. The diagram
draws six.

A second, smaller divergence is worth knowing: that document numbers `LLM Client` (2)
before `Translator` (3), while its own data-flow block and orchestrator line translate
the scenario *before* querying the four model slots. The diagram follows the execution
order, because that is what the pipeline does.

**One deliberate omission.** The retrieval panel names the stack - `LanceDB IVF_PQ,
mlx-embeddings` - and not the embedding models. `wikipedia-semantic-search/README.md` is
already stale on precisely that detail: it says `bge-m3`, while the indexer and service
use per-language `bge-small-en-v1.5-bf16` and `bge-small-zh-v1.5-mlx`, and that document
flags the mismatch against itself. A second copy of a drifting fact is how the first one
went stale, so this panel states only the part that has not moved and leaves the model
versions in the document that owns them.

Modules are composable through the interfaces in `types.ts`, so each stage can be
replaced without touching the others; the design doc names five extension points. The
whole chain runs with no model loaded under `MOCK_MODE=true`, which returns a distinct
canned response per slot.
