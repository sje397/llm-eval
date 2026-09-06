#!/bin/bash
# Run the full Wikipedia index pipeline once dumps are complete.
# Usage: ./run-pipeline.sh [--en-only]
set -euo pipefail
cd "$(dirname "$0")"
PY=~/venv/wikipedia/bin/python3

echo "==> [$(date)] Parsing EN dump"
$PY parser.py --dump dumps/enwiki-latest-pages-articles.xml.bz2 --out parsed/en.sqlite --lang en

if [[ "${1:-}" != "--en-only" ]]; then
    echo "==> [$(date)] Parsing ZH dump"
    $PY parser.py --dump dumps/zhwiki-latest-pages-articles.xml.bz2 --out parsed/zh.sqlite --lang zh
fi

echo "==> [$(date)] Indexing EN"
$PY indexer.py --sqlite parsed/en.sqlite --index index --lang en

if [[ "${1:-}" != "--en-only" ]]; then
    echo "==> [$(date)] Indexing ZH"
    $PY indexer.py --sqlite parsed/zh.sqlite --index index --lang zh
fi

echo "==> [$(date)] Restarting service"
launchctl kickstart -k gui/$(id -u)/com.lex.wikipedia-service

echo "==> [$(date)] Done. Verifying:"
sleep 3
curl -s http://localhost:21500/stats
echo
