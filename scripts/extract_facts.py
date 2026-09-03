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



def buildEnPrompt(topic: str, time_period: str, article: str) -> str:
    return "Read the provided article and extract its meaningful atomic facts.\n\
EXTRACT A MAXIMUM OF 100 FACTS.\n\
If there are more than 100 facts, RETURN ONLY THE 100 MOST RELEVANT FACTS.\n\
You will also be provided a topic and a time period.\n\
ONLY EXTRACT FACTS RELATING TO THE TOPIC AND IN THE GIVEN TIME PERIOD.\n\
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
- \"fact\": the extracted atomic fact as a string\n\
- \"relevance\": the relevance score as a float between 0 and 1\n\
\n\
IMPORTANT!!! REQUIRED FORMAT:\n\
[\n\
  {{\n\
    \"fact\": \"A concise atomic fact.\",\n\
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



def buildZhPrompt(article: str) -> str:
    return "阅读提供的文章，并提取其中有意义的原子事实。\n\
最多提取 100 个事实。\n\
如果事实超过 100 个，则仅返回其中相关性最高的 100 个事实。\n\
同时还会提供一个主题和一个时间段。\n\
仅提取与该主题相关且属于指定时间段内的事实。\n\
\n\
对于每个事实：\n\
    将恰好一个事实表述为简洁且自洽的字符串。\n\
    分配一个介于 0 和 1 之间的相关性分数，其中：\n\
        1.00 = 必要或高度相关\n\
        0.50 = 中等相关\n\
        0.05 = 相关性最低\n\
    使用完整的分数范围，确保至少有 1 个事实的相关性为 1.000，并且至少有 1 个事实的相关性为 0.05\n\
    保留源文本的含义。\n\
    不得推断、猜测、合并多个事实，也不得添加文本中未明确说明的信息。\n\
    避免重复。\n\
    仅包含文本支持的事实。\n\
    如果事实超过 100 个，仅返回相关性最高的 100 个事实。\n\
\n\
以 JSON 对象数组的形式返回结果。每个对象必须恰好包含以下字段：\n\
    \"fact\"：以字符串形式表示提取出的原子事实\n\
    \"relevance\"：介于 0 和 1 之间的浮点数相关性分数\n\
\n\
重要！！！必需格式：\n\
[\n\
  {{\n\
    \"fact\": \"简洁的原子事实。\",\n\
    \"relevance\": 0.85\n\
  }}\n\
]\n\
\n\
除有效的 JSON 数组外，不得返回任何内容。不得包含 Markdown、解释、注释或其他文本。\n\
\n\
主题：{0}\n\
时间段：{1}\n\
要分析的文章：\n\
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
    model: str = "Qwen3.8-Flash-Next-oQ4e-mtp",
) -> list[Dict[str, Any]]:

    # Validate inputs
    if not article or len(article) == 0:
        raise ValueError("article cannot be empty")

    config = load_config()
    onix_url = f"http://{config['onix']['host']}:{config['onix']['port']}"
    max_tokens = config["onix"]["max_tokens"]
    api_key = config["onix"]["api_key"]
    timeout = config["onix"]["timeout"]
    prompt = buildEnPrompt(topic, time_period, article) if lang.lower() == "en" else buildZhPrompt(article)

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
                "messages": [{ "role": 'user', "content": prompt }]
            },
            timeout=timeout
        )
        llm_response.raise_for_status()
        fact_data = llm_response.json()
    except requests.exceptions.RequestException as e:
        raise requests.RequestException(f"Extract failed: {e}")

    results = fact_data.get("content", [])

    if not results:
        return []

    try:
        results = parse_content(results)
    except Exception as e:
        print(results)
        raise ValueError(f"Failed to parse content: {e}")
        
    return results



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
        default="Qwen3.8-Flash-Next-oQ4e-mtp",
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
