# Topic Fact Indexing System - Quick Start Guide

## Overview
Three Python scripts for extracting atomic facts from Wikipedia articles and storing them in a SQLite database.

---

## 1. build_index.py
**Purpose:** Fetches Wikipedia articles, extracts facts using LLMs, stores in SQLite.

### Usage (CLI)
```bash
python build_index.py \
    --topics-file topics.json \
    --lang en \
    --model Qwen3.8-Flash-Next-Uncensored-oQ4e-mtp \
    --db-file index.db
```

### Python API Usage
```python
from build_index import build_index

indexed_count = build_index(
    topics=[
        {
            "id": "1",
            "topic": "World War II",
            "source": "https://en.wikipedia.org/wiki/World_War_II",
            "year": "1939-1945"
        }
    ],
    lang="en",
    model="Qwen3.8-Flash-Next-Uncensored-oQ4e-mtp",
    index_path="index.db"
)

print(f"Indexed {indexed_count} topics")
```

### Input: Topics List
```python
topics = [
    {
        "id": "1",
        "topic": "World War II",
        "source": "https://en.wikipedia.org/wiki/World_War_II",
        "year": "1939-1945"
    },
    {
        "id": "2",
        "topic": "Cold War",
        "source": "https://en.wikipedia.org/wiki/Cold_War",
        "year": "1947-1991"
    }
]
```

### Output: SQLite Database (`index.db`)
Table `articles`:
- `topic` (TEXT, PRIMARY KEY)
- `source_url` (TEXT)
- `facts_json` (TEXT - JSON array of facts)

---

## 2. extract_facts.py
**Purpose:** Extracts atomic facts from article text and translates to Chinese.

### Usage (CLI)
```bash
python extract_facts.py "World War II" --lang en
```

### Python API Usage
```python
from extract_facts import extract_facts

facts = extract_facts(
    article="Your article text here",
    topic="World War II",
    time_period="1939-1945",
    lang="en",
    model="Qwen3.8-Flash-Next-Uncensored-oQ4e-mtp"
)

print(json.dumps(facts, indent=2, ensure_ascii=False))
```

### Output Format
```json
[
  {
    "fact_en": "World War II was fought between 1939 and 1945.",
    "relevance": 0.95,
    "fact_zh": "第二次世界大战于1939年至1945年间进行。"
  }
]
```

---

## 3. search_index.py
**Purpose:** Searches the index database for facts by topic.

### Usage (CLI)
```bash
python search_index.py \
    --topic "World War II" \
    --index-path index.db
```

### Python API Usage
```python
from search_index import search_index

results = search_index(
    topic="World War II",
    index_path="../data/index.db"
)

for result in results:
    print(f"Topic: {result['topic']}")
    print(f"Facts count: {len(result['facts'])}")
    for fact in result['facts'][:3]:  # Show first 3 facts
        print(f"  - {fact['fact_en']} (relevance: {fact['relevance']})")
```

### Output
```python
[
  {
    "topic": "World War II",
    "source_url": "https://en.wikipedia.org/wiki/World_War_II",
    "facts": [
      {"fact_en": "...", "relevance": 0.95, "fact_zh": "..."},
      ...
    ]
  }
]
```

---

## Configuration (Optional)
Create `scripts/indexing_config.json` for API settings:
```json
{
  "onix": {
    "host": "localhost",
    "port": 21434,
    "timeout": 120,
    "api_key": "your-api-key",
    "max_tokens": 4096
  }
}
```

---

## Quick Workflow
1. **Build Index:** Use `build_index()` to populate the database
2. **Extract Facts:** Use `extract_facts()` for single articles
3. **Search:** Use `search_index()` to query the database

---

## Notes
- Supports partial topic matching in search (`LIKE '%topic%'`)
- Maximum 100 facts per article (top relevance)
- Facts include English, Chinese translation, and relevance score
- Relevance scores: 1.00 (essential), 0.50 (moderate), 0.05 (least relevant)