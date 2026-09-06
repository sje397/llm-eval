#!/usr/bin/env python3
"""Build a LanceDB semantic index from parsed Wikipedia SQLite.

Loads (title, intro) pairs from the parser's SQLite output, embeds the
intros with a per-language bge-small model (mlx-embeddings, direct load for
throughput), and writes a LanceDB table with an IVF_PQ index for fast ANN
search. The service reads the SAME per-language model at query time, so index
and query vectors live in the same space.

Usage:
  python3 indexer.py --sqlite parsed/en.sqlite --index index/en.lance --lang en
"""

import argparse
import os
import sqlite3
import time

import lancedb
import numpy as np
from mlx_embeddings import load, generate

BATCH_SIZE = (int(os.environ["WIKI_BATCH_SIZE"])
              if "WIKI_BATCH_SIZE" in os.environ else 512)
MAX_TOKENS = (int(os.environ["WIKI_MAX_TOKENS"])
              if "WIKI_MAX_TOKENS" in os.environ else 128)
IVF_NUM_PARTITIONS = (int(os.environ["WIKI_IVF_PARTITIONS"])
                      if "WIKI_IVF_PARTITIONS" in os.environ else 256)
# Per-language embedding models: small BERT-class models are ~17x faster than
# bge-m3 (570M) on MPS and plenty for fact-check retrieval. Index and query
# embeddings MUST share a model, so service.py picks the same model per lang.
DEFAULT_MODELS = {
    "en": "/Users/sje/.omlx/models/mlx-community/bge-small-en-v1.5-bf16",
    "zh": "/Users/sje/.omlx/models/bge-small-zh-v1.5-mlx",
}
# Wikipedia intros front-load entities; rankings identical at 256/128/64.
# Raising MAX_TOKENS improves recall on long intros but costs index time.


def _embed_fn(model, tokenizer):
    def embed(texts):
        out = generate(model, tokenizer, texts, max_length=MAX_TOKENS,
                       padding=True, truncation=True)
        if hasattr(out, "text_embeds") and out.text_embeds is not None:
            return out.text_embeds
        if hasattr(out, "pooler_output") and out.pooler_output is not None:
            return out.pooler_output
        return out.last_hidden_state
    return embed


def load_articles(sqlite_path: str):
    """Yield (title, intro) tuples for articles with a non-empty intro."""
    conn = sqlite3.connect(sqlite_path)
    conn.execute("PRAGMA query_only=ON")
    cur = conn.execute(
        "SELECT title, intro FROM articles WHERE intro != '' "
        # Skip redirect-marker junk ('重定向 X' from the old serial zh parser)
        # and heavily polluted intros (cleaner leaks / raw template residue).
        "AND intro NOT LIKE '重定向%' AND intro NOT LIKE 'Redirect%' "
        "AND instr(intro, '{{') = 0 AND intro NOT LIKE '|%' ORDER BY rowid")
    while True:
        rows = cur.fetchmany(10000)
        if not rows:
            break
        for title, intro in rows:
            yield title, intro
    conn.close()


def main(sqlite_path: str, index_path: str, lang: str, model_path: str | None = None) -> None:
    t0 = time.time()
    model_path = model_path or DEFAULT_MODELS[lang]
    print(f"loading model from {model_path} ...")
    model, tokenizer = load(model_path)
    embed = _embed_fn(model, tokenizer)

    db = lancedb.connect(index_path)
    table_name = lang
    if table_name in db.table_names():
        db.drop_table(table_name)

    # First pass: count articles with intros (for progress reporting)
    conn = sqlite3.connect(sqlite_path)
    total = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE intro != '' "
        "AND intro NOT LIKE '重定向%' AND intro NOT LIKE 'Redirect%' "
        "AND instr(intro, '{{') = 0 AND intro NOT LIKE '|%'").fetchone()[0]
    conn.close()
    print(f"{total:,} articles with intros")

    batch_titles: list[str] = []
    batch_texts: list[str] = []
    n_done = 0

    def flush(table):
        nonlocal batch_titles, batch_texts, n_done
        if not batch_texts:
            return
        vecs = np.asarray(embed(batch_texts))
        rows = [
            {"title": t, "intro": tx, "vector": vecs[i].astype(np.float32)}
            for i, (t, tx) in enumerate(zip(batch_titles, batch_texts))
        ]
        table.add(rows)
        n_done += len(rows)
        elapsed = time.time() - t0
        rate = n_done / elapsed if elapsed > 0 else 0
        pct = 100.0 * n_done / total if total else 100.0
        print(f"\r{lang}: {n_done:,}/{total:,} ({pct:.1f}%) {rate:.0f}/s "
              f"eta {(total-n_done)/rate:.0f}s", end="", flush=True)
        batch_titles = []
        batch_texts = []

    # Create the table once with an explicit schema (dim comes from the
    # model), then reuse the handle — db.open_table per batch costs a
    # manifest read each time.
    import pyarrow as pa

    dim = None
    for title, intro in load_articles(sqlite_path):
        batch_titles.append(title)
        batch_texts.append(intro)
        if len(batch_texts) >= BATCH_SIZE:
            vecs = np.asarray(embed(batch_texts))
            if dim is None:
                dim = vecs.shape[1]
                schema = pa.schema([
                    pa.field("title", pa.string()),
                    pa.field("intro", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), dim)),
                ])
                table = db.create_table(table_name, schema=schema, mode="overwrite")
            rows = [
                {"title": t, "intro": tx, "vector": vecs[i].astype(np.float32)}
                for i, (t, tx) in enumerate(zip(batch_titles, batch_texts))
            ]
            table.add(rows)
            n_done += len(rows)
            batch_titles = []
            batch_texts = []
            elapsed = time.time() - t0
            rate = n_done / elapsed if elapsed > 0 else 0
            pct = 100.0 * n_done / total if total else 100.0
            print(f"\r{lang}: {n_done:,}/{total:,} ({pct:.1f}%) {rate:.0f}/s "
                  f"eta {(total-n_done)/rate:.0f}s", end="", flush=True)

    if batch_texts:
        vecs = np.asarray(embed(batch_texts))
        if dim is None:
            dim = vecs.shape[1]
            schema = pa.schema([
                pa.field("title", pa.string()),
                pa.field("intro", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), dim)),
            ])
            table = db.create_table(table_name, schema=schema, mode="overwrite")
        rows = [
            {"title": t, "intro": tx, "vector": vecs[i].astype(np.float32)}
            for i, (t, tx) in enumerate(zip(batch_titles, batch_texts))
        ]
        table.add(rows)
        n_done += len(rows)

    print(f"\n{lang}: {n_done:,} vectors written in {time.time()-t0:.0f}s")

    # Build the ANN index for fast retrieval
    print("creating IVF_PQ index ...")
    table = db.open_table(table_name)
    t1 = time.time()
    table.create_index(
        metric="cosine",
        num_partitions=IVF_NUM_PARTITIONS,
        num_sub_vectors=32,
        index_type="IVF_PQ",
    )
    print(f"index created in {time.time()-t1:.0f}s")

    # Sanity check: search for a known topic
    probe = embed(["Taiwan presidential election 2024"])
    results = table.search(np.asarray(probe[0]).astype(np.float32)).limit(3).to_list()
    print("probe results:")
    for r in results:
        dist = r.get("_distance", 0.0)
        print(f"  dist={dist:.4f}  {r['title']}")

    print(f"index written to {index_path} ({lang})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Index Wikipedia intros with a per-language bge-small model")
    ap.add_argument("--sqlite", required=True, help="parser output SQLite path")
    ap.add_argument("--index", required=True, help="LanceDB index directory")
    ap.add_argument("--lang", required=True, help="language code (en|zh)")
    ap.add_argument("--model", default=None, help="override embedding model path")
    args = ap.parse_args()
    main(args.sqlite, args.index, args.lang, args.model)
