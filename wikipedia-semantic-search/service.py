#!/usr/bin/env python3
"""Wikipedia semantic search service for the llm-eval fact-verifier.

Runs on Mímir (port 21500), exposed to the AU server via an autossh
reverse tunnel. Replaces the fact-verifier's direct calls to the public
Wikimedia API with fast local semantic search + full-text retrieval.

Endpoints:
  POST /search   {query, lang, mode?, top_k?, constrain?}
                 -> [{title, score, intro, exact?}] semantic article search.
                    An exact title/redirect match is ALWAYS attempted first and
                    prepended (score 0.0, exact:true) so entity queries like
                    "The Great Leap Forward" surface the precise article even
                    in the default 'text' mode (bge-small intro-ANN is weak for
                    short entity phrases). mode='title' keeps this primary.
  POST /extract  {titles: [], lang, max_chars?}
                 -> [{title, extract, intro, paragraphs}] cleaned full text.
                    Titles are normalized (underscore -> space) so Wikimedia
                    underscore-form titles resolve correctly.
  GET  /article/{lang}/{title}   full article (clean text)
  GET  /health
  GET  /stats

The query embedding is computed by oMLX (/v1/embeddings) using the same
per-language model the indexer used to build the index, so query and index
vectors live in the same space. See README.md for the model + recall notes.
"""

import argparse
import json
import os
import sqlite3
import time
import urllib.request
import zlib
from contextlib import asynccontextmanager
from pathlib import Path

import opencc

import lancedb
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from cleaner import clean_full_text, split_paragraphs

# ---------------------------------------------------------------------------
# config (env-overridable; defaults match the Mímir deployment)
# ---------------------------------------------------------------------------

DEFAULT_PARSED_DIR = Path.home() / "wikipedia" / "parsed"
DEFAULT_INDEX_DIR = Path.home() / "wikipedia" / "index"
# oMLX embedding endpoint. The llm-eval .env defines OMLX_URL (without the
# /v1/embeddings path); the service appends it. Override with the OMLX_URL env
# var to point at a different gateway (e.g. the llm-eval reverse-tunnel port).
OMLX_BASE = os.environ.get("OMLX_URL", "http://localhost:21434").rstrip("/")
OMLX_URL = f"{OMLX_BASE}/v1/embeddings"
OMLX_KEY = os.environ.get("OMLX_KEY", "lmm-api-key")
# Per-language embedding models — MUST match the indexer's models so index
# and query vectors live in the same space. Small BERT-class models (33M/24M)
# are ~17x faster than bge-m3 on MPS; per-language indexes make this safe.
EMBED_MODELS = {
    "en": "bge-small-en-v1.5-bf16",
    "zh": "bge-small-zh-v1.5-mlx",
}
# zhwiki titles/intros are Traditional Chinese; fact queries (translated by
# LLMs) are often Simplified. Convert zh input to Traditional at the boundary
# so SQL lookups, embedding, and constrain filters all see the index's script.
_ZH_CONVERTER = opencc.OpenCC("s2t")


def normalize_zh(text: str, lang: str) -> str:
    return _ZH_CONVERTER.convert(text) if lang == "zh" and text else text


def normalize_title(title: str) -> str:
    """Wikimedia URLs/APIs encode spaces as underscores; the DB stores spaces.

    Normalize both at the boundary so /extract and /article accept underscore
    form ("Great_Leap_Forward") as well as space form ("Great Leap Forward").
    """
    return title.replace("_", " ") if title else title


# ---------------------------------------------------------------------------
# storage handles (initialized at startup)
# ---------------------------------------------------------------------------

class Store:
    def __init__(self, parsed_dir: Path, index_dir: Path):
        self.parsed_dir = parsed_dir
        self.index_dir = index_dir
        self.db = lancedb.connect(str(index_dir))
        self._conns: dict[str, sqlite3.Connection] = {}

    def _conn(self, lang: str) -> sqlite3.Connection:
        if lang not in self._conns:
            path = self.parsed_dir / f"{lang}.sqlite"
            if not path.exists():
                raise HTTPException(404, f"no index for language '{lang}'")
            # check_same_thread=False: FastAPI runs sync endpoints in a thread
            # pool, so the first request that opens a lang's connection may be
            # a different thread than subsequent requests. Reads are safe under
            # the GIL; writes are guarded by PRAGMA query_only=ON.
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.execute("PRAGMA query_only=ON")
            self._conns[lang] = conn
        return self._conns[lang]

    @staticmethod
    def _decompress_full_text(blob) -> str:
        """zlib-decompress the full_text blob; tolerate NULL/empty (redirect stubs)."""
        if not blob:
            return ""
        try:
            return zlib.decompress(blob).decode("utf-8")
        except (zlib.error, UnicodeDecodeError):
            return ""

    def get_article(self, lang: str, title: str):
        title = normalize_title(title)
        row = self._conn(lang).execute(
            "SELECT intro, full_text FROM articles WHERE title = ?", (title,)
        ).fetchone()
        if row:
            return {"title": title, "intro": row[0],
                    "full_text": self._decompress_full_text(row[1])}
        redirect = self._conn(lang).execute(
            "SELECT target FROM redirects WHERE title = ?", (title,)
        ).fetchone()
        if redirect:
            target = redirect[0]
            row = self._conn(lang).execute(
                "SELECT intro, full_text FROM articles WHERE title = ?", (target,)
            ).fetchone()
            if row:
                return {"title": target, "intro": row[0], "redirected_from": title,
                        "full_text": self._decompress_full_text(row[1])}
        return None

    def search(self, lang: str, vector: np.ndarray, top_k: int):
        table = self.db.open_table(lang)
        return table.search(vector).limit(top_k).to_list()

    def close(self):
        for c in self._conns.values():
            c.close()
        self._conns.clear()


store: Store | None = None

# ---------------------------------------------------------------------------
# oMLX query embedding
# ---------------------------------------------------------------------------

def embed_query(text: str, lang: str) -> np.ndarray:
    req = urllib.request.Request(
        OMLX_URL,
        data=json.dumps({"model": EMBED_MODELS[lang], "input": [text]}).encode(),
        headers={"Authorization": f"Bearer {OMLX_KEY}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return np.asarray(data["data"][0]["embedding"], dtype=np.float32)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

_PARSED_DIR = Path(os.environ.get("WIKI_PARSED_DIR", str(DEFAULT_PARSED_DIR)))
_INDEX_DIR = Path(os.environ.get("WIKI_INDEX_DIR", str(DEFAULT_INDEX_DIR)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store
    store = Store(_PARSED_DIR, _INDEX_DIR)
    yield
    if store:
        store.close()


app = FastAPI(title="Wikipedia semantic search", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    lang: str = Field(pattern="^(en|zh)$")
    mode: str = Field(default="text", pattern="^(text|title)$")
    top_k: int = Field(default=5, ge=1, le=20)
    constrain: list[str] = Field(
        default_factory=list,
        description="Result titles must contain at least one of these (case-insensitive). "
                    "Replicates Wikimedia's intitle:a|b OR-title constraint.",
    )


class ExtractRequest(BaseModel):
    titles: list[str] = Field(min_length=1, max_length=20)
    lang: str = Field(pattern="^(en|zh)$")
    max_chars: int = Field(default=12000, ge=500, le=50000)


@app.get("/health")
def health():
    return {"status": "ok", "embed_model": EMBED_MODELS}


@app.get("/stats")
def stats():
    if not store:
        raise HTTPException(503, "store not ready")
    out = {}
    for lang in ("en", "zh"):
        try:
            out[lang] = {"vectors": store.db.open_table(lang).count_rows()}
        except Exception:
            out[lang] = {"vectors": 0}
    return out


@app.post("/search")
def search(req: SearchRequest):
    if not store:
        raise HTTPException(503, "store not ready")
    t0 = time.time()

    query = normalize_zh(req.query, req.lang)
    constrain = [normalize_zh(c, req.lang) for c in (req.constrain or [])]
    results = []

    # Exact title/redirect match first, in BOTH modes. Entity queries such as
    # "The Great Leap Forward" are the common fact-verifier case and should
    # surface the precise article even under the default 'text' mode — bge-small
    # intro-ANN is genuinely weak for short entity phrases (see README).
    # mode='title' keeps this as the primary hit; mode='text' uses it as a
    # precision fallback before falling through to semantic search.
    article = store.get_article(req.lang, query)
    if article:
        results.append({
            "title": article["title"],
            "score": 0.0,  # best cosine distance (0 = identical)
            "exact": True,
            "intro": article["intro"],
        })

    # semantic search over intros
    vector = embed_query(query, req.lang)
    # fetch extra candidates when constraining (filtering shrinks the pool)
    fetch_k = req.top_k * 5 if constrain else req.top_k
    hits = store.search(req.lang, vector, fetch_k)
    seen = {r["title"] for r in results}
    semantic_count = 0
    for h in hits:
        if h["title"] in seen:
            continue
        if constrain:
            tl = h["title"].lower()
            if not any(c.lower() in tl for c in constrain):
                continue
        results.append({
            "title": h["title"],
            "score": float(h["_distance"]) if "_distance" in h else float(h.get("score", 0)),
            "intro": h.get("intro", ""),
        })
        semantic_count += 1
        if len(results) >= req.top_k:
            break

    # Leniency: when a constrain filter eliminates every semantic hit, the
    # constraint words are suspect (LLM entity pollution — e.g. a verb glued
    # onto an article title). Returning unconstrained semantic results is
    # strictly better than returning nothing; flag them for diagnostics.
    if constrain and semantic_count == 0 and len(results) < req.top_k:
        for h in store.search(req.lang, vector, req.top_k):
            if h["title"] in seen:
                continue
            seen.add(h["title"])
            results.append({
                "title": h["title"],
                "score": float(h["_distance"]) if "_distance" in h else float(h.get("score", 0)),
                "intro": h.get("intro", ""),
                "unconstrained": True,
            })
            if len(results) >= req.top_k:
                break

    return {"lang": req.lang, "mode": req.mode, "results": results[: req.top_k],
            "latency_ms": round((time.time() - t0) * 1000, 1)}


@app.post("/extract")
def extract(req: ExtractRequest):
    """Clean full text for the given titles (with redirect resolution).

    Mirrors the Wikimedia action=query&prop=extracts&explaintext contract the
    fact-verifier already consumes — paragraphs split on blank lines.
    """
    if not store:
        raise HTTPException(503, "store not ready")
    out = []
    for raw_title in req.titles:
        title = normalize_zh(raw_title, req.lang)
        article = store.get_article(req.lang, title)
        if article:
            clean = clean_full_text(article["full_text"], max_chars=req.max_chars)
            out.append({
                "title": article["title"],
                "intro": article["intro"],
                "extract": clean,
                "paragraphs": split_paragraphs(clean),
            })
        else:
            out.append({"title": title, "intro": "", "extract": "", "paragraphs": []})
    return {"lang": req.lang, "articles": out}


@app.get("/article/{lang}/{title}")
def article(lang: str, title: str):
    if not store:
        raise HTTPException(503, "store not ready")
    if lang not in ("en", "zh"):
        raise HTTPException(400, "lang must be en or zh")
    article = store.get_article(lang, normalize_zh(title, lang))
    if not article:
        raise HTTPException(404, f"no article '{title}' in {lang}")
    article["extract"] = clean_full_text(article["full_text"])
    article.pop("full_text", None)
    return article


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Wikipedia search service")
    ap.add_argument("--port", type=int, default=21500)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--parsed-dir", default=str(DEFAULT_PARSED_DIR))
    ap.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    args = ap.parse_args()
    _PARSED_DIR = Path(args.parsed_dir)
    _INDEX_DIR = Path(args.index_dir)
    uvicorn.run(app, host=args.host, port=args.port)
