#!/usr/bin/env python3
"""Parallel Wikipedia dump parser: bz2 XML -> SQLite.

Three passes (the serial bottleneck is bz2 decompression, ~10 min for EN;
the parse+clean+zlib work that would take ~4h single-core parallelizes):

  1. split_dump : decompress the bz2 once, round-robin <page> elements into
                  N chunk XML files (uncompressed)
  2. parse_chunk: parse chunks in parallel (multiprocessing) into per-chunk
                  SQLite databases
  3. merge      : merge chunk DBs into the final SQLite

Output schema (same as the serial parser):
  articles(title TEXT PK, intro TEXT, full_text BLOB zlib, text_len INT)
  redirects(title TEXT PK, target TEXT)

Usage:
  python3 parser.py --dump enwiki-latest-pages-articles.xml.bz2 \
      --out parsed/en.sqlite --lang en [--chunks 8] [--max-pages N]
"""

import argparse
import bz2
import multiprocessing as mp
import os
import re
import sqlite3
import sys
import time
import zlib

from lxml import etree

from cleaner import extract_intro

REDIRECT_RE = re.compile(r"^#\s*redirect\s*\[\[([^\]|]+)", re.I)
DEFAULT_CHUNKS = 8
COMMIT_EVERY = 5000


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _find_namespace(fh) -> str:
    """Read the root element to discover the MediaWiki XML namespace."""
    root = etree.iterparse(fh, events=("start",))
    for _, elem in root:
        tag = elem.tag
        elem.clear()
        if isinstance(tag, str) and tag.endswith("mediawiki"):
            return tag[: -len("mediawiki")]
    raise RuntimeError("could not find mediawiki root element")


def process_page(title: str, ns_code: int, wikitext: str):
    """Process one page -> (article_tuple|None, redirect_tuple|None)."""
    if ns_code != 0 or not title or not wikitext:
        return None, None
    m = REDIRECT_RE.match(wikitext.strip())
    if m:
        return None, (title, m.group(1).strip())
    intro = extract_intro(wikitext)
    return (
        (title, intro, zlib.compress(wikitext.encode("utf-8"), level=1), len(wikitext)),
        None,
    )


def _progress(label: str, done: int, total: int | None, t0: float) -> None:
    elapsed = time.time() - t0
    rate = done / elapsed if elapsed > 0 else 0
    pct = f"{100.0 * done / total:.1f}%" if total else f"{done:,}"
    eta = f" eta {(total - done) / rate:.0f}s" if total and rate > 0 else ""
    print(f"\r{label}: {done:,} pages ({pct}) {rate:.0f}/s{eta} "
          f"[{elapsed:.0f}s]", end="", flush=True)


# ---------------------------------------------------------------------------
# pass 1: split
# ---------------------------------------------------------------------------

def split_dump(dump_path: str, chunk_dir: str, n_chunks: int = DEFAULT_CHUNKS,
               max_pages: int | None = None) -> list[str]:
    """Decompress once, round-robin pages into chunk XML files."""
    os.makedirs(chunk_dir, exist_ok=True)
    t0 = time.time()

    with bz2.open(dump_path, "rb") as raw:
        ns = _find_namespace(raw)

    chunk_paths = [os.path.join(chunk_dir, f"chunk-{i:02d}.xml") for i in range(n_chunks)]
    # truncate existing chunks (idempotent re-run)
    handles = []
    for p in chunk_paths:
        handles.append(open(p, "wb"))
    # ns is lxml Clark notation "{uri}" — write a real xmlns declaration
    ns_uri = ns[1:-1]
    root_tag = f'<mediawiki xmlns="{ns_uri}">\n'.encode()
    for h in handles:
        h.write(root_tag)

    n_pages = 0
    with bz2.open(dump_path, "rb") as raw:
        page_tag = f"{ns}page"
        context = etree.iterparse(raw, events=("end",), tag=page_tag)
        for _, page in context:
            data = etree.tostring(page)
            handles[n_pages % n_chunks].write(data)
            n_pages += 1
            page.clear()
            while page.getprevious() is not None:
                del page.getparent()[0]
            if n_pages % 100_000 == 0:
                _progress("split", n_pages, None, t0)
            if max_pages and n_pages >= max_pages:
                break

    close_tag = b"</mediawiki>\n"
    for h in handles:
        h.write(close_tag)
        h.close()

    print(f"\nsplit: {n_pages:,} pages -> {n_chunks} chunks in {time.time() - t0:.0f}s")
    return chunk_paths


# ---------------------------------------------------------------------------
# pass 2: parallel chunk parse
# ---------------------------------------------------------------------------

def parse_chunk(args) -> tuple[int, int, str]:
    chunk_path, chunk_sqlite, lang = args
    t0 = time.time()
    conn = sqlite3.connect(chunk_sqlite)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            title TEXT PRIMARY KEY,
            intro TEXT NOT NULL,
            full_text BLOB NOT NULL,
            text_len INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS redirects (
            title TEXT PRIMARY KEY,
            target TEXT NOT NULL
        );
    """)

    n_articles = 0
    n_redirects = 0
    n_skipped = 0
    batch_articles = []
    batch_redirects = []

    with open(chunk_path, "rb") as f:
        ns = _find_namespace(f)
        f.seek(0)
        page_tag = f"{ns}page"
        context = etree.iterparse(f, events=("end",), tag=page_tag)
        for _, page in context:
            title_el = page.find(f"{ns}title")
            ns_el = page.find(f"{ns}ns")
            text_el = page.find(f"{ns}revision/{ns}text")

            title = title_el.text or "" if title_el is not None else ""
            ns_code = int(ns_el.text or "0") if ns_el is not None else 0
            wikitext = text_el.text or "" if text_el is not None else ""

            article, redirect = process_page(title, ns_code, wikitext)
            if article:
                batch_articles.append(article)
                n_articles += 1
            elif redirect:
                batch_redirects.append(redirect)
                n_redirects += 1
            else:
                n_skipped += 1

            page.clear()
            while page.getprevious() is not None:
                del page.getparent()[0]

            if len(batch_articles) >= COMMIT_EVERY:
                conn.executemany("INSERT OR REPLACE INTO articles VALUES (?,?,?,?)", batch_articles)
                conn.executemany("INSERT OR REPLACE INTO redirects VALUES (?,?)", batch_redirects)
                conn.commit()
                batch_articles.clear()
                batch_redirects.clear()

    if batch_articles or batch_redirects:
        conn.executemany("INSERT OR REPLACE INTO articles VALUES (?,?,?,?)", batch_articles)
        conn.executemany("INSERT OR REPLACE INTO redirects VALUES (?,?)", batch_redirects)
        conn.commit()
    conn.close()

    print(f"\r  {os.path.basename(chunk_path)}: {n_articles:,} articles, "
          f"{n_redirects:,} redirects ({time.time() - t0:.0f}s)", flush=True)
    return n_articles, n_redirects, chunk_sqlite


# ---------------------------------------------------------------------------
# pass 3: merge
# ---------------------------------------------------------------------------

def merge_sqlite(chunk_sqlites: list[str], final_path: str) -> None:
    t0 = time.time()
    conn = sqlite3.connect(final_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            title TEXT PRIMARY KEY,
            intro TEXT NOT NULL,
            full_text BLOB NOT NULL,
            text_len INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS redirects (
            title TEXT PRIMARY KEY,
            target TEXT NOT NULL
        );
    """)
    for chunk_db in chunk_sqlites:
        conn.execute("ATTACH DATABASE ? AS src", (chunk_db,))
        conn.execute("BEGIN")
        conn.execute("INSERT OR REPLACE INTO articles SELECT * FROM src.articles")
        conn.execute("INSERT OR REPLACE INTO redirects SELECT * FROM src.redirects")
        conn.execute("COMMIT")
        conn.execute("DETACH DATABASE src")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_len ON articles(text_len)")
    conn.commit()
    conn.close()
    print(f"merged {len(chunk_sqlites)} chunks -> {final_path} in {time.time() - t0:.0f}s")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_dump(dump_path: str, out_path: str, lang: str,
               n_chunks: int = DEFAULT_CHUNKS, max_pages: int | None = None,
               keep_chunks: bool = False) -> None:
    t0 = time.time()
    chunk_dir = os.path.join(os.path.dirname(out_path), f"_chunks_{lang}")
    chunk_paths = split_dump(dump_path, chunk_dir, n_chunks, max_pages)

    chunk_sqlites = [p[:-4] + ".sqlite" for p in chunk_paths]
    tasks = [(cp, cs, lang) for cp, cs in zip(chunk_paths, chunk_sqlites)]

    print(f"parsing {len(tasks)} chunks in parallel ...")
    t1 = time.time()
    with mp.Pool(n_chunks) as pool:
        results = pool.map(parse_chunk, tasks, chunksize=1)

    total_articles = sum(r[0] for r in results)
    total_redirects = sum(r[1] for r in results)
    print(f"chunk parse done: {total_articles:,} articles, {total_redirects:,} "
          f"redirects in {time.time() - t1:.0f}s")

    merge_sqlite(chunk_sqlites, out_path)

    if not keep_chunks:
        for p in chunk_paths + chunk_sqlites:
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(chunk_dir)
        except OSError:
            pass

    print(f"{lang} done: {total_articles:,} articles, {total_redirects:,} redirects "
          f"in {time.time() - t0:.0f}s -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Parallel Wikipedia dump parser")
    ap.add_argument("--dump", required=True, help="path to pages-articles .xml.bz2 dump")
    ap.add_argument("--out", required=True, help="output SQLite path")
    ap.add_argument("--lang", required=True, help="language code (en|zh)")
    ap.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS, help="parallel chunks")
    ap.add_argument("--max-pages", type=int, default=None, help="stop after N pages (testing)")
    ap.add_argument("--keep-chunks", action="store_true", help="keep intermediate chunk files")
    args = ap.parse_args()
    parse_dump(args.dump, args.out, args.lang, args.chunks, args.max_pages, args.keep_chunks)
