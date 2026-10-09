#!/usr/bin/env python3
"""LLMEV-145 - pipeline architecture diagram.

Source of truth is the CODE and the design doc, not prose recollection: the module
list is parsed out of docs/module-design.md and every module file it names is
checked to exist on disk before anything is drawn (see verify()).

THE SIX-OR-SEVEN QUESTION
    docs/module-design.md says "composed of six independent, composable modules"
    (line 5) and then numbers SEVEN entries (1..7). The team's tender draft, held
    outside this repository because it carries internal planning figures, says
    "6 modules". Those are not in conflict once you ask what a module is:

        src/pipeline/ holds 8 files - index.ts (the orchestrator, not a module),
        types.ts, and six functional modules.

    types.ts is "pure TypeScript interfaces ... no runtime code" by the doc's own
    description, so it is shared vocabulary, not a processing stage. The prose count
    (six) and the tender count (six) are correct; the doc's NUMBERING is what is
    wrong, because it lists shared types as entry 1 of 7.

    This script asserts that reconciliation rather than asserting it in a caption,
    so if anyone adds a seventh real module the diagram stops building.

Usage: python scripts/diagram_architecture.py [out_dir]
Default out_dir: docs/diagrams
"""
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/diagrams"
os.makedirs(OUT, exist_ok=True)

NAVY, MID, AMBER, GREY, GREEN, ICE = "#1E2761", "#3E5199", "#D98A2B", "#6B7280", "#2E7D5B", "#CADCFC"
plt.rcParams.update({"font.family": "DejaVu Sans"})

DESIGN = "docs/module-design.md"
TENDER = "docs/tender-deliverables-hours-timeline.md"
PIPELINE_DIR = "src/pipeline"

# The six processing stages, in data-flow order, as (name, file, what it does).
# Kept here and checked against the doc below, so a rename in one place is caught.
STAGES = [
    ("Translator", "translator.ts", "EN <-> ZH, using the LLM itself"),
    ("LLM Client", "llm-client.ts", "4 slots x OpenAI-compatible"),
    ("Refusal Detector", "refusal-detector.ts", "heuristic, EN + ZH patterns"),
    ("Fact Extractor", "fact-extractor.ts", "response -> atomic claims"),
    ("Fact Verifier", "fact-verifier.ts", "claims vs Wikipedia evidence"),
    ("Bias Aggregator", "aggregator.ts", "indicators -> bias score"),
]
NON_MODULE = ("types.ts", "index.ts")  # shared types, and the orchestrator


# ------------------------------------------------------------------ svg output
def stabilise_svg(path):
    """Rewrite matplotlib's clip-path ids, which are derived from object addresses.

    Every other byte of the SVG is deterministic, so without this a regenerated file
    differs from the committed one in those ids alone and each run is a spurious
    diff. Mapping them in order of first appearance makes the output byte-stable -
    checked by running the script twice and comparing hashes.
    """
    text = open(path, encoding="utf-8", newline="").read()
    names = {}

    def _sub(m):
        prefix, old = m.group(1), m.group(2)
        if old not in names:
            names[old] = "clipPath%d" % len(names)
        return prefix + names[old]

    text, n = re.subn(r'(url\(#|id=")(p[0-9a-f]{8,})', _sub, text)
    if n:
        open(path, "w", encoding="utf-8", newline="").write(text)
    dangling = set(re.findall(r'url\(#([^)]+)\)', text)) - set(re.findall(r'id="([^"]+)"', text))
    assert not dangling, "stabilised SVG has a dangling reference: %s" % sorted(dangling)


# ----------------------------------------------------------------- verification
def verify():
    """Reconcile the counts and check every named file exists. Raise rather than draw."""
    doc = open(DESIGN, encoding="utf-8").read()

    headings = re.findall(r"^###\s+(\d+)\.\s+(.+?)\s*\(`([^`]+)`\)\s*$", doc, re.M)
    assert len(headings) == 7, f"expected 7 numbered entries in {DESIGN}, found {len(headings)}"
    numbered_files = [h[2] for h in headings]

    prose = re.search(r"composed of\s+(\w+)\s+independent, composable modules", doc)
    assert prose, f"could not find the module-count sentence in {DESIGN}"
    words = {"six": 6, "seven": 7, "five": 5, "eight": 8}
    prose_count = words.get(prose.group(1).lower())
    assert prose_count == 6, f"{DESIGN} prose claims {prose.group(1)!r} modules"

    on_disk = sorted(f for f in os.listdir(PIPELINE_DIR) if f.endswith(".ts"))
    for f in numbered_files:
        assert f in on_disk, f"{DESIGN} names {f}, which is not in {PIPELINE_DIR}/"

    functional = [f for f in numbered_files if f not in NON_MODULE]
    assert len(functional) == 6, f"expected 6 functional modules, derived {len(functional)}"
    assert set(f for _, f, _ in STAGES) == set(functional), (
        "STAGES and the doc disagree on WHICH modules exist:\n"
        f"  script: {sorted(f for _, f, _ in STAGES)}\n  doc   : {sorted(functional)}"
    )

    # Order comes from the doc's stated FLOW, not from its module LIST. The list
    # numbers LLM Client (2) before Translator (3); the flow - and the orchestrator
    # line - translate the scenario BEFORE querying the slots. Checking order against
    # the list would have forced the diagram to draw a flow the doc does not describe.
    flow_block = doc[doc.index("## Architecture Overview"):doc.index("## Modules")]
    FLOW_TO_FILE = {
        "Translate": "translator.ts", "Query 4 slots": "llm-client.ts",
        "Detect Refusals": "refusal-detector.ts", "Extract Facts": "fact-extractor.ts",
        "Verify Facts": "fact-verifier.ts", "Score Bias": "aggregator.ts",
    }
    flow_all = [s for s in re.findall(r"\[([^\]]+)\]", flow_block) if s in FLOW_TO_FILE]
    assert len(flow_all) == 6, f"expected 6 flow stages in {DESIGN}, found {flow_all}"
    flow_order = [FLOW_TO_FILE[s] for s in flow_all]
    assert flow_order == [f for _, f, _ in STAGES], (
        "the drawn order must match the doc's stated data flow:\n"
        f"  script: {[f for _, f, _ in STAGES]}\n  flow  : {flow_order}"
    )
    list_order = functional
    flows_differ = flow_order != list_order

    # The tender's count, which is the claim the diagram exists to substantiate.
    # That document is present in the working tree but deliberately untracked - it is an
    # unreviewed draft and this repository is public, so .gitignore holds it out. It is
    # read when it is there, so this cross-check is CONDITIONAL: it asserts when the file
    # is present and says so when it is not. Every check above is unconditional, so a
    # clean clone still verifies the drawn structure from the code and the design doc -
    # it just cannot check the tender.
    tender_claim = None
    if os.path.exists(TENDER):
        tender = open(TENDER, encoding="utf-8").read()
        m = re.search(r"Architecture,\s*(\d+)\s*modules", tender)
        assert m, f"could not find the module count in {TENDER}"
        tender_claim = int(m.group(1))
        assert tender_claim == 6, f"{TENDER} claims {tender_claim} modules"
    assert len(on_disk) == 8, f"expected 8 files in {PIPELINE_DIR}/, found {len(on_disk)}"

    cross = (f"{TENDER} says {tender_claim}" if tender_claim is not None
             else f"NOT cross-checked against {TENDER} (absent - untracked here)")
    print(f"verified: {DESIGN} numbers {len(headings)} entries, prose says "
          f"{prose.group(1)}; {cross}")
    print(f"verified: {PIPELINE_DIR}/ holds {len(on_disk)} files = 6 modules "
          f"+ {', '.join(NON_MODULE)}")
    print(f"verified: drawn order matches the doc's data flow"
          f"{'; the module LIST is numbered in a different order' if flows_differ else ''}")
    return numbered_files


# ---------------------------------------------------------------------- drawing
FIG_W, FIG_H = 17.5, 9.6


def in_w(ax, fig, data_w):
    """Width of `data_w` x-data units, in INCHES.

    The axes do not span the figure - the default axes box is ~0.775 of the figure
    width - so a data-unit width is NOT `data_w * FIG_W`. Using the figure width
    overestimates every box by ~1.29x, and because fit() only ever SHRINKS, an
    overestimated budget silently disables the shrink: the label overruns its border
    instead of being scaled to it. Convert through the axes box.
    """
    x0, x1 = ax.get_xlim()
    return data_w * ax.get_position().width * fig.get_figwidth() / (x1 - x0)


def fit(ax, fig, x, y, s, ref, max_w_in, **kw):
    """Draw `s` at `ref` points, shrinking until it fits `max_w_in` inches.

    Measured through the renderer, not estimated - a character-width rule of thumb
    is wrong by enough to clip a box, and a clipped label in a report is worse than
    a small one.
    """
    t = ax.text(x, y, s, fontsize=ref, **kw)
    fig.canvas.draw()
    w = t.get_window_extent(renderer=fig.canvas.get_renderer()).width / fig.dpi
    if w > max_w_in:
        t.set_fontsize(ref * max_w_in / w)
    return t


def wrap(text, n):
    """Wrap by hand: fit() shrinks, it does not wrap."""
    out, cur = [], ""
    for wd in text.split():
        trial = f"{cur} {wd}".strip()
        if len(trial) > n and cur:
            out.append(cur)
            cur = wd
        else:
            cur = trial
    out.append(cur)
    return out


def box(ax, x, y, w, h, colour, fill="white", dashed=False, zorder=2):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.004,rounding_size=0.012",
        linewidth=1.4, edgecolor=colour, facecolor=fill, zorder=zorder,
        linestyle=(0, (4, 3)) if dashed else "solid"))


def panel(ax, fig, x, y, w, h, colour, title, lines, fill="white", dashed=False,
          ref=10.6, body=8.0, title_pad=0.028, line_h=0.024):
    """A titled box whose text is measured against the box's true inch width."""
    box(ax, x, y, w, h, colour, fill=fill, dashed=dashed)
    avail = in_w(ax, fig, w - 0.030)
    fit(ax, fig, x + 0.015, y + h - title_pad, title, ref=ref, max_w_in=avail,
        fontweight="bold", color=colour, va="center", zorder=4)
    for j, ln in enumerate(lines):
        fit(ax, fig, x + 0.015, y + h - title_pad - 0.028 - j * line_h, ln,
            ref=body, max_w_in=avail, color="#333333", va="center", zorder=4)


def main():
    verify()

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    ax.set_xlim(-0.008, 1.012)
    ax.set_ylim(0, 1)
    ax.axis("off")

    panel(ax, fig, 0.02, 0.885, 0.96, 0.075, NAVY,
          "Pipeline Orchestrator  (src/pipeline/index.ts)",
          ["Scenario -> translate -> 4 slots -> refuse -> extract -> verify -> score"],
          fill="#F4F6FC", ref=13)
    # the orchestrator's single body line reads as a caption, so lift it to the right
    ax.texts[-1].set_position((0.968, 0.933))
    ax.texts[-1].set_ha("right")
    ax.texts[-1].set_color(MID)
    ax.texts[-1].set_fontsize(9)

    panel(ax, fig, 0.02, 0.775, 0.96, 0.062, AMBER,
          "Types  (src/pipeline/types.ts)  -  shared interfaces, no runtime code",
          ["entry 1 of 7 in module-design.md, but NOT a module: this is why the doc says six and lists seven"],
          fill="#FDF6EC", dashed=True, ref=10.5, body=8.6)
    ax.texts[-1].set_position((0.968, 0.806))
    ax.texts[-1].set_ha("right")
    ax.texts[-1].set_color(AMBER)
    ax.texts[-1].set_style("italic")

    # ---- the six stages
    n = len(STAGES)
    x0, x1, gap = 0.095, 0.905, 0.013
    bw = ((x1 - x0) - gap * (n - 1)) / n
    by, bh = 0.545, 0.185
    badge_w, title_x, pad_r = 0.024, 0.034, 0.012
    centres = []
    for i, (name, fname, role) in enumerate(STAGES):
        bx = x0 + i * (bw + gap)
        centres.append(bx + bw / 2)
        box(ax, bx, by, bw, bh, MID)
        ax.add_patch(FancyBboxPatch(
            (bx + 0.007, by + bh - 0.052), badge_w, 0.040,
            boxstyle="round,pad=0.002,rounding_size=0.006",
            linewidth=0, facecolor=MID, alpha=0.16, zorder=3))
        ax.text(bx + 0.007 + badge_w / 2, by + bh - 0.032, str(i + 1), fontsize=10,
                color=MID, fontweight="bold", ha="center", va="center", zorder=4)
        fit(ax, fig, bx + title_x, by + bh - 0.032, name, ref=10.0,
            max_w_in=in_w(ax, fig, bw - title_x - pad_r),
            fontweight="bold", color=NAVY, va="center", zorder=4)
        fit(ax, fig, bx + 0.010, by + bh - 0.072, fname, ref=7.6,
            max_w_in=in_w(ax, fig, bw - 0.020), color=GREY, va="center", zorder=4,
            family="DejaVu Sans Mono")
        ax.plot([bx + 0.012, bx + bw - 0.012], [by + bh - 0.092] * 2,
                color="#D5DAE6", linewidth=0.9, zorder=3)
        for j, ln in enumerate(wrap(role, 20)[:3]):
            fit(ax, fig, bx + 0.010, by + bh - 0.113 - j * 0.026, ln, ref=8.0,
                max_w_in=in_w(ax, fig, bw - 0.020), color="#333333", va="center", zorder=4)

    for i in range(n - 1):
        p = (x0 + (i + 1) * (bw + gap) - gap, by + bh / 2)
        q = (x0 + (i + 1) * (bw + gap), by + bh / 2)
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=12,
                                     linewidth=1.3, color=GREY, zorder=1))

    # ---- scenario in / result out
    box(ax, 0.004, by + 0.045, 0.076, 0.095, GREEN, fill="#F1F8F4")
    ax.text(0.042, by + 0.092, "Scenario", fontsize=9, color=GREEN, ha="center",
            va="center", fontweight="bold", zorder=4)
    ax.add_patch(FancyArrowPatch((0.080, by + bh / 2), (x0, by + bh / 2),
                                 arrowstyle="-|>", mutation_scale=12, linewidth=1.3,
                                 color=GREEN, zorder=1))
    box(ax, 0.918, by + 0.045, 0.076, 0.095, GREEN, fill="#F1F8F4")
    ax.text(0.956, by + 0.092, "Result", fontsize=9, color=GREEN, ha="center",
            va="center", fontweight="bold", zorder=4)
    ax.add_patch(FancyArrowPatch((x1, by + bh / 2), (0.918, by + bh / 2),
                                 arrowstyle="-|>", mutation_scale=12, linewidth=1.3,
                                 color=GREEN, zorder=1))

    ax.add_patch(FancyArrowPatch((0.5, 0.885), (0.5, by + bh + 0.004),
                                 arrowstyle="-|>", mutation_scale=12, linewidth=1.1,
                                 color="#B9C0CE", zorder=1))

    # ---- external services
    ey, eh = 0.245, 0.155
    panel(ax, fig, 0.020, ey, 0.300, eh, NAVY, "oMLX  (OpenAI-compatible backend)",
          ["one endpoint per model slot; MOCK_MODE=true",
           "returns distinct canned responses per slot",
           "so the demo runs with no models loaded",
           "Qwen3.8-Flash-Next-oQ4e-mtp on Mimir :21434"], fill="#F4F6FC")
    panel(ax, fig, 0.352, ey, 0.305, eh, GREEN, "Wikipedia semantic search  (V6)",
          ["FastAPI :21500 on Mimir, tunneled to the box",
           "LanceDB IVF_PQ, mlx-embeddings",
           "6,988,632 EN + 1,513,737 ZH articles",
           "replaced the Wikimedia keyword API in V6"], fill="#F1F8F4")
    panel(ax, fig, 0.700, ey, 0.280, eh, GREY, "Wikimedia API  (fallback only)",
          ["reached only if the local service is",
           "unreachable; superseded, not removed"], fill="#F7F8FA", dashed=True)

    ax.add_patch(FancyArrowPatch((centres[1], by), (0.170, ey + eh),
                                 arrowstyle="-|>", mutation_scale=13, linewidth=1.2,
                                 color=NAVY, shrinkA=2, shrinkB=2, zorder=1))
    ax.text(centres[1] - 0.062, ey + eh + 0.046, "4 model slots", fontsize=8.6,
            color=NAVY, ha="center", va="center", style="italic", zorder=5,
            bbox=dict(boxstyle="round,pad=0.20", facecolor="white", edgecolor="none"))
    ax.add_patch(FancyArrowPatch((centres[4], by), (0.5045, ey + eh),
                                 arrowstyle="-|>", mutation_scale=13, linewidth=1.2,
                                 color=GREEN, shrinkA=2, shrinkB=2, zorder=1))
    ax.add_patch(FancyArrowPatch((0.657, ey + eh / 2), (0.700, ey + eh / 2),
                                 arrowstyle="-|>", mutation_scale=11, linewidth=1.0,
                                 color=GREY, linestyle=(0, (3, 3)), zorder=1))

    # ---- V6 verification detail
    steps = ("1 extract entity titles + queries  ->  2 constrained text search (intitle OR) + unconstrained supplement  ->  "
             "3 merge, dedupe, primary-entity filter  ->  4 fetch full article text (12,000 chars)  ->  "
             "5 split + score paragraphs (>=2 word tokens / 3 CJK bigrams)  ->  6 boost intitle-gated 1.3x, entity-matched 1.5x  ->  "
             "7 top 3 paragraphs + the fact -> judge")
    panel(ax, fig, 0.352, 0.075, 0.628, 0.145, GREEN,
          "V6 verification chain (fact-verifier.ts)  -  why the retrieval service exists",
          wrap(steps, 104)[:4], ref=10.0)

    ax.text(0.5, 1.012,
            "LLMEV-145 - Pipeline architecture: one orchestrator, six composable modules, shared types",
            fontsize=15, fontweight="bold", color=NAVY, ha="center", va="bottom")

    fig.text(0.010, -0.010,
             "The doc's own prose says the pipeline is 'composed of six independent, composable modules', and the tender quotes six. "
             "src/pipeline/ holds 8 files: index.ts (the orchestrator) and types.ts (interfaces only, no runtime code) are not modules, which leaves exactly six.\n"
             "The Modules section of module-design.md numbers seven entries because it lists the shared types as entry 1 - that numbering is the only thing inconsistent, and this diagram draws the six.\n"
             "A second, smaller divergence: that section numbers LLM Client (2) before Translator (3), while its own data-flow block and orchestrator line translate the scenario BEFORE querying the four slots. "
             "This diagram follows the FLOW, because that is what the pipeline executes.",
             fontsize=8.4, color=GREY, va="top", ha="left", linespacing=1.6)

    fig.text(0.010, -0.098,
             "Modules are composable through the interfaces in types.ts, so each stage can be replaced without touching the others (five named extension points in the design doc). "
             "Mock mode makes the whole chain runnable with no model loaded.\n"
             "Verification evidence for the Wikipedia chain is the V6 record in module-design.md, which enumerates five failed approaches (V0 model-only, V1 snippets, V2 LLM queries, V3 intros, V4 full-text) before the V6 semantic retrieval that replaced them.",
             fontsize=7.8, color=AMBER, va="top", ha="left", linespacing=1.6)

    # metadata Date=None: matplotlib stamps the generation time into the SVG's
    # <dc:date>, which makes every regeneration a diff. That SVG is committed, so
    # it is written byte-reproducible instead - run twice, get the same bytes.
    fig.savefig(os.path.join(OUT, "architecture.png"), dpi=200, bbox_inches="tight",
                facecolor="white", metadata={"Date": None})
    fig.savefig(os.path.join(OUT, "architecture.svg"), bbox_inches="tight",
                facecolor="white", metadata={"Date": None})
    print("wrote", os.path.join(OUT, "architecture.png"))
    stabilise_svg(os.path.join(OUT, "architecture.svg"))
    print("wrote", os.path.join(OUT, "architecture.svg"))


if __name__ == "__main__":
    main()
