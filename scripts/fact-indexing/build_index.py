import json
import csv
import sqlite3
import sys
import argparse

from pathlib import Path
from typing import Optional, List, Dict, Any

from fetch_articles import fetch_articles
from extract_facts import extract_facts



def initialize_index(index_path: str) -> None:
    index_path = Path(index_path)

    with sqlite3.connect(index_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                article_title TEXT NOT NULL,
                article_url TEXT NOT NULL,
                article_extract TEXT NOT NULL,
                facts_json TEXT NOT NULL
            )
            """
        )

        connection.commit()



def build_index(
    topics: list[str],
    article_count: int,
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
            print(f"[{indexed_count + 1} / {len(topics)}] Topic: {topic.get('topic_en', '')} ({topic.get('year', '')})")
            if not isinstance(topic, dict) or f"topic_{lang.lower()}" not in topic or not topic[f"topic_{lang.lower()}"].strip():
                continue
            
            topic_str = topic[f"topic_{lang.lower()}"].strip()

            # Fetch articles for the current topic
            articles = fetch_articles(
                query=topic_str,
                count=article_count,
                lang=lang
            )

            # Iterate over each fetched article
            for i, article in enumerate(articles):
                print(f"  [{i + 1} / {len(articles)}] Article: {article.get('title', '')} - {article.get('wikipedia_url', '')}")
                
                print(f"    Collecting article extract...")
                # Collect the article text extract
                extract = article.get("extract")

                if not isinstance(extract, str) or not extract.strip():
                    continue

                print(f"    Extracting facts...")
                # Extract facts from the article text
                facts = extract_facts(
                    article=extract,
                    lang=lang,
                    model=model
                )

                print(f"    Formatting {len(facts)} facts to JSON...")
                # Convert the enriched article to JSON
                facts_json = json.dumps(
                    facts,
                    ensure_ascii=False
                )

                print(f"    Storing into index...")
                # Add indexed article to the database
                connection.execute(
                    """
                    INSERT INTO articles (
                        topic,
                        article_title,
                        article_url,
                        article_extract,
                        facts_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        topic_str,
                        article.get("title", ""),
                        article.get("wikipedia_url", ""),
                        article.get("extract", ""),
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
        "--article-count",
        help="Number of articles to index per topic.",
        type=int,
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

    args = parser.parse_args()

    # Read topics out of topics file & format.
    topics: list[dict[str, Any]] = []

    with Path(args.topics_file).open(
        mode="r",
        encoding="utf-8"
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        for row in reader:
            id = row.get("id", "").strip()
            topic_en = row.get("topic_en", "").strip()
            topic_zh = row.get("topic_zh", "").strip()
            year = row.get("year", "").strip()

            if topic_en and topic_zh:
                topics.append(dict(id=id, topic_en=topic_en, topic_zh=topic_zh, year=year))

    build_index(
        topics=topics,
        article_count=args.article_count,
        lang=args.lang,
        model=args.model,
        index_path=args.db_file
    )


