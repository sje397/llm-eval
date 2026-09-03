#!/usr/bin/env python3

import sqlite3
import sys
import json
import argparse

from pathlib import Path
from typing import Optional, List, Dict, Any



def search_index(
    topic: str,
    index_path: str
) -> List[Dict[str, Any]]:

    if not topic or not isinstance(topic, str) or not topic.strip():
        return []

    with sqlite3.connect(index_path) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            """
            SELECT
                topic,
                source_url,
                facts_json
            FROM articles
            WHERE topic LIKE ?
            """,
            (f"%{topic.strip()}%",)
        ).fetchall()

        results = []

        for row in rows:
            result = dict(row)

            result["facts"] = json.loads(result.pop("facts_json"))

            results.append(result)

        return results



if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Search the article index by topic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python search_index.py --topic "topic" --index-path "path/to.index"
        """
    )

    parser.add_argument(
        "--topic",
        required=True,
        help="The topic to search for in the article index."
    )
    parser.add_argument(
        "--index-path",
        required=True,
        help="The path to the SQLite index file."
    )

    args = parser.parse_args()

    results = search_index(
        topic=args.topic,
        index_path=args.index_path
    )

    for result in results:
        print(result)