# Facts Indexing System Documentation

## Summary

This documentation describes a system for creating and querying an SQLite database index containing extracted facts from Wikipedia articles. The system consists of three main components:

- **`build_index.py`**: Creates a `.sqlite3` index by fetching Wikipedia articles, extracting facts using LLMs, and storing the structured data in a database
- **`search_index.py`**: Queries the SQLite database to retrieve relevant facts from indexed articles based on search topics
- **`extract_facts.py`**: Extracts structured facts from Wikipedia article text using an LLM-powered extraction service

The system enables efficient retrieval of factual information from large collections of Wikipedia articles by pre-extracting and indexing key facts, then allowing semantic search queries to retrieve relevant information.

## How to Use

### Building a New Index

To build a new index from the cli with default parameters:

```bash
python scripts/build_index.py \
  --topics-file ../../data/scenarios.json \
  --lang "en" \
  --model "Qwen3.8-Flash-Next-oQ4e-mtp" \
  --db-file "../../data/index_en_en.sqlite3"
```

**Parameters:**
- `--topics-file`: Path to JSON file containing list of topics/scenarios to index
- `--lang`: Language code ("en" for English, "zh" for Chinese)
- `--model`: LLM model name to use for fact extraction
- `--db-file`: Output path for the SQLite database file

### Searching the Index

To search from a python script for facts with default parameters:

```python
from fact_indexing.search_index import search_index

# Search for facts about a topic
results = search_index(
    topic="World War II",
    index_path="../data/index_en_en.sqlite3"
)
```

Results format:
{
    "topic": "The Opium Wars",
    "source_url": "https://en.wikipedia.org/wiki/Opium_Wars",
    "facts": [
        {
            "fact": "The Opium Wars were a series of wars fought between China and Britain over the trade of opium.",
            "relevance": 0.95
        },
        ...
    ]
}


To search from the cli for facts with default parameters:

```bash
python scripts/search_index.py \
  --topic "{topic as in scenarios.json}" \
  --index-path "../data/index_en_en.sqlite3"
```

**Example:**
```bash
python scripts/search_index.py \
  --topic "World War II" \
  --index-path "../data/index_en_en.sqlite3"
```

### Index Naming Convention

Index files follow the pattern: `index_{lang}_{lang}.sqlite3`

- **First component** (`{1}`): Wikipedia language version (e.g., "en" for English Wikipedia)
- **Second component** (`{2}`): Language of stored facts (e.g., "en" for English facts)

Examples:
- `index_en_en.sqlite3`: Facts in English from English Wikipedia
- `index_zh_en.sqlite3`: Facts in English from Chinese Wikipedia
- `index_en_zh.sqlite3`: Facts in Chinese from English Wikipedia

## Technical Explanation

### File Structure Overview

```
scripts/
├── build_index.py          # Main indexing script
└── fact-indexing/
    ├── search_index.py     # Search functionality
    └── extract_facts.py    # Fact extraction logic
```

### `build_index.py` - Index Building Script

**Purpose**: Fetches Wikipedia articles, extracts facts using LLMs, and stores them in an SQLite database.

#### Key Functions:

1. **`initialize_index(index_path)`** (Lines 13-26)
   - Creates the SQLite database if it doesn't exist
   - Creates `articles` table with columns: `topic`, `source_url`, `facts_json`
   - Uses `CREATE TABLE IF NOT EXISTS` for idempotency

2. **`fetch_article(title)`** (Lines 29-47)
   - Makes API call to Wikipedia's MediaWiki API
   - Retrieves plain text extract from article pages
   - Handles redirects automatically
   - Returns formatted article text

3. **`build_index(topics, lang, model, index_path)`** (Lines 50-126)
   - Main orchestration function
   - Iterates through topics from input file
   - For each topic:
     - Extracts article title from source URL
     - Fetches Wikipedia article text
     - Calls `extract_facts()` to extract structured facts
     - Converts facts to JSON format
     - Stores in SQLite database
   - Returns count of successfully indexed topics

4. **Main block** (Lines 129-175)
   - Parses command-line arguments
   - Reads scenarios from JSON file
   - Filters topics based on language selection
   - Calls `build_index()` with appropriate parameters

#### Data Flow:
```
scenarios.json → build_index() → fetch_article() → extract_facts() → SQLite database
```

### `search_index.py` - Search Functionality

**Purpose**: Queries the SQLite database to retrieve facts matching a search topic.

#### Key Functions:

1. **`search_index(topic, index_path)`** (Lines 4-23)
   - Validates input topic
   - Connects to SQLite database
   - Executes SQL query with LIKE pattern matching on `topic` column
   - Parses JSON facts from database into Python objects
   - Returns list of matching results with structured data

#### Search Strategy:
- Uses `LIKE ?` with `%{topic}%` pattern for partial matching
- Retrieves all articles where topic contains the search term
- Converts stored JSON to Python dictionaries for easy access

### `extract_facts.py` - Fact Extraction Logic

**Purpose**: Extracts structured facts from Wikipedia article text using an LLM service.

#### Key Functions:

1. **`extract_facts(article, lang, model)`** (Lines 4-52)
   - Validates input article text
   - Loads configuration (host, port, API key, timeout)
   - Builds appropriate prompt based on language (English/Chinese)
   - Makes POST request to LLM service endpoint
   - Parses and validates response
   - Returns list of extracted facts

#### Integration Points:
- Called by `build_index.py` during the indexing process
- Uses external LLM service via HTTP API
- Supports both English and Chinese language processing

### System Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  scenarios.json │────▶│   build_index.py │────▶│  extract_facts  │
└─────────────────┘     │                  │     │                 │
                        │  Fetch articles  │     │  LLM Service    │
                        │  Extract facts   │◀────┤                 │
                        │  Store in DB     │     └─────────────────┘
                        └──────────────────┘
                                │
                                ▼
                        ┌──────────────────┐
                        │   SQLite DB      │
                        │  (index_*.sqlite)│
                        └──────────────────┘
                                │
                                ▼
                        ┌──────────────────┐
                        │ search_index.py  │◀─── Search Query
                        └──────────────────┘
```

### Configuration Dependencies

The system relies on external configuration:
- **LLM Service**: Hosted at `http://{host}:{port}` with API authentication
- **Input Data**: JSON file containing scenarios/topics to index
- **Model**: LLM model name for fact extraction (default: "Qwen3.8-Flash-Next-oQ4e-mtp")

### Error Handling

- Input validation for empty topics and articles
- HTTP request timeout handling
- JSON parsing error management
- Database connection safety using context managers

## Best Practices

1. **Index Naming**: Always use consistent naming convention to avoid confusion between language components
2. **Topic Selection**: Ensure topics in scenarios.json match Wikipedia article titles
3. **Database Location**: Store indexes in persistent storage for production use
4. **Model Selection**: Choose appropriate LLM model based on fact extraction requirements
5. **Language Consistency**: Match `--lang` parameter with both source and target language needs

## Troubleshooting

- **Empty results**: Check that topics exist in Wikipedia and are properly formatted
- **Connection errors**: Verify LLM service is running and accessible
- **Database issues**: Ensure SQLite file has write permissions
- **Slow indexing**: Consider batching or parallelizing for large topic lists
