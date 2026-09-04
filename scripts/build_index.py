import json
import csv
import sqlite3
import sys
import requests
import argparse

from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, unquote

from extract_facts import extract_facts



def initialize_index(index_path: str) -> None:
    index_path = Path(index_path)

    with sqlite3.connect(index_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                topic TEXT PRIMARY KEY NOT NULL,
                source_url TEXT NOT NULL,
                facts_json TEXT NOT NULL
            )
            """
        )

        connection.commit()



def fetch_article(title: str) -> str:

    response = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1,
            "titles": title,
        },
        headers={"User-Agent": "MyWikipediaClient/1.0"}
    )

    try:
        pages = response.json()["query"]["pages"]
        page = next(iter(pages.values()))

        plain_text = page.get("extract", "")

        return plain_text
    except Exception as e:
        print(f"Failed to fetch article '{title}': {e}", file=sys.stderr)
        print(f"Response JSON: {response.json()}")
        raise Exception(f"Failed to fetch article '{title}': {e}")



def build_index(
    topics: list[str],
    lang: str,
    model: str,
    index_path: str
) -> int:

    # If no topics, do nothing, return 0 topics indexed
    if not topics:
        return 0

    # Ensure an index exists at the specified path
    initialize_index(index_path)

    # Initialize topics indexed count
    indexed_count = 0

    with sqlite3.connect(index_path) as connection:
        # Iterate over each topic
        for topic in topics:
            print(f"[{indexed_count + 1} / {len(topics)}] Topic: {topic.get('topic', '')} ({topic.get('year', '')})")

            # Check formatting and type
            if not isinstance(topic, dict) or "topic" not in topic or not topic["topic"].strip():
                continue

            print(f"  Fetching Article {topic.get('topic', '')} - {topic.get('year', '')} - {topic.get('source', '')}")

            # Extract article title out of source URL
            article_title = unquote(urlparse(topic.get("source", "")).path.removeprefix("/wiki/"))
            # Fetch article for the current topic
            article_text = fetch_article(article_title)

            print(f"  Extracting facts...")
            # Extract facts from the article text
            facts = extract_facts(
                article=article_text,
                topic=topic.get('topic', ''),
                time_period=topic.get('year', ''),
                lang=lang,
                model=model
            )

            print(f"  Formatting {len(facts)} facts to JSON...")
            # Convert the enriched article to JSON
            facts_json = json.dumps(
                facts,
                ensure_ascii=False
            )

            print(f"  Storing into index...")
            # Add indexed article to the database
            connection.execute(
                """
                INSERT INTO articles (
                    topic,
                    source_url,
                    facts_json
                )
                VALUES (?, ?, ?)
                """,
                (
                    topic.get('topic', ''),
                    topic.get('source', ''),
                    facts_json
                )
            )

            indexed_count += 1

        connection.commit()
    
    return indexed_count



if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(
        description="Build topic fact index from list of Topics using Wikipedia.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_index.py
        """
    )

    parser.add_argument(
        "--topics-file",
        help="Path to the file containing the list of topics to index.",
        required=True
    )

    parser.add_argument(
        "--lang",
        help="Language of the articles to index.  Either 'en' or 'zh'.",
        type=str,
        required=True
    )

    parser.add_argument(
        "--model",
        help="Model to use for indexing.",
        type=str,
        required=True
    )

    parser.add_argument(
        "--db-file",
        help="Path to the output db file where the index will be saved.",
        required=True
    )

    parser.add_argument(
        "--start-from",
        help="Start from a specific topic index in the topics file.",
        type=int,
        default=0
    )

    parser.add_argument(
        "--count",
        help="Number of topics to process from the start index.",
        type=int,
        default=None
    )

    args = parser.parse_args()

    # Read topics out of topics file & format.
    topics: list[dict[str, Any]] = []

    with Path(args.topics_file).open(
        mode="r",
        encoding="utf-8"
    ) as json_file:
        data = json.load(json_file)
        
        scenarios = data.get("scenarios", [])
        
        for scenario in scenarios:
            id_val = scenario.get("id", "").strip()
            topic_en = scenario.get("event", {}).get("en", "").strip()
            topic_zh = scenario.get("event", {}).get("zh", "").strip()
            topic = topic_en if args.lang == "en" else topic_zh
            source_en = scenario.get("source", {}).get("en", "").strip()
            source_zh = scenario.get("source", {}).get("zh", "").strip()
            source = source_en if args.lang == "en" else source_zh
            period = scenario.get("period", "").strip()

            if topic_en and topic_zh:
                topics.append(dict(id=id_val, topic=topic_en, source=source, year=period))

    topics = topics[args.start_from:]
    if args.count is not None:
        topics = topics[:args.count]

    build_index(
        topics=topics,
        lang=args.lang,
        model=args.model,
        index_path=args.db_file
    )


