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
    "onix": {
        "host": "localhost",
        "port": 21434,
        "timeout": 120
    }
}



def load_config() -> Dict[str, Any]:
    """Load configuration from indexing_config.json."""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                config.update(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config file {CONFIG_FILE}: {e}", file=sys.stderr)
    return config



def build_translate_prompt(fact: str) -> str:
    try:
        return "Translate the following atomic fact into chinese\n\
Return nothing else appart from the translated fact.\n\
Fact:\n\
{0}".format(fact.get("fact_en"))
    except Exception as e:
        print(f"Fact: {fact}")
        print(f"Type: {type(fact)}")
        print(f"fact_en: {fact.get('fact_en')}")
        print(f"fact_en Type: {type(fact.get('fact_en'))}")
        raise Exception(f"Error building translate prompt for fact '{fact}': {e}")



def build_extract_prompt(topic: str, time_period: str, article: str) -> str:
    return "Read the provided article and extract its meaningful atomic facts.\n\
EXTRACT A MAXIMUM OF 100 FACTS.\n\
If there are more than 100 facts, RETURN ONLY THE 100 MOST RELEVANT FACTS.\n\
You will also be provided a topic and a time period.\n\
ONLY EXTRACT FACTS RELATING TO THE TOPIC AND IN THE GIVEN TIME PERIOD.\n\
MAKE SURE TO START AND END ALL STRINGS WITH DOUBLE QUOTES \n\
\n\
For each fact:\n\
- Express exactly one fact as a concise, self-contained string.\n\
- Assign a relevance score from 0 to 1, where:\n\
  - 1.00 = essential or highly relevant\n\
  - 0.50 = moderately relevant\n\
  - 0.05 = least relevant\n\
- Use the full range so that there is at least 1 fact with a relevance of 1.000 and one of 0.05\n\
- Preserve the meaning of the source text.\n\
- Do not infer, speculate, combine multiple facts, or add information not explicitly stated.\n\
- Avoid duplicates.\n\
- Include only facts supported by the text.\n\
- Return only the top 100 most relevant facts if there are more than 100.\n\
\n\
Return the results as a JSON array of objects,  Each object must contain exactly these fields:\n\
|- \"fact_en\": the extracted atomic fact in English as a string\n\
|- \"relevance\": the relevance score as a float between 0 and 1\n\
\n\
IMPORTANT!!! REQUIRED FORMAT:\n\
[\n\
  {{\n\
    \"fact_en\": \"A concise atomic fact in english.\",\n\
    \"relevance\": 0.85\n\
  }}\n\
]\n\
\n\
Return nothing except the valid JSON array. Do not include Markdown, explanations, comments, or additional text.\n\
\n\
Topic: {0}\n\
Time Period: {1}\n\
Article to analyze:\n\
{2}\n\
".format(topic, time_period, article)



def parse_content(
    content: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    text: List[Dict[str, Any]] = json.loads(content[0].get("text", "[]"))
    return text



def extract_facts(
    article: str,
    topic: str,
    time_period: str,
    lang: str,
    model: str = "Qwen3.8-Flash-Next-Uncensored-oQ4e-mtp",
) -> list[Dict[str, Any]]:

    # Validate inputs
    if not article or len(article) == 0:
        raise ValueError("article cannot be empty")

    config = load_config()
    onix_url = f"http://{config['onix']['host']}:{config['onix']['port']}"
    max_tokens = config["onix"]["max_tokens"]
    api_key = config["onix"]["api_key"]
    timeout = config["onix"]["timeout"]
    prompt_extract = build_extract_prompt(topic, time_period, article)

    # Extract facts using the LLM
    try:
        llm_response = requests.post(
            f"{onix_url}/v1/messages",
            headers={
                'x-api-key': api_key,
                "Content-Type": "application/json",
                'anthropic-version': '2023-06-01',
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "thinking": { "type": "disabled" },
                "messages": [{ "role": 'user', "content": prompt_extract }]
            },
            timeout=timeout
        )
        llm_response.raise_for_status()
        fact_data = llm_response.json()
    except requests.exceptions.RequestException as e:
        raise requests.RequestException(f"Extract failed: {e}")

    # Parse the LLM response content
    results = fact_data.get("content", [])

    if not results:
        return []

    try:
        results = parse_content(results)
    except Exception as e:
        print(results)
        raise ValueError(f"Failed to parse content: {e}")

    # Translate facts
    output = []
    for fact in results:
        try:
            translate_prompt = build_translate_prompt(fact)
            translate_response = requests.post(
                f"{onix_url}/v1/messages",
                headers={
                    'x-api-key': api_key,
                    "Content-Type": "application/json",
                    'anthropic-version': '2023-06-01',
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "thinking": { "type": "disabled" },
                    "messages": [{ "role": 'user', "content": translate_prompt }]
                },
                timeout=timeout
            )
            translate_response.raise_for_status()
            translate_data = translate_response.json()
        except requests.exceptions.RequestException as e:
            raise requests.RequestException(f"Translation failed: {e}")

        fact["fact_zh"] = translate_data.get("content", "")[0].get("text")
        
        output.append(fact)
    
    return output



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract weighted atomic facts from Wikipedia text using an LLM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python extract_facts.py "{article}" --lang "en"
        """
    )

    parser.add_argument(
        "article",
        help="Article text string"
    )

    parser.add_argument(
        "--lang",
        help="Language of the article text"
    )

    parser.add_argument(
        "--model",
        default="Qwen3.8-Flash-Next-Uncensored-oQ4e-mtp",
        help="Override the default model (default: Qwen3.8-Flash-Next-oQ4e-mtp).  Find models that can be used at {{onix_url}}/v1/models"
    )

    args = parser.parse_args()

    try:
        facts = extract_facts(article=args.article, lang=args.lang, model=args.model)
        print(json.dumps(facts, indent=2, ensure_ascii=False))
    except ValueError as e:
        print(f"Value Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)



if __name__ == "__main__":
    main()
