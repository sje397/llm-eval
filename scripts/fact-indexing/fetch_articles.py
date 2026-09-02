#!/usr/bin/env python3

import requests
import json
import sys
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any

# Load configuration
CONFIG_FILE = Path(__file__).parent / "indexing_config.json"
DEFAULT_CONFIG = {
    "mimr": {
        "host": "localhost",
        "port": 21500,
        "timeout": 8
    }
}



def load_config() -> Dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                config.update(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config file {CONFIG_FILE}: {e}", file=sys.stderr)
    return config



def fetch_articles(
    query: str,
    count: int = 3,
    lang: str = "en"
) -> List[Dict[str, Any]]:

    # Validate inputs
    if not query or len(query) == 0:
        raise ValueError("query cannot be empty")
    if not 1 <= count <= 20:
        raise ValueError(f"count must be between 1 and 20, got {count}")
    if lang not in ("en", "zh"):
        raise ValueError(f"lang must be 'en' or 'zh', got '{lang}'")

    config = load_config()
    mimir_url = f"http://{config['mimir']['host']}:{config['mimir']['port']}"
    timeout = config["mimir"]["timeout"]

    # Step 1: Search
    try:
        search_response = requests.post(
            f"{mimir_url}/search",
            json={
                "query": query,
                "lang": lang,
                "mode": "text",
                "top_k": count,
                "constrain": []
            },
            timeout=timeout
        )
        search_response.raise_for_status()
        search_data = search_response.json()
    except requests.exceptions.RequestException as e:
        raise requests.RequestException(f"Search failed: {e}")

    results = search_data.get("results", [])
    if not results:
        return []

    # Step 2: Extract full text for each article
    titles = [r["title"] for r in results]

    try:
        extract_response = requests.post(
            f"{mimir_url}/extract",
            json={
                "titles": titles,
                "lang": lang,
                "max_chars": 12000
            },
            timeout=timeout
        )
        extract_response.raise_for_status()
        extract_data = extract_response.json()
    except requests.exceptions.RequestException as e:
        raise requests.RequestException(f"Extract failed: {e}")

    articles_by_title = {}
    for article in extract_data.get("articles", []):
        articles_by_title[article["title"]] = article

    # Step 3: Combine search results with extracts, maintaining relevance order
    collated = []
    wikipedia_host = "en.wikipedia.org" if lang == "en" else "zh.wikipedia.org"

    for search_result in results:
        title = search_result["title"]
        extract = articles_by_title.get(title, {})

        # Construct Wikipedia URL (URL-encoded title with underscores instead of spaces)
        url_title = title.replace(" ", "_")
        wikipedia_url = f"https://{wikipedia_host}/wiki/{url_title}"

        collated.append({
            "title": title,
            "score": search_result["score"],
            "intro": search_result.get("intro", ""),
            "extract": extract.get("extract", ""),
            "wikipedia_url": wikipedia_url,
            "lang": lang
        })

    return collated


def main():
    """Command-line interface for fetching and extracting Wikipedia articles."""
    parser = argparse.ArgumentParser(
        description="Fetch and extract Wikipedia articles from Mímir semantic search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fetch_articles.py "Mobile payments in China"
  python fetch_articles.py "Taiwan election" --count 5
  python fetch_articles.py "台灣選舉" --count 3 --lang zh
  python fetch_articles.py "QR code" -c 10 -l en
        """
    )

    parser.add_argument(
        "query",
        help="Search query string (1-500 characters)"
    )
    parser.add_argument(
        "--count", "-c",
        type=int,
        default=3,
        help="Number of articles to return (default: 3, max: 20)"
    )
    parser.add_argument(
        "--lang", "-l",
        choices=["en", "zh"],
        default="en",
        help="Language code: 'en' (English) or 'zh' (Chinese) (default: en)"
    )

    args = parser.parse_args()

    try:
        articles = fetch_articles(query=args.query, count=args.count, lang=args.lang)
        print(json.dumps(articles, indent=2, ensure_ascii=False))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)



if __name__ == "__main__":
    main()
